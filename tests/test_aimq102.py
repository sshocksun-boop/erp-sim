"""Offline feature checks independent of production captures and credentials."""
import unittest

from erp_sim.errors import ErpError
from erp_sim.features.aimq102 import Aimq102, StockQuery
from erp_sim.protocol.dcp import AuiTree
from tests.e2e_backend import add, spec
from tests.helpers import FakeChannel


STOCK_ROW = {'img02': 'WH-001', 'imd02': 'Synthetic warehouse', 'img03': '',
             'ime03': '', 'img04': '', 'img23': 'Y', 'img10': '10.000',
             'sig05': '', 'img09': 'PCS', 'img38': ''}
STOCK_COLUMNS = ('img02', 'imd02', 'img03', 'ime03', 'img04', 'img23',
                 'img10', 'sig05', 'img09', 'img38')
MASTER = (('ima_file.ima05', ''), ('ima_file.ima06', '1000'),
          ('ima_file.ima25', 'PCS'), ('ima_file.ima08', 'P'),
          ('ima_file.ima37', '2'), ('ima_file.ima906', ''),
          ('ima_file.ima907', ''), ('ima_file.ima70', 'N'),
          ('ima_file.ima15', 'N'))
QUANTITIES = (('formonly.avl_stk', '10.000'), ('formonly.oeb_q', '2.000'),
              ('formonly.sfa_q1', '0.000'), ('formonly.sfa_q2', '0.000'),
              ('formonly.pml_q', '0.000'), ('formonly.pmn_q', '1.000'),
              ('formonly.sfb_q1', '0.000'), ('formonly.sfb_q2', '0.000'),
              ('formonly.rvb_q2', '0.000'), ('formonly.rvb_q', '0.000'),
              ('formonly.qcf_q', '0.000'), ('formonly.atp_qty', '7.000'),
              ('formonly.unavl_stk', '0.000'), ('formonly.sie_q', '0.000'))
# Summary-grid column -> header field; quantities may differ in decimal scale.
SUMMARY_TEXT = (('ima01_1', 'ima_file.ima01'), ('ima02_1', 'ima_file.ima02'),
                ('ima021_1', 'ima_file.ima021'), ('ima05_1', 'ima_file.ima05'),
                ('ima06_1', 'ima_file.ima06'), ('ima25_1', 'ima_file.ima25'),
                ('ima08_1', 'ima_file.ima08'), ('ima37_1', 'ima_file.ima37'),
                ('ima70_1', 'ima_file.ima70'), ('ima15_1', 'ima_file.ima15'))
SUMMARY_QTY = (('avl_stk_1', 'formonly.avl_stk'), ('oeb_q_1', 'formonly.oeb_q'),
               ('sfa_q1_1', 'formonly.sfa_q1'), ('sfa_q2_1', 'formonly.sfa_q2'),
               ('pml_q_1', 'formonly.pml_q'), ('pmn_q_1', 'formonly.pmn_q'),
               ('sfb_q1_1', 'formonly.sfb_q1'), ('sfb_q2_1', 'formonly.sfb_q2'),
               ('rvb_q2_1', 'formonly.rvb_q2'), ('rvb_q_1', 'formonly.rvb_q'),
               ('qcf_q_1', 'formonly.qcf_q'), ('unavl_stk_1', 'formonly.unavl_stk'),
               ('sie_q_1', 'formonly.sie_q'))


def result_tree(*, item='ITEM-001', rows=None, total=None, cn2=None, cnt='1',
                quantities=None, summary_values=None, drop_column=None):
    rows = [dict(STOCK_ROW)] if rows is None else rows
    total = len(rows) if total is None else total
    quantities = dict(QUANTITIES, **(quantities or {}))
    fields = [('ima_file.ima01', item), ('ima_file.ima02', 'Synthetic product'),
              ('ima_file.ima021', '230V'), ('formonly.cnt', cnt),
              ('formonly.cn2', str(total) if cn2 is None else cn2)]
    fields.extend(MASTER)
    fields.extend(quantities.items())
    commands = [add(0, 'Interface', {'name': 'aimq102'})]
    commands.extend(add(i, 'FormField', {'name': name, 'value': value})
                    for i, (name, value) in enumerate(fields, 100))
    columns = []
    for index, name in enumerate(STOCK_COLUMNS):
        if name == drop_column:
            continue
        ident = 200 + index * 10
        values = ''.join(spec('Value', ident + 2 + row_index, {'value': row[name]})
                         for row_index, row in enumerate(rows))
        columns.append(spec('TableColumn', ident, {'colName': name, 'text': name},
                            spec('ValueList', ident + 1, children=values)))
    commands.append(add(190, 'Table', {'name': 's_img', 'dialogType': 'DisplayArray',
                                       'active': '1', 'size': str(total), 'offset': '0',
                                       'pageSize': '16'}, ''.join(columns)))
    summary = {}
    for column, field in (*SUMMARY_TEXT, *SUMMARY_QTY):
        summary[column] = fields_value(fields, field)
    summary['atp_qty_1'] = '9.000'  # legitimately differs from the header value
    summary.update(summary_values or {})
    summary_columns = []
    for index, (column, value) in enumerate(summary.items()):
        ident = 400 + index * 10
        summary_columns.append(spec('TableColumn', ident, {'colName': column},
                                    spec('ValueList', ident + 1,
                                         children=spec('Value', ident + 2,
                                                       {'value': value}))))
    commands.append(add(390, 'Table', {'name': 'table1', 'dialogType': 'DisplayArray',
                                       'active': '1', 'size': '1', 'offset': '0',
                                       'pageSize': '5'}, ''.join(summary_columns)))
    return AuiTree('img02').apply('om 0 {' + ''.join(commands) + '}\n')


