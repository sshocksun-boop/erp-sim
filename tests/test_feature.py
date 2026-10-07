from datetime import date
import unittest
from erp_sim.features.cxmr4103 import OrderQuery, Cxmr4103
from erp_sim.errors import ErpError
from tests.helpers import FakeChannel, result_tree, node

QUERY = OrderQuery('S1702*', date(2026,9,10), date(2026,9,11))
ROW = {'oea01_1':'S1702-0001', 'oea02':'26/09/10', 'oeb12':'0.000'}


class FeatureTests(unittest.TestCase):
    def test_invalid_queries_fail_before_network(self):
        for pattern, start, end in [('x"}', date(2026,9,10), date(2026,9,11)),
                                     ('S*', date(2026,9,11), date(2026,9,10)),
                                     ('S*', date(1999,1,1), date(2000,1,1))]:
            with self.assertRaises(ErpError): OrderQuery(pattern, start, end)

    def test_input_focus_and_two_date_submission_events(self):
        ch = FakeChannel(result_tree(QUERY)); feature = Cxmr4103(QUERY, pause=lambda _:None)
        feature.advance(ch); feature.advance(ch)
        events = [p[9:].decode() for p in ch.sent if p[8] == 1]
        self.assertEqual(len(events), 6)
        self.assertIn('value "26/09/10"', events[4])
        self.assertNotIn('ActionEvent', events[4])
        self.assertIn('value "26/09/11"', events[5])
        self.assertIn('ActionEvent', events[5])

    def test_conditions_and_each_row_are_verified(self):
        variants = [('condition', ROW), ('pattern', {**ROW,'oea01_1':'S1701-1'}),
                    ('date', {**ROW,'oea02':'26/09/09'})]
        for kind, row in variants:
            tree = result_tree(QUERY,{0:row}); ch=FakeChannel(tree); f=Cxmr4103(QUERY)
            if kind=='condition': tree.nodes[103]['attrs']['value']='26/09/01'
            with self.assertRaises(ErpError) as caught: f.collect(ch,[(169,tree.nodes[169])])
            self.assertEqual(caught.exception.code,'CONDITION_MISMATCH')
            self.assertFalse(f.done)
            self.assertIsNone(f.result)

    def test_multiple_tables_pagination_and_no_progress(self):
        tree=result_tree(QUERY,{0:ROW},3); ch=FakeChannel(tree); f=Cxmr4103(QUERY)
        node(tree,500,'Table',{'dialogType':'DisplayArray'},[501]);node(tree,501,'TableColumn',{'colName':'other'})
        f.collect(ch,[(169,tree.nodes[169])])
        self.assertIn(b'idRef "169"',ch.sent[-1]);self.assertIn(b'offset "1"',ch.sent[-1])
        self.assertFalse(f.result['complete'])
        with self.assertRaises(ErpError) as caught:f.collect(ch,[(169,tree.nodes[169])])
        self.assertEqual(caught.exception.code,'INCOMPLETE_RESULT')

    def test_complete_result_and_zero_are_distinct_from_missing(self):
        for rows in ({}, {0:ROW,1:{**ROW,'oeb12':''}}):
            tree=result_tree(QUERY,rows);ch=FakeChannel(tree);f=Cxmr4103(QUERY)
            f.collect(ch,[(169,tree.nodes[169])])
            self.assertTrue(f.done);self.assertTrue(f.result['complete'])
            self.assertEqual(f.result['row_count'],len(rows))
            self.assertEqual(f.result['rows'],list(rows.values()))
        self.assertEqual(f.result['order_count'],1)

    def test_features_do_not_share_mutable_state(self):
        a,b=Cxmr4103(QUERY),Cxmr4103(QUERY)
        a.requested_offsets.add(1)
        self.assertEqual(b.requested_offsets,set())
