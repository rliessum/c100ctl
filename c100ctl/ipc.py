"""JSON-lines Unix socket protocol between GUI/CLI and the daemon."""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import socket_path

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class IpcServer:
    def __init__(self, handler: Handler, path: Path | None = None):
        self.handler = handler
        self.path = path or socket_path()
        self._sock: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        sock.listen(8)
        sock.settimeout(0.5)
        self._sock = sock
        self._thread = threading.Thread(target=self._accept, name="c100-ipc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1.5)
        try:
            self.path.unlink()
        except OSError:
            pass

    def broadcast(self, payload: dict[str, Any]) -> None:
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        dead: list[socket.socket] = []
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.sendall(line)
            except OSError:
                dead.append(c)
        if dead:
            with self._lock:
                for c in dead:
                    if c in self._clients:
                        self._clients.remove(c)
                    try:
                        c.close()
                    except OSError:
                        pass

    def _accept(self) -> None:
        assert self._sock
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                self._clients.append(conn)
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        buf = b""
        try:
            while not self._stop.is_set():
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    try:
                        req = json.loads(raw.decode())
                    except json.JSONDecodeError:
                        _send(conn, {"ok": False, "error": "invalid json"})
                        continue
                    try:
                        resp = self.handler(req)
                    except Exception as e:
                        resp = {"ok": False, "error": str(e)}
                    if req.get("id") is not None:
                        resp["id"] = req["id"]
                    _send(conn, resp)
        except OSError:
            pass
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            try:
                conn.close()
            except OSError:
                pass


def _send(conn: socket.socket, payload: dict[str, Any]) -> None:
    conn.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())


class IpcClient:
    def __init__(self, path: Path | None = None, timeout: float = 2.0):
        self.path = path or socket_path()
        self.timeout = timeout
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect(str(self.path))
        self._buf = b""
        self._n = 0
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def request(self, op: str, **fields: Any) -> dict[str, Any]:
        self._n += 1
        req = {"id": self._n, "op": op, **fields}
        with self._lock:
            self._sock.sendall((json.dumps(req) + "\n").encode())
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise ConnectionError("daemon closed the socket")
                self._buf += chunk
                while b"\n" in self._buf:
                    raw, self._buf = self._buf.split(b"\n", 1)
                    msg = json.loads(raw.decode())
                    if msg.get("id") == self._n:
                        return msg
                    self._events.append(msg)

    def fileno(self) -> int:
        return self._sock.fileno()

    def read_event(self) -> dict[str, Any] | None:
        """Non-blocking-ish read of the next line. Used by the GUI."""
        with self._lock:
            if self._events:
                return self._events.pop(0)
            self._sock.settimeout(0.0)
            try:
                chunk = self._sock.recv(4096)
            except BlockingIOError:
                return None
            except OSError:
                return None
            finally:
                self._sock.settimeout(self.timeout)
            if not chunk:
                return None
            self._buf += chunk
            if b"\n" not in self._buf:
                return None
            raw, self._buf = self._buf.split(b"\n", 1)
            return json.loads(raw.decode())


def daemon_available() -> bool:
    path = socket_path()
    if not path.exists():
        return False
    try:
        c = IpcClient(timeout=0.4)
    except OSError:
        return False
    try:
        r = c.request("ping")
        return bool(r.get("ok"))
    except OSError:
        return False
    finally:
        c.close()
