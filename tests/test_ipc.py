import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from c100ctl.ipc import MAX_LINE, IpcClient, IpcServer, daemon_available


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


class IpcHardeningTest(unittest.TestCase):
    """A local peer must not be able to grow the daemon's buffers without
    bound, and a malformed event line must not reach the GTK main loop.
    """

    def test_oversized_request_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.sock"
            server = IpcServer(lambda req: {"ok": True}, path=path)
            server.start()
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect(str(path))
                # a peer that never sends a newline
                blob = b"x" * 65536
                refused = False
                try:
                    for _ in range((MAX_LINE // len(blob)) + 4):
                        sock.sendall(blob)
                except OSError:
                    refused = True
                reply = b""
                try:
                    reply = sock.recv(4096)
                except OSError:
                    refused = True
                self.assertTrue(refused or b"too large" in reply or reply == b"")
                sock.close()
            finally:
                server.stop()

    def test_read_event_swallows_malformed_json(self):
        client = IpcClient.__new__(IpcClient)
        client._lock = threading.Lock()
        client._events = []
        client._buf = b""
        client.timeout = 1.0

        class Sock:
            def settimeout(self, _t): pass
            def recv(self, _n): return b"{ not json at all\n"

        client._sock = Sock()
        self.assertIsNone(client.read_event())

    def test_read_event_returns_valid_json(self):
        client = IpcClient.__new__(IpcClient)
        client._lock = threading.Lock()
        client._events = []
        client._buf = b""
        client.timeout = 1.0

        class Sock:
            def settimeout(self, _t): pass
            def recv(self, _n): return b'{"event":"key","row":1}\n'

        client._sock = Sock()
        self.assertEqual(client.read_event(), {"event": "key", "row": 1})
