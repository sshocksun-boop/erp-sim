"""Synthetic end-to-end coverage for the abmr001 BOM CLI."""
import unittest
import time

from tests.e2e_backend import add, spec, field, action, update
from tests.e2e_support import EndToEndMixin


REPORT = '''测试公司
产品结构表
制表日期:26/09/16 12:00:00 有效日期:26/09/16  版本:V1  页次:1

ROOT-001  (测试主件)
    ├0010──COMP-A  M   PCS 1 (一级组件) * 1.000 DRAW-A PCS 1.000000
    │                              补充说明
    │   └0020──COMP-B  P   G 1 (二级组件) * 2.500 MISC G 0.001000
    └0030──COMP-C  P   PCS 1 (另一个一级组件) * 3.000 MISC PCS 1.000000
'''.encode('utf-8')
REPORT_PATH = '/topprod/tiptop/out/abmr001synthetic.01.txt'


def bom_workflow(peer, mismatch):
    peer.send(add(0, 'Interface'), field(99, 'bma01'), action(501), action(900, 'exit'))
    peer.expect('value "ROOT-001"', 'ActionEvent', 'idRef "501"')
    peer.send(update(99, value='ROOT-001', active='0'), '{rn 501}',
              field(125, 's', '3'), action(516))
    peer.expect('ConfigureEvent', 'idRef "125"', 'cursor "0"')
    peer.expect('idRef "125"', 'value "1"', 'ActionEvent', 'idRef "516"')
    peer.send(update(125, value='1', active='0'), '{rn 516}',
              field(519, 'choice', 'V'), field(541, 'choice4', 'T'), action(544))
    peer.expect('idRef "519"', 'value "O"')
    peer.send(update(519, value='O'))
    peer.expect('idRef "541"', 'cursor "0"')
    peer.expect('ActionEvent', 'idRef "544"')
    peer.send(update(519, active='0'), update(541, active='0'),
              update(99, value='OTHER' if mismatch else 'ROOT-001'),
              add(700, 'FunctionCall', {'moduleName': 'standard', 'name': 'shellexec'},
                  spec('FunctionCallParameter', 701,
                       {'value': f'EXPLORER "http://127.0.0.1{REPORT_PATH}"'})))
    if not mismatch:
        peer.expect('FunctionCallReturn', 'dataType "INTEGER"', 'value "1"')


class Abmr001EndToEndTests(EndToEndMixin, unittest.TestCase):
    def test_slow_report_starts_only_after_server_logout(self):
        observations = []

        def slow_report(handler, backend):
            observations.append(backend.finished.wait(1) and backend.error is None
                                and backend.logout_actions == ['feature_exit', 'menu_exit'])
            handler.send_response(200)
            handler.send_header('Content-Length', str(len(REPORT)))
            handler.end_headers()
            for offset in range(0, len(REPORT), 100):
                handler.wfile.write(REPORT[offset:offset + 100])
                handler.wfile.flush()
                time.sleep(0.05)

        self.invoke('abmr001', {'item': 'ROOT-001'}, 'abmr001.schema.json',
                    bom_workflow, report_bytes=REPORT, report_path=REPORT_PATH,
                    report_handler=slow_report)
        self.assertEqual(observations, [True])

    def test_download_failure_preserves_verified_logout(self):
        def missing_report(handler, backend):
            handler.send_error(404)

        self.invoke('abmr001', {'item': 'ROOT-001'}, 'abmr001.schema.json',
                    bom_workflow, report_bytes=REPORT, report_path=REPORT_PATH,
                    report_handler=missing_report, expected_error='CONNECTION_FAILED')

    def test_abmr001_end_to_end(self):
        doc = self.invoke('abmr001', {'item': 'ROOT-001'}, 'abmr001.schema.json',
                          bom_workflow, report_bytes=REPORT, report_path=REPORT_PATH)
        self.assertEqual(doc['query'], {'item': 'ROOT-001', 'sort': 'bom_sequence',
                                      'output_format': 'text'})
        data = doc['data']
        self.assertEqual(data['component_count'], len(data['components']))
        self.assertEqual(data['component_count'], 3)
        self.assertEqual(data['item'], 'ROOT-001')
        self.assertEqual(data['description'], '测试主件')
        self.assertEqual(data['effective_date'], '26/09/16')
        self.assertEqual(data['report_created_at'], '26/09/16 12:00:00')
        self.assertEqual(data['version'], 'V1')
        self.assertEqual([row['level'] for row in data['components']], [1, 2, 1])
        self.assertEqual([row['parent_item'] for row in data['components']],
                         ['ROOT-001', 'COMP-A', 'ROOT-001'])
        self.assertEqual([row['sequence'] for row in data['components']], ['0010', '0020', '0030'])
        self.assertEqual(data['components'][0]['notes'], ['补充说明'])
        self.assertEqual(data['components'][1]['quantity'], '2.500')

    def test_abmr001_end_to_end_rejects_wrong_conditions_before_download(self):
        self.invoke('abmr001', {'item': 'ROOT-001'}, 'abmr001.schema.json',
                          bom_workflow, report_bytes=REPORT, report_path=REPORT_PATH, mismatch=True)
