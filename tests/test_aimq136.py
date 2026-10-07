"""Offline feature checks independent of production captures and credentials."""
import unittest

from erp_sim.errors import ErpError
from erp_sim.features.aimq136 import Aimq136, WipQuery
from erp_sim.protocol.dcp import AuiTree
from tests.e2e_backend import add, spec
from tests.helpers import FakeChannel


ROW = {'sfb01': 'WO-001', 'sfb04': '2', 'sfb82': '5387', 'sfb82_n': 'Synthetic dept',
       'sfb13': '26/10/20', 'sfb15': '26/10/20', 'sfb08': '10.000',
       'woo_qty': '10.000', 'sub_qty': '0.000'}
COLUMNS = ('sfb01', 'sfb04', 'sfb82', 'sfb82_n', 'sfb13', 'sfb15',
           'sfb08', 'woo_qty', 'sub_qty')


def result_tree(*, item='ITEM-001', rows=None, include_order=True,
                total=None, cnt='1', cn2=None, sum_qty=None,
                sum_woo=None, sum_sub='0.000'):
    rows = [dict(ROW)] if rows is None else rows
    total = len(rows) if total is None else total
    sum_qty = sum(float(row['sfb08']) for row in rows) if sum_qty is None else sum_qty
    sum_woo = sum(float(row['woo_qty']) for row in rows) if sum_woo is None else sum_woo
    fields = [
        (100, 'ima_file.ima01', item), (101, 'ima_file.ima02', 'Synthetic product'),
        (102, 'ima_file.ima021', '230V'), (103, 'ima_file.ima08', 'P'),
        (104, 'formonly.cnt', cnt),
        (105, 'formonly.cn2', str(total) if cn2 is None else cn2),
        (106, 'formonly.sum_qty', f'{sum_qty:.3f}' if isinstance(sum_qty, float) else sum_qty),
        (107, 'formonly.sum_woo', f'{sum_woo:.3f}' if isinstance(sum_woo, float) else sum_woo),
        (108, 'formonly.sum_sub', sum_sub),
    ]
    commands = [add(0, 'Interface', {'name': 'aimq136'})]
    commands.extend(add(i, 'FormField', {'name': name, 'value': value})
                    for i, name, value in fields)
    columns = []
    for index, name in enumerate(COLUMNS):
        if name == 'sfb01' and not include_order:
            continue
        values = ''.join(spec('Value', 202 + index * 10 + row_index,
                              {'value': row[name]})
                         for row_index, row in enumerate(rows))
        columns.append(spec('TableColumn', 200 + index * 10,
                            {'colName': name, 'text': name},
                            spec('ValueList', 201 + index * 10, children=values)))
    commands.append(add(190, 'Table', {'name': 's_sr', 'dialogType': 'DisplayArray',
                                       'active': '1', 'size': str(total), 'offset': '0',
                                       'pageSize': '1'}, ''.join(columns)))
    return AuiTree('sfb01').apply('om 0 {' + ''.join(commands) + '}\n')


class Aimq136Tests(unittest.TestCase):
    def driver(self):
        feature = Aimq136(WipQuery('ITEM-001'))
        feature.query_clicked = feature.submitted = True
        return feature

    def test_input_matches_existing_single_item_boundary(self):
        self.assertEqual(WipQuery('ITEM-001').as_dict(), {'item': 'ITEM-001'})
        for value in ('', 'bad item', 'bad*item', 'x"}', 'X' * 81):
            with self.subTest(value=value), self.assertRaises(ErpError):
                WipQuery(value)

    def test_complete_result_preserves_strings(self):
        feature = self.driver()
        feature.advance(FakeChannel(result_tree()))
        self.assertTrue(feature.done)
        result = feature.result
        self.assertEqual(result['rows'], [ROW])
        self.assertEqual(result['work_order_count'], 1)
        self.assertEqual(result['source_code'], 'P')
        self.assertEqual(result['production_qty_total'], '10.000')
        self.assertEqual(result['wo_in_process_total'], '10.000')
        self.assertEqual(result['subcontract_in_process_total'], '0.000')
        self.assertEqual([column['id'] for column in result['columns']], list(COLUMNS))

    def test_zero_row_fails_closed_with_evidence(self):
        feature = self.driver()
        with self.assertRaises(ErpError) as caught:
            feature.advance(FakeChannel(result_tree(rows=[], total=0, cn2='0',
                                                    sum_qty='0.000',
                                                    sum_woo='0.000')))
        self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')
        self.assertFalse(feature.done)
        self.assertIsNotNone(feature.result)
        self.assertFalse(feature.result['complete'])
        self.assertEqual(feature.result['rows'], [])
        self.assertEqual(feature.result['row_count'], 0)

    def test_wrong_echo_and_missing_column_are_rejected(self):
        for tree, code in [(result_tree(item='OTHER'), 'CONDITION_MISMATCH'),
                           (result_tree(include_order=False), 'PROTOCOL_ERROR')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_counter_mismatches_are_rejected(self):
        for tree, code in [(result_tree(cn2='5'), 'INCOMPLETE_RESULT'),
                           (result_tree(cnt='2'), 'INCOMPLETE_RESULT')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_total_mismatch_and_invalid_quantity_are_rejected(self):
        nan_row = dict(ROW, sfb08='NaN')
        for tree, code in [(result_tree(sum_woo='9.000'), 'INCOMPLETE_RESULT'),
                           (result_tree(sum_sub=''), 'INCOMPLETE_RESULT'),
                           (result_tree(rows=[nan_row]), 'PROTOCOL_ERROR')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_duplicate_work_order_is_rejected(self):
        rows = [dict(ROW), dict(ROW, sfb13='26/11/08')]
        tree = result_tree(rows=rows)
        with self.assertRaises(ErpError) as caught:
            self.driver().advance(FakeChannel(tree))
        self.assertEqual(caught.exception.code, 'PROTOCOL_ERROR')

    def test_missing_row_cannot_become_complete(self):
        feature = self.driver()
        channel = FakeChannel(result_tree(rows=[dict(ROW)], total=2, cn2='2'))
        feature.advance(channel)
        self.assertFalse(feature.done)
        self.assertTrue(channel.touched)
        with self.assertRaises(ErpError) as caught:
            feature.advance(channel)
        self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')


if __name__ == '__main__':
    unittest.main()
