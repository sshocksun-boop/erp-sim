"""Private bounded-output HTTP worker; generated URLs travel only on stdin."""
import sys
from http.client import HTTPException

from ..errors import ErpError
from .abmr001 import download_report


def main():
    try:
        url = sys.stdin.buffer.read(65537)
        if len(url) > 65536:
            return 7
        raw = download_report(url.decode('utf-8'))
        sys.stdout.buffer.write(raw)
        return 0
    except ErpError as error:
        return error.exit_code
    except (HTTPException, UnicodeError, ValueError):
        return 7
    except OSError:
        return 5


if __name__ == '__main__':
    raise SystemExit(main())
