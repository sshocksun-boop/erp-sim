"""Synthetic end-to-end coverage for the aimq131 material-order CLI."""
import unittest

from tests.e2e_backend import add, spec, action, update
from tests.e2e_support import EndToEndMixin


ITEM = 'ITEM-001'
ROWS = [
    {'oeb01': 'ORDER-001', 'oeb03': '1', 'oea03': 'CUSTOMER-001',
     'occ02': 'Synthetic customer', 'oeb15': '26/09/28', 'oeb12': '10.000',
     'on_order': '2.000', 'oeb05': 'PCS'},
    {'oeb01': 'ORDER-001', 'oeb03': '2', 'oea03': 'CUSTOMER-001',
     'occ02': 'Synthetic customer', 'oeb15': '26/09/29', 'oeb12': '20.000',
     'on_order': '5.000', 'oeb05': 'PCS'},
    {'oeb01': 'ORDER-002', 'oeb03': '1', 'oea03': 'CUSTOMER-002',
     'occ02': 'Second customer', 'oeb15': '26/09/30', 'oeb12': '30.000',
     'on_order': '8.000', 'oeb05': 'PCS'},
]
COLUMNS = [
    ('oeb01', '订单单号'), ('oeb03', '项次'), ('oea03', '客户'), ('occ02', '简称'),
    ('oeb15', '交货日期'), ('oeb12', '受订量'), ('on_order', '未出货量'),
    ('oeb05', '单位'),
]


def result_table(offset, rows, total=3):
    columns = []
    for column_index, (name, label) in enumerate(COLUMNS):
        ident = 170 + column_index * 10
        values = ''.join(spec('Value', ident + 2 + row_index,
                              {'value': row[name]})
                         for row_index, row in enumerate(rows))
        columns.append(spec('TableColumn', ident, {'colName': name, 'text': label},
                            spec('ValueList', ident + 1, children=values)))
    return add(169, 'Table', {'name': 's_sr', 'dialogType': 'DisplayArray',
                             'active': '1', 'size': total, 'offset': offset,
                             'pageSize': 2}, ''.join(columns))


def aimq_workflow(peer, mismatch):
    peer.send(add(0, 'Interface', {'name': 'aimq131'}),
              add(100, 'FormField', {'name': 'ima_file.ima01', 'value': '', 'active': '0'}),
              add(101, 'FormField', {'name': 'ima_file.ima02', 'value': ''}),
              add(102, 'FormField', {'name': 'ima_file.ima021', 'value': ''}),
              add(103, 'FormField', {'name': 'formonly.cn2', 'value': ''}),
              add(104, 'FormField', {'name': 'formonly.oeb12_t', 'value': ''}),
              add(105, 'FormField', {'name': 'formonly.oeb12_o', 'value': ''}),
              action(500, 'query'), action(900, 'exit'))
    peer.expect('ActionEvent', 'idRef "500"')
    peer.send(update(100, active='1'), action(400, 'accept'))
    peer.expect('ConfigureEvent', 'idRef "100"', 'value "ITEM-001"',
                'ActionEvent', 'idRef "400"')
    peer.send(update(100, value='OTHER-ITEM' if mismatch else ITEM, active='0'),
              update(101, value='Synthetic product'),
              update(102, value='Synthetic specification'),
              update(103, value='3'), update(104, value='60.000'),
              update(105, value='15.000'),
              result_table(0, ROWS[:2]),
              add(800, 'Table', {'name': 'unrelated', 'dialogType': 'DisplayArray',
                                  'active': '1', 'size': '1'}))
    if mismatch:
        return
    peer.expect('ConfigureEvent', 'idRef "169"', 'offset "1"')
    peer.send('{rn 169}', result_table(1, ROWS[1:]))


class Aimq131EndToEndTests(EndToEndMixin, unittest.TestCase):
    def test_aimq131_end_to_end_paginated(self):
        doc = self.invoke('aimq131', {'item': ITEM}, 'aimq131.schema.json',
                          aimq_workflow)
        self.assertEqual(doc['query'], {'item': ITEM})
        self.assertEqual(doc['data'], {
            'item': ITEM, 'description': 'Synthetic product',
            'specification': 'Synthetic specification',
            'columns': [{'id': name, 'label': label} for name, label in COLUMNS],
            'rows': ROWS, 'row_count': 3, 'expected_row_count': 3,
            'order_count': 2, 'ordered_quantity_total': '60.000',
            'open_quantity_total': '15.000', 'complete': True,
        })

    def test_aimq131_end_to_end_rejects_wrong_item(self):
        self.invoke('aimq131', {'item': ITEM}, 'aimq131.schema.json',
                    aimq_workflow, mismatch=True)


if __name__ == '__main__':
    unittest.main()
