"""GDC 2.40 greeting and file announcements; no captured sessions required."""
from dataclasses import dataclass, field
import hashlib
import re
import struct
import uuid
from .events import attrs, frame
from ..errors import ErpError


@dataclass(frozen=True)
class SessionKeys:
    feid: str = field(default_factory=lambda: '{' + str(uuid.uuid4()) + '}')
    feid2: str = field(default_factory=lambda: '{' + str(uuid.uuid4()) + '}')


def app_id(proc_id, feid2):
    digest = hashlib.md5(('{' + proc_id + '}-' + feid2).encode('latin1')).digest()
    return str(uuid.UUID(bytes=digest))


def client_greeting(greeting, keys, settings, active_connections):
    if not greeting.startswith(b'meta Connection'):
        raise ErpError('PROTOCOL_ERROR', 'Expected a DCP Connection greeting')
    key = re.search(rb'\{frontEndID "([^"]+)"\}', greeting)
    proc = re.search(rb'\{procId "([^"]+)"\}', greeting)
    if not key or key[1].decode() != keys.feid or not proc:
        raise ErpError('PROTOCOL_ERROR', 'Callback session key or process challenge is invalid')
    info = (f'host-name ={settings.hostname}^hw-addr   =00-00-00-00-00-00'
            f'^host-addr ={settings.callback_host}^user-name ={settings.username}'
            f'^app-id    ={{{app_id(proc[1].decode(), keys.feid2)}}}^cx-mode   =direct')
    return ('meta Client{' + attrs({'name': 'GDC', 'version': '2.40.21-4635.80',
        'host': settings.hostname, 'connections': active_connections, 'port': settings.listen_port,
        'frontEndID2': keys.feid2, 'encapsulation': '1', 'filetransfer': '1', 'clientInfo': info}) + '}\n').encode()


def announcements(names):
    extensions = b'.svg;.SVG;.png;.PNG;.gif;.GIF;.jpg;.JPG;.tif;.TIF;.tiff;.TIFF;.bmp;.BMP;.ico;.ICO'
    # Constructed from the observed file-channel request/ack format.
    for index, name in enumerate(names):
        encoded = name.encode('ascii')
        slot = struct.pack('>i', -1 - index)
        yield frame(b'\x02' + slot + struct.pack('>I', len(encoded)) + encoded +
                    struct.pack('>I', len(extensions)) + extensions + b'\x00\x00', 5)
        yield frame(b'\x05' + slot + b'\x00\x00\x00\x00', 5)
