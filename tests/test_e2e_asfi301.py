"""Synthetic end-to-end coverage for the asfi301 write CLI."""
import unittest

from tests.e2e_backend import add, spec, action, update
from tests.e2e_support import EndToEndMixin


ENTRY_ARGS = {
    'prefix': 'TST01',
    'department_vendor': 'V001',
    'product': 'ITEM-001',
    'quantity': 42,
    'remark': 'first line\nsecond line',
    'expected_manufacturing_department': 'D001',
    'confirm_write': True,
}


def form_field(ident, name, value=''):
    return add(ident, 'FormField', {'name': name, 'value': value, 'active': '1'})


def input_dialog():
    return add(2942, 'Dialog', {'active': '1'},
               spec('DialogInfo', 2943, {'dialogType': 'Input'})
               + spec('Action', 2944, {'name': 'accept', 'active': '1'}))


def detail_table():
    values = ''.join(spec('Value', 810 + index, {'value': f'ROW-{index}'})
                     for index in range(10))
    return add(808, 'Table', {'name': 's_sfa', 'size': '26', 'offset': '0',
                              'pageSize': '10'},
               spec('TableColumn', 809, {'colName': 'sfa03'},
                    spec('ValueList', 820, children=values)))


def work_order_workflow(peer, mismatch, continue_after_mismatch=False):
    manufacturing_department = 'WRONG' if mismatch else 'D001'
    peer.send(
        add(0, 'Interface', {'name': 'asfi301', 'focus': '0'}),
        form_field(104, 'sfb_file.sfb01', 'old'),
        form_field(112, 'sfb_file.sfb44'),
        form_field(118, 'sfb_file.sfb81'),
        form_field(121, 'sfb_file.sfb02'),
        form_field(129, 'sfb_file.sfb39'),
        form_field(212, 'sfb_file.sfb82'),
        form_field(214, 'formonly.pmc03'),
        form_field(217, 'formonly.ta_sfb06', manufacturing_department),
        form_field(219, 'formonly.ta_sfb06_name', 'Synthetic factory'),
        form_field(254, 'sfb_file.sfb05'),
        form_field(259, 'formonly.ima02'),
        form_field(274, 'sfb_file.sfb08'),
        form_field(279, 'sfb_file.sfb07'),
        form_field(355, 'formonly.ta_sfb09'),
        form_field(418, 'sfb_file.sfb96'),
        action(2693, 'insert'), action(900, 'exit'))
    peer.expect('ActionEvent', 'idRef "2693"')

    peer.send(update(104, value='     -         '), update(0, focus='104'), input_dialog())
    peer.expect('ConfigureEvent', 'idRef "104"', 'value "TST01-         "',
                'KeyEvent', 'keyName "Tab"')
    peer.send(update(104, value='TST01-'), update(0, focus='112'))
    peer.expect('KeyEvent', 'keyName "Tab"')
    peer.send(update(0, focus='118'))
    peer.expect('KeyEvent', 'keyName "Tab"')
    peer.send(update(0, focus='121'))
    peer.expect('KeyEvent', 'keyName "Tab"')
    peer.send(update(0, focus='129'))
    if mismatch and not continue_after_mismatch:
        return
    peer.expect('ConfigureEvent', 'idRef "212"', 'cursor "4"')

    peer.send(update(0, focus='212'))
    peer.expect('ConfigureEvent', 'idRef "212"', 'value "V001"',
                'KeyEvent', 'keyName "Tab"')
    peer.send(update(212, value='V001'), update(214, value='Synthetic vendor'),
              update(0, focus='217'))
    peer.expect('ConfigureEvent', 'idRef "254"', 'cursor "0"')
    peer.send(update(0, focus='254'))
    peer.expect('ConfigureEvent', 'idRef "254"', 'value "ITEM-001"',
                'KeyEvent', 'keyName "Tab"')
    peer.send(update(254, value='ITEM-001'), update(259, value='Synthetic product'),
              update(0, focus='274'))
    peer.expect('ConfigureEvent', 'idRef "274"', 'value "42"',
                'KeyEvent', 'keyName "Tab"')
    peer.send(update(274, value='42.000'), update(0, focus='279'))
    peer.expect('ConfigureEvent', 'idRef "355"', 'cursor "0"')
    peer.send(update(0, focus='355'))
    peer.expect('ConfigureEvent', 'idRef "418"', 'cursor "0"')
    peer.send(update(0, focus='418'))
    peer.expect('ConfigureEvent', 'idRef "418"',
                r'value "first line\nsecond line"', 'ActionEvent', 'idRef "2944"')

    peer.send('{rn 2942}', update(104, value='TST01-123456789'),
              update(418, value='first line\nsecond line'),
              add(800, 'Message', {'type': 'error', 'text': '(csf-a06) synthetic warning'}),
              detail_table())


def unguarded_work_order_workflow(peer, mismatch):
    work_order_workflow(peer, True, continue_after_mismatch=True)


class Asfi301EndToEndTests(EndToEndMixin, unittest.TestCase):
    def test_asfi301_end_to_end_submits_once_and_returns_number(self):
        doc = self.invoke('asfi301', ENTRY_ARGS, 'asfi301.schema.json',
                          work_order_workflow, require_complete=False)
        self.assertEqual(doc['query'], {
            **{key: value for key, value in ENTRY_ARGS.items() if key != 'confirm_write'},
            'operation': 'create_one', 'automatic_retry': False,
        })
        self.assertEqual(doc['data']['status'], 'server_confirmed')
        self.assertEqual(doc['data']['work_order_number'], 'TST01-123456789')
        self.assertEqual(doc['data']['fields_verified']['department_vendor_name'],
                         'Synthetic vendor')
        self.assertEqual(doc['data']['fields_verified']['remark'],
                         'first line\nsecond line')
        self.assertEqual(doc['data']['detail'], {
            'expected_row_count': 26, 'visible_row_count': 10,
            'column_count': 1, 'complete': False,
        })
        self.assertEqual(doc['data']['persistence_readback'], 'not_performed')

    def test_asfi301_rejects_wrong_manufacturing_department_before_submit(self):
        self.invoke('asfi301', ENTRY_ARGS, 'asfi301.schema.json',
                    work_order_workflow, mismatch=True, require_complete=False)

    def test_asfi301_accepts_omitted_manufacturing_department_guard(self):
        args = {key: value for key, value in ENTRY_ARGS.items()
                if key != 'expected_manufacturing_department'}
        doc = self.invoke('asfi301', args, 'asfi301.schema.json',
                          unguarded_work_order_workflow, require_complete=False)
        self.assertTrue(doc['ok'])
        self.assertNotIn('expected_manufacturing_department', doc['query'])
        self.assertEqual(doc['data']['fields_verified']['manufacturing_department'],
                         'WRONG')


if __name__ == '__main__':
    unittest.main()
