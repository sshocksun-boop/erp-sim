"""Read-only abmr001 product-structure queries and BOM report parsing."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import os
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

from ..errors import ErpError
from ..navigation import field_id, last_accept
from ..protocol.events import action, configure, function_return
from ..protocol.handshake import announcements


ITEM_CODE = re.compile(r'[A-Za-z0-9_.-]{1,80}')
ROOT_LINE = re.compile(r'^\s*(?P<item>[A-Za-z0-9_.-]+)\s+\((?P<description>.*)\)\s*$')
COMPONENT_LINE = re.compile(
    r'^(?P<prefix>[ │]*)[├└](?P<sequence>\d{4})──'
    r'(?P<component>\S+)\s+(?P<component_type>\S+)\s+'
    r'(?P<unit>\S+)\s+(?P<source>\S+)\s+'
    r'\((?P<description>.*?)\)\s+(?P<tail>.+?)\s*$'
)
COMPONENT_PREFIX = re.compile(r'^[ │]*[├└]')
TRUNCATED_COMPONENT_PREFIX = re.compile(r'^[ │]*[├└](?:\d{0,4}(?:─{0,2})?)?$')
TAIL = re.compile(
    r'^(?P<marker>\*|\+)?\s*'
    r'(?:(?P<numerator>\d+(?:\.\d+)?)/\s*)?'
    r'(?P<quantity>\d+(?:\.\d+)?)\s+'
    r'(?P<drawing>\S+)\s+(?P<conversion_unit>\S+)\s+'
    r'(?P<conversion>\d+(?:\.\d+)?)$'
)
REPORT_META = re.compile(
    r'制表日期:(?P<created>\S+\s+\S+)\s+有效日期:(?P<effective>\S+)\s+'
    r'版本:(?P<version>.*?)\s+页次:(?P<page>\d+)'
)
SHELLEXEC_URL = re.compile(r'^EXPLORER\s+"(?P<url>http://[^"\s]+)"$', re.IGNORECASE)
MAX_REPORT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class BomQuery:
    item: str

    def __post_init__(self):
        if not ITEM_CODE.fullmatch(self.item):
            raise ErpError('INVALID_ARGUMENT', 'item must be an ERP material identifier')

    def as_dict(self):
        return {'item': self.item, 'sort': 'bom_sequence', 'output_format': 'text'}


def parse_bom_report(text, expected_item):
    """Parse every tree row and reject mismatched or partially understood reports."""
    lines = text.replace('\f', '\n').splitlines()
    metadata = next((REPORT_META.search(line) for line in lines if '制表日期:' in line), None)
    root = next((ROOT_LINE.match(line) for line in lines
                 if line.lstrip().startswith(expected_item)), None)
    if metadata is None or root is None or root.group('item') != expected_item:
        raise ErpError('CONDITION_MISMATCH', 'BOM report does not match the requested item')

    components = []
    parents = {0: expected_item}
    current = None
    for line_number, line in enumerate(lines, 1):
        match = COMPONENT_LINE.match(line)
        if match is None:
            if COMPONENT_PREFIX.match(line):
                truncated = TRUNCATED_COMPONENT_PREFIX.match(line) is not None
                raise ErpError(
                    'INCOMPLETE_RESULT' if truncated else 'PROTOCOL_ERROR',
                    ('Truncated' if truncated else 'Unrecognized')
                    + f' BOM component on report line {line_number}',
                )
            if current is not None and '│' in line and not re.fullmatch(r'[ │]*', line):
                note = line.replace('│', '').strip()
                if note:
                    current['notes'].append(note)
            continue
        tail = TAIL.match(match.group('tail'))
        if tail is None:
            raise ErpError('PROTOCOL_ERROR', f'Unrecognized BOM columns on report line {line_number}')
        level = max(1, len(match.group('prefix')) // 4)
        parent = parents.get(level - 1)
        if parent is None:
            raise ErpError('PROTOCOL_ERROR', f'Broken BOM hierarchy on report line {line_number}')
        row = {
            'level': level,
            'parent_item': parent,
            'sequence': match.group('sequence'),
            'component_item': match.group('component'),
            'component_type': match.group('component_type'),
            'unit': match.group('unit'),
            'source': match.group('source'),
            'description': match.group('description'),
            'marker': tail.group('marker') or '',
            'quantity_numerator': tail.group('numerator'),
            'quantity': tail.group('quantity'),
            'drawing': tail.group('drawing'),
            'conversion_unit': tail.group('conversion_unit'),
            'conversion': tail.group('conversion'),
            'notes': [],
        }
        for name in ('quantity_numerator', 'quantity', 'conversion'):
            value = row[name]
            if value is not None:
                try:
                    Decimal(value)
                except InvalidOperation:
                    raise ErpError('PROTOCOL_ERROR', f'Invalid number on report line {line_number}') from None
        components.append(row)
        current = row
        parents[level] = row['component_item']
        for obsolete in [key for key in parents if key > level]:
            del parents[obsolete]

    return {
        'item': expected_item,
        'description': root.group('description'),
        'effective_date': metadata.group('effective'),
        'report_created_at': metadata.group('created'),
        'version': metadata.group('version').strip(),
        'sort': 'bom_sequence',
        'component_count': len(components),
        'components': components,
        'complete': True,
    }


def validate_report_url(url, expected_host=None):
    try:
        parsed = urlsplit(url)
        valid_port = parsed.port in (None, 80)
    except ValueError:
        return False
    return bool(
        parsed.scheme == 'http' and parsed.hostname
        and (expected_host is None or parsed.hostname == expected_host)
        and parsed.username is None and parsed.password is None and valid_port
        and parsed.path.startswith('/topprod/tiptop/out/abmr001')
        and parsed.path.endswith('.txt') and not parsed.query and not parsed.fragment
    )


def report_request(tree):
    for node in tree.nodes.values():
        if (node['kind'] != 'FunctionCall' or node['attrs'].get('moduleName') != 'standard'
                or node['attrs'].get('name') != 'shellexec'):
            continue
        values = [tree.nodes[child]['attrs'].get('value', '') for child in node['children']]
        match = SHELLEXEC_URL.fullmatch(values[0]) if len(values) == 1 else None
        if match is None or not validate_report_url(match.group('url')):
            raise ErpError('PROTOCOL_ERROR', 'ERP returned an unsupported BOM report request')
        return match.group('url')
    return None


class Abmr001:
    program = 'abmr001'
    key_column = None

    def __init__(self, query, fetch=None):
        self.query = query
        self.fetch = fetch
        self.announced = False
        self.item_submitted = False
        self.sort_focused = False
        self.sort_submitted = False
        self.output_selected = False
        self.format_focused = False
        self.output_submitted = False
        self.done = False
        self.erp_done = False
        self.report_url = None
        self.result = None
        self.report_bytes = None

    def advance(self, channel):
        tree = channel.tree
        item_id = field_id(tree, 'bma01')
        sort_id = field_id(tree, 's')
        choice_id = field_id(tree, 'choice')
        format_id = field_id(tree, 'choice4')

        if not self.announced and item_id is not None:
            for payload in announcements(['file_q', 'file_w']):
                channel.send(payload)
            self.announced = True

        if not self.item_submitted and item_id is not None and channel.quiet(2):
            accept = last_accept(tree)
            if accept:
                channel.emit(
                    configure(item_id, cursor=len(self.query.item), cursor2=len(self.query.item),
                              value=self.query.item),
                    action(accept),
                )
                self.item_submitted = True
            return

        if (self.item_submitted and not self.sort_submitted and sort_id is not None
                and tree.nodes[sort_id]['attrs'].get('active') == '1'):
            if not self.sort_focused and channel.quiet(0.5):
                channel.emit(configure(sort_id, cursor=0, cursor2=0))
                self.sort_focused = True
                return
            if self.sort_focused and channel.quiet(0.5):
                accept = last_accept(tree)
                if accept:
                    channel.emit(configure(sort_id, value='1'), action(accept))
                    self.sort_submitted = True
                return

        if self.sort_submitted and choice_id is not None and format_id is not None:
            if not self.output_selected and channel.quiet(0.5):
                channel.emit(configure(choice_id, value='O'))
                self.output_selected = True
                return
            if (self.output_selected and not self.format_focused
                    and tree.nodes[choice_id]['attrs'].get('value') == 'O'
                    and channel.quiet(0.5)):
                channel.emit(configure(format_id, cursor=0, cursor2=0))
                self.format_focused = True
                return
            if self.format_focused and not self.output_submitted and channel.quiet(0.5):
                accept = last_accept(tree)
                if accept and tree.nodes[format_id]['attrs'].get('value') == 'T':
                    channel.emit(action(accept))
                    self.output_submitted = True
                return

        if self.output_submitted and not self.erp_done:
            url = report_request(tree)
            if url is None:
                return
            actual_item = tree.nodes.get(item_id, {}).get('attrs', {}).get('value')
            actual_sort = tree.nodes.get(sort_id, {}).get('attrs', {}).get('value')
            if actual_item != self.query.item or actual_sort != '1':
                raise ErpError('CONDITION_MISMATCH', 'ERP did not preserve the BOM query fields')
            channel.emit(function_return('1', 'INTEGER'))
            self.report_url = url
            self.erp_done = True

    def finish(self):
        """Materialize the report after the session has released ERP connections."""
        if not self.erp_done or self.done:
            return
        raw = (download_report(self.report_url, self.fetch) if self.fetch is not None
               else bounded_download(self.report_url))
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ErpError('PROTOCOL_ERROR', 'Generated BOM report is not UTF-8') from None
        self.result = parse_bom_report(text, self.query.item)
        self.report_bytes = raw
        self.done = True


def download_report(url, fetch=urlopen):
    if not validate_report_url(url):
        raise ErpError('PROTOCOL_ERROR', 'Unsupported BOM report URL')
    try:
        with fetch(url, timeout=20) as response:
            final_url = response.geturl() if hasattr(response, 'geturl') else url
            if not validate_report_url(final_url, urlsplit(url).hostname):
                raise ErpError('PROTOCOL_ERROR', 'BOM report download redirected unexpectedly')
            raw = response.read(MAX_REPORT_BYTES + 1)
            length = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
            if length is not None and len(raw) < int(length):
                raise ErpError('INCOMPLETE_RESULT', 'Generated BOM report transfer was truncated')
    except TimeoutError:
        raise ErpError('TIMEOUT', 'BOM report download deadline reached') from None
    except OSError:
        raise ErpError('CONNECTION_FAILED', 'Could not download the generated BOM report') from None
    if len(raw) > MAX_REPORT_BYTES:
        raise ErpError('PROTOCOL_ERROR', 'Generated BOM report exceeds 16 MiB')
    return raw


def bounded_download(url, timeout=20):
    """A disposable worker bounds DNS, headers and slow body reads together."""
    try:
        process = subprocess.run(
            [sys.executable, '-m', 'erp_sim.features.report_worker'],
            input=url.encode('utf-8'), capture_output=True, timeout=timeout,
            env={key: value for key, value in os.environ.items()
                 if not key.upper().startswith('ERP_SIM_')},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired:
        raise ErpError('TIMEOUT', 'BOM report download deadline reached') from None
    except OSError:
        raise ErpError('CONNECTION_FAILED', 'Could not start BOM report download') from None
    if process.returncode:
        code = {6: 'TIMEOUT', 7: 'PROTOCOL_ERROR', 9: 'INCOMPLETE_RESULT'}.get(
            process.returncode, 'CONNECTION_FAILED')
        raise ErpError(code, 'Could not download the generated BOM report')
    return process.stdout
