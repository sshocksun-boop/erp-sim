"""JSON transports, strict input contracts, and pre-session failure boundaries."""
import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from erp_sim.cli import main
from erp_sim.errors import ErpError
from erp_sim.request import MAX_REQUEST_BYTES, parse_request, request_schema


BOM = {'command':'abmr001', 'feature_args':{'item':'ROOT-001'}}
AIMQ = {'command':'aimq131', 'feature_args':{'item':'ITEM-001'}}
ORDERS = {'command':'cxmr4103', 'feature_args':{
    'pattern':'TEST-*', 'date_from':'2026-09-01', 'date_to':'2026-09-21'}}
WORK_ORDER = {'command':'asfi301', 'feature_args':{
    'prefix':'TST01', 'department_vendor':'V001', 'product':'ITEM-001',
    'quantity':42, 'remark':'first line\nsecond line',
    'expected_manufacturing_department':'D001', 'confirm_write':True}}


class RequestTests(unittest.TestCase):
    def invoke(self, args, stdin=''):
        out, err = io.StringIO(), io.StringIO()
        with patch('sys.stdin', io.StringIO(stdin)), patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, json.loads(out.getvalue()), out.getvalue() + err.getvalue()

    def test_three_transports_and_bom_have_identical_discovery_output(self):
        raw = json.dumps({'command':'features'})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'request with spaces.json'
            path.write_text(raw, encoding='utf-8-sig')
            results = [self.invoke([raw]), self.invoke(['--request',str(path)]),
                       self.invoke(['--request','-'], '\ufeff' + raw)]
        self.assertTrue(all(result[:2] == results[0][:2] for result in results))
        self.assertEqual(results[0][0], 0)

    def test_invalid_json_and_types_never_connect_or_leak(self):
        raw_cases = ['', '[]', 'null', '{}', '{"command":"features"} {}',
                     '{"command":"features","command":"version"}',
                     '{"command":"abmr001","feature_args":{"item":"A","item":"B"}}',
                     '{"command":"private-secret"}',
                     '{"command":"features","private-secret":1}',
                     '{"password":"private-secret",',
                     'NaN', 'Infinity', '[' * 2000,
                     '{"command":"features","output":"\\ud800"}',
                     ' ' * (MAX_REQUEST_BYTES + 1)]
        invalid_objects = [
            {**BOM, 'request_version':2}, {**BOM, 'request_version':'2'},
            {**BOM, 'feature_args':None}, {**BOM, 'item':'ROOT-001'},
            {**BOM, 'feature_args':{'item':123}},
            {**BOM, 'feature_args':{'item':'ROOT-001','pattern':'*'}},
            *[{**BOM, key:value} for key,value in [
                ('username',None), ('password',123), ('password','secret\n'),
                ('listen_port',True), ('listen_port',6401.5), ('listen_port',6501),
                ('listen_port',10**500), ('timeout','150'), ('timeout',False),
                ('timeout',float('nan')), ('timeout',float('inf')), ('timeout',0),
                ('timeout',3601), ('verbose',1), ('output','bad\x00path'), ('output','bad\n'),
                ('format','json')]],
            {'command':'schema','feature_args':{'kind':'response'}},
            {'command':'schema','feature_args':{'feature':'abmr001'}},
            {'command':'features','username':'private-secret'},
        ]
        with patch('erp_sim.cli.GdcSession') as session, patch('erp_sim.cli.load_settings') as settings:
            for raw in raw_cases + [json.dumps(value) for value in invalid_objects]:
                with self.subTest(case=raw[:80] if 'secret' not in raw else 'sensitive case'):
                    code, doc, text = self.invoke(['--request','-'], raw)
                    self.assertEqual(code, 2)
                    self.assertEqual(doc['error']['code'], 'INVALID_ARGUMENT')
                    self.assertNotIn('private-secret', text)
            session.assert_not_called()
            settings.assert_not_called()

    def test_schema_matches_runtime_for_field_type_and_required_mutations(self):
        schema = request_schema()
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        examples = [BOM, AIMQ, ORDERS, WORK_ORDER, {'command':'features'}, {'command':'capabilities'},
                    {'command':'version'}, {'command':'schema'},
                    {'command':'schema','feature_args':{'kind':'request_error'}},
                    {'command':'schema','feature_args':{'kind':'response','feature':'abmr001'}},
                    {'command':'schema','feature_args':{'kind':'response','feature':'aimq131'}}]
        cases = deepcopy(examples)
        for example in examples:
            branch = next(b for b in schema['oneOf'] if b['properties']['command']['const'] == example['command'])
            for key in branch['properties']:
                for value in (None, False, 0, 1.5, [], {}, '', 'unknown'):
                    cases.append({**deepcopy(example), key:value})
            for key in example:
                mutated = deepcopy(example)
                del mutated[key]
                cases.append(mutated)
        for request in (BOM, AIMQ, ORDERS, WORK_ORDER):
            for key in request['feature_args']:
                for value in (None, True, 5, [], {}, '', '2026-02-30', 'trailing\n'):
                    mutated = deepcopy(request)
                    mutated['feature_args'][key] = value
                    cases.append(mutated)
            for key in request['feature_args']:
                mutated = deepcopy(request)
                del mutated['feature_args'][key]
                cases.append(mutated)
        for case in cases:
            with self.subTest(case=case):
                try:
                    parse_request(json.dumps(case))
                    accepted = True
                except ErpError:
                    accepted = False
                self.assertEqual(accepted, validator.is_valid(case))

    def test_asfi301_multiline_remark_and_explicit_confirmation(self):
        self.assertEqual(parse_request(json.dumps(WORK_ORDER))['feature_args']['remark'],
                         'first line\nsecond line')
        without_department_guard = deepcopy(WORK_ORDER)
        del without_department_guard['feature_args']['expected_manufacturing_department']
        parsed = parse_request(json.dumps(without_department_guard))
        self.assertNotIn('expected_manufacturing_department', parsed['feature_args'])
        for changes in ({'confirm_write':False}, {'remark':'line 1\rline 2'},
                        {'remark':'bad\ttext'}, {'quantity':True}):
            request = deepcopy(WORK_ORDER)
            request['feature_args'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ErpError):
                parse_request(json.dumps(request))

    def test_schema_uses_only_supported_validation_keywords(self):
        supported = {'$schema','title','description','default','oneOf','type','additionalProperties',
                     'required','properties','const','enum','minLength','maxLength','pattern',
                     'format','minimum','maximum','exclusiveMinimum'}
        def visit(rule):
            self.assertFalse(set(rule) - supported)
            if 'type' in rule:
                self.assertIn(rule['type'], ('object','string','boolean','number','integer'))
            if 'additionalProperties' in rule:
                self.assertIs(rule['additionalProperties'], False)
            if 'format' in rule:
                self.assertEqual(rule['format'], 'date')
            for nested in rule.get('properties', {}).values():
                visit(nested)
            for nested in rule.get('oneOf', []):
                visit(nested)
        visit(request_schema())

    def test_input_size_utf8_and_missing_file_errors(self):
        raw = b'{"command":"features"}'
        self.assertEqual(parse_request(raw + b' ' * (MAX_REQUEST_BYTES - len(raw)))['command'], 'features')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'private-secret.json'
            for content in (b'\xff', raw + b' ' * MAX_REQUEST_BYTES):
                path.write_bytes(content)
                code, _, text = self.invoke(['--request',str(path)])
                self.assertEqual(code, 2)
                self.assertNotIn('private-secret', text)
            path.unlink()
            self.assertEqual(self.invoke(['--request',str(path)])[0], 2)
            self.assertEqual(self.invoke(['--request',tmp])[0], 2)

    def test_transport_sources_cannot_be_mixed_repeated_or_abbreviated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'request.json'
            path.write_text('{"command":"features"}')
            for args in ([str(path)], ['--req',str(path)],
                         ['--request',str(path),'--request',str(path)],
                         ['--request='+str(path),'--request='+str(path)],
                         ['--request',str(path),'{"command":"features"}']):
                self.assertEqual(self.invoke(args)[0], 2)

    def test_outputs_cannot_overwrite_request_or_config(self):
        with tempfile.TemporaryDirectory() as tmp, patch('erp_sim.cli.GdcSession') as session:
            source = Path(tmp)/'request.json'
            config = Path(tmp)/'connection.toml'
            config.write_text('[connection]')
            for target in (source, config):
                for report in (False, True):
                    request = {**deepcopy(BOM), 'config':str(config)}
                    if report:
                        request['feature_args']['report_output'] = str(target)
                    else:
                        request['output'] = str(target)
                    source.write_text(json.dumps(request), encoding='utf-8')
                    before = source.read_bytes()
                    code, _, _ = self.invoke(['--request',str(source)])
                    self.assertEqual(code, 2)
                    self.assertEqual(source.read_bytes(), before)
                    self.assertEqual(config.read_text(), '[connection]')
            session.assert_not_called()

    def test_invalid_request_does_not_write_requested_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'result.json'
            output.write_text('original')
            request = {**BOM, 'output':str(output), 'feature_args':{'item':None}}
            self.assertEqual(self.invoke([json.dumps(request)])[0], 2)
            self.assertEqual(output.read_text(), 'original')

    def test_real_subprocess_transports_and_error_schema(self):
        env = {k:v for k,v in os.environ.items() if not k.startswith('ERP_SIM_')}
        base = [sys.executable, '-I', '-m', 'erp_sim']
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp)/'request.json'
            request.write_text('{"command":"features"}', encoding='utf-8-sig')
            for args, stdin in [(['{"command":"features"}'], None),
                                (['--request',str(request)], None),
                                (['--request','-'], b'{"command":"features"}')]:
                result = subprocess.run(base + args, input=stdin, capture_output=True, cwd=tmp, env=env, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b'')
                self.assertEqual(json.loads(result.stdout)['command'], 'features')
            result = subprocess.run(base + ['--request','-'], input=b'\xff', capture_output=True,
                                    cwd=tmp, env=env, timeout=15)
            self.assertEqual(result.returncode, 2)
            _, schema, _ = self.invoke(['{"command":"schema","feature_args":{"kind":"request_error"}}'])
            Draft202012Validator(schema).validate(json.loads(result.stdout))

    def test_real_stdin_without_eof_times_out_without_shutdown_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.Popen([sys.executable,'-I','-m','erp_sim','--request','-'],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp)
            try:
                process.stdin.write(b'{"command":"features"}')
                process.stdin.flush()
                self.assertEqual(process.wait(timeout=15), 2)
                self.assertEqual(json.loads(process.stdout.read())['error']['code'], 'INVALID_ARGUMENT')
                self.assertEqual(process.stderr.read(), b'')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
