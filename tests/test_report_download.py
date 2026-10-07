from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
import unittest
from unittest.mock import patch

from erp_sim.errors import ErpError
from erp_sim.features.abmr001 import bounded_download


class ReportDownloadTests(unittest.TestCase):
    def test_continuous_slow_bytes_cannot_extend_absolute_deadline(self):
        requested = threading.Event()
        stop = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requested.set()
                self.send_response(200)
                self.send_header('Content-Length', '100000')
                self.end_headers()
                try:
                    while not stop.wait(0.02):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        with HTTPServer(('127.0.0.1', 80), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            started = time.monotonic()
            try:
                with self.assertRaises(ErpError) as caught:
                    bounded_download('http://127.0.0.1/topprod/tiptop/out/abmr001test.txt',
                                     timeout=2)
                self.assertEqual(caught.exception.code, 'TIMEOUT')
                self.assertTrue(requested.is_set())
                self.assertLess(time.monotonic() - started, 5)
            finally:
                stop.set()
                server.shutdown()
                thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_worker_launch_failure_is_sanitized(self):
        with patch('erp_sim.features.abmr001.subprocess.run', side_effect=OSError('secret')):
            with self.assertRaises(ErpError) as caught:
                bounded_download('http://example.test/topprod/tiptop/out/abmr001test.txt')
        self.assertEqual(caught.exception.code, 'CONNECTION_FAILED')
        self.assertNotIn('secret', str(caught.exception))
