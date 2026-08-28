"""User-session daemon: grab the C100, dispatch bindings, serve IPC."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

from . import COLS, LOCKED_KEYS, PID, PRODUCT, ROWS, VID, __version__
from .actions import ActionError, Executor
from .config import Store, backup_dir, key_id, lock_path
from .device import find_c100, hidraw_exists
from .identity import layer_with_identity, looks_factory
from .ipc import IpcServer
from .pad import PadGrab
from .via import ViaClient, ViaError

log = logging.getLogger("c100ctl.daemon")

RGB_EFFECTS = [
    "None",
    "Solid Color",
    "Breathing",
    "Band Spiral Val",
    "Cycle All",
    "Cycle Left Right",
    "Cycle Up Down",
    "Rainbow Moving Chevron",
    "Cycle Out In",
    "Cycle Out In Dual",
    "Cycle Pinwheel",
    "Cycle Spiral",
    "Dual Beacon",
    "Rainbow Beacon",
    "Jellybean Raindrops",
    "Pixel Rain",
    "Typing Heatmap",
    "Digital Rain",
    "Reactive Simple",
    "Reactive Multiwide",
    "Reactive Multinexus",
    "Splash",
    "Solid Splash",
    "Per Key RGB",
    "Mix RGB",
]


class Engine:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()
        self.via: ViaClient | None = None
        self.pad: PadGrab | None = None
        self.executor = Executor(switch_profile=self._switch_profile)
        self.connected = False
        self.serial = ""
        self.protocol = 0
        self.layers = 0
        self.info: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.ipc: IpcServer | None = None
        self._stop = threading.Event()
        self._jobs: list[dict[str, Any]] = []
        self._jobs_cv = threading.Condition()
        self._worker = threading.Thread(target=self._action_loop, name="c100-actions", daemon=True)
        self._worker.start()

    def start_ipc(self) -> None:
        self.ipc = IpcServer(self.handle)
        self.ipc.start()

    def stop(self) -> None:
        self._stop.set()
        with self._jobs_cv:
            self._jobs_cv.notify_all()
        self._disconnect()
        self.executor.close()
        if self.ipc:
            self.ipc.stop()

    def run_forever(self) -> None:
        self.start_ipc()
        log.info("c100ctl daemon %s listening", __version__)
        while not self._stop.is_set():
            try:
                if not self.connected:
                    self._try_connect()
                elif self.via and not hidraw_exists(self.via.path):
                    log.info("C100 disconnected")
                    self._disconnect()
                time.sleep(0.8)
            except Exception:
                log.exception("reconnect loop")
                self._disconnect()
                time.sleep(1.5)

    def _try_connect(self) -> None:
        found = find_c100()
        if not found:
            return
        log.info("found C100 at %s serial=%s", found.via_path, found.serial)
        try:
            via = ViaClient(found.via_path)
            protocol = via.protocol_version()
            layers = via.layer_count()
            keymap = via.read_keymap(layers, ROWS, COLS)
        except (ViaError, OSError) as e:
            log.warning("VIA open failed: %s", e)
            return
        self.via = via
        self.serial = found.serial
        self.protocol = protocol
        self.layers = layers
        self.store.data["serial"] = found.serial
        if not self.store.data.get("provisioned") and looks_factory(keymap[0]):
            log.info("factory keymap detected — writing identity map")
            try:
                self.provision(backup=True)
            except Exception:
                log.exception("provision failed")
        try:
            self._apply_lighting()
        except Exception:
            log.exception("lighting apply failed")
        try:
            pad = PadGrab(found.evdev_paths, via=via, on_key=self._on_key)
            pad.start()
            self.pad = pad
        except Exception:
            log.exception("evdev grab failed")
            via.close()
            self.via = None
            return
        self.connected = True
        self.info = {
            "product": PRODUCT,
            "serial": found.serial,
            "via_path": found.via_path,
            "evdev": found.evdev_paths,
            "protocol": protocol,
            "layers": layers,
        }
        log.info("C100 ready protocol=%s layers=%s", protocol, layers)
        self._broadcast({"event": "connected", "info": self.status()})

    def _disconnect(self) -> None:
        was = self.connected
        self.connected = False
        if self.pad:
            try:
                self.pad.stop()
            except Exception:
                pass
            self.pad = None
        if self.via:
            try:
                self.via.close()
            except Exception:
                pass
            self.via = None
        if was:
            self._broadcast({"event": "disconnected"})

    def _on_key(self, row: int, col: int, pressed: bool) -> None:
        self._broadcast({"event": "key", "row": row, "col": col, "pressed": pressed})
        if not pressed:
            return
        if (row, col) in LOCKED_KEYS:
            return
        binding = self.store.get_binding(row, col)
        if not binding:
            return
        log.info("key %s,%s → %s", row, col, binding.get("type"))
        with self._jobs_cv:
            self._jobs.append(dict(binding))
            self._jobs_cv.notify()

    def _action_loop(self) -> None:
        while not self._stop.is_set():
            with self._jobs_cv:
                while not self._jobs and not self._stop.is_set():
                    self._jobs_cv.wait(timeout=0.4)
                if self._stop.is_set():
                    return
                binding = self._jobs.pop(0)
            try:
                self.executor.run(binding)
            except ActionError as e:
                log.warning("action failed: %s", e)
                self._broadcast({"event": "error", "error": str(e)})
            except Exception:
                log.exception("action crashed")

    def _switch_profile(self, name: str) -> None:
        self.store.set_profile(name)
        self._broadcast({"event": "profile", "name": name, "config": self.store.snapshot()})

    def _apply_lighting(self) -> None:
        if not self.via:
            return
        lighting = self.store.data.get("lighting", {})
        if "brightness" in lighting:
            self.via.set_brightness(int(lighting["brightness"]), save=True)
        if "effect" in lighting:
            self.via.set_effect(int(lighting["effect"]), save=True)
        if "speed" in lighting:
            self.via.set_speed(int(lighting["speed"]), save=True)

    def provision(self, backup: bool = True) -> None:
        if not self.via:
            raise RuntimeError("C100 is not connected")
        keymap = self.via.read_keymap(self.layers or 4, ROWS, COLS)
        if backup:
            dest = backup_dir()
            dest.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = dest / f"keymap-{stamp}.json"
            path.write_text(json.dumps({"layers": keymap}, indent=2))
            log.info("backed up keymap to %s", path)
        identity = layer_with_identity(keymap[0])
        for layer in range(self.layers or 4):
            self.via.write_keymap_layer(layer, ROWS, COLS, identity)
        self.store.data["provisioned"] = True
        self.store.save()

    def status(self) -> dict[str, Any]:
        lighting = {}
        if self.via and self.connected:
            try:
                lighting = {
                    "brightness": self.via.brightness(),
                    "effect": self.via.effect(),
                    "speed": self.via.speed(),
                }
            except ViaError:
                lighting = self.store.data.get("lighting", {})
        else:
            lighting = self.store.data.get("lighting", {})
        return {
            "ok": True,
            "version": __version__,
            "connected": self.connected,
            "product": PRODUCT,
            "vid": f"{VID:04x}",
            "pid": f"{PID:04x}",
            "serial": self.serial,
            "protocol": self.protocol,
            "layers": self.layers,
            "provisioned": bool(self.store.data.get("provisioned")),
            "profile": self.store.active_profile_name(),
            "lighting": lighting,
            "effects": RGB_EFFECTS,
            "info": self.info,
        }

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        op = req.get("op")
        if op == "ping":
            return {"ok": True, "pong": True}
        if op == "status":
            return self.status()
        if op == "get_config":
            return {"ok": True, "config": self.store.snapshot()}
        if op == "set_binding":
            row, col = int(req["row"]), int(req["col"])
            if (row, col) in LOCKED_KEYS:
                return {"ok": False, "error": "corner keys are firmware lighting controls"}
            self.store.set_binding(row, col, req.get("binding"))
            self._broadcast({"event": "config", "config": self.store.snapshot()})
            return {"ok": True}
        if op == "set_profile":
            self._switch_profile(req["name"])
            return {"ok": True}
        if op == "ensure_profile":
            self.store.ensure_profile(req["name"], req.get("label"))
            return {"ok": True, "config": self.store.snapshot()}
        if op == "delete_profile":
            self.store.delete_profile(req["name"])
            return {"ok": True, "config": self.store.snapshot()}
        if op == "set_lighting":
            lighting = self.store.data.setdefault("lighting", {})
            if "brightness" in req:
                lighting["brightness"] = int(req["brightness"])
            if "effect" in req:
                lighting["effect"] = int(req["effect"])
            if "speed" in req:
                lighting["speed"] = int(req["speed"])
            self.store.save()
            if self.via and self.connected:
                self._apply_lighting()
            self._broadcast({"event": "lighting", "lighting": lighting})
            return {"ok": True, "lighting": lighting}
        if op == "provision":
            self.provision(backup=req.get("backup", True))
            return {"ok": True}
        if op == "reload":
            self.store.load()
            return {"ok": True, "config": self.store.snapshot()}
        return {"ok": False, "error": f"unknown op {op!r}"}

    def _broadcast(self, payload: dict[str, Any]) -> None:
        if self.ipc:
            self.ipc.broadcast(payload)


def _take_lock() -> int:
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise SystemExit("c100ctl daemon is already running") from e
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    fd = _take_lock()
    engine = Engine()

    def handle_signal(signum: int, _frame: object) -> None:
        log.info("signal %s, shutting down", signum)
        engine.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        engine.run_forever()
    finally:
        engine.stop()
        os.close(fd)
    return 0
