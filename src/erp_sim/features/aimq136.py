"""Read-only work-in-process detail query for aimq136."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from ..errors import ErpError
from ..navigation import active_action, last_accept
from ..protocol.events import action, configure
from ..protocol.handshake import announcements

# Required table columns. sfb82_n (department short name) may legitimately be
# empty and is therefore not required to be present with a value.
REQUIRED_COLUMNS = ('sfb01', 'sfb04', 'sfb82', 'sfb13', 'sfb15', 'sfb08',
                    'woo_qty', 'sub_qty')
QUANTITY_COLUMNS = ('sfb08', 'woo_qty', 'sub_qty')
# Output key, header formonly total, row column that must sum to it.
TOTALS = (
    ('production_qty_total', 'formonly.sum_qty', 'sfb08'),
    ('wo_in_process_total', 'formonly.sum_woo', 'woo_qty'),
    ('subcontract_in_process_total', 'formonly.sum_sub', 'sub_qty'),
)


@dataclass(frozen=True)
class WipQuery:
    item: str

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', self.item):
            raise ErpError('INVALID_ARGUMENT', 'item must be an ERP material identifier')

    def as_dict(self):
        return {'item': self.item}


def named_field(tree, name):
    found = [i for i, node in tree.nodes.items() if node['kind'] == 'FormField'
             and node['attrs'].get('name') == name]
    return found[-1] if found else None


def display_array(tree, name):
    found = [(i, node) for i, node in tree.nodes.items()
             if node['kind'] == 'Table' and node['attrs'].get('name') == name
             and node['attrs'].get('dialogType') == 'DisplayArray']
    if len(found) != 1:
        raise ErpError('PROTOCOL_ERROR', f'Ambiguous aimq136 {name} table')
    return found[0]


def decimal_value(value):
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ErpError('PROTOCOL_ERROR', 'Invalid aimq136 quantity') from None
    if not parsed.is_finite():
        raise ErpError('PROTOCOL_ERROR', 'Invalid aimq136 quantity')
    return parsed


class Aimq136:
    """Single-accept exact-item query: submitting the item runs the query."""

    program = 'aimq136'
    key_column = 'sfb01'

    def __init__(self, query):
        self.query = query
        self.announced = self.query_clicked = self.submitted = self.done = False
        self.result = None
        self.rows = {}
        self.columns = {}
        self.requested_offsets = set()

    def advance(self, channel):
        tree = channel.tree
        if self.done or tree.nodes.get(0, {}).get('attrs', {}).get('name') != self.program:
            return
        if not self.announced:
            for payload in announcements(['file_q', 'file_w']):
                channel.send(payload)
            self.announced = True
        if not self.query_clicked:
            query_action = active_action(tree, 'query')
            if query_action and channel.quiet(2):
                channel.emit(action(query_action))
                self.query_clicked = True
            return
        if not self.submitted:
            # Single-accept flow (native evidence 2026-09-29): submitting the
            # item with its accept both locks the condition and runs the query;
            # unlike aimq102 no second result-dialog accept is sent.
            item_id = named_field(tree, 'ima_file.ima01')
            accept = last_accept(tree)
            if (item_id is not None and accept and channel.quiet(0.5)
                    and tree.nodes[item_id]['attrs'].get('active') == '1'):
                channel.emit(
                    configure(item_id, cursor=len(self.query.item),
                              cursor2=len(self.query.item), value=self.query.item),
                    action(accept),
                )
                self.submitted = True
            return
        fields = {node['attrs'].get('name'): node['attrs'].get('value', '')
                  for node in tree.nodes.values() if node['kind'] == 'FormField'}
        if fields.get('formonly.cnt') not in ('', None) and channel.quiet(2):
            table_id, table = display_array(tree, 's_sr')
            self.collect(channel, table_id, table)

    def collect(self, channel, table_id, table):
        tree = channel.tree
        fields = {node['attrs'].get('name'): node['attrs'].get('value', '')
                  for node in tree.nodes.values() if node['kind'] == 'FormField'}
        if fields.get('ima_file.ima01') != self.query.item:
            raise ErpError('CONDITION_MISMATCH', 'Server item does not match requested item')
        try:
            total = int(table['attrs']['size'])
            offset = int(table['attrs'].get('offset', '0'))
            page_size = int(table['attrs'].get('pageSize', '13'))
        except (KeyError, TypeError, ValueError):
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq136 table bounds') from None
        if total < 0 or total > 100000 or offset < 0 or offset > total or page_size <= 0:
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq136 table bounds')
        # Counter semantics (native and prototype-live evidence 2026-09-29):
        # formonly.cn2 is the detail row count (s_sr size) and formonly.cnt is
        # the item count; the exact-item flow echoed cnt='1' in every observed
        # query. Zero-row behaviour is not yet observed, so zero stays
        # incomplete below instead of being accepted via counters alone.
        cnt, cn2 = fields.get('formonly.cnt'), fields.get('formonly.cn2')
        if cn2 != str(total):
            raise ErpError('INCOMPLETE_RESULT', 'Aimq136 row count does not match table size')
        if cnt != '1':
            raise ErpError('INCOMPLETE_RESULT', 'Aimq136 item counter is not one')

        page = {}
        page_columns = set()
        # Columns keep AUI node (visual) order; sfb82_n carries tabIndex 18
        # while sitting in the fourth visual position (native evidence).
        for column_id in table['children']:
            column = tree.nodes[column_id]
            if column['kind'] != 'TableColumn':
                continue
            name = column['attrs'].get('colName')
            if not name:
                raise ErpError('PROTOCOL_ERROR', 'Aimq136 column has no field identifier')
            if name in page_columns:
                raise ErpError('PROTOCOL_ERROR', 'Duplicate aimq136 column identifier')
            page_columns.add(name)
            label = column['attrs'].get('text', name)
            if name in self.columns and self.columns[name] != label:
                raise ErpError('PROTOCOL_ERROR', 'Aimq136 column changed between pages')
            self.columns[name] = label
            lists = [tree.nodes[i] for i in column['children']
                     if tree.nodes[i]['kind'] == 'ValueList']
            if len(lists) != 1:
                raise ErpError('INCOMPLETE_RESULT', 'Aimq136 column value list is missing')
            for index, value_id in enumerate(lists[0]['children']):
                rowno = offset + index
                if rowno >= total:
                    break
                page.setdefault(rowno, {})[name] = tree.nodes[value_id]['attrs'].get('value', '')
        if not set(REQUIRED_COLUMNS).issubset(self.columns):
            raise ErpError('PROTOCOL_ERROR', 'Aimq136 required columns are missing')
        for rowno, row in page.items():
            if not row.get(self.key_column):
                continue
            if any(not row.get(field) for field in REQUIRED_COLUMNS):
                raise ErpError('INCOMPLETE_RESULT', 'Aimq136 visible row value is missing')
            for field in QUANTITY_COLUMNS:
                decimal_value(row[field])
            previous = self.rows.get(rowno)
            if previous is not None and previous != row:
                raise ErpError('PROTOCOL_ERROR', 'Aimq136 row changed between pages')
            self.rows[rowno] = row

        if sorted(self.rows) != list(range(total)):
            missing = min(set(range(total)) - set(self.rows))
            next_offset = min(missing, max(0, total - page_size))
            if next_offset in self.requested_offsets:
                raise ErpError('INCOMPLETE_RESULT', 'Aimq136 pagination made no progress')
            self.requested_offsets.add(next_offset)
            channel.emit(configure(table_id, offset=next_offset))
            channel.touch()
            return

        totals = {}
        for key, field, _ in TOTALS:
            text = fields.get(field, '')
            if text == '':
                raise ErpError('INCOMPLETE_RESULT', f'Aimq136 {key} is missing')
            decimal_value(text)
            totals[key] = text

        result = {
            'item': self.query.item,
            'description': fields.get('ima_file.ima02', ''),
            'specification': fields.get('ima_file.ima021', ''),
            'source_code': fields.get('ima_file.ima08', ''),
            **totals,
            'columns': [{'id': name, 'label': label} for name, label in self.columns.items()],
            'rows': [self.rows[i] for i in range(total)],
            'row_count': total,
            'expected_row_count': total,
            'work_order_count': 0,
            'complete': False,
        }
        if total == 0:
            # A zero-row answer is a plausible business result, but no production
            # evidence covers the server echo shape yet. Keep the collected
            # evidence and fail closed instead of claiming an empty success.
            self.result = result
            raise ErpError('INCOMPLETE_RESULT',
                           'Aimq136 zero-row results are not yet verified')
        rows = result['rows']
        if any(set(row) != set(self.columns) for row in rows):
            raise ErpError('INCOMPLETE_RESULT', 'Aimq136 row columns are incomplete')
        if len({row['sfb01'] for row in rows}) != total:
            raise ErpError('PROTOCOL_ERROR', 'Duplicate aimq136 work order')
        for key, field, column in TOTALS:
            row_sum = sum((decimal_value(row[column]) for row in rows), Decimal(0))
            if row_sum != decimal_value(totals[key]):
                raise ErpError('INCOMPLETE_RESULT', 'Aimq136 quantity totals do not match rows')
        result['work_order_count'] = len({row['sfb01'] for row in rows})
        result['complete'] = True
        self.result = result
        self.done = True
