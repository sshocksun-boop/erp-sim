import contextlib
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from erp_sim import __version__
from erp_sim.cli import FEATURES, main, envelope, atomic_write, atomic_write_bytes
from erp_sim.config import load_settings, Settings, detect_callback_host
from erp_sim.errors import ErpError
from erp_sim.session import SessionResult

ENV = {'ERP_SIM_HOST':'erp.test', 'ERP_SIM_CALLBACK_HOST':'127.0.0.1',
       'ERP_SIM_USERNAME':'test', 'ERP_SIM_PASSWORD':'top-secret'}
QUERY = {'command':'cxmr4103','feature_args':{'pattern':'S1702*','date_from':'2026-09-10','date_to':'2026-09-11'}}
BOM_QUERY = {'command':'abmr001','feature_args':{'item':'ROOT-001'}}
WORK_ORDER = {'command':'asfi301','feature_args':{'prefix':'TST01',
    'department_vendor':'V001','product':'ITEM-001','quantity':42,
    'remark':'first line\nsecond line','expected_manufacturing_department':'D001',
    'confirm_write':True}}
CLI_CREDENTIALS = {'username':'cli-user','password':'cli-secret'}


class ConfigCliTests(unittest.TestCase):
    def test_package_version_matches_metadata_lock_and_discovery(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
        lock = tomllib.loads((root / 'uv.lock').read_text(encoding='utf-8'))
        locked_package = next(package for package in lock['package']
                              if package['name'] == 'erp-sim')
        self.assertEqual(project['project']['version'], __version__)
        self.assertEqual(locked_package['version'], __version__)
        for command in ('version', 'capabilities'):
            with self.subTest(command=command):
                code, document, _ = self.invoke({'command': command})
                self.assertEqual(code, 0)
                self.assertEqual(document['version'], __version__)

    def test_work_order_json_integer_numbers_reach_driver_as_int(self):
        for quantity in (42, 42.0, 4.2e1, 1.0, 99999999.0):
            request = {**WORK_ORDER, 'feature_args': {
                **WORK_ORDER['feature_args'], 'quantity': quantity}}
            with self.subTest(quantity=quantity), patch('erp_sim.cli.GdcSession') as session:
                session.return_value.execute.return_value = SessionResult(None, True, None)
                code, document, _ = self.invoke(request, ENV)
                self.assertEqual(code, 0)
                entry = session.return_value.execute.call_args.args[0].entry
                self.assertIs(type(entry.quantity), int)
                self.assertEqual(entry.quantity, int(quantity))
                self.assertIs(type(document['query']['quantity']), int)

    def test_invalid_work_order_quantity_is_rejected_before_session(self):
        for quantity in (42.5, True, '42', 0, -1, 100000000, float('inf'), float('nan')):
            request = {**WORK_ORDER, 'feature_args': {
                **WORK_ORDER['feature_args'], 'quantity': quantity}}
            with self.subTest(quantity=quantity), patch('erp_sim.cli.GdcSession') as session:
                code, document, _ = self.invoke(request, ENV)
                self.assertEqual(code, 2)
                self.assertEqual(document['error']['code'], 'INVALID_ARGUMENT')
                session.assert_not_called()

    def invoke(self, args, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict('os.environ', env or {}, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([json.dumps(args)] if isinstance(args, dict) else args)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_configuration_precedence_and_secret_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.toml'
            path.write_text('[connection]\nhost="file.test"\nlisten_port=6402\nhostname="file-host"\n')
            cfg=load_settings(path,{'listen_port':6404,'hostname':'cli-host'},
                              {**ENV,'ERP_SIM_LISTEN_PORT':'6403','ERP_SIM_HOSTNAME':'env-host'})
        self.assertEqual((cfg.host,cfg.listen_port,cfg.hostname),('erp.test',6404,'cli-host'))
        self.assertNotIn('top-secret',repr(cfg))

    def test_host_defaults_and_callback_uses_selected_route(self):
        env={'ERP_SIM_USERNAME':'test','ERP_SIM_PASSWORD':'top-secret'}
        with patch('erp_sim.config.detect_callback_host',return_value='192.168.29.68') as detect:
            cfg=load_settings(environ=env)
        self.assertEqual(cfg.host,'192.168.0.160')
        self.assertEqual(cfg.callback_host,'192.168.29.68')
        detect.assert_called_once_with('192.168.0.160',23)

    def test_explicit_callback_overrides_detection(self):
        with patch('erp_sim.config.detect_callback_host') as detect:
            cfg=load_settings(environ=ENV)
        self.assertEqual(cfg.callback_host,'127.0.0.1')
        detect.assert_not_called()

    def test_callback_override_can_use_the_default_host(self):
        env={'ERP_SIM_CALLBACK_HOST':'192.0.2.10','ERP_SIM_USERNAME':'test',
             'ERP_SIM_PASSWORD':'top-secret'}
        with patch('erp_sim.config.detect_callback_host') as detect:
            cfg=load_settings(environ=env)
        self.assertEqual((cfg.host,cfg.callback_host),('192.168.0.160','192.0.2.10'))
        detect.assert_not_called()

    def test_callback_detection_failure_is_actionable_config_error(self):
        env={'ERP_SIM_USERNAME':'test','ERP_SIM_PASSWORD':'top-secret'}
        with patch('erp_sim.config.socket.getaddrinfo',side_effect=OSError):
            with self.assertRaises(ErpError) as caught:
                load_settings(environ=env)
        self.assertEqual(caught.exception.code,'CONFIG_ERROR')
        self.assertIn('ERP_SIM_CALLBACK_HOST',str(caught.exception))

    def test_callback_detection_uses_ipv4_route_to_effective_server(self):
        route=unittest.mock.MagicMock()
        route.__enter__.return_value=route
        route.getsockname.return_value=('192.168.29.68',49152)
        target=(2,2,17,'',('192.168.0.160',23))
        with patch('erp_sim.config.socket.getaddrinfo',return_value=[target]) as resolve, \
             patch('erp_sim.config.socket.socket',return_value=route) as create:
            actual=detect_callback_host('192.168.0.160',23)
        self.assertEqual(actual,'192.168.29.68')
        resolve.assert_called_once_with('192.168.0.160',23,2,2)
        create.assert_called_once_with(2,2)
        route.connect.assert_called_once_with(('192.168.0.160',23))

    def test_config_rejects_shell_characters_password_file_and_nonfinite_timeout(self):
        for env in ({**ENV,'ERP_SIM_CALLBACK_HOST':'127.0.0.1;bad'},
                    {**ENV,'ERP_SIM_TIMEOUT':'nan'}, {**ENV,'ERP_SIM_USERNAME':'x\ncommand'},
                    {**ENV,'ERP_SIM_HOSTNAME':'bad host'},
                    {**ENV,'ERP_SIM_CALLBACK_HOST':'','ERP_SIM_HOST':'bad\nname'}):
            with self.assertRaises(ErpError):load_settings(environ=env)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.toml';path.write_text('[connection]\npassword="secret"')
            with self.assertRaises(ErpError):load_settings(path,environ=ENV)


    def test_discovery_requires_no_credentials_or_network(self):
        with patch('erp_sim.cli.GdcSession') as session, patch('erp_sim.cli.load_settings') as settings:
            for command in ('capabilities','features','schema','version'):
                code, doc, logs = self.invoke({'command': command})
                self.assertEqual(code, 0)
                self.assertIsInstance(doc, dict)
                self.assertEqual(logs, '')
            session.assert_not_called()
            settings.assert_not_called()
        code, schema, _ = self.invoke({'command':'schema','feature_args':{'kind':'response','feature':'abmr001'}})
        self.assertEqual(code, 0)
        self.assertEqual(schema['properties']['command']['const'], 'abmr001')
        caps = self.invoke({'command':'capabilities'})[1]
        self.assertFalse(caps['input']['legacy_cli_supported'])
        self.assertEqual(caps['configuration_precedence'][0], 'JSON request')
        self.assertNotIn('global_options', caps)
        for request in [caps['schemas']['request'], caps['schemas']['request_error'], *caps['schemas']['responses'].values()]:
            self.assertEqual(self.invoke(request)[0], 0)

    def test_features_lists_json_commands(self):
        code, doc, logs = self.invoke({'command':'features'})
        self.assertEqual((code, logs), (0, ''))
        self.assertEqual(doc['schema_version'], '3')
        self.assertEqual(doc['data'], {'count':6,'features':[
            {'program':'cxmr4103','description':'销售订单查询','command':'cxmr4103'},
            {'program':'abmr001','description':'产品结构表查询','command':'abmr001'},
            {'program':'aimq131','description':'料件订单受订量明细查询','command':'aimq131'},
            {'program':'aimq102','description':'料件数量明细查询-动态资料','command':'aimq102'},
            {'program':'aimq136','description':'料件在制量明细查询','command':'aimq136'},
            {'program':'asfi301','description':'工单维护作业','command':'asfi301'}]})

    def test_feature_registration_matches_public_schemas(self):
        metadata_commands = {'capabilities', 'features', 'schema', 'version'}
        request_schema = self.invoke({'command':'schema'})[1]
        branches = {branch['properties']['command']['const']: branch
                    for branch in request_schema['oneOf']}
        self.assertEqual(set(FEATURES), set(branches) - metadata_commands)

        schema_args = branches['schema']['properties']['feature_args']['oneOf']
        response_options = next(option for option in schema_args
                                if option['properties']['kind']['const'] == 'response')
        self.assertEqual(set(FEATURES), set(response_options['properties']['feature']['enum']))

        capabilities = self.invoke({'command':'capabilities'})[1]
        listed = self.invoke({'command':'features'})[1]['data']['features']
        version = self.invoke({'command':'version'})[1]
        self.assertEqual(capabilities['commands'],
                         ['capabilities', 'features', 'schema', 'version', *FEATURES])
        self.assertEqual([item['command'] for item in listed], list(FEATURES))
        self.assertEqual(set(capabilities['schemas']['responses']), set(FEATURES))
        self.assertEqual(capabilities['response_versions'], version['response_versions'])

        for name, spec in FEATURES.items():
            with self.subTest(feature=name):
                request = {'command': 'schema', 'feature_args':
                           {'kind': 'response', 'feature': name}}
                code, response_schema, _ = self.invoke(request)
                self.assertEqual(code, 0)
                self.assertEqual(response_schema['properties']['command']['const'], name)
                self.assertEqual(response_schema['properties']['schema_version']['const'],
                                 spec.response_version)
                self.assertEqual(version['response_versions'][name], spec.response_version)
                self.assertEqual(envelope(command=name)['schema_version'], spec.response_version)

    def test_asfi301_builds_write_driver_from_json(self):
        data = {'status':'server_confirmed','work_order_number':'TST01-123456789'}
        with patch('erp_sim.cli.GdcSession') as session:
            session.return_value.execute.return_value = SessionResult(data, True, None)
            code, doc, logs = self.invoke(WORK_ORDER, ENV)
            driver = session.return_value.execute.call_args.args[0]
        self.assertEqual((code, logs), (0, ''))
        self.assertEqual(driver.program, 'asfi301')
        self.assertEqual(driver.entry.remark, 'first line\nsecond line')
        self.assertEqual(doc['query']['operation'], 'create_one')
        self.assertFalse(doc['query']['automatic_retry'])

    def test_asfi301_accepts_omitted_manufacturing_department_guard(self):
        data = {'status':'server_confirmed','work_order_number':'TST01-123456789'}
        request = {**WORK_ORDER, 'feature_args': {
            key: value for key, value in WORK_ORDER['feature_args'].items()
            if key != 'expected_manufacturing_department'}}
        with patch('erp_sim.cli.GdcSession') as session:
            session.return_value.execute.return_value = SessionResult(data, True, None)
            code, doc, logs = self.invoke(request, ENV)
            driver = session.return_value.execute.call_args.args[0]
        self.assertEqual((code, logs), (0, ''))
        self.assertIsNone(driver.entry.expected_manufacturing_department)
        self.assertNotIn('expected_manufacturing_department', doc['query'])

    def test_asfi301_requires_explicit_write_confirmation(self):
        with patch('erp_sim.cli.GdcSession') as session:
            request = {**WORK_ORDER, 'feature_args': {**WORK_ORDER['feature_args'],
                                                      'confirm_write': False}}
            code, doc, _ = self.invoke(request, ENV)
        self.assertEqual(code, 2)
        self.assertEqual(doc['error']['code'], 'INVALID_ARGUMENT')
        session.assert_not_called()

    def test_legacy_cli_is_rejected_without_echo_or_network(self):
        with patch('erp_sim.cli.GdcSession') as session:
            for args in ([], ['features'], ['schema','abmr001'], ['abmr001','--item','ROOT-001'],
                         ['--password','secret-value','abmr001'], ['--format','json'],
                         ['--request','missing','--password','secret-value']):
                code, doc, logs = self.invoke(args)
                self.assertEqual(code, 2)
                self.assertEqual(doc['error']['code'], 'INVALID_ARGUMENT')
                self.assertNotIn('secret-value', json.dumps(doc) + logs)
            session.assert_not_called()

    def test_query_validation_precedes_configuration_and_network(self):
        with patch('erp_sim.cli.load_settings') as settings, patch('erp_sim.cli.GdcSession') as session:
            for fields in ({'date_from':'20260910'}, {'date_to':'2026-02-30'},
                           {'date_to':'2026-09-09'}, {'pattern':12}):
                request = {**QUERY, 'feature_args': {**QUERY['feature_args'], **fields}}
                self.assertEqual(self.invoke(request)[0], 2)
            settings.assert_not_called()
            session.assert_not_called()

    def test_success_output_and_atomic_file_are_identical(self):
        data = {'complete':True}
        with tempfile.TemporaryDirectory() as tmp, patch('erp_sim.cli.GdcSession') as session:
            session.return_value.execute.return_value = SessionResult(data, True, None)
            path = Path(tmp) / 'result.json'
            code, doc, logs = self.invoke({**QUERY, 'output':str(path)}, ENV)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), doc)
        self.assertEqual((code, logs), (0, ''))
        self.assertTrue(doc['ok'])
        self.assertEqual(datetime.fromisoformat(doc['queried_at']).utcoffset(), timedelta(hours=8))
        self.assertNotIn('top-secret', json.dumps(doc))

    def test_request_credentials_and_hostname_override_environment(self):
        for env in (ENV, {'ERP_SIM_CALLBACK_HOST':'127.0.0.1'}):
            with patch('erp_sim.cli.GdcSession') as session:
                session.return_value.execute.return_value = SessionResult({'complete':True}, True, None)
                code, doc, logs = self.invoke({**QUERY, **CLI_CREDENTIALS, 'hostname':'cli-host'}, env)
            settings = session.call_args.args[0]
            self.assertEqual((settings.username,settings.password,settings.hostname), ('cli-user','cli-secret','cli-host'))
            self.assertEqual(code, 0)
            for secret in ('cli-user','cli-secret','cli-host'):
                self.assertNotIn(secret, json.dumps(doc) + logs)

    def test_feature_args_reject_shared_settings(self):
        with patch('erp_sim.cli.GdcSession') as session:
            for key, value in {'password':'secret-value','timeout':20,'output':'result.json'}.items():
                request = {**BOM_QUERY, 'feature_args':{**BOM_QUERY['feature_args'], key:value}}
                code, doc, logs = self.invoke(request, ENV)
                self.assertEqual(code, 2)
                self.assertNotIn('secret-value', json.dumps(doc) + logs)
            session.assert_not_called()

    def test_failure_preserves_verified_partial_data_and_exit_code(self):
        with patch('erp_sim.cli.GdcSession') as session:
            session.return_value.execute.return_value = SessionResult({'complete':False}, False, ErpError('INCOMPLETE_RESULT','Missing page'))
            code, doc, _ = self.invoke(QUERY, ENV)
        self.assertEqual(code, 9)
        self.assertFalse(doc['ok'])
        self.assertFalse(doc['data']['complete'])

    def test_atomic_failures_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result'
            path.write_bytes(b'original')
            for writer, content in ((atomic_write, 'new'), (atomic_write_bytes, b'new')):
                with patch('erp_sim.cli.os.replace', side_effect=OSError):
                    with self.assertRaises(ErpError):
                        writer(path, content)
                self.assertEqual(path.read_bytes(), b'original')
                self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_abmr001_saves_structured_and_original_outputs(self):
        def execute(driver):
            driver.report_bytes = '产品结构表'.encode()
            return SessionResult({'complete':True}, True, None)
        with tempfile.TemporaryDirectory() as tmp, patch('erp_sim.cli.GdcSession') as session:
            session.return_value.execute.side_effect = execute
            report, output = Path(tmp)/'bom.txt', Path(tmp)/'bom.json'
            request = {**BOM_QUERY, 'output':str(output), 'feature_args':{**BOM_QUERY['feature_args'], 'report_output':str(report)}}
            code, doc, logs = self.invoke(request, ENV)
            self.assertEqual((code, logs), (0, ''))
            self.assertEqual(doc['query'], {'item':'ROOT-001','sort':'bom_sequence','output_format':'text'})
            self.assertEqual(report.read_bytes(), '产品结构表'.encode())
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), doc)

    def test_abmr001_rejects_same_report_and_json_path_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp, patch('erp_sim.cli.GdcSession') as session:
            path = Path(tmp)/'same'
            path.write_text('original')
            request = {**BOM_QUERY, 'output':str(path), 'feature_args':{**BOM_QUERY['feature_args'], 'report_output':str(path)}}
            code, doc, _ = self.invoke(request, ENV)
            self.assertEqual(path.read_text(), 'original')
        self.assertEqual(code, 2)
        self.assertEqual(doc['command'], 'abmr001')
        session.assert_not_called()

    def test_config_failure_is_also_saved_when_output_is_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'failure.json'
            code, doc, _ = self.invoke({**QUERY,'output':str(path)})
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), doc)

    def test_internal_exception_does_not_leak_secrets(self):
        with patch('erp_sim.cli.GdcSession', side_effect=RuntimeError('top-secret')):
            code, doc, logs = self.invoke(QUERY, ENV)
        self.assertEqual(code, 70)
        self.assertNotIn('top-secret', json.dumps(doc) + logs)

    def test_config_parse_failure_does_not_echo_path_or_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'private-identity.toml'
            path.write_text('[connection]\nusername = "private-identity"\nbroken =')
            code, doc, logs = self.invoke({**QUERY,'config':str(path)}, ENV)
        self.assertEqual(code, 3)
        self.assertNotIn('private-identity', json.dumps(doc) + logs)

    def test_discovery_output_failure_uses_error_contract(self):
        with patch('erp_sim.cli.atomic_write', side_effect=ErpError('OUTPUT_ERROR','Could not write output')):
            code, doc, _ = self.invoke({'command':'schema','output':'result.json'})
        self.assertEqual(code, 12)
        self.assertEqual(set(doc), {'schema_version','command','ok','error'})
