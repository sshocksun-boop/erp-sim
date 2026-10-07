"""Offline feature checks independent of production captures and credentials."""
import unittest

from erp_sim.errors import ErpError
from erp_sim.features.aimq131 import Aimq131, ItemQuery
from erp_sim.protocol.dcp import AuiTree
from tests.e2e_backend import add, spec
from tests.helpers import FakeChannel


ROW = {'oeb01': 'ORDER-001', 'oeb03': '1', 'oea03': 'CUSTOMER-001',
       'occ02': 'Synthetic customer', 'oeb15': '26/09/28',
       'oeb12': '10.000', 'on_order': '2.000', 'oeb05': 'PCS'}


def result_tree(*, item='ITEM-001', quantity='10.000', include_order=True,
                total='1', ordered_total='10.000', open_total='2.000'):
    fields = [
        (100, 'ima_file.ima01', item), (101, 'ima_file.ima02', 'Synthetic product'),
        (102, 'ima_file.ima021', '230V'), (103, 'formonly.cn2', total),
        (104, 'formonly.oeb12_t', ordered_total),
        (105, 'formonly.oeb12_o', open_total),
    ]
    commands = [add(0, 'Interface', {'name': 'aimq131'})]
    commands.extend(add(i, 'FormField', {'name': name, 'value': value})
                    for i, name, value in fields)
    columns = []
    for index, (name, value) in enumerate({**ROW, 'oeb12': quantity}.items()):
        if name == 'oeb01' and not include_order:
            continue
        ident = 200 + index * 10
        columns.append(spec('TableColumn', ident, {'colName': name, 'text': name},
                            spec('ValueList', ident + 1,
                                 children=spec('Value', ident + 2, {'value': value}))))
    commands.append(add(190, 'Table', {'name': 's_sr', 'dialogType': 'DisplayArray',
                                       'active': '1', 'size': total, 'offset': '0',
                                       'pageSize': '1'}, ''.join(columns)))
    return AuiTree('oeb01').apply('om 0 {' + ''.join(commands) + '}\n')


class Aimq131Tests(unittest.TestCase):
    def driver(self):
        feature = Aimq131(ItemQuery('ITEM-001'))
        feature.query_clicked = feature.submitted = True
        return feature

    def test_input_matches_existing_single_item_boundary(self):
        self.assertEqual(ItemQuery('ITEM-001').as_dict(), {'item': 'ITEM-001'})
        for value in ('', 'bad item', 'bad*item', 'x"}', 'X' * 81):
            with self.subTest(value=value), self.assertRaises(ErpError):
                ItemQuery(value)

    def test_complete_result_preserves_strings(self):
        feature = self.driver()
        feature.advance(FakeChannel(result_tree()))
        self.assertTrue(feature.done)
        self.assertEqual(feature.result['rows'], [ROW])
        self.assertEqual(feature.result['order_count'], 1)

    def test_explicit_zero_result_is_distinct_from_missing_data(self):
        feature = self.driver()
        feature.advance(FakeChannel(result_tree(total='0', ordered_total='0.000',
                                                open_total='0.000')))
        self.assertTrue(feature.done)
        self.assertEqual(feature.result['rows'], [])
        self.assertEqual(feature.result['expected_row_count'], 0)

    def test_wrong_echo_and_missing_column_are_rejected(self):
        for tree, code in [(result_tree(item='OTHER'), 'CONDITION_MISMATCH'),
                           (result_tree(include_order=False), 'PROTOCOL_ERROR')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_wrong_total_and_invalid_quantity_are_rejected(self):
        for tree, code in [(result_tree(ordered_total='9.000'), 'INCOMPLETE_RESULT'),
                           (result_tree(quantity='NaN'), 'PROTOCOL_ERROR')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_missing_row_cannot_become_complete(self):
        feature = self.driver()
        channel = FakeChannel(result_tree(total='2'))
        feature.advance(channel)
        self.assertFalse(feature.done)
        self.assertTrue(channel.touched)
        with self.assertRaises(ErpError) as caught:
            feature.advance(channel)
        self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')


if __name__ == '__main__':
    unittest.main()
