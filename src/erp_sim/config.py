"""Explicit configuration; credentials are never included in repr or results."""
from dataclasses import dataclass, field
import ipaddress
import math
import os
import re
import socket
import tomllib
from pathlib import Path
from .errors import ErpError


DEFAULT_ERP_HOST = '192.168.0.160'


def detect_callback_host(host, port):
    """Return the local IPv4 address selected by the OS route to the ERP host."""
    try:
        targets = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
        if not targets:
            raise OSError
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(targets[0][4])
            address = route.getsockname()[0]
        parsed = ipaddress.IPv4Address(address)
        if parsed.is_unspecified or parsed.is_multicast:
            raise OSError
        return address
    except (OSError, ValueError, TypeError):
        raise ErpError(
            'CONFIG_ERROR',
            'Could not detect callback_host from the route to the ERP server; '
            'set ERP_SIM_CALLBACK_HOST explicitly',
        ) from None


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_ERP_HOST
    callback_host: str | None = None
    username: str = ''
    password: str = field(default='', repr=False)
    telnet_port: int = 23
    listen_port: int = 6401
    timeout: float = 150
    cleanup_timeout: float = 20
    hostname: str = field(default_factory=socket.gethostname)

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}', self.host):
            raise ErpError('CONFIG_ERROR', 'host must be an IPv4 address or DNS name')
        try:
            callback = ipaddress.IPv4Address(self.callback_host)
        except (ValueError, TypeError):
            raise ErpError('CONFIG_ERROR', 'callback_host must be a reachable local IPv4 address') from None
        if callback.is_unspecified or callback.is_multicast:
            raise ErpError('CONFIG_ERROR', 'callback_host must be a usable local IPv4 address')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', self.username):
            raise ErpError('CONFIG_ERROR', 'username must be an ASCII account identifier')
        if not self.password or any(c in self.password for c in '\r\n\x00'):
            raise ErpError('CONFIG_ERROR', 'password is required and must not contain CR, LF or NUL')
        if not 1 <= self.telnet_port <= 65535 or not 6400 <= self.listen_port <= 6500:
            raise ErpError('CONFIG_ERROR', 'telnet_port must be 1..65535; listen_port must be 6400..6500')
        if not all(math.isfinite(x) and 0 < x <= 3600 for x in (self.timeout, self.cleanup_timeout)):
            raise ErpError('CONFIG_ERROR', 'timeouts must be finite and in (0, 3600] seconds')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', self.hostname):
            raise ErpError('CONFIG_ERROR', 'hostname must be an ASCII host identifier')


def effective_config_path(config_path=None, environ=None):
    env = os.environ if environ is None else environ
    return config_path or env.get('ERP_SIM_CONFIG')


def load_settings(config_path=None, overrides=None, environ=None):
    env = os.environ if environ is None else environ
    values = {}
    path = effective_config_path(config_path, env)
    if path:
        try:
            document = tomllib.loads(Path(path).read_text(encoding='utf-8-sig'))
            if set(document) != {'connection'} or not isinstance(document['connection'], dict):
                raise ValueError('expected only a [connection] table')
            values.update(document['connection'])
        except (OSError, ValueError):
            raise ErpError('CONFIG_ERROR', 'Cannot load connection TOML; check path and syntax') from None
    allowed = set(Settings.__dataclass_fields__)
    if set(values) - allowed or 'password' in values:
        raise ErpError(
            'CONFIG_ERROR',
            'Unknown configuration key or password in TOML; use request.password or ERP_SIM_PASSWORD',
        )
    for key in allowed:
        value = env.get('ERP_SIM_' + key.upper())
        if value is not None:
            values[key] = value
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    values.setdefault('host', DEFAULT_ERP_HOST)
    for key in ('username', 'password'):
        if not values.get(key):
            raise ErpError('CONFIG_ERROR', f'Missing {key}; provide a JSON request field or configuration value')
    try:
        for key in ('telnet_port', 'listen_port'):
            if key in values:
                values[key] = int(values[key])
        for key in ('timeout', 'cleanup_timeout'):
            if key in values:
                values[key] = float(values[key])
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}', values['host']):
            raise ErpError('CONFIG_ERROR', 'host must be an IPv4 address or DNS name')
        if not values.get('callback_host'):
            values['callback_host'] = detect_callback_host(values['host'], values.get('telnet_port', 23))
        return Settings(**values)
    except (TypeError, ValueError):
        raise ErpError('CONFIG_ERROR', 'Invalid configuration type') from None
