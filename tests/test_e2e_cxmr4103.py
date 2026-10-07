"""Synthetic end-to-end coverage for the cxmr4103 order CLI."""
import unittest

from tests.e2e_backend import add, spec, field, action, update
from tests.e2e_support import EndToEndMixin


ORDER_ROWS = [
    {'oea01_1': 'TEST-001', 'oea02': '26/09/15', 'oeb12': '0.000'},
    {'oea01_1': 'TEST-001', 'oea02': '26/09/15', 'oeb12': ''},
    {'oea01_1': 'TEST-002', 'oea02': '26/09/16', 'oeb12': '2.500'},
]
CONDITIONS = {'oea01': 'TEST-*', 'd': '1', 'n': 'N',
              'd_s': '26/09/15', 'd_e': '26/09/16'}
QUERY_ARGS = {'pattern': 'TEST-*', 'date_from': '2026-09-15', 'date_to': '2026-09-16'}


def order_table(offset=0, rows=(), total=0, dialog='DisplayArray'):
    columns = []
    for index, (name, label) in enumerate([
        ('oea01_1', '订单单号'), ('oea02', '订单日期'), ('oeb12', '数量'),
    ]):
        ident = 170 + index * 10
        # Empty values deliberately omit the value attribute.
        values = ''.join(spec('Value', ident + 2 + i,
                              {'value': row[name]} if row[name] else {})
                         for i, row in enumerate(rows))
        columns.append(spec('TableColumn', ident, {'colName': name, 'text': label},
                            spec('ValueList', ident + 1, children=values)))
    return add(169, 'Table', {'dialogType': dialog, 'size': total,
                             'offset': offset, 'pageSize': 2}, ''.join(columns))



def orders_workflow(peer, mismatch):
    peer.send(add(0, 'Interface'),
              *(field(100 + i, name) for i, name in enumerate(CONDITIONS)),
              order_table(dialog='InputArray'), action(400), action(900, 'exit'))
    for tokens in [
        ('idRef "169"', 'pageSize "38"'),
        ('idRef "100"', 'value "TEST-*"', 'idRef "101"'),
        ('idRef "101"', 'value "1"', 'idRef "102"'),
        ('idRef "102"', 'value "N"', 'idRef "103"'),
        ('idRef "103"', 'value "26/09/15"', 'idRef "104"'),
        ('idRef "104"', 'value "26/09/16"', 'ActionEvent', 'idRef "400"'),
    ]:
        peer.expect(*tokens)
    values = {**CONDITIONS, 'oea01': 'OTHER-*'} if mismatch else CONDITIONS
    peer.send(*(update(100 + i, value=value, active='0')
                for i, value in enumerate(values.values())),
              '{rn 169}', order_table(rows=ORDER_ROWS[:2], total=3),
              add(500, 'Table', {'dialogType': 'DisplayArray', 'size': 1},
                  spec('TableColumn', 501, {'colName': 'unrelated'})))
    if mismatch:
        return
    peer.expect('ConfigureEvent', 'idRef "169"', 'offset "1"')
    peer.send('{rn 169}', order_table(offset=1, rows=ORDER_ROWS[1:], total=3))
    peer.expect('ActionEvent', 'idRef "400"')


class Cxmr4103EndToEndTests(EndToEndMixin, unittest.TestCase):
    def test_cxmr4103_end_to_end(self):
        doc = self.invoke('cxmr4103', QUERY_ARGS, 'result.schema.json', orders_workflow)
        self.assertEqual(doc['query'], {'pattern': 'TEST-*', 'date_from': '2026-09-15',
                                      'date_to': '2026-09-16', 'date_type': 'order_date',
                                      'include_internal': True})
        self.assertEqual(doc['data'], {
            'columns': [{'id': 'oea01_1', 'label': '订单单号'},
                        {'id': 'oea02', 'label': '订单日期'}, {'id': 'oeb12', 'label': '数量'}],
            'rows': ORDER_ROWS, 'row_count': 3, 'expected_row_count': 3,
            'order_count': 2, 'complete': True,
        })

    def test_cxmr4103_end_to_end_rejects_wrong_conditions(self):
        self.invoke('cxmr4103', QUERY_ARGS, 'result.schema.json', orders_workflow, mismatch=True)
