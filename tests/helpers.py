from erp_sim.protocol.dcp import AuiTree
from erp_sim.protocol.events import Events


class FakeChannel:
    def __init__(self, tree=None):
        self.tree = tree or AuiTree('oea01_1')
        self.tag = 'test'
        self.events = Events()
        self.sent = []
        self.touched = False

    def quiet(self, seconds):
        return True

    def touch(self):
        self.touched = True

    def send(self, payload):
        self.sent.append(payload)

    def emit(self, *commands):
        self.send(self.events.emit(*commands))


def node(tree, ident, kind, attrs=None, children=None):
    tree.nodes[ident] = {'kind': kind, 'attrs': attrs or {}, 'children': children or [], 'parent': 0}


def result_tree(query, rows=None, total=None):
    tree = AuiTree('oea01_1')
    for i, (key, value) in enumerate(query.conditions.items(), 100):
        node(tree, i, 'FormField', {'name': 'formonly.' + key, 'value': value})
    node(tree, 169, 'Table', {'dialogType': 'DisplayArray', 'pageSize': '2'}, [170])
    node(tree, 170, 'TableColumn', {'colName': 'oea01_1'})
    node(tree, 400, 'Action', {'name': 'accept', 'active': '1'})
    tree.columns = {'oea01_1': '订单单号', 'oea02': '订单日期', 'oeb12': '数量'}
    tree.rows = rows or {}
    tree.total = len(tree.rows) if total is None else total
    return tree
