"""Stable errors shared by the library and JSON CLI."""

EXIT_CODES = {
    'INVALID_ARGUMENT': 2, 'CONFIG_ERROR': 3, 'AUTH_FAILED': 4,
    'CONNECTION_FAILED': 5, 'TIMEOUT': 6, 'PROTOCOL_ERROR': 7,
    'CONDITION_MISMATCH': 8, 'INCOMPLETE_RESULT': 9,
    'LOGOUT_UNVERIFIED': 10, 'PORT_IN_USE': 11,
    'OUTPUT_ERROR': 12, 'INTERNAL_ERROR': 70, 'INTERRUPTED': 130,
}


class ErpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.exit_code = EXIT_CODES[code]

    def as_dict(self):
        return {'code': self.code, 'message': str(self)}
