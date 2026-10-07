"""One isolated ERP session per execution; serialized callback state transitions."""
from dataclasses import dataclass
import logging
from pathlib import Path
import select
import socket
import threading
import time
from .auth.bootstrap import bootstrap_command
from .auth.telnet import run_session
from .errors import ErpError
from .navigation import (LoginFlow, MenuFlow, FrontendCalls, LogoutFlow,
                         account_binding_rejected, screen_role)
from .protocol.dcp import AuiTree, FrameDecoder, IncompleteDcp, decode_text
from .protocol.events import Events
from .protocol.handshake import SessionKeys, client_greeting

log = logging.getLogger(__name__)


class Channel:
    def __init__(self, sock, tag, key_column, trace_dir=None):
        self.sock, self.tag, self.key_column = sock, tag, key_column
        self.trace_dir = trace_dir
        self.raw = bytearray()
        self.tree = AuiTree(key_column)
        self.events = Events()
        self.changed = time.monotonic()
        self.greeted = self.closed = False
        self.role = 'feature'
        self.parsed_size = 0

    def quiet(self, seconds):
        return time.monotonic() - self.changed >= seconds

    def touch(self):
        self.changed = time.monotonic()

    def send(self, payload):
        self.sock.sendall(payload)
        if self.trace_dir:
            with (self.trace_dir / f'{self.tag}-c2s.bin').open('ab') as stream:
                stream.write(payload)

    def emit(self, *commands):
        self.send(self.events.emit(*commands))

    def parse(self):
        if len(self.raw) != self.parsed_size:
            decoder = FrameDecoder()
            decoder.feed(bytes(self.raw))
            if decoder.pending:
                return False
            try:
                tree = AuiTree(self.key_column).apply(decode_text(bytes(self.raw)))
            except IncompleteDcp:
                return False
            self.tree = tree
            self.parsed_size = len(self.raw)
        return True


@dataclass
class SessionResult:
    data: dict | None
    logout_verified: bool
    error: ErpError | None


