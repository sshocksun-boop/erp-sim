"""Synthetic end-to-end coverage for the aimq102 stock-detail CLI."""
import unittest

from tests.e2e_backend import add, spec, action, update
from tests.e2e_support import EndToEndMixin


ITEM = 'ITEM-001'
STOCK_COLUMNS = ('img02', 'imd02', 'img03', 'ime03', 'img04', 'img23',
                 'img10', 'sig05', 'img09', 'img38')
STOCK_ROW = {'img02': 'WH-001', 'imd02': 'Synthetic warehouse', 'img03': '',
             'ime03': '', 'img04': '', 'img23': 'Y', 'img10': '10.000',
             'sig05': '', 'img09': 'PCS', 'img38': ''}
MASTER = (('ima05', ''), ('ima06', '1000'), ('ima25', 'PCS'), ('ima08', 'P'),
          ('ima37', '2'), ('ima906', ''), ('ima907', ''), ('ima70', 'N'),
          ('ima15', 'N'))
QUANTITIES = (('avl_stk', '10.000'), ('oeb_q', '2.000'), ('sfa_q1', '0.000'),
              ('sfa_q2', '0.000'), ('pml_q', '0.000'), ('pmn_q', '1.000'),
              ('sfb_q1', '0.000'), ('sfb_q2', '0.000'), ('rvb_q2', '0.000'),
              ('rvb_q', '0.000'), ('qcf_q', '0.000'), ('atp_qty', '7.000'),
              ('unavl_stk', '0.000'), ('sie_q', '0.000'))
HEADER_FIELDS = (
    ('ima_file.ima02', 'Synthetic product'), ('ima_file.ima021', '230V'),
    ('formonly.cnt', '1'), ('formonly.cn2', '1'),
    *[('ima_file.' + name, value) for name, value in MASTER],
    *[('formonly.' + name, value) for name, value in QUANTITIES],
)


def stock_table(rows, total):
    columns = []
    for index, name in enumerate(STOCK_COLUMNS):
        ident = 200 + index * 10
        values = ''.join(spec('Value', ident + 2 + row_index, {'value': row[name]})
                         for row_index, row in enumerate(rows))
        columns.append(spec('TableColumn', ident, {'colName': name, 'text': name},
                            spec('ValueList', ident + 1, children=values)))
    return add(190, 'Table', {'name': 's_img', 'dialogType': 'DisplayArray',
                              'active': '1', 'size': total, 'offset': '0',
                              'pageSize': '15'}, ''.join(columns))


def summary_table():
    values = {'ima01_1': ITEM, 'ima02_1': 'Synthetic product', 'ima021_1': '230V'}
    values.update({'ima05_1': '', 'ima06_1': '1000', 'ima25_1': 'PCS',
                   'ima08_1': 'P', 'ima37_1': '2', 'ima70_1': 'N', 'ima15_1': 'N'})
    values.update({name + '_1': value for name, value in QUANTITIES})
    values['atp_qty_1'] = '9.000'
    columns = []
    for index, (name, value) in enumerate(values.items()):
        ident = 400 + index * 10
        columns.append(spec('TableColumn', ident, {'colName': name},
                            spec('ValueList', ident + 1,
                                 children=spec('Value', ident + 2, {'value': value}))))
    return add(390, 'Table', {'name': 'table1', 'dialogType': 'DisplayArray',
                              'active': '1', 'size': '1', 'offset': '0',
                              'pageSize': '5'}, ''.join(columns))


def initial_fields():
    fields = [('ima_file.ima01', ''), ('ima_file.ima02', ''), ('ima_file.ima021', ''),
              ('formonly.cnt', ''), ('formonly.cn2', ''),
              *[('ima_file.' + name, value) for name, value in MASTER],
              *[('formonly.' + name, value) for name, value in QUANTITIES]]
    return [add(100 + index, 'FormField', {'name': name, 'value': value})
            for index, (name, value) in enumerate(fields)]


def aimq_workflow(peer, mismatch, zero=False):
    peer.send(add(0, 'Interface', {'name': 'aimq102'}),
              *initial_fields(),
              update(100, active='0'),
              action(500, 'query'), action(900, 'exit'))
    peer.expect('ActionEvent', 'idRef "500"')
    peer.send(update(100, active='1'), action(400, 'accept'))
    peer.expect('ConfigureEvent', 'idRef "100"', 'value "ITEM-001"',
                'ActionEvent', 'idRef "400"')
    if mismatch:
        # The server locks a foreign echo; the client must reject it before
        # sending the second accept.
        peer.send(update(100, value='OTHER-ITEM', active='0'))
        return
    peer.send('{rn 400}', update(100, value=ITEM, active='0'), action(600, 'accept'))
    peer.expect('ActionEvent', 'idRef "600"')
    commands = [update(101 + index, value=value)
                for index, (name, value) in enumerate(HEADER_FIELDS)]
    if zero:
        commands[3] = update(104, value='0')
        commands.append(stock_table([], '0'))
    else:
        commands.append(stock_table([STOCK_ROW], '1'))
    commands.append(summary_table())
    peer.send(*commands)


class Aimq102EndToEndTests(EndToEndMixin, unittest.TestCase):
    def test_aimq102_end_to_end_single_row(self):
        doc = self.invoke('aimq102', {'item': ITEM}, 'aimq102.schema.json',
                          aimq_workflow)
        self.assertEqual(doc['query'], {'item': ITEM})
        self.assertEqual(doc['data'], {
            'item': ITEM, 'description': 'Synthetic product', 'specification': '230V',
            'current_version': '', 'group_code': '1000', 'stock_unit': 'PCS',
            'source_code': 'P', 'replenish_code': '2', 'unit_policy': '',
            'second_unit': '', 'consumable': 'N', 'bonded': 'N',
            'available_stock': '10.000', 'ordered_qty': '2.000',
            'wo_material_prepared': '0.000', 'wo_material_short': '0.000',
            'purchase_request_qty': '0.000', 'purchase_order_qty': '1.000',
            'wo_in_process': '0.000', 'subcontract_in_process': '0.000',
            'subcontract_iqc_inspect': '0.000', 'iqc_inspect': '0.000',
            'fqc_inspect': '0.000', 'projected_available_header': '7.000',
            'projected_available_table': '9.000',
            'unavailable_stock': '0.000', 'setup_qty': '0.000',
            'columns': [{'id': name, 'label': name} for name in STOCK_COLUMNS],
            'rows': [STOCK_ROW], 'row_count': 1, 'expected_row_count': 1,
            'warehouse_count': 1, 'complete': True,
        })

    def test_aimq102_end_to_end_zero_rows(self):
        doc = self.invoke('aimq102', {'item': ITEM}, 'aimq102.schema.json',
                          lambda peer, mismatch: aimq_workflow(peer, mismatch, zero=True))
        self.assertEqual(doc['data']['rows'], [])
        self.assertEqual(doc['data']['row_count'], 0)
        self.assertEqual(doc['data']['expected_row_count'], 0)
        self.assertEqual(doc['data']['warehouse_count'], 0)
        self.assertTrue(doc['data']['complete'])

    def test_aimq102_end_to_end_rejects_wrong_item(self):
        self.invoke('aimq102', {'item': ITEM}, 'aimq102.schema.json',
                    aimq_workflow, mismatch=True)


if __name__ == '__main__':
    unittest.main()
