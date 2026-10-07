"""Bounded JSON request transport and validation against the packaged input contract.

Only the small schema vocabulary used by request.schema.json is supported here.
This is not a general JSON Schema implementation; conformance is cross-checked
against jsonschema in the offline tests. No runtime dependency is required.
"""
import argparse
from datetime import date
from importlib.resources import files
import io
import json
import math
import os
from pathlib import Path
import queue
import re
import sys
import threading
from typing import NoReturn

from .errors import ErpError


MAX_REQUEST_BYTES = 64 * 1024
STDIN_TIMEOUT = 10


def invalid(message: str) -> NoReturn:
    raise ErpError('INVALID_ARGUMENT', message)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse messages can contain the complete JSON request or credentials.
        invalid('Use one JSON argument or --request FILE (use - for stdin); see --help')


def build_parser():
    parser = Parser(prog='erp-sim', allow_abbrev=False,
                    description='ERP JSON request CLI. Legacy subcommands are not supported.',
                    epilog='All commands use JSON, including {"command":"features"}. '
                           'Read request.schema.json with {"command":"schema"}. '
                           'Input: UTF-8, at most 65536 bytes; stdin must reach EOF within 10 seconds.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('json_request', nargs='?', metavar='JSON', help='One JSON object as a single argument')
    source.add_argument('--request', metavar='FILE', help='Read a JSON file, or - for stdin')
    return parser


def request_schema():
    return json.loads(files('erp_sim.resources').joinpath('request.schema.json').read_text(encoding='utf-8'))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            invalid('Duplicate JSON property')
        result[key] = value
    return result


def _constant(value):
    invalid('Non-finite JSON numbers are not supported')


def _validate(value, rule, path='request'):
    if 'oneOf' in rule:
        matches = 0
        for branch in rule['oneOf']:
            try:
                _validate(value, branch, path)
                matches += 1
            except ErpError:
                pass
        if matches != 1:
            invalid(f'{path} must select request, request_error, or response with a feature')
        return
    kind = rule['type']
    matches = {
        'object': lambda: type(value) is dict,
        'string': lambda: type(value) is str,
        'boolean': lambda: type(value) is bool,
        'integer': lambda: type(value) is int or (type(value) is float and math.isfinite(value) and value.is_integer()),
        'number': lambda: type(value) is int or (type(value) is float and math.isfinite(value)),
    }
    if not matches[kind]():
        invalid(f'{path} must be {kind}')
    if 'const' in rule and value != rule['const']:
        invalid(f'{path} has an unsupported value')
    if 'enum' in rule and value not in rule['enum']:
        invalid(f'{path} has an unsupported value')
    if kind == 'object':
        properties = rule['properties']
        if set(value) - properties.keys():
            invalid(f'{path} contains an unknown property')
        for key in rule.get('required', []):
            if key not in value:
                invalid(f'{path}.{key} is required')
        for key, item in value.items():
            _validate(item, properties[key], f'{path}.{key}')
    elif kind == 'string':
        if not rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', MAX_REQUEST_BYTES):
            invalid(f'{path} has an invalid length')
        if 'pattern' in rule and re.search(rule['pattern'], value) is None:
            invalid(f'{path} has an invalid format')
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            invalid(f'{path} contains invalid Unicode')
        if rule.get('format') == 'date':
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    raise ValueError
            except ValueError:
                invalid(f'{path} must be a valid YYYY-MM-DD date')
    elif kind in ('integer', 'number'):
        if (value < rule.get('minimum', -math.inf) or value > rule.get('maximum', math.inf)
                or ('exclusiveMinimum' in rule and value <= rule['exclusiveMinimum'])):
            invalid(f'{path} is outside the supported range')


def parse_request(raw):
    try:
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        if len(raw) > MAX_REQUEST_BYTES:
            invalid('Request exceeds 65536 bytes')
        document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                              parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError):
        invalid('Request must contain exactly one valid UTF-8 JSON object')
    if type(document) is not dict:
        invalid('request must be object')
    command = document.get('command')
    branches = request_schema()['oneOf']
    branch = next((item for item in branches if item['properties']['command']['const'] == command), None)
    if branch is None:
        invalid('request.command is required and must name a supported command')
    _validate(document, branch)
    document.setdefault('request_version', '1')
    document.setdefault('feature_args', {})
    return document


def _stdin_bytes(stream):
    if stream.isatty():
        invalid('Pipe a complete JSON request to stdin and close the pipe')
    try:
        descriptor = stream.fileno()
    except (AttributeError, io.UnsupportedOperation):
        # In-memory streams used by library callers and unit tests.
        return stream.read(MAX_REQUEST_BYTES + 1)
    result = queue.Queue(maxsize=1)

    def read():
        try:
            chunks, total = [], 0
            while total <= MAX_REQUEST_BYTES:
                chunk = os.read(descriptor, min(8192, MAX_REQUEST_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            result.put(b''.join(chunks))
        except OSError:
            result.put(None)

    # Use os.read, not a buffered stdin reader: an unfinished daemon must not
    # hold Python's buffered stream lock during interpreter shutdown.
    threading.Thread(target=read, daemon=True).start()
    try:
        raw = result.get(timeout=STDIN_TIMEOUT)
    except queue.Empty:
        invalid('Stdin must reach EOF within 10 seconds')
    if raw is None:
        invalid('Could not read the JSON request from stdin')
    return raw


def read_request(argv=None):
    tokens = list(sys.argv[1:] if argv is None else argv)
    if sum(token == '--request' or token.startswith('--request=') for token in tokens) > 1:
        invalid('Specify exactly one request source')
    args = build_parser().parse_args(tokens)
    source = None
    try:
        if args.request == '-':
            raw = _stdin_bytes(sys.stdin)
        elif args.request is not None:
            source = Path(args.request).resolve()
            if not source.is_file():
                invalid('Request file must be an existing regular file')
            with source.open('rb') as stream:
                raw = stream.read(MAX_REQUEST_BYTES + 1)
        else:
            raw = args.json_request
    except (OSError, ValueError):
        invalid('Could not read the JSON request file')
    return parse_request(raw), source
