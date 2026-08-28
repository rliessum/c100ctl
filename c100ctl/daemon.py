"""User-session daemon: grab the C100, dispatch bindings, serve IPC."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import COLS, LOCKED_KEYS, PID, PRODUCT, ROWS, VID, __version__
from .actions import ActionError, Executor
from .config import Store, backup_dir, key_id, lock_path
from .device import find_c100, hidraw_exists
from .identity import layer_with_identity, looks_factory
from .ipc import IpcServer
from .pad import PadGrab
from .config import default_advanced, default_mix, parse_key_id
from .via import (
    MIX_RGB_EFFECT,
    PER_KEY_EFFECT,
    ViaClient,
    ViaError,
    parse_hex_color,
    poll_div_from_hz,
    poll_hz_from_div,
    rgb_to_hsv255,
)

log = logging.getLogger("c100ctl.daemon")

# Wait this long after a tap to see if it's a double-tap (close) vs launch.
DOUBLE_TAP_S = 0.30
HOLD_S = 0.40
CHORD_S = 0.05

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
        self.executor = Executor(switch_profile=self._switch_profile, on_light=self._light_action)
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
        self._down: set[tuple[int, int]] = set()
        self._hold_timer: dict[tuple[int, int], threading.Timer] = {}
        self._chord_timer: dict[tuple[int, int], threading.Timer] = {}
        self._consumed: set[tuple[int, int]] = set()
        self._hold_fired: set[tuple[int, int]] = set()
        self._momentary_from: str | None = None
        self._idle_timer: threading.Timer | None = None
        self._dimmed = False
        self._pre_dim_brightness = 255
        self.hardware: dict[str, Any] = {}
        self._macro_hold: dict[tuple[int, int], threading.Event] = {}

    def start_ipc(self) -> None:
        self.ipc = IpcServer(self.handle)
        self.ipc.start()

    def stop(self) -> None:
        self._stop.set()
        with self._tap_lock:
            for timer in self._pending_tap.values():
                timer.cancel()
            self._pending_tap.clear()
            for timer in self._hold_timer.values():
                timer.cancel()
            self._hold_timer.clear()
            for timer in self._chord_timer.values():
                timer.cancel()
            self._chord_timer.clear()
            for stop in self._macro_hold.values():
                stop.set()
            self._macro_hold.clear()
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
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
            self.hardware = self._probe_hardware()
        except Exception:
            log.exception("hardware probe")
            self.hardware = {}
        self._arm_idle()
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
        self.hardware = {}
        if was:
            self._broadcast({"event": "disconnected"})

    def _on_key(self, row: int, col: int, pressed: bool) -> None:
        self._broadcast({"event": "key", "row": row, "col": col, "pressed": pressed})
        self._bump_idle()
        cell = (row, col)
        if pressed:
            self._down.add(cell)
        else:
            self._down.discard(cell)
        if (row, col) in LOCKED_KEYS:
            return
        if pressed:
            self._on_press(cell)
        else:
            self._on_release(cell)

    def _on_press(self, cell: tuple[int, int]) -> None:
        chord = self._matching_chord()
        if chord and cell in chord[0]:
            for other in chord[0]:
                self._cancel_cell(other)
                self._consumed.add(other)
            log.info("chord %s", sorted(chord[0]))
            self._dispatch_binding(dict(chord[1]))
            return
        if self._cell_in_any_chord(cell):
            timer = threading.Timer(CHORD_S, lambda: self._arm_key(cell))
            timer.daemon = True
            with self._tap_lock:
                old = self._chord_timer.pop(cell, None)
                if old:
                    old.cancel()
                self._chord_timer[cell] = timer
            timer.start()
            return
        self._arm_key(cell)

    def _on_release(self, cell: tuple[int, int]) -> None:
        with self._tap_lock:
            hold = self._hold_timer.pop(cell, None)
            chord = self._chord_timer.pop(cell, None)
            stop = self._macro_hold.pop(cell, None)
        if hold:
            hold.cancel()
        if chord:
            chord.cancel()
        if stop:
            stop.set()
        if cell in self._consumed:
            self._consumed.discard(cell)
            return
        if cell in self._hold_fired:
            self._hold_fired.discard(cell)
            if self._momentary_from:
                name = self._momentary_from
                self._momentary_from = None
                self._switch_profile(name)
            return
        binding = self.store.get_binding(*cell)
        if binding and isinstance(binding.get("hold"), dict):
            self._dispatch_binding(dict(binding))

    def _arm_key(self, cell: tuple[int, int]) -> None:
        with self._tap_lock:
            pending = self._chord_timer.pop(cell, None)
            if pending:
                pending.cancel()
        if cell not in self._down or cell in self._consumed:
            return
        binding = self.store.get_binding(*cell)
        if not binding:
            return
        hold = binding.get("hold") if isinstance(binding.get("hold"), dict) else None
        if hold:
            timer = threading.Timer(HOLD_S, lambda: self._fire_hold(cell, dict(hold)))
            timer.daemon = True
            with self._tap_lock:
                old = self._hold_timer.pop(cell, None)
                if old:
                    old.cancel()
                self._hold_timer[cell] = timer
            timer.start()
            return
        self._dispatch_binding(dict(binding), cell=cell)

    def _fire_hold(self, cell: tuple[int, int], hold: dict[str, Any]) -> None:
        with self._tap_lock:
            self._hold_timer.pop(cell, None)
        if cell not in self._down or cell in self._consumed:
            return
        self._hold_fired.add(cell)
        if hold.get("type") == "profile" and hold.get("momentary"):
            self._momentary_from = self.store.active_profile_name()
        log.info("hold %s,%s → %s", cell[0], cell[1], hold.get("type"))
        self._dispatch_binding(dict(hold), cell=cell)

    def _dispatch_binding(self, binding: dict[str, Any], cell: tuple[int, int] | None = None) -> None:
        kind = binding.get("type")
        log.info("fire %s", kind)
        if kind in ("app", "command"):
            if cell is None:
                self._queue_job(dict(binding))
                return
            self._handle_app_tap(cell[0], cell[1], dict(binding))
            return
        if kind == "macro" and str(binding.get("repeat") or "") in {"hold", "while_held"} and cell:
            self._start_macro_hold(cell, dict(binding))
            return
        repeat = binding.get("repeat")
        if kind == "macro" and isinstance(repeat, int) and repeat > 1:
            job = dict(binding)
            job["_repeat"] = int(repeat)
            self._queue_job(job)
            return
        self._queue_job(dict(binding))

    def _start_macro_hold(self, cell: tuple[int, int], binding: dict[str, Any]) -> None:
        stop = threading.Event()
        with self._tap_lock:
            old = self._macro_hold.pop(cell, None)
            if old:
                old.set()
            self._macro_hold[cell] = stop

        def loop() -> None:
            while not stop.is_set() and not self._stop.is_set():
                try:
                    self.executor.run(binding)
                except Exception:
                    log.exception("macro hold")
                    return
                if stop.wait(0.04):
                    return

        threading.Thread(target=loop, daemon=True).start()

    def _cancel_cell(self, cell: tuple[int, int]) -> None:
        with self._tap_lock:
            for bucket in (self._pending_tap, self._hold_timer, self._chord_timer):
                timer = bucket.pop(cell, None)
                if timer:
                    timer.cancel()

    def _chords(self) -> list[tuple[set[tuple[int, int]], dict[str, Any]]]:
        out: list[tuple[set[tuple[int, int]], dict[str, Any]]] = []
        for chord in self.store.data.get("chords") or []:
            cells: set[tuple[int, int]] = set()
            for kid in chord.get("keys") or []:
                try:
                    cells.add(parse_key_id(str(kid)))
                except ValueError:
                    cells = set()
                    break
            binding = chord.get("binding")
            if len(cells) >= 2 and isinstance(binding, dict):
                out.append((cells, binding))
        return out

    def _matching_chord(self) -> tuple[set[tuple[int, int]], dict[str, Any]] | None:
        for cells, binding in self._chords():
            if cells <= self._down:
                return cells, binding
        return None

    def _cell_in_any_chord(self, cell: tuple[int, int]) -> bool:
        return any(cell in cells for cells, _b in self._chords())

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
                times = int(binding.get("_repeat") or 1)
                for _ in range(max(1, times)):
                    self.executor.run(binding)
            except ActionError as e:
                log.warning("action failed: %s", e)
                self._broadcast({"event": "error", "error": str(e)})
            except Exception:
                log.exception("action crashed")

    def _switch_profile(self, name: str) -> None:
        self.store.set_profile(name)
        profile = self.store.profile(name)
        lighting = profile.get("lighting")
        if isinstance(lighting, dict) and lighting:
            store_l = self.store.data.setdefault("lighting", {})
            if isinstance(lighting.get("keys"), dict):
                store_l["keys"] = dict(lighting["keys"])
            for field in ("brightness", "effect", "speed", "color", "per_key_type", "mix"):
                if field in lighting:
                    store_l[field] = lighting[field]
            self.store.save()
            if self.via and self.connected:
                try:
                    self._apply_lighting()
                except Exception:
                    log.exception("profile lighting")
        self._broadcast({"event": "profile", "name": name, "config": self.store.snapshot()})

    def _apply_mix(self, mix: dict[str, Any]) -> None:
        if not self.via:
            return
        regions = mix.get("regions") or [0] * 100
        if len(regions) < 100:
            regions = list(regions) + [0] * (100 - len(regions))
        self.via.set_mix_regions(regions[:100])
        slots = mix.get("slots") or default_mix()["slots"]
        for layer, layer_slots in enumerate(slots[:2]):
            self.via.set_mix_slots(layer, layer_slots)
        self.via.save_leds()

    def _apply_advanced(self) -> None:
        if not self.via:
            return
        adv = self.store.data.setdefault("advanced", default_advanced())
        try:
            self.via.set_poll_div(poll_div_from_hz(int(adv.get("poll_hz") or 8000)))
        except ViaError:
            log.warning("poll rate not supported")
        try:
            self.via.set_debounce(int(adv.get("debounce_type") or 4), int(adv.get("debounce_ms") or 5))
        except ViaError:
            log.warning("debounce not supported")
        try:
            self.via.set_nkro(bool(adv.get("nkro", True)))
        except ViaError:
            log.warning("nkro not supported")
        self._arm_idle()

    def _light_action(self, action: str) -> None:
        lighting = self.store.data.setdefault("lighting", {})
        action = action.strip().lower()
        if action in {"next", "prev"}:
            cur = int(lighting.get("effect") or 0)
            nxt = (cur + (1 if action == "next" else -1)) % len(RGB_EFFECTS)
            lighting["effect"] = nxt
        elif action == "brighter":
            lighting["brightness"] = min(255, int(lighting.get("brightness") or 0) + 16)
        elif action == "dimmer":
            lighting["brightness"] = max(0, int(lighting.get("brightness") or 0) - 16)
        elif action == "toggle":
            cur = int(lighting.get("brightness") or 0)
            if cur <= 0:
                lighting["brightness"] = int(lighting.get("_prev_brightness") or 255)
            else:
                lighting["_prev_brightness"] = cur
                lighting["brightness"] = 0
        elif action == "perkey":
            lighting["effect"] = PER_KEY_EFFECT
        elif action == "mix":
            lighting["effect"] = MIX_RGB_EFFECT
        else:
            raise ActionError(f"unknown light action {action!r}")
        self.store.save()
        if self.via and self.connected:
            self._apply_lighting()
        self._broadcast({"event": "lighting", "lighting": lighting, "config": self.store.snapshot()})

    def _bump_idle(self) -> None:
        if self._dimmed and self.via and self.connected:
            try:
                self.via.set_brightness(self._pre_dim_brightness, save=False)
            except ViaError:
                pass
            self._dimmed = False
        self._arm_idle()

    def _arm_idle(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        seconds = int((self.store.data.get("advanced") or {}).get("idle_dim_s") or 0)
        if seconds <= 0:
            return

        def dim() -> None:
            if not self.via or not self.connected or self._dimmed:
                return
            lighting = self.store.data.get("lighting") or {}
            self._pre_dim_brightness = int(lighting.get("brightness") or 255)
            try:
                self.via.set_brightness(0, save=False)
                self._dimmed = True
            except ViaError:
                pass

        self._idle_timer = threading.Timer(seconds, dim)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _probe_hardware(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not self.via:
            return out
        try:
            out["firmware"] = self.via.firmware_string()
        except ViaError:
            out["firmware"] = ""
        try:
            div = self.via.get_poll_div()
            out["poll_hz"] = poll_hz_from_div(div) if div is not None else None
            out["poll_supported"] = div is not None
        except ViaError:
            out["poll_supported"] = False
        try:
            deb = self.via.get_debounce()
            out["debounce"] = {"type": deb[0], "ms": deb[1]} if deb else None
            out["debounce_supported"] = deb is not None
        except ViaError:
            out["debounce_supported"] = False
        try:
            nkro = self.via.get_nkro()
            out["nkro"] = {"on": nkro[0], "can_toggle": nkro[1]} if nkro else None
            out["nkro_supported"] = nkro is not None
        except ViaError:
            out["nkro_supported"] = False
        return out

    def _apply_lighting(self) -> None:
        if not self.via:
            return
        lighting = self.store.data.setdefault("lighting", {})
        colors = lighting.get("keys") or {}
        effect = int(lighting.get("effect", 1))
        if colors and effect not in (PER_KEY_EFFECT, MIX_RGB_EFFECT):
            effect = PER_KEY_EFFECT
            lighting["effect"] = effect
        if "brightness" in lighting:
            self.via.set_brightness(int(lighting["brightness"]), save=True)
        if "speed" in lighting:
            self.via.set_speed(int(lighting["speed"]), save=True)
        color = lighting.get("color")
        if color:
            try:
                h, s, _v = rgb_to_hsv255(*parse_hex_color(str(color)))
                self.via.set_color_hsv(h, s, save=True)
            except ValueError:
                pass
        self.via.set_effect(effect, save=True)
        if effect == PER_KEY_EFFECT:
            type_id = int(lighting.get("per_key_type") or 0)
            self.via.enable_per_key(save=False)
            self.via.set_per_key_type(type_id)
            if colors:
                self._write_all_key_colors(dict(colors), save=True)
            else:
                self.via.save_leds()
        elif effect == MIX_RGB_EFFECT:
            self._apply_mix(lighting.get("mix") or default_mix())
        self._dimmed = False

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
            "advanced": dict(self.store.data.get("advanced") or default_advanced()),
            "effects": RGB_EFFECTS,
            "hardware": dict(self.hardware),
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
            if "color" in req and req["color"]:
                parse_hex_color(str(req["color"]))
                color = str(req["color"])
                lighting["color"] = color if color.startswith("#") else f"#{color.lstrip('#')}"
            if "per_key_type" in req:
                lighting["per_key_type"] = max(0, min(4, int(req["per_key_type"])))
            self.store.save()
            if self.via and self.connected:
                self._apply_lighting()
            self._broadcast({"event": "lighting", "lighting": lighting, "config": self.store.snapshot()})
            return {"ok": True, "lighting": lighting}
        if op == "set_mix":
            lighting = self.store.data.setdefault("lighting", {})
            mix = lighting.setdefault("mix", default_mix())
            if "regions" in req and isinstance(req["regions"], list):
                regs = [1 if int(x) else 0 for x in req["regions"][:100]]
                mix["regions"] = regs + [0] * (100 - len(regs))
            if "slots" in req and isinstance(req["slots"], list):
                mix["slots"] = req["slots"]
            lighting["effect"] = MIX_RGB_EFFECT
            self.store.save()
            if self.via and self.connected:
                self.via.set_effect(MIX_RGB_EFFECT, save=True)
                self._apply_mix(mix)
            self._broadcast({"event": "lighting", "lighting": lighting, "config": self.store.snapshot()})
            return {"ok": True, "lighting": lighting}
        if op == "clear_key_colors":
            lighting = self.store.data.setdefault("lighting", {})
            lighting["keys"] = {}
            self.store.save()
            if self.via and self.connected:
                black = [(0, 0, 0)] * 100
                self.via.write_all_rgb(black, save=True)
            self._broadcast({"event": "lighting", "lighting": lighting, "config": self.store.snapshot()})
            return {"ok": True, "lighting": lighting}
        if op == "save_profile_lighting":
            name = req.get("name") or self.store.active_profile_name()
            profile = self.store.profile(name)
            profile["lighting"] = deepcopy(self.store.data.get("lighting") or {})
            self.store.save()
            return {"ok": True, "config": self.store.snapshot()}
        if op == "set_advanced":
            adv = self.store.data.setdefault("advanced", default_advanced())
            for key in ("poll_hz", "debounce_type", "debounce_ms", "idle_dim_s"):
                if key in req:
                    adv[key] = int(req[key])
            if "nkro" in req:
                adv["nkro"] = bool(req["nkro"])
            self.store.save()
            if self.via and self.connected:
                self._apply_advanced()
                try:
                    self.hardware = self._probe_hardware()
                except Exception:
                    pass
            self._broadcast({"event": "advanced", "advanced": adv, "config": self.store.snapshot()})
            return {"ok": True, "advanced": adv}
        if op == "set_chords":
            self.store.set_chords(list(req.get("chords") or []))
            self._broadcast({"event": "config", "config": self.store.snapshot()})
            return {"ok": True, "chords": self.store.data.get("chords")}
        if op == "import_config":
            payload = req.get("config")
            if not isinstance(payload, dict):
                return {"ok": False, "error": "config object required"}
            self.store.replace_config(payload)
            if self.via and self.connected:
                self._apply_lighting()
                self._apply_advanced()
            self._broadcast({"event": "config", "config": self.store.snapshot()})
            return {"ok": True, "config": self.store.snapshot()}
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
