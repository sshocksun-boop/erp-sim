"""Read-only stock-quantity detail query for aimq102."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from ..errors import ErpError
from ..navigation import active_action, last_accept
from ..protocol.events import action, configure
from ..protocol.handshake import announcements

REQUIRED_COLUMNS = ('img02', 'imd02', 'img23', 'img10', 'img09')
REQUIRED_ROW_VALUES = ('img02', 'img23', 'img10', 'img09')

MASTER_FIELDS = (
    ('current_version', 'ima_file.ima05'),
    ('group_code', 'ima_file.ima06'),
    ('stock_unit', 'ima_file.ima25'),
    ('source_code', 'ima_file.ima08'),
    ('replenish_code', 'ima_file.ima37'),
    ('unit_policy', 'ima_file.ima906'),
    ('second_unit', 'ima_file.ima907'),
    ('consumable', 'ima_file.ima70'),
    ('bonded', 'ima_file.ima15'),
)

QUANTITY_FIELDS = (
    ('available_stock', 'formonly.avl_stk'),
    ('ordered_qty', 'formonly.oeb_q'),
    ('wo_material_prepared', 'formonly.sfa_q1'),
    ('wo_material_short', 'formonly.sfa_q2'),
    ('purchase_request_qty', 'formonly.pml_q'),
    ('purchase_order_qty', 'formonly.pmn_q'),
    ('wo_in_process', 'formonly.sfb_q1'),
    ('subcontract_in_process', 'formonly.sfb_q2'),
    ('subcontract_iqc_inspect', 'formonly.rvb_q2'),
    ('iqc_inspect', 'formonly.rvb_q'),
    ('fqc_inspect', 'formonly.qcf_q'),
    ('projected_available_header', 'formonly.atp_qty'),
    ('unavailable_stock', 'formonly.unavl_stk'),
    ('setup_qty', 'formonly.sie_q'),
)

# The summary grid repeats the header values for one exact item. Text columns
# must match exactly; quantity columns are compared numerically because the
# grid formats decimals to its column width (native evidence 2026-09-28:
# header '48600.000' versus grid '48600.00', both eight characters wide).
# atp_qty_1 is excluded: it legitimately differs from the header field and is
# returned separately as projected_available_table.
SUMMARY_TEXT_CROSSCHECK = {
    'ima01_1': 'ima_file.ima01', 'ima02_1': 'ima_file.ima02',
    'ima021_1': 'ima_file.ima021', 'ima05_1': 'ima_file.ima05',
    'ima06_1': 'ima_file.ima06', 'ima25_1': 'ima_file.ima25',
    'ima08_1': 'ima_file.ima08', 'ima37_1': 'ima_file.ima37',
    'ima70_1': 'ima_file.ima70', 'ima15_1': 'ima_file.ima15',
}
SUMMARY_QUANTITY_CROSSCHECK = {
    'avl_stk_1': 'formonly.avl_stk', 'oeb_q_1': 'formonly.oeb_q',
    'sfa_q1_1': 'formonly.sfa_q1', 'sfa_q2_1': 'formonly.sfa_q2',
    'pml_q_1': 'formonly.pml_q', 'pmn_q_1': 'formonly.pmn_q',
    'sfb_q1_1': 'formonly.sfb_q1', 'sfb_q2_1': 'formonly.sfb_q2',
    'rvb_q2_1': 'formonly.rvb_q2', 'rvb_q_1': 'formonly.rvb_q',
    'qcf_q_1': 'formonly.qcf_q', 'unavl_stk_1': 'formonly.unavl_stk',
    'sie_q_1': 'formonly.sie_q',
}


@dataclass(frozen=True)
class StockQuery:
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
        raise ErpError('PROTOCOL_ERROR', f'Ambiguous aimq102 {name} table')
    return found[0]


def decimal_value(value):
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ErpError('PROTOCOL_ERROR', 'Invalid aimq102 quantity') from None
    if not parsed.is_finite():
        raise ErpError('PROTOCOL_ERROR', 'Invalid aimq102 quantity')
    return parsed


class Aimq102:
    """Two-accept exact-item query: submit the item, confirm, then collect."""

    program = 'aimq102'
    key_column = 'img02'

    def __init__(self, query):
        self.query = query
        self.announced = self.query_clicked = self.submitted = self.confirmed = self.done = False
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
        if not self.confirmed:
            # After the first accept the server echoes the item and locks the
            # field (active=0); a second accept on the result dialog runs the
            # query. A locked foreign echo is rejected without a second accept.
            item_id = named_field(tree, 'ima_file.ima01')
            attrs = tree.nodes[item_id]['attrs'] if item_id is not None else {}
            if attrs.get('active') == '0' and attrs.get('value', '') != '':
                if attrs.get('value') != self.query.item:
                    raise ErpError('CONDITION_MISMATCH', 'Server item does not match requested item')
                accept = last_accept(tree)
                if accept and channel.quiet(0.5):
                    channel.emit(action(accept))
                    self.confirmed = True
            return
        fields = {node['attrs'].get('name'): node['attrs'].get('value', '')
                  for node in tree.nodes.values() if node['kind'] == 'FormField'}
        if fields.get('formonly.cnt') not in ('', None) and channel.quiet(2):
            table_id, table = display_array(tree, 's_img')
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
            page_size = int(table['attrs'].get('pageSize', '15'))
        except (KeyError, TypeError, ValueError):
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq102 table bounds') from None
        if total < 0 or total > 100000 or offset < 0 or offset > total or page_size <= 0:
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq102 table bounds')
        # Counter semantics (production evidence 2026-09-28): formonly.cnt is
        # the item count (summary grid rows); formonly.cn2 is the stock-detail
        # row count, including the explicit zero echo cn2='0'.
        _, summary = display_array(tree, 'table1')
        try:
            summary_total = int(summary['attrs']['size'])
        except (KeyError, TypeError, ValueError):
            raise ErpError('PROTOCOL_ERROR', 'Invalid aimq102 summary table size') from None
        cnt, cn2 = fields.get('formonly.cnt'), fields.get('formonly.cn2')
        if cnt is None or cn2 is None or cnt != str(summary_total) or cn2 != str(total):
            raise ErpError('INCOMPLETE_RESULT', 'Aimq102 counters do not match table sizes')

        page = {}
        for column_id in table['children']:
            column = tree.nodes[column_id]
            if column['kind'] != 'TableColumn':
                continue
            name = column['attrs'].get('colName')
            if not name:
                raise ErpError('PROTOCOL_ERROR', 'Aimq102 column has no field identifier')
            label = column['attrs'].get('text', name)
            if name in self.columns and self.columns[name] != label:
                raise ErpError('PROTOCOL_ERROR', 'Aimq102 column changed between pages')
            self.columns[name] = label
            lists = [tree.nodes[i] for i in column['children']
                     if tree.nodes[i]['kind'] == 'ValueList']
            if len(lists) != 1:
                raise ErpError('INCOMPLETE_RESULT', 'Aimq102 column value list is missing')
            for index, value_id in enumerate(lists[0]['children']):
                rowno = offset + index
                if rowno >= total:
                    break
                page.setdefault(rowno, {})[name] = tree.nodes[value_id]['attrs'].get('value', '')
        if not set(REQUIRED_COLUMNS).issubset(self.columns):
            raise ErpError('PROTOCOL_ERROR', 'Aimq102 required columns are missing')
        for rowno, row in page.items():
            if not row.get('img02'):
                continue
            if any(not row.get(field) for field in REQUIRED_ROW_VALUES):
                raise ErpError('INCOMPLETE_RESULT', 'Aimq102 visible row value is missing')
            decimal_value(row['img10'])
            previous = self.rows.get(rowno)
            if previous is not None and previous != row:
                raise ErpError('PROTOCOL_ERROR', 'Aimq102 row changed between pages')
            self.rows[rowno] = row

        if sorted(self.rows) != list(range(total)):
            missing = min(set(range(total)) - set(self.rows))
            next_offset = min(missing, max(0, total - page_size))
            if next_offset in self.requested_offsets:
                raise ErpError('INCOMPLETE_RESULT', 'Aimq102 pagination made no progress')
            self.requested_offsets.add(next_offset)
            channel.emit(configure(table_id, offset=next_offset))
            channel.touch()
            return

        rows = [self.rows[i] for i in range(total)]
        keys = [(row['img02'], row['img03'], row['img04']) for row in rows]
        if len(keys) != len(set(keys)):
            raise ErpError('PROTOCOL_ERROR', 'Duplicate aimq102 stock line')

        quantities = {}
        for key, field in QUANTITY_FIELDS:
            text = fields.get(field, '')
            if text == '':
                raise ErpError('INCOMPLETE_RESULT', f'Aimq102 {key} is missing')
            decimal_value(text)
            quantities[key] = text

        if summary_total != 1:
            raise ErpError('PROTOCOL_ERROR', 'Aimq102 summary table is not a single row')
        summary_row = self.table_rows(tree, summary).get(0, {})
        for column_name, field_name in SUMMARY_TEXT_CROSSCHECK.items():
            if summary_row.get(column_name, None) != fields.get(field_name, ''):
                raise ErpError('PROTOCOL_ERROR',
                               f'Aimq102 summary {column_name} differs from header {field_name}')
        for column_name, field_name in SUMMARY_QUANTITY_CROSSCHECK.items():
            if decimal_value(summary_row.get(column_name, '')) != decimal_value(fields.get(field_name, '')):
                raise ErpError('PROTOCOL_ERROR',
                               f'Aimq102 summary {column_name} differs from header {field_name}')
        projected_table = summary_row.get('atp_qty_1')
        if not projected_table:
            raise ErpError('INCOMPLETE_RESULT', 'Aimq102 projected_available_table is missing')
        decimal_value(projected_table)

        if total == 1:
            if quantities['available_stock'] != rows[0]['img10']:
                raise ErpError('INCOMPLETE_RESULT',
                               'Aimq102 available stock does not match the single stock row')
            complete = True
        else:
            # Zero rows are a verified complete result when ERP echoed
            # cn2='0' (checked above). Production evidence for more than one
            # stock row is still missing, so multi-row data is returned
            # incomplete instead of being claimed complete.
            complete = total == 0

        self.result = {
            'item': self.query.item,
            'description': fields.get('ima_file.ima02', ''),
            'specification': fields.get('ima_file.ima021', ''),
            **{key: fields.get(field, '') for key, field in MASTER_FIELDS},
            **quantities,
            'projected_available_table': projected_table,
            'columns': [{'id': name, 'label': label} for name, label in self.columns.items()],
            'rows': rows, 'row_count': len(rows), 'expected_row_count': total,
            'warehouse_count': len({row['img02'] for row in rows}),
            'complete': complete,
        }
        if not complete:
            raise ErpError('INCOMPLETE_RESULT',
                           'Aimq102 multi-row results are not yet verified')
        self.done = True

    @staticmethod
    def table_rows(tree, table):
        offset = int(table['attrs'].get('offset', '0'))
        rows = {}
        for column_id in table['children']:
            column = tree.nodes[column_id]
            if column['kind'] != 'TableColumn':
                continue
            name = column['attrs'].get('colName')
            for list_id in column['children']:
                value_list = tree.nodes[list_id]
                if value_list['kind'] != 'ValueList':
                    continue
                for index, value_id in enumerate(value_list['children']):
                    rows.setdefault(offset + index, {})[name] = \
                        tree.nodes[value_id]['attrs'].get('value', '')
        return rows
