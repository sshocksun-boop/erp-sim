"""Incremental Telnet negotiation and bounded, prompt-driven session handling."""
import socket
import time
from pathlib import Path


class TelnetCodec:
    def __init__(self, user):
        self.user = user.encode('ascii')
        self.pending = bytearray()
        self.local = set()
        self.remote = set()

    def feed(self, data):
        self.pending.extend(data)
        b = self.pending
        pos = 0
        plain = bytearray()
        replies = []
        while pos < len(b):
            if b[pos] != 255:
                plain.append(b[pos]); pos += 1; continue
            if pos + 1 >= len(b): break
            cmd = b[pos + 1]
            if cmd == 255:
                plain.append(255); pos += 2; continue
            if cmd == 250:
                end = b.find(b'\xff\xf0', pos + 2)
                if end < 0: break
                sub = bytes(b[pos + 2:end]).replace(b'\xff\xff', b'\xff')
                if len(sub) >= 2 and sub[1] == 1:
                    values = {24: b'XTERM', 32: b'38400,38400',
                              39: b'\x00USER\x01' + self.user}
                    if sub[0] in values:
                        replies.append(b'\xff\xfa' + bytes([sub[0], 0]) + values[sub[0]] + b'\xff\xf0')
                pos = end + 2; continue
            if cmd in (251, 252, 253, 254):
                if pos + 2 >= len(b): break
                opt = b[pos + 2]
                if cmd == 253:
                    if opt not in self.local:
                        supported = opt in (0, 3, 24, 31, 32, 39)
                        replies.append(bytes([255, 251 if supported else 252, opt]))
                        if supported:
                            self.local.add(opt)
                            if opt == 31:
                                replies.append(b'\xff\xfa\x1f\x00\x50\x00\x18\xff\xf0')
                elif cmd == 251:
                    if opt not in self.remote:
                        supported = opt in (0, 1, 3)
                        replies.append(bytes([255, 253 if supported else 254, opt]))
                        if supported: self.remote.add(opt)
                elif cmd == 254 and opt in self.local:
                    self.local.remove(opt)
                    replies.append(bytes([255, 252, opt]))
                elif cmd == 252 and opt in self.remote:
                    self.remote.remove(opt)
                    replies.append(bytes([255, 254, opt]))
                pos += 3; continue
            pos += 2
        del b[:pos]
        return bytes(plain), replies


def run_session(host, port, user, password, command, output_dir, stop, timeout=90,
                on_text=None, log=print, command_trigger='shell'):
    """Execute only the caller's explicit command, close socket in all paths.

    Socket closure alone is not proof of ERP logout; caller records that separately.
    """
    codec = TelnetCodec(user)
    raw = bytearray()
    plain = bytearray()
    password_sent = command_sent = False
    started = time.monotonic()
    output_dir = Path(output_dir) if output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
    status = 'timeout'
    with socket.create_connection((host, port), timeout=min(timeout, 10)) as sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(0.5)
        while time.monotonic() - started < timeout and not stop.is_set():
            try:
                data = sock.recv(65536)
                if not data:
                    status = 'server_eof'; break
            except socket.timeout:
                continue
            raw.extend(data)
            cooked, replies = codec.feed(data)
            for reply in replies: sock.sendall(reply)
            plain.extend(cooked)
            if on_text: on_text(bytes(plain))
            if not password_sent and b'assword:' in plain[-160:]:
                # NVT represents a bare carriage return as CR NUL.
                sock.sendall(password.encode('utf-8') + b'\r\x00')
                password_sent = True
                log('Telnet password prompt answered')
            # Wait for the actual shell prompt, not the earlier DVM version banner.
            ready = (b'last login:' in plain.lower() if command_trigger == 'last_login'
                     else b'<topprod:' in plain[-500:] and b'> ' in plain[-80:])
            if password_sent and not command_sent and ready:
                sock.sendall(command.encode('utf-8') + b'\r\x00\xff\xf1')
                command_sent = True
                log('Telnet shell command submitted')
            if output_dir:
                # Never persist password echoes from an unexpected server mode.
                secret = password.encode('utf-8')
                (output_dir / 'telnet-s2c.bin').write_bytes(bytes(raw).replace(secret, b'[REDACTED]'))
                (output_dir / 'telnet.txt').write_bytes(bytes(plain).replace(secret, b'[REDACTED]'))
        if stop.is_set(): status = 'stopped'
    return {'status': status, 'command_sent': command_sent,
            'password_prompt_seen': password_sent, 'bytes': len(raw)}
