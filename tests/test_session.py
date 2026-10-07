from datetime import date
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from erp_sim.config import Settings
from erp_sim.errors import ErpError
from erp_sim.features.cxmr4103 import OrderQuery, Cxmr4103
from erp_sim.session import Channel, GdcSession
from erp_sim.protocol.events import frame


class SessionTests(unittest.TestCase):
    def settings(self, **kw):
        return Settings('erp.test','127.0.0.1','test','secret',**kw)

    def feature(self):
        return Cxmr4103(OrderQuery('S*',date(2026,9,10),date(2026,9,11)))

    def test_port_collision_never_starts_authentication(self):
        sock=MagicMock();sock.bind.side_effect=OSError(10048,'occupied')
        with patch('erp_sim.session.socket.socket',return_value=sock), patch('erp_sim.session.run_session') as auth:
            result=GdcSession(self.settings()).execute(self.feature())
        self.assertEqual(result.error.code,'PORT_IN_USE');auth.assert_not_called();sock.close.assert_called()

    def test_existing_trace_directory_is_rejected_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp, patch('erp_sim.session.socket.socket') as factory:
            with self.assertRaises(ErpError) as caught:
                GdcSession(self.settings(),tmp).execute(self.feature())
            self.assertEqual(caught.exception.code,'INVALID_ARGUMENT');factory.assert_not_called()

    def test_auth_failure_and_socket_cleanup(self):
        with patch('erp_sim.session.socket.socket') as factory, patch('erp_sim.session.select.select',return_value=([],[],[])), \
             patch('erp_sim.session.run_session',return_value={'status':'server_eof','command_sent':False}):
            result=GdcSession(self.settings()).execute(self.feature())
        self.assertEqual(result.error.code,'AUTH_FAILED');self.assertFalse(result.logout_verified)
        factory.return_value.close.assert_called()

    def test_timeout_stops_worker_and_closes_listener(self):
        def wait_for_stop(*args,**kwargs):
            args[6].wait(2)
            return {'status':'stopped','command_sent':True}
        with patch('erp_sim.session.socket.socket') as factory, patch('erp_sim.session.select.select',return_value=([],[],[])), \
             patch('erp_sim.session.run_session',side_effect=wait_for_stop):
            result=GdcSession(self.settings(timeout=0.01,cleanup_timeout=0.01)).execute(self.feature())
        self.assertEqual(result.error.code,'TIMEOUT');factory.return_value.close.assert_called()

    def test_eof_without_result_is_not_success(self):
        with patch('erp_sim.session.socket.socket'), patch('erp_sim.session.select.select',return_value=([],[],[])), \
             patch('erp_sim.session.run_session',return_value={'status':'server_eof','command_sent':True}):
            result=GdcSession(self.settings()).execute(self.feature())
        self.assertEqual(result.error.code,'INCOMPLETE_RESULT');self.assertIsNone(result.data)

    def test_complete_data_without_logout_evidence_is_failure(self):
        feature=self.feature()
        def finished(*args, **kwargs):
            feature.done=True
            feature.result={'complete':True,'rows':[]}
            return {'status':'server_eof','command_sent':True}
        with patch('erp_sim.session.socket.socket'), patch('erp_sim.session.select.select',return_value=([],[],[])), \
             patch('erp_sim.session.run_session',side_effect=finished):
            result=GdcSession(self.settings()).execute(feature)
        self.assertEqual(result.error.code,'LOGOUT_UNVERIFIED')
        self.assertTrue(result.data['complete']);self.assertFalse(result.logout_verified)

    def test_channels_have_independent_event_sequences(self):
        a,b=Channel(MagicMock(),'a','key'),Channel(MagicMock(),'b','key')
        a.emit('{ActionEvent 0{{idRef "1"}}}')
        self.assertEqual(a.events.sequence,1);self.assertEqual(b.events.sequence,0)

    def test_delayed_partial_frame_does_not_trigger_protocol_failure(self):
        channel=Channel(MagicMock(),'test','key')
        raw=b'meta Connection{}\n'+frame('om 0{}')
        channel.raw.extend(raw[:-2])
        self.assertFalse(channel.parse())
        channel.raw.extend(raw[-2:])
        self.assertTrue(channel.parse())
        self.assertEqual(channel.tree.om_count,1)

    def test_complete_frames_can_split_one_utf8_character(self):
        channel=Channel(MagicMock(),'test','key')
        text='om 0{{an 0 Label 1{{text "中文"}}{}}}'
        payload=text.encode('utf-8')
        split=payload.index('中'.encode('utf-8'))+1
        channel.raw.extend(b'meta Connection{}\n'+frame(payload[:split]))
        self.assertFalse(channel.parse())
        channel.raw.extend(frame(payload[split:]))
        self.assertTrue(channel.parse())
        self.assertEqual(channel.tree.nodes[1]['attrs']['text'],'中文')

    def test_complete_frames_can_split_one_aui_message(self):
        channel=Channel(MagicMock(),'test','key')
        payload=b'om 0{{an 0 Label 1{{text "value"}}{}}}'
        split=payload.index(b'"value"')+len(b'"value"')
        channel.raw.extend(b'meta Connection{}\n'+frame(payload[:split]))
        self.assertFalse(channel.parse())
        channel.raw.extend(frame(payload[split:]))
        self.assertTrue(channel.parse())
        self.assertEqual(channel.tree.nodes[1]['attrs']['text'],'value')

    def test_complete_frame_still_rejects_invalid_utf8(self):
        channel=Channel(MagicMock(),'test','key')
        channel.raw.extend(b'meta Connection{}\n'+frame(b'\xff'))
        with self.assertRaises(UnicodeDecodeError):
            channel.parse()
