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
from .via import PER_KEY_EFFECT, ViaClient, ViaError, parse_hex_color, rgb_to_hsv255

log = logging.getLogger("c100ctl.daemon")

# Wait this long after a tap to see if it's a double-tap (close) vs launch.
DOUBLE_TAP_S = 0.30

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
        self._led_map: list[list[int]] | None = None
        self._led_save_timer: threading.Timer | None = None
        self._tap_lock = threading.Lock()
        self._pending_tap: dict[tuple[int, int], threading.Timer] = {}
        self._last_tap: dict[tuple[int, int], float] = {}
        self._tap_seq: dict[tuple[int, int], int] = {}

    def start_ipc(self) -> None:
        self.ipc = IpcServer(self.handle)
        self.ipc.start()

    def stop(self) -> None:
        self._stop.set()
        with self._tap_lock:
            for timer in self._pending_tap.values():
                timer.cancel()
            self._pending_tap.clear()
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
            self._led_map = via.led_map(ROWS, COLS)
        except Exception:
            log.exception("LED map failed")
            self._led_map = None
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
        kind = binding.get("type")
        log.info("key %s,%s → %s", row, col, kind)
        if kind in ("app", "command"):
            self._handle_app_tap(row, col, dict(binding))
            return
        self._queue_job(dict(binding))

    def _queue_job(self, binding: dict[str, Any]) -> None:
        with self._jobs_cv:
            self._jobs.append(binding)
            self._jobs_cv.notify()

    def _handle_app_tap(self, row: int, col: int, binding: dict[str, Any]) -> None:
        cell = (row, col)
        now = time.monotonic()
        with self._tap_lock:
            pending = self._pending_tap.pop(cell, None)
            if pending is not None:
                pending.cancel()
            last = self._last_tap.get(cell, 0.0)
            double = last > 0 and (now - last) <= DOUBLE_TAP_S
            self._last_tap[cell] = now
            self._tap_seq[cell] = self._tap_seq.get(cell, 0) + 1
            seq = self._tap_seq[cell]
            if double:
                log.info("double-tap %s,%s → close", row, col)
                job = dict(binding)
                job["_close"] = True
                self._queue_job(job)
                return

            def fire() -> None:
                with self._tap_lock:
                    self._pending_tap.pop(cell, None)
                    if self._tap_seq.get(cell) != seq:
                        return
                self._queue_job(dict(binding))

            timer = threading.Timer(DOUBLE_TAP_S, fire)
            timer.daemon = True
            self._pending_tap[cell] = timer
            timer.start()

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
        colors = lighting.get("keys") or {}
        if colors:
            lighting["effect"] = PER_KEY_EFFECT
        if "brightness" in lighting:
            self.via.set_brightness(int(lighting["brightness"]), save=True)
        if "effect" in lighting:
            effect = int(lighting["effect"])
            self.via.set_effect(effect, save=True)
            if effect == PER_KEY_EFFECT:
                self.via.enable_per_key(save=False)
        if "speed" in lighting:
            self.via.set_speed(int(lighting["speed"]), save=True)
        if colors:
            self._write_all_key_colors(dict(colors), save=True)

    def _led_index(self, row: int, col: int) -> int:
        if self._led_map and 0 <= row < len(self._led_map) and 0 <= col < len(self._led_map[row]):
            return int(self._led_map[row][col])
        return row * COLS + col

    def _write_key_color(self, row: int, col: int, color: str | None, save: bool = False) -> None:
        if not self.via:
            return
        index = self._led_index(row, col)
        if color:
            hsv = rgb_to_hsv255(*parse_hex_color(color))
        else:
            hsv = (0, 0, 0)
        self.via.set_led_hsv(index, hsv)
        if save:
            self._schedule_led_save()

    def _write_all_key_colors(self, colors: dict[str, str], save: bool = True) -> None:
        if not self.via:
            return
        packed: dict[int, tuple[int, int, int]] = {}
        for kid, hex_color in colors.items():
            try:
                r, c = (int(x) for x in kid.split(",", 1))
                packed[self._led_index(r, c)] = rgb_to_hsv255(*parse_hex_color(hex_color))
            except (ValueError, TypeError):
                continue
        if not packed:
            return
        start = min(packed)
        end = max(packed)
        i = start
        while i <= end:
            chunk: list[tuple[int, int, int]] = []
            j = i
            while j <= end and len(chunk) < 9 and j in packed:
                chunk.append(packed[j])
                j += 1
            if chunk:
                self.via.set_leds_hsv(i, chunk)
                i = j
            else:
                i += 1
        if save:
            self.via.save_leds()

    def _schedule_led_save(self) -> None:
        if self._led_save_timer:
            self._led_save_timer.cancel()

        def _save() -> None:
            try:
                if self.via:
                    self.via.save_leds()
            except Exception:
                log.exception("save LED conf failed")

        self._led_save_timer = threading.Timer(0.4, _save)
        self._led_save_timer.daemon = True
        self._led_save_timer.start()

    def set_key_color(self, row: int, col: int, color: str | None) -> dict[str, Any]:
        return self.set_key_colors([(row, col, color)])

    def set_key_colors(self, updates: list[tuple[int, int, str | None]]) -> dict[str, Any]:
        normalized: list[tuple[int, int, str | None]] = []
        for row, col, color in updates:
            if color in ("", "off"):
                color = None
            if color:
                parse_hex_color(color)
                color = color if str(color).startswith("#") else f"#{str(color).lstrip('#')}"
            normalized.append((int(row), int(col), color))
        if not normalized:
            return {"ok": False, "error": "no keys"}
        self.store.set_key_colors(normalized)
        lighting = self.store.data.setdefault("lighting", {})
        if any(color for _r, _c, color in normalized):
            lighting["effect"] = PER_KEY_EFFECT
            self.store.save()
        if self.via and self.connected:
            if any(color for _r, _c, color in normalized):
                self.via.enable_per_key(save=False)
            for row, col, color in normalized:
                self._write_key_color(row, col, color, save=False)
            self._schedule_led_save()
        payload = {
            "event": "lighting",
            "lighting": self.store.data.get("lighting", {}),
            "config": self.store.snapshot(),
        }
        self._broadcast(payload)
        return {"ok": True, "count": len(normalized), "lighting": lighting}

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
        lighting = dict(self.store.data.get("lighting") or {})
        if self.via and self.connected:
            try:
                lighting["brightness"] = self.via.brightness()
                lighting["effect"] = self.via.effect()
                lighting["speed"] = self.via.speed()
            except ViaError:
                pass
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
            self._broadcast({"event": "lighting", "lighting": lighting, "config": self.store.snapshot()})
            return {"ok": True, "lighting": lighting}
        if op == "set_key_color":
            color = req.get("color")
            if color == "" or color == "off":
                color = None
            return self.set_key_color(int(req["row"]), int(req["col"]), color)
        if op == "set_key_colors":
            items = req.get("keys") or []
            updates = []
            for item in items:
                color = item.get("color")
                if color == "" or color == "off":
                    color = None
                updates.append((int(item["row"]), int(item["col"]), color))
            return self.set_key_colors(updates)
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
