"""CLI subprocess -> real loopback Telnet/DCP/HTTP -> files and verified logout."""
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker
from tests.e2e_backend import SyntheticErp


class EndToEndMixin:
    def invoke(self, program, feature_args, schema_name, workflow, mismatch=False,
               report_bytes=None, report_path=None, require_complete=True,
               report_handler=None, expected_error=None):
        with tempfile.TemporaryDirectory() as tmp, SyntheticErp(
                program, lambda peer: workflow(peer, mismatch), report_bytes, report_path,
                report_handler) as backend:
            output = Path(tmp) / 'result.json'
            report = Path(tmp) / 'bom.txt'
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('ERP_SIM_')}
            env.update(ERP_SIM_HOST='127.0.0.1', ERP_SIM_CALLBACK_HOST='127.0.0.1',
                       ERP_SIM_TELNET_PORT=str(backend.telnet_port),
                       ERP_SIM_USERNAME='synthetic-user', ERP_SIM_PASSWORD='synthetic-password',
                       ERP_SIM_HOSTNAME='synthetic-client', PYTHONIOENCODING='utf-8',
                       NO_PROXY='127.0.0.1', no_proxy='127.0.0.1')
            for key in list(env):
                if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy'):
                    del env[key]
            request = {'command': program, 'listen_port': backend.callback_port,
                       'timeout': 40, 'cleanup_timeout': 5, 'output': str(output),
                       'feature_args': dict(feature_args)}
            args = [sys.executable, '-I', '-m', 'erp_sim', '--request', '-']
            input_text = json.dumps(request)
            if report_bytes is not None:
                request['feature_args']['report_output'] = str(report)
                request_file = Path(tmp) / 'request.json'
                request_file.write_text(json.dumps(request), encoding='utf-8-sig')
                args[-1] = str(request_file)
                input_text = None
            backend.reservation.close()
            process = subprocess.run(args, cwd=tmp, env=env, capture_output=True,
                                     encoding='utf-8', input=input_text, timeout=60)
            self.assertTrue(backend.finished.wait(2), 'Synthetic ERP did not finish')
            if backend.error:
                raise AssertionError('Synthetic ERP protocol expectation failed') from backend.error
            self.assertEqual(process.stderr, '')
            # json.loads rejects extra stdout documents or non-JSON logging.
            doc = json.loads(process.stdout)
            self.assertEqual(output.read_text(encoding='utf-8'), process.stdout)
            schema = json.loads(files('erp_sim.resources').joinpath(schema_name).read_text())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(doc)
            self.assertEqual(doc['command'], program)
            self.assertEqual(doc['session'], {'logout_verified': True})
            self.assertEqual(backend.logout_actions, ['feature_exit', 'menu_exit'])
            for secret in ('synthetic-password', 'synthetic-user', 'synthetic-client'):
                self.assertNotIn(secret, process.stdout + process.stderr)
            if expected_error:
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(doc['ok'])
                self.assertEqual(doc['error']['code'], expected_error)
                self.assertIsNone(doc['data'])
                self.assertFalse(report.exists())
            elif mismatch:
                self.assertEqual(process.returncode, 8)
                self.assertFalse(doc['ok'])
                self.assertEqual(doc['error']['code'], 'CONDITION_MISMATCH')
                self.assertIsNone(doc['data'])
                self.assertEqual(backend.downloads, [])
                self.assertFalse(report.exists())
            else:
                self.assertEqual(process.returncode, 0)
                self.assertTrue(doc['ok'])
                self.assertIsNone(doc['error'])
                if require_complete:
                    self.assertTrue(doc['data']['complete'])
                if report_bytes is not None:
                    self.assertEqual(backend.downloads, [report_path])
                    self.assertEqual(report.read_bytes(), report_bytes)
            return doc
