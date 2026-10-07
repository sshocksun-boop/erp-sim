import unittest

from erp_sim.errors import ErpError
from erp_sim.features.abmr001 import BomQuery, Abmr001, parse_bom_report, report_request
from erp_sim.protocol.dcp import AuiTree
from tests.helpers import FakeChannel, node


REPORT = '''莱克电气股份有限公司
产品结构表
制表日期:26/09/15 16:07:05 有效日期:26/09/15  版本:V1  页次:1

ROOT-001  (测试主件)
    ├0010──COMP-A  M   PCS 1 (一级组件) * 1.000 DRAW-A PCS 1.000000
    │                              补充说明
    │   ├0020──COMP-B  P   G 1 (二级组件) * 2.500 MISC G 0.001000
    │   │   └0030──COMP-C  S   PCS 2 (三级组件) * 1.000/ 100.000 DRAW-C PCS 1.000000
    └0040──COMP-D  P   PCS 1 (另一个一级组件) * 3.000 MISC PCS 1.000000
'''


def stage_tree(fields, accept=None, function_url=None):
    tree = AuiTree(None)
    for ident, name, value, active in fields:
        node(tree, ident, 'FormField', {
            'name': 'formonly.' + name, 'value': value, 'active': active,
        })
    if accept is not None:
        node(tree, accept, 'Action', {'name': 'accept', 'active': '1'})
    if function_url is not None:
        node(tree, 700, 'FunctionCall', {'moduleName': 'standard', 'name': 'shellexec'}, [701])
        node(tree, 701, 'FunctionCallParameter', {'value': f'EXPLORER "{function_url}"'})
    return tree


class Response:
    def __init__(self, content, url):
        self.content = content
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.content


