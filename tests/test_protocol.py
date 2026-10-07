import re
import struct
import unittest
from erp_sim.config import Settings
from erp_sim.errors import ErpError
from erp_sim.protocol.dcp import FrameDecoder, AuiTree, decode_text, parse_lists
from erp_sim.protocol.events import Events, action, configure, frame, function_return
from erp_sim.protocol.handshake import SessionKeys, app_id, client_greeting, announcements


class ProtocolTests(unittest.TestCase):
    def test_native_handshake_vectors(self):
        vectors = [
            ('LEXYERPAP01:48308', '{39944577-960e-439b-a925-44d3a80e23fb}', '42d1ec3a-4f5b-3a25-4e60-14a0b539c201'),
            ('LEXYERPAP02:23166', '{e01f1716-0e04-4408-b204-66edb52a6151}', '0675bebd-f50b-f800-d9ae-a6f2094306f7'),
            ('LEXYERPAP02:23273', '{e01f1716-0e04-4408-b204-66edb52a6151}', '2b714097-fa97-e7c0-9070-92055b245cfc'),
            ('LEXYERPAP02:23390', '{e01f1716-0e04-4408-b204-66edb52a6151}', '8954d251-4429-66f2-e899-3b00332653cb')]
        for proc, key, expected in vectors:
            self.assertEqual(app_id(proc, key), expected)

    def test_greeting_fresh_keys_and_callback_validation(self):
        keys = SessionKeys()
        cfg = Settings('erp.test', '127.0.0.1', 'test', 'secret', hostname='injected-host')
        server = ('meta Connection{{frontEndID "%s"}{procId "server:123"}}' % keys.feid).encode()
        actual = client_greeting(server, keys, cfg, 2)
        self.assertIn(keys.feid2.encode(), actual)
        self.assertIn(b'{connections "2"}', actual)
        self.assertIn(b'{port "6401"}', actual)
        self.assertIn(b'{host "injected-host"}', actual)
        self.assertIn(b'host-name =injected-host', actual)
        self.assertNotIn(b'secret', actual)
        self.assertNotEqual(keys, SessionKeys())
        with self.assertRaises(ErpError):
            client_greeting(server, SessionKeys(), cfg, 1)

    def test_binary_announcements_match_wire_format(self):
        packets = list(announcements(['file_q', 'file_w']))
        extensions = b'.svg;.SVG;.png;.PNG;.gif;.GIF;.jpg;.JPG;.tif;.TIF;.tiff;.TIFF;.bmp;.BMP;.ico;.ICO'
        self.assertEqual(packets[0][9:], b'\x02\xff\xff\xff\xff\x00\x00\x00\x06file_q\x00\x00\x00Q' + extensions + b'\x00\x00')
        self.assertEqual(packets[3][9:], b'\x05\xff\xff\xff\xfe\x00\x00\x00\x00')
        self.assertEqual(struct.unpack('>II', packets[0][:8]), (102, 102))

    def test_event_sequence_is_local_and_escaped(self):
        first, second = Events(), Events()
        self.assertIn(b'event _om 0', first.emit(action(400)))
        self.assertIn(b'event _om 1', first.emit(action(400)))
        self.assertIn(b'event _om 0', second.emit(action(400)))
        value = 'a"\\中文\nline\\n'
        wire = second.emit(configure(10, value=value), action(20))
        self.assertEqual(wire[9:].count(b'\n'), 1)
        parsed = parse_lists(wire[9:].decode())
        self.assertEqual(dict(parsed[4][0][2])['value'], value)
        parse_lists(second.emit(function_return('host', 'STRING'))[9:].decode())

    def test_frame_splits_and_utf8_boundaries(self):
        value = '中文'.encode()
        raw = b'meta Connection{}\n' + frame(value[:2]) + frame(value[2:])
        self.assertEqual(decode_text(raw), '中文')
        for i in range(len(raw) + 1):
            decoder = FrameDecoder()
            frames = decoder.feed(raw[:i]) + decoder.feed(raw[i:])
            self.assertEqual(b''.join(p for _, p in frames), value)
        with self.assertRaises(ValueError):
            decode_text(raw[:-1])

    def test_compression_and_malformed_aui_rejected(self):
        with self.assertRaises(ValueError):
            decode_text(b'meta Connection{}\n' + struct.pack('>II', 1, 2) + b'\x01x')
        for text in ('om 0{', 'om 0{{un 99{{value "x"}}}}', 'om 0{{bad 0}}'):
            with self.assertRaises(ValueError):
                AuiTree().apply(text)

    def test_generic_tree_selects_only_requested_key_and_accumulates_pages(self):
        import json
        def serialize(value):
            return '{' + ' '.join(map(serialize,value)) + '}' if isinstance(value,list) else json.dumps(value)
        table = ['Table',1,[['dialogType','DisplayArray'],['size','2'],['offset','0']],
                 [['TableColumn',2,[['colName','key'],['text','ID']],
                   [['ValueList',3,[],[['Value',4,[['value','001']],[]]]]]]]]
        other = ['Table',10,[['dialogType','DisplayArray'],['size','1'],['offset','0']],
                 [['TableColumn',11,[['colName','other']],[]]]]
        text = 'om 0' + serialize([['an',0,'Interface',0,[],[table,other]]])
        text += 'om 1{{un 1{{offset "1"}}}{un 4{{value "002"}}}}'
        tree = AuiTree('key').apply(text)
        self.assertEqual(tree.rows, {0: {'key': '001'}, 1: {'key': '002'}})
        self.assertEqual(tree.total, 2)
        tree.apply('om 2{{rn 0}}')
        self.assertEqual(tree.nodes, {})
        self.assertEqual(len(tree.rows), 2)