def fields_value(fields, name):
    return next(value for field, value in fields if field == name)


class Aimq102Tests(unittest.TestCase):
    def driver(self):
        feature = Aimq102(StockQuery('ITEM-001'))
        feature.query_clicked = feature.submitted = feature.confirmed = True
        return feature

    def test_input_matches_existing_single_item_boundary(self):
        self.assertEqual(StockQuery('ITEM-001').as_dict(), {'item': 'ITEM-001'})
        for value in ('', 'bad item', 'bad*item', 'x"}', 'X' * 81):
            with self.subTest(value=value), self.assertRaises(ErpError):
                StockQuery(value)

    def test_complete_result_preserves_strings(self):
        feature = self.driver()
        feature.advance(FakeChannel(result_tree()))
        self.assertTrue(feature.done)
        result = feature.result
        self.assertEqual(result['rows'], [STOCK_ROW])
        self.assertEqual(result['warehouse_count'], 1)
        self.assertEqual(result['available_stock'], '10.000')
        self.assertEqual(result['projected_available_header'], '7.000')
        self.assertEqual(result['projected_available_table'], '9.000')
        self.assertEqual(result['group_code'], '1000')
        self.assertEqual(result['stock_unit'], 'PCS')

    def test_explicit_zero_result_is_complete(self):
        feature = self.driver()
        feature.advance(FakeChannel(result_tree(rows=[], cn2='0')))
        self.assertTrue(feature.done)
        self.assertEqual(feature.result['rows'], [])
        self.assertEqual(feature.result['row_count'], 0)
        self.assertEqual(feature.result['expected_row_count'], 0)
        self.assertEqual(feature.result['warehouse_count'], 0)
        self.assertTrue(feature.result['complete'])

    def test_wrong_echo_and_missing_column_are_rejected(self):
        for tree, code in [(result_tree(item='OTHER'), 'CONDITION_MISMATCH'),
                           (result_tree(drop_column='img23'), 'PROTOCOL_ERROR')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_counter_mismatch_is_rejected(self):
        with self.assertRaises(ErpError) as caught:
            self.driver().advance(FakeChannel(result_tree(cn2='5')))
        self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')

    def test_summary_scale_difference_is_tolerated_but_text_mismatch_is_not(self):
        scaled = self.driver()
        scaled.advance(FakeChannel(result_tree(
            summary_values={'oeb_q_1': '2.00'})))
        self.assertTrue(scaled.done)
        for tree, code in [(result_tree(summary_values={'ima06_1': '9999'}), 'PROTOCOL_ERROR'),
                           (result_tree(summary_values={'avl_stk_1': '9.000'}),
                            'PROTOCOL_ERROR')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_invalid_quantity_and_single_row_mismatch_are_rejected(self):
        for tree, code in [(result_tree(quantities={'formonly.avl_stk': 'NaN'}),
                            'PROTOCOL_ERROR'),
                           (result_tree(quantities={'formonly.avl_stk': '9.000'},
                                        summary_values={'avl_stk_1': '9.000'}),
                            'INCOMPLETE_RESULT')]:
            with self.subTest(code=code), self.assertRaises(ErpError) as caught:
                self.driver().advance(FakeChannel(tree))
            self.assertEqual(caught.exception.code, code)

    def test_multi_row_result_stays_incomplete_after_pagination(self):
        rows = [dict(STOCK_ROW), dict(STOCK_ROW, img02='WH-002', img10='5.000',
                                      imd02='Second warehouse')]
        feature = self.driver()
        channel = FakeChannel(result_tree(rows=rows[:1], total='2'))
        feature.advance(channel)  # page one is incomplete: offset re-request
        self.assertFalse(feature.done)
        self.assertTrue(channel.touched)
        channel.tree = result_tree(rows=rows, total='2')  # page two arrives
        with self.assertRaises(ErpError) as caught:
            feature.advance(channel)
        self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')
        self.assertFalse(feature.result['complete'])
        self.assertEqual(feature.result['row_count'], 2)
        self.assertEqual(feature.result['warehouse_count'], 2)

    def test_pagination_must_make_progress(self):
        feature = self.driver()
        channel = FakeChannel(result_tree(rows=[dict(STOCK_ROW)], total='2'))
        feature.advance(channel)
        self.assertTrue(channel.touched)
        with self.assertRaises(ErpError) as caught:
            feature.advance(channel)  # same page again
        self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')


if __name__ == '__main__':
    unittest.main()
