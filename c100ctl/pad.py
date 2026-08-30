"""Exclusive grab of the C100. Identity map → (row, col)."""

from __future__ import annotations

import logging
import select
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .host import is_macos
from .identity import identity_evdev_map

if TYPE_CHECKING:
    from evdev import InputDevice, ecodes

    from .via import ViaClient
else:

    def _evdev_symbols() -> tuple[Any, Any]:
        try:
            from evdev import InputDevice, ecodes
        except ImportError:  # pragma: no cover
            return None, None
        return InputDevice, ecodes

    InputDevice, ecodes = _evdev_symbols()

log = logging.getLogger("c100ctl.pad")

OnKey = Callable[[int, int, bool], None]


def open_pad(
    paths: list[str],
    via: ViaClient | None = None,
    on_key: OnKey | None = None,
) -> Any:
    """Grab the pad on this host (evdev on Linux, IOHID/VIA on macOS)."""
    if is_macos():
        from .pad_macos import PadGrab as MacPadGrab

        pad: Any = MacPadGrab(paths, via=via, on_key=on_key)
    else:
        pad = PadGrab(paths, via=via, on_key=on_key)
    pad.start()
    return pad


class PadGrab:
    def __init__(
        self,
        paths: list[str],
        via: ViaClient | None = None,
        on_key: OnKey | None = None,
    ):
        self.paths = paths
        self.via = via
        self.on_key = on_key
        self._devs: list[InputDevice] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._evdev_to_cell = identity_evdev_map()
        self._code_cell: dict[int, tuple[int, int]] = {}
        self._last: dict[tuple[int, int], tuple[bool, float]] = {}

    def start(self) -> None:
        self._open()
        self._thread = threading.Thread(target=self._loop, name="c100-pad", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        self._close()

    def _open(self) -> None:
        for path in self.paths:
            try:
                dev = InputDevice(path)
            except OSError as e:
                log.warning("open %s: %s", path, e)
                continue
            try:
                dev.grab()
            except OSError as e:
                log.warning("grab %s: %s", path, e)
                dev.close()
                continue
            self._devs.append(dev)
            log.info("grabbed %s (%s)", path, dev.name)
        if not self._devs:
            raise RuntimeError("could not grab any C100 input nodes")

    def _close(self) -> None:
        for dev in self._devs:
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass
        self._devs.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._devs:
                break
            try:
                r, _w, _x = select.select(self._devs, [], [], 0.25)
            except (OSError, ValueError):
                break
            for dev in r:
                try:
                    for event in dev.read():
                        self._handle(event)
                except OSError:
                    log.info("input node vanished")
                    self._stop.set()
                    return

    def _handle(self, event) -> None:
        if event.type != ecodes.EV_KEY:
            return
        if event.value not in (0, 1):
            return  # ignore aut repeat (value=2)
        pressed = event.value == 1
        try:
            key = ecodes.KEY[event.code]
        except KeyError:
            key = f"KEY_{event.code}"
        # A code with several names comes back as a tuple (older evdev used a
        # list). Checking only for list left those keys unmapped.
        if isinstance(key, (list, tuple)):
            key = key[0]
        cell = self._evdev_to_cell.get(key)
        if pressed:
            if cell is None and self.via is not None:
                try:
                    found = self.via.matrix_pressed(10, 10)
                except Exception as e:
                    log.debug("matrix poll failed: %s", e)
                    found = []
                if len(found) == 1:
                    cell = found[0]
            if cell is not None:
                self._code_cell[event.code] = cell
        elif cell is None:
            cell = self._code_cell.pop(event.code, None)
        else:
            self._code_cell.pop(event.code, None)
        if cell is None:
            log.debug("unmapped key %s", key)
            return
        now = time.monotonic()
        last = self._last.get(cell)
        if last and last[0] == pressed and now - last[1] < 0.008:
            return
        self._last[cell] = (pressed, now)
        if self.on_key:
            try:
                self.on_key(cell[0], cell[1], pressed)
            except Exception:
                log.exception("on_key failed")