class GdcSession:
    """Execute a fresh feature driver; no mutable state is shared across runs."""
    def __init__(self, settings, trace_dir=None):
        self.settings = settings
        self.trace_dir = Path(trace_dir) if trace_dir else None

    def execute(self, feature):
        if feature.done or feature.result is not None or getattr(feature, 'erp_done', False):
            raise ErpError('INVALID_ARGUMENT', 'Create a fresh feature driver for each execution')
        cfg, keys = self.settings, SessionKeys()
        stop, telnet_done = threading.Event(), threading.Event()
        telnet_status, channels = {}, []
        login, menu = LoginFlow(), MenuFlow(feature.program)
        frontend, logout = FrontendCalls(cfg.hostname), LogoutFlow()
        first_error = None
        closing_at = None
        feature_started = False
        worker = listener = None
        if self.trace_dir:
            try:
                self.trace_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                raise ErpError('INVALID_ARGUMENT', 'trace-dir must be a new directory') from None
        command, expected_env = bootstrap_command(cfg, keys)
        log.info('ERP host %s:%s; callback %s:%s', cfg.host, cfg.telnet_port,
                 cfg.callback_host, cfg.listen_port)

        def authenticate():
            try:
                def observe(text):
                    if expected_env in text:
                        telnet_status['environment_verified'] = True
                telnet_status.update(run_session(cfg.host, cfg.telnet_port, cfg.username, cfg.password,
                    command, self.trace_dir, stop, timeout=cfg.timeout + cfg.cleanup_timeout,
                    on_text=observe, log=log.info))
            except OSError:
                telnet_status['status'] = 'connection_failed'
            except Exception:
                telnet_status['status'] = 'error'
            finally:
                telnet_done.set()

        try:
            listener = socket.socket()
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind(('0.0.0.0', cfg.listen_port))
            except OSError as exc:
                code = 'PORT_IN_USE' if exc.errno in (98, 48, 10048) or getattr(exc, 'winerror', None) == 10048 else 'CONNECTION_FAILED'
                raise ErpError(code, 'Cannot bind callback listener; check listen_port and permissions') from None
            listener.listen(4)
            worker = threading.Thread(target=authenticate, daemon=True, name='erp-sim-auth')
            worker.start()
            deadline = time.monotonic() + cfg.timeout
            while True:
                now = time.monotonic()
                if closing_at is None and now >= deadline:
                    first_error = first_error or ErpError('TIMEOUT', 'Query deadline reached')
                    closing_at = now
                if (feature.done or getattr(feature, 'erp_done', False) or first_error) and closing_at is None:
                    closing_at = now
                if closing_at is not None and now - closing_at >= cfg.cleanup_timeout:
                    break
                if telnet_done.is_set():
                    if not telnet_status.get('command_sent') and not first_error:
                        code = 'CONNECTION_FAILED' if telnet_status.get('status') == 'connection_failed' else 'AUTH_FAILED'
                        first_error = ErpError(code, 'ERP authentication or shell bootstrap did not complete')
                    if not channels or all(c.closed for c in channels):
                        break
                sockets = [listener] + [c.sock for c in channels if not c.closed]
                try:
                    ready, _, _ = select.select(sockets, [], [], 0.1)
                    for sock in ready:
                        if sock is listener:
                            conn, _ = listener.accept()
                            conn.settimeout(1)
                            channels.append(Channel(conn, f'c{len(channels)+1}', feature.key_column, self.trace_dir))
                            continue
                        channel = next(c for c in channels if c.sock is sock)
                        chunk = sock.recv(65536)
                        if not chunk:
                            channel.closed = True
                            sock.close()
                            continue
                        channel.raw.extend(chunk)
                        channel.touch()
                        if len(channel.raw) > 128 * 1024 * 1024:
                            raise ErpError('PROTOCOL_ERROR', 'Callback exceeds the 128 MiB capture limit')
                        if self.trace_dir:
                            (self.trace_dir / f'{channel.tag}-s2c.bin').write_bytes(channel.raw)
                    for channel in channels:
                        if channel.closed:
                            continue
                        if not channel.greeted:
                            if b'\n' not in channel.raw:
                                continue
                            greeting = bytes(channel.raw).split(b'\n', 1)[0]
                            channel.send(client_greeting(greeting, keys, cfg, sum(not c.closed for c in channels)))
                            channel.greeted = True
                        if not channel.quiet(0.5):
                            continue
                        if not channel.parse():
                            continue
                        if account_binding_rejected(channel.tree):
                            raise ErpError(
                                'AUTH_FAILED',
                                'ERP account is not bound to the reported client hostname',
                            )
                        channel.role = screen_role(channel.tree)
                        frontend.advance(channel)
                        if closing_at is not None or feature.done or getattr(feature, 'erp_done', False):
                            if channel.role == 'menu' and any(c.role == 'feature' and not c.closed and c.tree.nodes for c in channels):
                                continue
                            logout.advance(channel)
                        elif channel.role == 'login':
                            login.advance(channel)
                        elif channel.role == 'menu':
                            menu.advance(channel, feature_started)
                        else:
                            # A feature may complete through a non-table UI, so any
                            # parsed feature screen suppresses the menu launch retry.
                            feature_started = bool(channel.tree.nodes)
                            feature.advance(channel)
                except KeyboardInterrupt:
                    first_error = ErpError('INTERRUPTED', 'Execution interrupted; cleanup requested')
                    closing_at = closing_at or time.monotonic()
                except ErpError as exc:
                    first_error = first_error or exc
                    closing_at = closing_at or time.monotonic()
                except (ValueError, UnicodeError, KeyError, IndexError):
                    first_error = first_error or ErpError('PROTOCOL_ERROR', 'Invalid or unsupported server protocol data')
                    closing_at = closing_at or time.monotonic()
                except OSError:
                    first_error = first_error or ErpError('CONNECTION_FAILED', 'Callback connection failed')
                    closing_at = closing_at or time.monotonic()
        except ErpError as exc:
            first_error = first_error or exc
        finally:
            stop.set()
            if listener:
                listener.close()
            for channel in channels:
                if not channel.closed:
                    try:
                        channel.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    channel.sock.close()
            if worker:
                worker.join(timeout=11)
        verified = bool(channels and all(c.closed for c in channels) and logout.sent and
                        telnet_status.get('status') == 'server_eof' and telnet_status.get('environment_verified'))
        if first_error is None and getattr(feature, 'erp_done', False):
            try:
                feature.finish()
            except ErpError as exc:
                first_error = exc
            except KeyboardInterrupt:
                first_error = ErpError('INTERRUPTED', 'Execution interrupted after session cleanup')
        if first_error is None and not feature.done:
            first_error = ErpError('INCOMPLETE_RESULT', 'Server session ended without a complete verified result')
        if first_error is None and not verified:
            first_error = ErpError('LOGOUT_UNVERIFIED', 'Data is complete but graceful ERP logout was not verified')
        return SessionResult(feature.result, verified, first_error)
