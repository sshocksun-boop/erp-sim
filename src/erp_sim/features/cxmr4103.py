"""Read-only cxmr4103 order queries with verified conditions and pagination."""
from dataclasses import dataclass
from datetime import date
import re
import time
from ..errors import ErpError
from ..navigation import field_id, last_accept, active_action
from ..protocol.events import action, configure
from ..protocol.handshake import announcements


@dataclass(frozen=True)
class OrderQuery:
    pattern: str
    date_from: date
    date_to: date

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9*?_-]{1,80}', self.pattern):
            raise ErpError('INVALID_ARGUMENT', 'pattern must be an order identifier or wildcard pattern')
        if not (2000 <= self.date_from.year <= self.date_to.year <= 2099) or self.date_from > self.date_to:
            raise ErpError('INVALID_ARGUMENT', 'dates must be ordered and within 2000..2099')

    @property
    def conditions(self):
        return {'oea01': self.pattern, 'd': '1', 'n': 'N',
                'd_s': self.date_from.strftime('%y/%m/%d'), 'd_e': self.date_to.strftime('%y/%m/%d')}

    def as_dict(self):
        return {'pattern': self.pattern, 'date_from': self.date_from.isoformat(),
                'date_to': self.date_to.isoformat(), 'date_type': 'order_date', 'include_internal': True}


class Cxmr4103:
    program = 'cxmr4103'
    key_column = 'oea01_1'

    def __init__(self, query, pause=time.sleep):
        self.query = query
        self.pause = pause
        self.announced = self.configured = self.submitted = self.done = False
        self.requested_offsets = set()
        self.result = None

    def advance(self, channel):
        tree = channel.tree
        if self.done or field_id(tree, 'oea01') is None:
            return
        if not self.announced:
            for payload in announcements(['file_q', 'file_w']):
                channel.send(payload)
            self.announced = True
        ids = {n: field_id(tree, n) for n in self.query.conditions}
        tables = [(i, n) for i, n in tree.nodes.items() if n['kind'] == 'Table'
                  and any(tree.nodes[j]['attrs'].get('colName') == self.key_column for j in n['children'])]
        accept = last_accept(tree)
        if not self.configured and channel.quiet(2) and all(ids.values()) and len(tables) == 1 and accept:
            channel.emit(configure(tables[0][0], pageSize=38, bufferSize=39)); self.pause(0.3)
            channel.emit(configure(ids['oea01'], cursor=len(self.query.pattern), cursor2=len(self.query.pattern), value=self.query.pattern),
                         configure(ids['d'], cursor=0, cursor2=0)); self.pause(0.4)
            channel.emit(configure(ids['d'], value='1'), configure(ids['n'], cursor=0, cursor2=0)); self.pause(0.4)
            channel.emit(configure(ids['n'], value='N'), configure(ids['d_s'], cursor=2, cursor2=2)); self.pause(0.4)
            channel.emit(configure(ids['d_s'], value=self.query.conditions['d_s']),
                         configure(ids['d_e'], cursor=0, cursor2=-1))
            self.configured = True
            return
        if self.configured and not self.submitted and channel.quiet(1) and accept:
            channel.emit(configure(ids['d_e'], cursor=8, cursor2=0, value=self.query.conditions['d_e']), action(accept))
            self.submitted = True
            return
        result_tables = [(i, n) for i, n in tables if n['attrs'].get('dialogType') == 'DisplayArray']
        if self.submitted and channel.quiet(4) and result_tables:
            self.collect(channel, result_tables)

    def collect(self, channel, tables):
        tree = channel.tree
        actual = {n['attrs'].get('name', '').removeprefix('formonly.'): n['attrs'].get('value', '')
                  for n in tree.nodes.values() if n['kind'] == 'FormField'}
        mismatch = [k for k, v in self.query.conditions.items() if actual.get(k) != v]
        if mismatch:
            raise ErpError('CONDITION_MISMATCH', 'Server did not preserve query fields: ' + ', '.join(mismatch))
        if len(tables) != 1:
            raise ErpError('PROTOCOL_ERROR', 'Ambiguous order result table')
        rows = [tree.rows[k].copy() for k in sorted(tree.rows)]
        # Verify every returned record, not just the form's displayed conditions.
        regex = re.compile(re.escape(self.query.pattern).replace(r'\*', '.*').replace(r'\?', '.'))
        for row in rows:
            if not regex.fullmatch(row.get(self.key_column, '')):
                raise ErpError('CONDITION_MISMATCH', 'A returned order does not match the requested pattern')
            try:
                value = date.fromisoformat('20' + row['oea02'].replace('/', '-'))
            except (KeyError, ValueError):
                raise ErpError('PROTOCOL_ERROR', 'A returned order date is invalid') from None
            if not self.query.date_from <= value <= self.query.date_to:
                raise ErpError('CONDITION_MISMATCH', 'A returned order date is outside the requested range')
        complete = sorted(tree.rows) == list(range(tree.total))
        self.result = {'columns': [{'id': k, 'label': v} for k, v in tree.columns.items()],
                       'rows': rows, 'row_count': len(rows), 'expected_row_count': tree.total,
                       'order_count': len({r[self.key_column] for r in rows}), 'complete': complete}
        if not complete:
            missing = min(set(range(tree.total)) - set(tree.rows), default=None)
            if missing is None:
                raise ErpError('INCOMPLETE_RESULT', 'Unexpected result row indexes')
            page_size = int(tables[0][1]['attrs'].get('pageSize', '38'))
            offset = min(missing, max(0, tree.total - page_size))
            if offset in self.requested_offsets:
                raise ErpError('INCOMPLETE_RESULT', 'Pagination made no progress')
            self.requested_offsets.add(offset)
            channel.emit(configure(tables[0][0], offset=offset))
            channel.touch()
            return
        self.done = True
        accept = active_action(tree, 'accept')
        if accept:
            channel.emit(action(accept))
