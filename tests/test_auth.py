import tempfile
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch
from erp_sim.auth.telnet import TelnetCodec, run_session
from erp_sim.auth.bootstrap import bootstrap_command
from erp_sim.config import Settings
from erp_sim.protocol.handshake import SessionKeys


class AuthTests(unittest.TestCase):
    def test_telnet_at_every_split(self):
        wire = b'\xff\xfd\x18\xff\xfd\x27\xff\xfa\x27\x01\x00USER\xff\xf0\xff\xfd\x1fPassword: '
        baseline = TelnetCodec('test').feed(wire)
        for i in range(len(wire) + 1):
            codec = TelnetCodec('test')
            a, x = codec.feed(wire[:i]); b, y = codec.feed(wire[i:])
            self.assertEqual((a + b, x + y), baseline)

    def test_telnet_escaped_iac_and_option_refusal(self):
        codec = TelnetCodec('test')
        plain, replies = codec.feed(b'A\xff\xffB\xff\xfd\x63')
        self.assertEqual(plain, b'A\xffB')
        self.assertEqual(replies, [b'\xff\xfc\x63'])

    def test_bootstrap_uses_same_session_keys_and_port_offset(self):
        cfg = Settings('erp.test', '127.0.0.1', 'test', 'secret', listen_port=6407)
        keys = SessionKeys()
        command, marker = bootstrap_command(cfg, keys)
        self.assertIn('127.0.0.1:7', command)
        self.assertIn(keys.feid2, command)
        self.assertIn(keys.feid.encode(), marker)
        self.assertNotIn('secret', command)
        self.assertTrue(command.endswith('udm7;exit;'))

    def test_prompt_sequence_sends_command_once_and_redacts_trace(self):
        class Socket:
            def __init__(self):
                self.chunks = iter([b'Pass', b'word: ', b'DVM banner', b'secret\n<topprod:host> ', b'<topprod:host> ', b''])
                self.sent, self.closed = [], False
            def __enter__(self): return self
            def __exit__(self, *args): self.closed = True
            def setsockopt(self, *args): pass
            def settimeout(self, *args): pass
            def recv(self, *args): return next(self.chunks)
            def sendall(self, data): self.sent.append(data)
        sock = Socket()
        with tempfile.TemporaryDirectory() as tmp, patch('erp_sim.auth.telnet.socket.create_connection', return_value=sock):
            result = run_session('test', 23, 'test', 'secret', 'fixed-command', tmp, Event(), log=lambda x: None)
            self.assertNotIn(b'secret', (Path(tmp)/'telnet.txt').read_bytes())
        self.assertEqual(sock.sent, [b'secret\r\x00', b'fixed-command\r\x00\xff\xf1'])
        self.assertTrue(sock.closed)
        self.assertEqual(result['status'], 'server_eof')