class Abmr001Tests(unittest.TestCase):
    def test_query_validation_and_public_conditions(self):
        self.assertEqual(BomQuery('ROOT-001').as_dict(), {
            'item': 'ROOT-001', 'sort': 'bom_sequence', 'output_format': 'text',
        })
        for value in ('', 'bad item', 'bad*item', 'x"}'):
            with self.assertRaises(ErpError):
                BomQuery(value)

    def test_report_parser_preserves_hierarchy_strings_and_notes(self):
        result = parse_bom_report(REPORT, 'ROOT-001')
        self.assertTrue(result['complete'])
        self.assertEqual(result['component_count'], 4)
        self.assertEqual([row['level'] for row in result['components']], [1, 2, 3, 1])
        self.assertEqual(result['components'][1]['parent_item'], 'COMP-A')
        self.assertEqual(result['components'][2]['parent_item'], 'COMP-B')
        self.assertEqual(result['components'][0]['notes'], ['补充说明'])
        self.assertEqual(result['components'][2]['sequence'], '0030')
        self.assertEqual(result['components'][2]['quantity_numerator'], '1.000')
        self.assertEqual(result['components'][2]['quantity'], '100.000')

    def test_report_parser_distinguishes_empty_from_mismatch_and_bad_rows(self):
        empty = '\n'.join(line for line in REPORT.splitlines() if '──' not in line)
        result = parse_bom_report(empty, 'ROOT-001')
        self.assertTrue(result['complete'])
        self.assertEqual(result['component_count'], 0)
        self.assertEqual(result['components'], [])
        cases = [
            ('OTHER', REPORT, 'CONDITION_MISMATCH'),
            ('ROOT-001', REPORT.replace('├0010──', '├0010--'), 'PROTOCOL_ERROR'),
            ('ROOT-001', REPORT.replace('DRAW-A PCS 1.000000', 'unknown columns'), 'PROTOCOL_ERROR'),
        ]
        for item, report, code in cases:
            with self.assertRaises(ErpError) as caught:
                parse_bom_report(report, item)
            self.assertEqual(caught.exception.code, code)

    def test_report_parser_rejects_truncated_component_prefixes(self):
        last_line = next(line for line in REPORT.splitlines() if '└0040' in line)
        start = REPORT.index(last_line)
        branch = last_line.index('└')
        for end in range(branch + 1, branch + len('└0040──') + 1):
            with self.subTest(fragment=last_line[:end]):
                truncated = REPORT[:start] + last_line[:end]
                with self.assertRaises(ErpError) as caught:
                    parse_bom_report(truncated, 'ROOT-001')
                self.assertEqual(caught.exception.code, 'INCOMPLETE_RESULT')

    def test_report_parser_allows_branch_glyphs_inside_notes(self):
        report = REPORT.replace('补充说明', '补充说明 └ 仅作文本')
        result = parse_bom_report(report, 'ROOT-001')
        self.assertEqual(result['components'][0]['notes'], ['补充说明 └ 仅作文本'])

    def test_protocol_sequence_matches_report_workflow(self):
        query = BomQuery('ROOT-001')
        url = 'http://erp-report.test/topprod/tiptop/out/abmr001user.01.txt'
        response = Response(REPORT.encode(), url)
        feature = Abmr001(query, fetch=lambda *args, **kwargs: response)
        channel = FakeChannel(stage_tree([(99, 'bma01', '', '1')], 501))

        feature.advance(channel)
        channel.tree = stage_tree([(99, 'bma01', 'ROOT-001', '0'), (125, 's', '3', '1')], 516)
        feature.advance(channel)
        feature.advance(channel)
        channel.tree = stage_tree([
            (99, 'bma01', 'ROOT-001', '0'), (125, 's', '1', '0'),
            (519, 'choice', 'V', '1'), (541, 'choice4', 'T', '1'),
        ], 544)
        feature.advance(channel)
        channel.tree.nodes[519]['attrs']['value'] = 'O'
        feature.advance(channel)
        feature.advance(channel)
        channel.tree = stage_tree([
            (99, 'bma01', 'ROOT-001', '0'), (125, 's', '1', '0'),
            (519, 'choice', 'O', '0'), (541, 'choice4', 'T', '0'),
        ], function_url=url)
        feature.advance(channel)

        events = [payload[9:].decode() for payload in channel.sent if payload[8] == 1]
        self.assertEqual(len(events), 7)
        self.assertIn('value "ROOT-001"', events[0])
        self.assertIn('idRef "501"', events[0])
        self.assertIn('idRef "125"', events[1])
        self.assertIn('value "1"', events[2])
        self.assertIn('idRef "516"', events[2])
        self.assertIn('value "O"', events[3])
        self.assertIn('idRef "541"', events[4])
        self.assertIn('idRef "544"', events[5])
        self.assertIn('FunctionCallReturn', events[6])
        self.assertTrue(feature.erp_done)
        self.assertFalse(feature.done)
        self.assertIsNone(feature.result)
        feature.finish()
        self.assertTrue(feature.done)
        self.assertEqual(feature.result['component_count'], 4)
        self.assertEqual(feature.report_bytes, REPORT.encode())

    def test_report_request_rejects_arbitrary_shell_or_redirect(self):
        tree = stage_tree([], function_url='http://erp-report.test/not-allowed/file.txt')
        with self.assertRaises(ErpError) as caught:
            report_request(tree)
        self.assertEqual(caught.exception.code, 'PROTOCOL_ERROR')

        url = 'http://erp-report.test/topprod/tiptop/out/abmr001user.01.txt'
        response = Response(REPORT.encode(), 'http://other.test/topprod/tiptop/out/abmr001user.01.txt')
        feature = Abmr001(BomQuery('ROOT-001'), fetch=lambda *args, **kwargs: response)
        feature.item_submitted = feature.sort_submitted = True
        feature.output_submitted = True
        channel = FakeChannel(stage_tree([
            (99, 'bma01', 'ROOT-001', '0'), (125, 's', '1', '0'),
        ], function_url=url))
        feature.advance(channel)
        with self.assertRaises(ErpError) as caught:
            feature.finish()
        self.assertEqual(caught.exception.code, 'PROTOCOL_ERROR')

    def test_server_condition_mismatch_is_rejected_before_download(self):
        url = 'http://erp-report.test/topprod/tiptop/out/abmr001user.01.txt'
        feature = Abmr001(BomQuery('ROOT-001'), fetch=lambda *args, **kwargs: self.fail('downloaded'))
        feature.item_submitted = feature.sort_submitted = True
        feature.output_submitted = True
        channel = FakeChannel(stage_tree([
            (99, 'bma01', 'OTHER', '0'), (125, 's', '1', '0'),
        ], function_url=url))
        with self.assertRaises(ErpError) as caught:
            feature.advance(channel)
        self.assertEqual(caught.exception.code, 'CONDITION_MISMATCH')


if __name__ == '__main__':
    unittest.main()
