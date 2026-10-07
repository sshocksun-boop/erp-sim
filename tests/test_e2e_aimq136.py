"""Synthetic end-to-end coverage for the aimq136 WIP-detail CLI."""
import unittest

from tests.e2e_backend import add, spec, action, update
from tests.e2e_support import EndToEndMixin


ITEM = 'ITEM-001'
ROWS = [
    {'sfb01': 'WO-001', 'sfb04': '2', 'sfb82': '5387', 'sfb82_n': 'Synthetic dept',
     'sfb13': '26/10/20', 'sfb15': '26/10/20', 'sfb08': '10.000',
     'woo_qty': '10.000', 'sub_qty': '0.000'},
    {'sfb01': 'WO-002', 'sfb04': '2', 'sfb82': '5387', 'sfb82_n': 'Synthetic dept',
     'sfb13': '26/11/08', 'sfb15': '26/11/08', 'sfb08': '20.000',
     'woo_qty': '20.000', 'sub_qty': '0.000'},
    {'sfb01': 'WO-003', 'sfb04': '7', 'sfb82': '5387', 'sfb82_n': 'Synthetic dept',
     'sfb13': '27/01/13', 'sfb15': '27/01/13', 'sfb08': '50.000',
     'woo_qty': '1.000', 'sub_qty': '0.000'},
]
COLUMNS = [
    ('sfb01', '工单单号'), ('sfb04', '状态'), ('sfb82', '部门/厂商'),
    ('sfb82_n', '简称'), ('sfb13', '预计开工日'), ('sfb15', '预计完工日'),
    ('sfb08', '生产数量'), ('woo_qty', '工单在制量'), ('sub_qty', '委外在制量'),
]


def wip_table(offset, rows, total=3):
    columns = []
    for column_index, (name, label) in enumerate(COLUMNS):
        ident = 170 + column_index * 10
        values = ''.join(spec('Value', ident + 2 + row_index, {'value': row[name]})
                         for row_index, row in enumerate(rows))
        columns.append(spec('TableColumn', ident, {'colName': name, 'text': label},
                            spec('ValueList', ident + 1, children=values)))
    return add(169, 'Table', {'name': 's_sr', 'dialogType': 'DisplayArray',
                              'active': '1', 'size': total, 'offset': offset,
                              'pageSize': 2}, ''.join(columns))


def initial_fields():
    fields = [('ima_file.ima01', ''), ('ima_file.ima02', ''), ('ima_file.ima021', ''),
              ('ima_file.ima08', ''), ('formonly.cnt', ''), ('formonly.cn2', ''),
              ('formonly.sum_qty', ''), ('formonly.sum_woo', ''), ('formonly.sum_sub', '')]
    return [add(100 + index, 'FormField', {'name': name, 'value': value})
            for index, (name, value) in enumerate(fields)]


def aimq136_workflow(peer, mismatch):
    peer.send(add(0, 'Interface', {'name': 'aimq136'}),
              *initial_fields(),
              update(100, active='0'),
              action(500, 'query'), action(900, 'exit'))
    peer.expect('ActionEvent', 'idRef "500"')
    peer.send(update(100, active='1'), action(400, 'accept'))
    peer.expect('ConfigureEvent', 'idRef "100"', 'value "ITEM-001"',
                'ActionEvent', 'idRef "400"')
    # Single accept: one response carries the echo lock, header fields,
    # counters, totals and the first table page.
    peer.send(update(100, value='OTHER-ITEM' if mismatch else ITEM, active='0'),
              update(101, value='Synthetic product'),
              update(102, value='230V'),
              update(103, value='P'),
              update(104, value='1'), update(105, value='3'),
              update(106, value='80.000'), update(107, value='31.000'),
              update(108, value='0.000'),
              wip_table(0, ROWS[:2]))
    if mismatch:
        return
    peer.expect('ConfigureEvent', 'idRef "169"', 'offset "1"')
    peer.send('{rn 169}', wip_table(1, ROWS[1:]))


class Aimq136EndToEndTests(EndToEndMixin, unittest.TestCase):
    def test_aimq136_end_to_end_paginated(self):
        doc = self.invoke('aimq136', {'item': ITEM}, 'aimq136.schema.json',
                          aimq136_workflow)
        self.assertEqual(doc['query'], {'item': ITEM})
        self.assertEqual(doc['data'], {
            'item': ITEM, 'description': 'Synthetic product', 'specification': '230V',
            'source_code': 'P',
            'production_qty_total': '80.000', 'wo_in_process_total': '31.000',
            'subcontract_in_process_total': '0.000',
            'columns': [{'id': name, 'label': label} for name, label in COLUMNS],
            'rows': ROWS, 'row_count': 3, 'expected_row_count': 3,
            'work_order_count': 3, 'complete': True,
        })

    def test_aimq136_end_to_end_rejects_wrong_item(self):
        self.invoke('aimq136', {'item': ITEM}, 'aimq136.schema.json',
                    aimq136_workflow, mismatch=True)


if __name__ == '__main__':
    unittest.main()
