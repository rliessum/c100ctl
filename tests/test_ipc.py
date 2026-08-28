import os
import tempfile
import time
import unittest
from pathlib import Path

from c100ctl.ipc import IpcClient, IpcServer, daemon_available


class IpcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = Path(self.tmp.name) / "t.sock"
        self.seen = []

        def handler(req):
            self.seen.append(req)
            if req.get("op") == "boom":
                raise RuntimeError("nope")
            return {"ok": True, "echo": req.get("op")}

        self.server = IpcServer(handler, path=self.sock)
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def test_request_and_broadcast(self):
        c = IpcClient(self.sock, timeout=2)
        try:
            r = c.request("ping")
            self.assertTrue(r["ok"])
            self.assertEqual(r["echo"], "ping")
            self.server.broadcast({"event": "hi"})
            time.sleep(0.05)
            ev = c.read_event()
            self.assertEqual(ev["event"], "hi")
        finally:
            c.close()

    def test_handler_error(self):
        c = IpcClient(self.sock, timeout=2)
        try:
            r = c.request("boom")
            self.assertFalse(r["ok"])
            self.assertIn("nope", r["error"])
        finally:
            c.close()

    def test_daemon_available_false_without_socket(self):
        missing = Path(self.tmp.name) / "nope.sock"
        from unittest.mock import patch

        with patch("c100ctl.ipc.socket_path", return_value=missing):
            self.assertFalse(daemon_available())

    def test_daemon_available_true(self):
        from unittest.mock import patch

        with patch("c100ctl.ipc.socket_path", return_value=self.sock):
            self.assertTrue(daemon_available())

    def test_invalid_json_is_ignored_safely(self):
        import socket

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(str(self.sock))
        try:
            s.sendall(b"{not json\n")
            data = s.recv(1024)
            self.assertIn(b"invalid json", data)
        finally:
            s.close()
