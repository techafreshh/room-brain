"""Skeleton tests: help text, byte-exact health body, echo formatting."""

import io
import os
import socket
import sys
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import roombrain.cli as cli_mod
from roombrain.cli import HEALTH_BODY, HealthHandler, build_parser, format_echo_line


class TestSkeleton(unittest.TestCase):
    def test_help_lists_commands(self):
        help_text = build_parser().format_help()
        for cmd in ("register", "run", "seed-demo"):
            self.assertIn(cmd, help_text)

    def test_health_returns_exact_body(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            deadline = time.time() + 5
            last_exc = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:%d/health" % port, timeout=2
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        self.assertEqual(resp.read(), b'{"status":"ok"}')
                        self.assertEqual(HEALTH_BODY, b'{"status":"ok"}')
                        return
                except Exception as exc:  # server still starting
                    last_exc = exc
                    time.sleep(0.05)
            raise last_exc
        finally:
            server.shutdown()
            server.server_close()

    def test_echo_formats_line(self):
        self.assertEqual(format_echo_line("hello skeleton"), "echo: hello skeleton")

    def test_run_echo_survives_stdin_eof(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        stdin = io.StringIO("hello skeleton\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), mock.patch.object(
            sys, "stdout", stdout
        ), mock.patch.object(sys, "stderr", stderr):
            thread = threading.Thread(
                target=cli_mod.run_echo, args=(port,), daemon=True
            )
            thread.start()
            deadline = time.time() + 5
            body = None
            last_exc = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:%d/health" % port, timeout=2
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        body = resp.read()
                    break
                except Exception as exc:
                    last_exc = exc
                    time.sleep(0.05)
            self.assertEqual(body, b'{"status":"ok"}')
            self.assertIn("echo: hello skeleton", stdout.getvalue())
            # stdin is exhausted (EOF) but the server must stay alive.
            time.sleep(0.2)
            self.assertTrue(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
