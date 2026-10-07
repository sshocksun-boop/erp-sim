"""Read-only material-order detail query for aimq131."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from ..errors import ErpError
from ..navigation import active_action, last_accept
from ..protocol.events import action, configure
from ..protocol.handshake import announcements

REQUIRED = ('oeb01', 'oeb03', 'oea03', 'occ02', 'oeb15', 'oeb12', 'on_order', 'oeb05')


@dataclass(frozen=True)
class ItemQuery:
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


def decimal_value(value):
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ErpError('PROTOCOL_ERROR', 'Invalid aimq131 quantity') from None
    if not parsed.is_finite():
        raise ErpError('PROTOCOL_ERROR', 'Invalid aimq131 quantity')
    return parsed


class Aimq131:
    program = 'aimq131'
    key_column = 'oeb01'

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
        tables = [(i, node) for i, node in tree.nodes.items()
                  if node['kind'] == 'Table' and node['attrs'].get('name') == 's_sr'
                  and node['attrs'].get('dialogType') == 'DisplayArray'
                  and node['attrs'].get('active') == '1']
        if tables and channel.quiet(2):
            if len(tables) != 1:
                raise ErpError('PROTOCOL_ERROR', 'Ambiguous aimq131 result table')
            self.collect(channel, *tables[0])

    def collect(self, channel, table_id, table):
        tree = channel.tree
        fields = {node['attrs'].get('name'): node['attrs'].get('value', '')
                  for node in tree.nodes.values() if node['kind'] == 'FormField'}
        if fields.get('ima_file.ima01') != self.query.item:
            raise ErpError('CONDITION_MISMATCH', 'Server item does not match requested item')
        try:
            total = int(table['attrs']['size'])
            offset = int(table['attrs'].get('offset', '0'))
            page_size = int(table['attrs'].get('pageSize', '46'))
        except (KeyError, TypeError, ValueError):
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq131 table bounds') from None
        if total < 0 or total > 100000 or offset < 0 or offset > total or page_size <= 0:
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq131 table bounds')
        if fields.get('formonly.cn2') != str(total):
            raise ErpError('INCOMPLETE_RESULT', 'Aimq131 row count does not match table size')

        page = {}
        page_columns = set()
        for column_id in table['children']:
            column = tree.nodes[column_id]
            if column['kind'] != 'TableColumn':
                continue
            name = column['attrs'].get('colName')
            if not name:
                raise ErpError('PROTOCOL_ERROR', 'Aimq131 column has no field identifier')
            if name in page_columns:
                raise ErpError('PROTOCOL_ERROR', 'Duplicate aimq131 column identifier')
            page_columns.add(name)
            label = column['attrs'].get('text', name)
            if name in self.columns and self.columns[name] != label:
                raise ErpError('PROTOCOL_ERROR', 'Aimq131 column changed between pages')
            self.columns[name] = label
            lists = [tree.nodes[i] for i in column['children']
                     if tree.nodes[i]['kind'] == 'ValueList']
            if len(lists) != 1:
                raise ErpError('INCOMPLETE_RESULT', 'Aimq131 column value list is missing')
            for index, value_id in enumerate(lists[0]['children']):
                rowno = offset + index
                if rowno >= total:
                    break
                page.setdefault(rowno, {})[name] = tree.nodes[value_id]['attrs'].get('value', '')
        if not set(REQUIRED).issubset(self.columns):
            raise ErpError('PROTOCOL_ERROR', 'Aimq131 required columns are missing')
        for rowno, row in page.items():
            if not row.get(self.key_column):
                continue
            if any(not row.get(field) for field in REQUIRED):
                raise ErpError('INCOMPLETE_RESULT', 'Aimq131 visible row value is missing')
            previous = self.rows.get(rowno)
            if previous is not None and previous != row:
                raise ErpError('PROTOCOL_ERROR', 'Aimq131 row changed between pages')
            self.rows[rowno] = row

        if sorted(self.rows) != list(range(total)):
            missing = min(set(range(total)) - set(self.rows))
            next_offset = min(missing, max(0, total - page_size))
            if next_offset in self.requested_offsets:
                raise ErpError('INCOMPLETE_RESULT', 'Aimq131 pagination made no progress')
            self.requested_offsets.add(next_offset)
            channel.emit(configure(table_id, offset=next_offset))
            channel.touch()
            return

        rows = [self.rows[i] for i in range(total)]
        if any(set(row) != set(self.columns) for row in rows):
            raise ErpError('INCOMPLETE_RESULT', 'Aimq131 row columns are incomplete')
        keys = [(row['oeb01'], row['oeb03']) for row in rows]
        if len(keys) != len(set(keys)):
            raise ErpError('PROTOCOL_ERROR', 'Duplicate aimq131 order line')
        ordered = sum((decimal_value(row['oeb12']) for row in rows), Decimal(0))
        open_qty = sum((decimal_value(row['on_order']) for row in rows), Decimal(0))
        ordered_text = fields.get('formonly.oeb12_t', '')
        open_text = fields.get('formonly.oeb12_o', '')
        if ordered != decimal_value(ordered_text) or open_qty != decimal_value(open_text):
            raise ErpError('INCOMPLETE_RESULT', 'Aimq131 quantity totals do not match rows')
        self.result = {
            'item': self.query.item,
            'description': fields.get('ima_file.ima02', ''),
            'specification': fields.get('ima_file.ima021', ''),
            'columns': [{'id': name, 'label': label} for name, label in self.columns.items()],
            'rows': rows, 'row_count': len(rows), 'expected_row_count': total,
            'order_count': len({row['oeb01'] for row in rows}),
            'ordered_quantity_total': ordered_text,
            'open_quantity_total': open_text,
            'complete': True,
        }
        self.done = True
