from decimal import Decimal
import unittest

from erp_sim.errors import ErpError
from erp_sim.features.asfi301 import WorkOrderEntry, Asfi301, detail_page


def node(kind, name=None, value=None, active=None, children=None, **attrs):
    if name is not None: attrs['name'] = name
    if value is not None: attrs['value'] = value
    if active is not None: attrs['active'] = '1' if active else '0'
    return {'kind': kind, 'attrs': attrs, 'children': children or [], 'parent': 0}


class Tree:
    def __init__(self, program='asfi301'):
        self.nodes = {0: node('UserInterface', program, focus='0')}

    def field(self, ident, name, value='', active=True):
        self.nodes[ident] = node('FormField', name, value, active)
        return ident

    def focus(self, ident):
        self.nodes[0]['attrs']['focus'] = str(ident)


class Channel:
    def __init__(self, tag='main', program='asfi301'):
        self.tag = tag
        self.tree = Tree(program)
        self.events = []
        self.sent = []

    def emit(self, *commands): self.events.append(commands)
    def send(self, payload): self.sent.append(payload)
    def touch(self): pass


class Asfi301Tests(unittest.TestCase):
    def test_quantity_normalization_and_invalid_direct_inputs(self):
        entry = WorkOrderEntry('TST01', 'V001', 'ITEM-001', 42.0, 'note')
        self.assertIs(type(entry.quantity), int)
        self.assertEqual(str(entry.quantity), '42')
        for value in (True, '42', None, 42.5, 0, -1, 100000000,
                      float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value), self.assertRaises(ErpError) as caught:
                WorkOrderEntry('TST01', 'V001', 'ITEM-001', value, 'note')
            self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')

    def setUp(self):
        self.entry = WorkOrderEntry('TST01', 'V001', 'ITEM-001', 42,
                                    '第一行\n第二行', 'D001')

    def test_request_normalizes_multiline_remark_and_rejects_controls(self):
        entry = WorkOrderEntry('TST01', 'V001', 'ITEM-001', 1,
                               '第一行\r\n第二行\r第三行', 'D001')
        self.assertEqual(entry.remark, '第一行\n第二行\n第三行')
        self.assertFalse(entry.as_dict()['automatic_retry'])
        for remark in ('', 'x' * 256, 'bad\ttext', 'bad\0text'):
            with self.subTest(remark=repr(remark)), self.assertRaises(ErpError):
                WorkOrderEntry('TST01', 'V001', 'ITEM-001', 1, remark, 'D001')
        for bad in (None, 1, []):
            with self.subTest(bad=bad), self.assertRaises(ErpError):
                WorkOrderEntry('TST01', 'V001', 'ITEM-001', 1, bad, 'D001')

    def test_optional_manufacturing_department_guard_accepts_derived_value(self):
        feature = Asfi301(WorkOrderEntry('TST01', 'V001', 'ITEM-001', 42, 'note'))
        channel = Channel()
        feature.stage = 'tab3'
        channel.tree.field(129, 'sfb_file.sfb39')
        channel.tree.field(212, 'sfb_file.sfb82')
        channel.tree.field(217, 'formonly.ta_sfb06', 'OTHER')
        channel.tree.field(219, 'formonly.ta_sfb06_name', 'Synthetic factory')
        channel.tree.focus(129)
        feature.advance(channel)
        self.assertEqual(feature.stage, 'vendor_focused')
        self.assertNotIn('expected_manufacturing_department', feature.entry.as_dict())

        missing = Asfi301(WorkOrderEntry('TST01', 'V001', 'ITEM-001', 42, 'note'))
        missing.stage = 'tab3'
        channel.tree.nodes[217]['attrs']['value'] = ''
        with self.assertRaises(ErpError):
            missing.advance(channel)

    def test_full_state_machine_submits_once_and_returns_server_number(self):
        feature, main = Asfi301(self.entry), Channel()
        main.tree.field(104, 'sfb_file.sfb01', 'old')
        main.tree.nodes[2693] = node('Action', 'insert', active=True)
        feature.advance(main)

        main.tree.nodes.pop(2693)
        main.tree.field(104, 'sfb_file.sfb01', '     -         ')
        main.tree.nodes[2942] = node('Dialog', active=True, children=[2943, 2944])
        main.tree.nodes[2943] = node('DialogInfo', dialogType='Input')
        main.tree.nodes[2944] = node('Action', 'accept', active=True)
        main.tree.focus(104); feature.advance(main)

        steps = [(112, 'sfb_file.sfb44'), (118, 'sfb_file.sfb81'),
                 (121, 'sfb_file.sfb02'), (129, 'sfb_file.sfb39')]
        main.tree.nodes[104]['attrs']['value'] = 'TST01-'
        for ident, name in steps:
            main.tree.field(ident, name); main.tree.focus(ident)
            if ident == 129:
                main.tree.field(217, 'formonly.ta_sfb06', 'D001')
                main.tree.field(219, 'formonly.ta_sfb06_name', 'Synthetic factory')
                main.tree.field(212, 'sfb_file.sfb82', 'D001')
            feature.advance(main)

        main.tree.focus(212); feature.advance(main)
        main.tree.nodes[212]['attrs']['value'] = 'V001'
        main.tree.field(214, 'formonly.pmc03', 'Synthetic vendor')
        main.tree.focus(217); feature.advance(main)
        main.tree.field(254, 'sfb_file.sfb05'); main.tree.focus(254); feature.advance(main)
        main.tree.nodes[254]['attrs']['value'] = 'ITEM-001'
        main.tree.field(259, 'formonly.ima02', '产品名称')
        main.tree.field(274, 'sfb_file.sfb08'); main.tree.focus(274); feature.advance(main)
        main.tree.nodes[274]['attrs']['value'] = '42.000'
        main.tree.field(279, 'sfb_file.sfb07'); main.tree.focus(279); feature.advance(main)
        main.tree.field(355, 'formonly.ta_sfb09', 'N'); main.tree.focus(355); feature.advance(main)
        main.tree.field(418, 'sfb_file.sfb96'); main.tree.focus(418); feature.advance(main)

        action_events = sum('ActionEvent' in command for event in main.events for command in event)
        self.assertEqual(feature.result['status'], 'uncertain')
        self.assertEqual(action_events, 2)  # insert plus the only business submit

        child = Channel('child', 'asfp301')
        child.tree.nodes[90] = node('MenuAction', 'ok', active=True, text='确定')
        feature.advance(child)
        feature.advance(child)
        self.assertEqual(len(child.events), 1)

        main.tree.nodes.pop(2942); main.tree.nodes.pop(2943); main.tree.nodes.pop(2944)
        main.tree.nodes[104]['attrs']['value'] = 'TST01-123456789'
        main.tree.nodes[418]['attrs']['value'] = self.entry.remark
        main.tree.nodes[800] = node('Message', text='(csf-a06) detail warning', type='error')
        values = [811, 812]
        main.tree.nodes[810] = node('ValueList', children=values)
        main.tree.nodes[811] = node('Value', value='A')
        main.tree.nodes[812] = node('Value', value='B')
        main.tree.nodes[809] = node('TableColumn', colName='sfa03', children=[810])
        main.tree.nodes[808] = node('Table', 's_sfa', size='2', offset='0', pageSize='10', children=[809])
        feature.advance(main)
        self.assertTrue(feature.done)
        self.assertEqual(feature.result['status'], 'server_confirmed')
        self.assertEqual(feature.result['work_order_number'], 'TST01-123456789')
        self.assertEqual(feature.result['fields_verified']['department_vendor_name'],
                         'Synthetic vendor')
        self.assertEqual(feature.result['fields_verified']['remark'], '第一行\n第二行')
        self.assertEqual(feature.result['detail']['visible_row_count'], 2)

    def test_paginated_detail_page_is_valid_but_incomplete(self):
        tree = Tree()
        values = list(range(4, 14))
        tree.nodes[1] = node('Table', 's_sfa', size='26', offset='0', pageSize='10', children=[2])
        tree.nodes[2] = node('TableColumn', colName='sfa03', children=[3])
        tree.nodes[3] = node('ValueList', children=values)
        for ident in values: tree.nodes[ident] = node('Value', value=str(ident))
        self.assertEqual(detail_page(tree), {'expected_row_count': 26, 'visible_row_count': 10,
                                             'column_count': 1, 'complete': False})

    def test_unexpected_error_and_wrong_final_echo_are_rejected(self):
        feature, channel = Asfi301(self.entry), Channel()
        channel.tree.nodes[1] = node('Message', text='unexpected', type='error')
        with self.assertRaisesRegex(ErpError, 'unexpected form error'):
            feature.advance(channel)

    def test_child_confirmation_requires_the_verified_button_text(self):
        feature, child = Asfi301(self.entry), Channel('child', 'asfp301')
        child.tree.nodes[90] = node('MenuAction', 'ok', active=True, text='Cancel')
        feature.advance(child)
        self.assertEqual(child.events, [])
        child.tree.nodes[90]['attrs']['text'] = '确定'
        feature.advance(child)
        self.assertEqual(len(child.events), 1)


if __name__ == '__main__':
    unittest.main()
