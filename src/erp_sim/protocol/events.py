"""Construct DCP events without interpolating unescaped server or user strings."""
import struct


def quote(value):
    escaped = (str(value).replace('\\', '\\\\').replace('"', '\\"')
               .replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t'))
    return '"' + escaped + '"'


def attrs(values):
    return ''.join('{' + name + ' ' + quote(value) + '}' for name, value in values.items())


def configure(ident, **values):
    return '{ConfigureEvent 0{' + attrs({'idRef': ident, **values}) + '}}'


def action(ident):
    return '{ActionEvent 0{' + attrs({'idRef': ident}) + '}}'


def function_return(value, data_type):
    return ('{FunctionCallEvent 0 {{result "0"}}{ {FunctionCallReturn 0 {' +
            attrs({'dataType': data_type, 'isNull': '0', 'value': value}) + '}{}}}}')


def frame(payload, kind=1):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    return struct.pack('>II', len(payload), len(payload)) + bytes([kind]) + payload


class Events:
    def __init__(self):
        self.sequence = 0

    def emit(self, *commands):
        result = frame('event _om %d{}{%s}\n' % (self.sequence, ''.join(commands)))
        self.sequence += 1
        return result
