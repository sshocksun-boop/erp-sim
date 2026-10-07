"""Noninteractive JSON CLI. Only --help writes human-readable stdout."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Protocol
from . import __version__
from .config import load_settings, effective_config_path
from .errors import ErpError, EXIT_CODES
from .features.abmr001 import BomQuery, Abmr001
from .features.aimq102 import StockQuery, Aimq102
from .features.aimq131 import ItemQuery, Aimq131
from .features.aimq136 import WipQuery, Aimq136
from .features.asfi301 import WorkOrderEntry, Asfi301
from .features.cxmr4103 import OrderQuery, Cxmr4103
from .session import GdcSession
from .request import read_request, request_schema, MAX_REQUEST_BYTES, STDIN_TIMEOUT


RESPONSE_TIMEZONE = timezone(timedelta(hours=8))


class Query(Protocol):
    def as_dict(self) -> dict[str, Any]: ...


FeatureDriver = Cxmr4103 | Abmr001 | Aimq131 | Aimq102 | Aimq136 | Asfi301


@dataclass(frozen=True)
class FeatureSpec:
    description: str
    capabilities: dict[str, object]
    response_schema: str
    response_version: str
    build_driver: Callable[[dict[str, Any]], tuple[Query, FeatureDriver]]


def build_cxmr4103(args):
    query = OrderQuery(args['pattern'], date.fromisoformat(args['date_from']),
                       date.fromisoformat(args['date_to']))
    return query, Cxmr4103(query)


def build_abmr001(args):
    query = BomQuery(args['item'])
    return query, Abmr001(query)


def build_aimq131(args):
    query = ItemQuery(args['item'])
    return query, Aimq131(query)


def build_aimq102(args):
    query = StockQuery(args['item'])
    return query, Aimq102(query)


def build_aimq136(args):
    query = WipQuery(args['item'])
    return query, Aimq136(query)


def build_asfi301(args):
    query = WorkOrderEntry(args['prefix'], args['department_vendor'],
                           args['product'], args['quantity'], args['remark'],
                           args.get('expected_manufacturing_department'))
    return query, Asfi301(query)


FEATURES = {
    'cxmr4103': FeatureSpec(
        '销售订单查询',
        {'access': 'read', 'date_type': 'order_date', 'include_internal': True},
        'result.schema.json', '2', build_cxmr4103),
    'abmr001': FeatureSpec(
        '产品结构表查询',
        {'access': 'read', 'sort': 'bom_sequence', 'output_format': 'text'},
        'abmr001.schema.json', '2', build_abmr001),
    'aimq131': FeatureSpec(
        '料件订单受订量明细查询',
        {'access': 'read', 'query_type': 'exact_item'},
        'aimq131.schema.json', '2', build_aimq131),
    'aimq102': FeatureSpec(
        '料件数量明细查询-动态资料',
        {'access': 'read', 'query_type': 'exact_item'},
        'aimq102.schema.json', '2', build_aimq102),
    'aimq136': FeatureSpec(
        '料件在制量明细查询',
        {'access': 'read', 'query_type': 'exact_item'},
        'aimq136.schema.json', '2', build_aimq136),
    'asfi301': FeatureSpec(
        '工单维护作业',
        {'access': 'write', 'operation': 'create_one',
         'automatic_retry': False, 'multiline_remark': True},
        'asfi301.schema.json', '2', build_asfi301),
}


def response_versions():
    return {name: spec.response_version for name, spec in FEATURES.items()}


def capabilities():
    return {'schema_version': '3', 'version': __version__,
        'read_only': all(spec.capabilities['access'] == 'read' for spec in FEATURES.values()),
        'request_version': '1', 'response_versions': response_versions(),
        'commands': ['capabilities', 'features', 'schema', 'version', *FEATURES],
        'features': [{'program': name, 'command': name,
                      'description': spec.description, **spec.capabilities}
                     for name, spec in FEATURES.items()],
        'schemas': {
            'request': {'command': 'schema'},
            'request_error': {'command': 'schema', 'feature_args': {'kind': 'request_error'}},
            'responses': {name: {'command': 'schema', 'feature_args': {'kind': 'response', 'feature': name}}
                          for name in FEATURES}},
        'input': {'transports': ['JSON argument', '--request FILE', '--request -'],
                  'encoding': 'UTF-8 (optional BOM)', 'max_bytes': MAX_REQUEST_BYTES,
                  'stdin_eof_timeout_seconds': STDIN_TIMEOUT, 'legacy_cli_supported': False,
                  'relative_paths': 'caller working directory'},
        'date_format': 'YYYY-MM-DD', 'dates_inclusive': True, 'timezone': 'Asia/Shanghai',
        'output': 'One JSON document on stdout; logs on stderr; --help is human-readable',
        'configuration_precedence': ['JSON request', 'ERP_SIM_* environment', 'explicit TOML', 'defaults'],
        'required_connection_values': ['username', 'password'],
        'credential_inputs': {
            'username': ['request.username', 'ERP_SIM_USERNAME', 'TOML'],
            'password': ['request.password', 'ERP_SIM_PASSWORD']},
        'request_fields': {
            item['properties']['command']['const']: item['properties']
            for item in request_schema()['oneOf']},
        'connection_inputs': {
            'hostname': ['request.hostname', 'ERP_SIM_HOSTNAME', 'TOML', 'OS hostname default']},
        'defaults': {'callback_host': 'Auto-detected from the OS route to host'},
        'limitations': ['One feature invocation per authenticated session',
                       'Uncompressed DCP only', 'Server must reach the callback IPv4 listener',
                       'Concurrent sessions must use distinct listen ports',
                       'No automatic query or write retries', 'No generic business action execution',
                       'asfi301 performs one explicitly confirmed create operation',
                       'abmr001 requires access to the ERP-generated HTTP report',
                       'Operating center is inherited from the account login; account set is reported per row'],
        'exit_codes': {'SUCCESS': 0, **EXIT_CODES}}


def features():
    items = [{'program': name, 'description': spec.description, 'command': name}
             for name, spec in FEATURES.items()]
    return {'schema_version': '3', 'ok': True, 'command': 'features',
            'data': {'count': len(items), 'features': items}, 'error': None}


def envelope(query=None, command='cxmr4103'):
    return {'schema_version': FEATURES[command].response_version, 'ok': False, 'command': command,
            'queried_at': datetime.now(RESPONSE_TIMEZONE).isoformat(timespec='seconds'),
            'query': query, 'session': {'logout_verified': False}, 'data': None, 'error': None}


def atomic_write(path, content):
    target = Path(path).resolve()
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, target)
    except OSError:
        raise ErpError('OUTPUT_ERROR', 'Could not write the output JSON file') from None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def atomic_write_bytes(path, content):
    target = Path(path).resolve()
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, target)
    except OSError:
        raise ErpError('OUTPUT_ERROR', 'Could not write the BOM report file') from None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def request_error(command=None):
    return {'schema_version': '1', 'ok': False, 'command': command, 'error': None}


def validate_paths(request, source):
    """Never overwrite an input file or alias the two result representations."""
    report = request['feature_args'].get('report_output')
    targets = [Path(value).resolve() for value in (request.get('output'), report) if value]
    config = effective_config_path(request.get('config')) if request['command'] in FEATURES else None
    protected = [Path(value).resolve() for value in (source, config) if value]

    def same(left, right):
        return left == right or (left.exists() and right.exists() and left.samefile(right))

    if len(targets) == 2 and same(*targets):
        raise ErpError('INVALID_ARGUMENT', 'output and feature_args.report_output must be different files')
    if any(same(target, original) for target in targets for original in protected):
        raise ErpError('INVALID_ARGUMENT', 'Output files must not overwrite request or configuration inputs')


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8', errors='strict')
    document, code = request_error(), 0
    output = None
    command = None
    try:
        request, source = read_request(argv)
        command = request['command']
        args = request['feature_args']
        document = envelope(command=command) if command in FEATURES else request_error(command)
        validate_paths(request, source)
        output = request.get('output')
        if command == 'capabilities':
            document = capabilities()
        elif command == 'features':
            document = features()
        elif command == 'schema':
            kind = args.get('kind', 'request')
            if kind == 'response':
                if 'feature' not in args:
                    raise ErpError('INVALID_ARGUMENT', 'feature_args.feature is required for a response schema')
                resource = FEATURES[args['feature']].response_schema
            else:
                if 'feature' in args:
                    raise ErpError('INVALID_ARGUMENT', 'feature_args.feature is only valid for a response schema')
                resource = 'request.schema.json' if kind == 'request' else 'request-error.schema.json'
            document = json.loads(files('erp_sim.resources').joinpath(resource).read_text(encoding='utf-8'))
        elif command == 'version':
            document = {'version': __version__, 'schema_version': '3', 'request_version': '1',
                        'response_versions': response_versions()}
        else:
            query, driver = FEATURES[command].build_driver(args)
            document = envelope(query.as_dict(), command)
            settings = load_settings(request.get('config'), {
                key: request[key] for key in ('username', 'password', 'hostname', 'listen_port',
                                              'timeout', 'cleanup_timeout') if key in request})
            if request.get('verbose', False):
                logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')
            result = GdcSession(settings, request.get('trace_dir')).execute(driver)
            document.update(ok=result.error is None, data=result.data,
                            session={'logout_verified': result.logout_verified},
                            queried_at=datetime.now(RESPONSE_TIMEZONE).isoformat(timespec='seconds'),
                            error=result.error.as_dict() if result.error else None)
            code = result.error.exit_code if result.error else 0
            if (command == 'abmr001' and args.get('report_output')
                    and isinstance(driver, Abmr001) and driver.report_bytes is not None):
                try:
                    atomic_write_bytes(args['report_output'], driver.report_bytes)
                except ErpError as exc:
                    document.update(ok=False, error=exc.as_dict())
                    code = exc.exit_code
    except ErpError as exc:
        document.update(ok=False, error=exc.as_dict())
        code = exc.exit_code
    except KeyboardInterrupt:
        document.update(ok=False, error=ErpError('INTERRUPTED', 'Execution interrupted').as_dict())
        code = 130
    except OSError:
        document.update(ok=False, error=ErpError('CONNECTION_FAILED', 'Local I/O or network operation failed').as_dict())
        code = 5
    except Exception:
        # Never serialize arbitrary exception repr: it may contain credentials.
        document.update(ok=False, error=ErpError('INTERNAL_ERROR', 'Unexpected internal failure').as_dict())
        code = 70
    text = json.dumps(document, ensure_ascii=False, allow_nan=False) + '\n'
    if output:
        try:
            atomic_write(output, text)
        except ErpError as exc:
            if command not in FEATURES:
                document = request_error(command)
            document.update(ok=False, error=exc.as_dict())
            code = exc.exit_code
            text = json.dumps(document, ensure_ascii=False, allow_nan=False) + '\n'
    try:
        sys.stdout.write(text)
    except (BrokenPipeError, OSError):
        return 12
    return code
