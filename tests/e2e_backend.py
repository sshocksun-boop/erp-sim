"""Synthetic loopback ERP peer; no production code or captured data is used."""
from contextlib import ExitStack
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import socket
import struct
import threading
import uuid


def attributes(values):
    return ''.join('{' + key + ' ' + json.dumps(str(value), ensure_ascii=False) + '}'
                   for key, value in values.items())


def spec(kind, ident, values=None, children=''):
    return f'{{{kind} {ident} {{{attributes(values or {})}}} {{{children}}}}}'


def add(ident, kind, values=None, children='', parent=0):
    # an has a flattened node specification, unlike its nested children.
    return f'{{an {parent} {kind} {ident} {{{attributes(values or {})}}} {{{children}}}}}'


def update(ident, **values):
    return f'{{un {ident} {{{attributes(values)}}}}}'


def field(ident, name, value='', active='1'):
    return add(ident, 'FormField', {'name': 'formonly.' + name,
                                  'value': value, 'active': active})


def action(ident, name='accept'):
    return add(ident, 'Action', {'name': name, 'active': '1'})


class Peer:
    def __init__(self, sock, feid, feid2, port, proc):
        self.sock = sock
        self.pending = bytearray()
        self.sequence = 0
        sock.sendall((f'meta Connection{{{{frontEndID "{feid}"}}'
                      f'{{procId "{proc}"}}}}\n').encode())
        greeting = self.until(b'\n').decode()
        digest = hashlib.md5(('{' + proc + '}-' + feid2).encode()).digest()
        expected_id = str(uuid.UUID(bytes=digest))
        for token in ('meta Client', f'{{frontEndID2 "{feid2}"}}',
                      f'{{port "{port}"}}', f'app-id    ={{{expected_id}}}'):
            if token not in greeting:
                raise AssertionError('Invalid callback handshake: ' + token)

    def receive(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise AssertionError('CLI closed the callback before expected ERP action')
        self.pending.extend(chunk)
        if len(self.pending) > 1024 * 1024:
            raise AssertionError('Synthetic peer receive limit exceeded')

    def until(self, marker):
        while marker not in self.pending:
            self.receive()
        end = self.pending.index(marker) + len(marker)
        result = bytes(self.pending[:end])
        del self.pending[:end]
        return result

    def expect(self, *tokens):
        while True:
            while len(self.pending) < 9:
                self.receive()
            length, decoded, kind = struct.unpack('>IIB', self.pending[:9])
            if length != decoded or length > 1024 * 1024:
                raise AssertionError('Invalid client frame')
            while len(self.pending) < 9 + length:
                self.receive()
            payload = bytes(self.pending[9:9 + length])
            del self.pending[:9 + length]
            if kind == 5:
                continue  # File announcements are binary, not UI events.
            if kind != 1:
                raise AssertionError('Unexpected client frame kind')
            text = payload.decode('utf-8')
            for token in tokens:
                if token not in text:
                    raise AssertionError(f'Expected {token!r} in client event {text!r}')
            return text

    def send(self, *commands):
        payload = ('om %d {%s}\n' % (self.sequence, ''.join(commands))).encode('utf-8')
        self.sequence += 1
        # Split a multibyte character across DCP frames, then fragment TCP writes.
        chinese = next((i for i, byte in enumerate(payload) if byte >= 128), None)
        split = chinese + 1 if chinese is not None else len(payload) // 2
        for part in (payload[:split], payload[split:]):
            frame = struct.pack('>IIB', len(part), len(part), 1) + part
            self.sock.sendall(frame[:3])
            self.sock.sendall(frame[3:])


class SyntheticErp:
    """Bounded scripted Telnet, three DCP callbacks, and optional real HTTP."""
    def __init__(self, program, workflow, report=None, report_path=None, report_handler=None):
        self.program = program
        self.workflow = workflow
        self.report = report
        self.report_path = report_path
        self.report_handler = report_handler
        self.error = None
        self.finished = threading.Event()
        self.connections = []
        self.downloads = []
        self.logout_actions = []
        self.stack = ExitStack()

    def __enter__(self):
        try:
            self.telnet = self.stack.enter_context(socket.socket())
            self.telnet.bind(('127.0.0.1', 0))
            self.telnet.listen(1)
            self.telnet.settimeout(40)
            self.telnet_port = self.telnet.getsockname()[1]
            # Reserve a supported callback port until just before CLI startup.
            self.reservation = self.stack.enter_context(socket.socket())
            for port in range(6500, 6399, -1):
                try:
                    self.reservation.bind(('0.0.0.0', port))
                    self.callback_port = port
                    break
                except OSError:
                    continue
            else:
                raise AssertionError('No free synthetic callback port in 6400..6500')
            if self.report is not None:
                self.start_http()
            self.worker = threading.Thread(target=self.run, daemon=True)
            self.worker.start()
            return self
        except BaseException:
            self.stack.close()
            raise

    def start_http(self):
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                backend.downloads.append(self.path)
                if backend.report_handler is not None:
                    backend.report_handler(self, backend)
                    return
                if self.path != backend.report_path:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(backend.report)))
                self.end_headers()
                self.wfile.write(backend.report)

            def log_message(self, *args):
                pass

        # Report workflows use HTTP port 80. Fail explicitly if busy.
        class LoopbackHttp(HTTPServer):
            allow_reuse_address = False

            def server_bind(self):
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()

            def get_request(self):
                sock, address = super().get_request()
                sock.settimeout(5)
                return sock, address

        self.http = LoopbackHttp(('127.0.0.1', 80), Handler)
        self.stack.callback(self.http.server_close)
        self.http_worker = threading.Thread(
            target=lambda: self.http.serve_forever(poll_interval=0.1), daemon=True)
        self.http_worker.start()
        self.stack.callback(self.http_worker.join, 2)
        self.stack.callback(self.http.shutdown)

    def __exit__(self, *args):
        for sock in self.connections:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self.telnet.close()
        self.worker.join(2)
        self.stack.close()
        if self.worker.is_alive():
            raise AssertionError('Synthetic ERP worker did not stop within deadline')

    def connect(self, feid, feid2):
        sock = socket.create_connection(('127.0.0.1', self.callback_port), timeout=20)
        sock.settimeout(20)
        self.connections.append(sock)
        return Peer(sock, feid, feid2, self.callback_port, str(len(self.connections)))

    def run(self):
        try:
            telnet, _ = self.telnet.accept()
            self.connections.append(telnet)
            telnet.settimeout(35)
            telnet.sendall(b'\xff\xfd\x18Password:')
            pending = bytearray()

            def until(marker):
                while marker not in pending:
                    chunk = telnet.recv(65536)
                    if not chunk:
                        raise AssertionError('Telnet ended before bootstrap')
                    pending.extend(chunk)
                    if len(pending) > 65536:
                        raise AssertionError('Telnet receive limit exceeded')
                end = pending.index(marker) + len(marker)
                result = bytes(pending[:end])
                del pending[:end]
                return result

            until(b'synthetic-password\r\x00')
            telnet.sendall(b'\r\n<topprod:test> ')
            command = until(b'\r\x00\xff\xf1').decode('utf-8', errors='ignore')
            feid = re.search(r'_FGLFEID="([^"]+)"', command)[1]
            feid2 = re.search(r'_FGLFEID2="([^"]+)"', command)[1]
            endpoint = re.search(r'FGLSERVER="([^"]+)"', command)[1]
            if endpoint != f'127.0.0.1:{self.callback_port - 6400}' or not command.endswith('udm7;exit;\r\x00'):
                raise AssertionError('Unexpected shell bootstrap')
            telnet.sendall(f'SIM_ENV|{endpoint}|{feid}|{feid2}|END\r\n'.encode())

            login = self.connect(feid, feid2)
            login.send(add(0, 'Interface'), field(10, 'g_plant', 'TEST'), action(11),
                       add(12, 'FunctionCall', {'name': 'getenv'},
                           spec('FunctionCallParameter', 13, {'value': 'COMPUTERNAME'})))
            login.expect('FunctionCallReturn', 'value "synthetic-client"')
            login.expect('ActionEvent', 'idRef "11"')
            login.sock.close()

            menu = self.connect(feid, feid2)
            menu.send(add(0, 'Interface'), field(20, 'favorite_prog'), action(21),
                      add(22, 'Menu', {'active': '1'},
                          spec('MenuAction', 23, {'name': 'close_udmtree', 'active': '1'})))
            menu.expect('ConfigureEvent', 'idRef "20"', 'cursor "0"')
            menu.expect(f'value "{self.program}"', 'ActionEvent', 'idRef "21"')

            feature = self.connect(feid, feid2)
            self.workflow(feature)
            feature.expect('ActionEvent', 'idRef "900"')
            self.logout_actions.append('feature_exit')
            feature.sock.close()
            menu.expect('ActionEvent', 'idRef "23"')
            self.logout_actions.append('menu_exit')
            menu.sock.close()
            telnet.shutdown(socket.SHUT_WR)  # Server EOF is independent of client closure.
            telnet.close()
        except BaseException as exc:
            self.error = exc
        finally:
            self.finished.set()
