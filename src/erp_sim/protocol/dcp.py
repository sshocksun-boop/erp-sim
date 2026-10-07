"""DCP framing and AUI tree reconstruction without positional value guessing."""
import re
import struct
import codecs


class IncompleteDcp(ValueError):
    """The received bytes are valid so far but need another transport frame."""


class FrameDecoder:
    def __init__(self):
        self.pending = bytearray()
        self.greeting = None

    def feed(self, data):
        self.pending.extend(data)
        out = []
        if self.greeting is None:
            end = self.pending.find(b'\n')
            if end < 0: return out
            self.greeting = bytes(self.pending[:end + 1])
            if not self.greeting.startswith(b'meta '):
                raise ValueError('Missing DCP greeting')
            del self.pending[:end + 1]
        while len(self.pending) >= 9:
            length, decoded = struct.unpack('>II', self.pending[:8])
            if length != decoded:
                raise ValueError('Compressed DCP frames are not supported')
            if length > 64 * 1024 * 1024:
                raise ValueError('Invalid DCP frame size')
            if len(self.pending) < 9 + length: break
            out.append((self.pending[8], bytes(self.pending[9:9 + length])))
            del self.pending[:9 + length]
        return out


def decode_text(raw, allow_incomplete=False):
    decoder = FrameDecoder()
    frames = decoder.feed(raw)
    if decoder.pending and not allow_incomplete: raise IncompleteDcp('Incomplete DCP frame')
    # A UTF-8 character can cross two transport frames.
    data = b''.join(payload for kind, payload in frames if kind == 1)
    try:
        return codecs.getincrementaldecoder('utf-8')().decode(data, final=not allow_incomplete)
    except UnicodeDecodeError as exc:
        if exc.reason == 'unexpected end of data':
            raise IncompleteDcp('Incomplete UTF-8 payload') from None
        raise


TOKEN = re.compile(r'\s+|([{}])|"((?:[^"\\]|\\.)*)"|([^\s{}"]+)')


def unescape(value):
    controls = {'n': '\n', 'r': '\r', 't': '\t'}
    return re.sub(r'\\(.)', lambda match: controls.get(match.group(1), match.group(1)), value)


def parse_lists(text):
    root, stack = [], []
    current = root
    pos = 0
    for match in TOKEN.finditer(text):
        if match.start() != pos: raise ValueError(f'Unparsed DCP token at {pos}')
        pos = match.end()
        brace, quoted, atom = match.groups()
        if brace == '{':
            child = []
            current.append(child)
            stack.append(current)
            current = child
        elif brace == '}':
            if not stack: raise ValueError('Unbalanced DCP close brace')
            current = stack.pop()
        elif quoted is not None:
            current.append(unescape(quoted))
        elif atom is not None:
            current.append(atom)
    if stack or pos != len(text): raise IncompleteDcp('Incomplete DCP message')
    return root


class AuiTree:
    def __init__(self, key_column=None):
        self.key_column = key_column
        self.nodes = {}
        self.rows = {}
        self.columns = {}
        self.total = 0
        self.om_count = 0

    def add(self, parent, spec):
        kind, ident, attributes, children = spec
        ident = int(ident)
        node = {'kind': kind, 'attrs': dict(attributes), 'children': [], 'parent': parent}
        self.nodes[ident] = node
        if parent in self.nodes and parent != ident:
            self.nodes[parent]['children'].append(ident)
        for child in children: self.add(ident, child)

    def remove(self, ident):
        node = self.nodes.get(ident)
        if node is None: return
        for child in list(node['children']): self.remove(child)
        parent = self.nodes.get(node['parent'])
        if parent and ident in parent['children']: parent['children'].remove(ident)
        self.nodes.pop(ident, None)

    def snapshot(self):
        for ident, table in list(self.nodes.items()):
            attrs = table['attrs']
            if table['kind'] != 'Table' or attrs.get('dialogType') != 'DisplayArray': continue
            columns = [self.nodes[i] for i in table['children'] if self.nodes[i]['kind'] == 'TableColumn']
            if self.key_column is None or not any(c['attrs'].get('colName') == self.key_column for c in columns): continue
            self.total = int(attrs.get('size', '0'))
            offset = int(attrs.get('offset', '0'))
            page = {}
            for column in columns:
                name = column['attrs']['colName']
                self.columns[name] = column['attrs'].get('text', name)
                lists = [self.nodes[i] for i in column['children'] if self.nodes[i]['kind'] == 'ValueList']
                if not lists: continue
                for i, child in enumerate(lists[0]['children']):
                    value = self.nodes[child]['attrs'].get('value', '')
                    page.setdefault(offset + i, {})[name] = value
            for rowno, row in page.items():
                if rowno < self.total and row.get(self.key_column):
                    self.rows[rowno] = row

    def apply(self, text):
        messages = parse_lists(text)
        if len(messages) % 3: raise IncompleteDcp('Incomplete top-level DCP layout')
        for i in range(0, len(messages), 3):
            name, sequence, commands = messages[i:i + 3]
            if name != 'om': raise ValueError(f'Unexpected DCP message: {name}')
            for command in commands:
                op = command[0]
                if op == 'an': self.add(int(command[1]), command[2:])
                elif op == 'un':
                    ident = int(command[1])
                    if ident not in self.nodes: raise ValueError(f'Unknown node: {ident}')
                    self.nodes[ident]['attrs'].update(dict(command[2]))
                elif op == 'rn': self.remove(int(command[1]))
                else: raise ValueError(f'Unsupported DCP command: {op}')
            self.om_count += 1
            self.snapshot()
        return self
