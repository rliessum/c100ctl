"""Exclusive IOHID seize of the C100 keyboard collections. Identity map → (row, col).

If Input Monitoring is not granted, falls back to VIA matrix polling. Pad keys
then still fire bindings, but they also type into the focused app.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from ctypes import (
    CDLL,
    CFUNCTYPE,
    Structure,
    byref,
    c_bool,
    c_char_p,
    c_double,
    c_int,
    c_int32,
    c_long,
    c_uint32,
    c_void_p,
)
from typing import TYPE_CHECKING, Any

from . import PID, VID
from .identity import identity_hid_map

if TYPE_CHECKING:
    from .via import ViaClient

log = logging.getLogger("c100ctl.pad")

OnKey = Callable[[int, int, bool], None]

kIOHIDOptionsTypeNone = 0
kIOHIDOptionsTypeSeizeDevice = 1
kIOHIDRequestTypeListenEvent = 0
kIOHIDAccessTypeGranted = 0
kHIDPage_KeyboardOrKeypad = 0x07
kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt32Type = 3
kIOReturnSuccess = 0

KEYBOARD_USAGE_PAGE = 0x01
KEYBOARD_USAGE = 0x06
KEYPAD_USAGE = 0x07

_ValueCallback = CFUNCTYPE(None, c_void_p, c_int, c_void_p, c_void_p)


class _CFDictKeyCBs(Structure):
    _fields_ = [
        ("version", c_long),
        ("retain", c_void_p),
        ("release", c_void_p),
        ("copyDescription", c_void_p),
        ("equal", c_void_p),
        ("hash", c_void_p),
    ]


class _CFDictValCBs(Structure):
    _fields_ = [
        ("version", c_long),
        ("retain", c_void_p),
        ("release", c_void_p),
        ("copyDescription", c_void_p),
        ("equal", c_void_p),
    ]


class _CFArrayCBs(Structure):
    _fields_ = [
        ("version", c_long),
        ("retain", c_void_p),
        ("release", c_void_p),
        ("copyDescription", c_void_p),
        ("equal", c_void_p),
    ]


def hid_listen_granted() -> bool | None:  # pragma: no cover
    """True/False when IOHIDCheckAccess exists; None if the symbol is missing."""
    try:
        iokit = CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDCheckAccess.restype = c_int
        iokit.IOHIDCheckAccess.argtypes = [c_int]
        return iokit.IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeGranted
    except (OSError, AttributeError):
        return None


def request_hid_listen() -> bool:  # pragma: no cover
    try:
        iokit = CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDRequestAccess.restype = c_bool
        iokit.IOHIDRequestAccess.argtypes = [c_int]
        return bool(iokit.IOHIDRequestAccess(kIOHIDRequestTypeListenEvent))
    except (OSError, AttributeError):
        return False


def _frameworks() -> tuple[Any, Any]:  # pragma: no cover
    iokit = CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    cf = CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
    cf.CFNumberCreate.restype = c_void_p
    cf.CFNumberCreate.argtypes = [c_void_p, c_long, c_void_p]
    cf.CFDictionaryCreate.restype = c_void_p
    cf.CFDictionaryCreate.argtypes = [c_void_p, c_void_p, c_void_p, c_long, c_void_p, c_void_p]
    cf.CFArrayCreate.restype = c_void_p
    cf.CFArrayCreate.argtypes = [c_void_p, c_void_p, c_long, c_void_p]
    cf.CFRelease.argtypes = [c_void_p]
    cf.CFSetGetCount.restype = c_long
    cf.CFSetGetCount.argtypes = [c_void_p]
    cf.CFRunLoopGetCurrent.restype = c_void_p
    cf.CFRunLoopRunInMode.restype = c_int32
    cf.CFRunLoopRunInMode.argtypes = [c_void_p, c_double, c_bool]
    cf.CFRunLoopStop.argtypes = [c_void_p]
    iokit.IOHIDManagerCreate.restype = c_void_p
    iokit.IOHIDManagerCreate.argtypes = [c_void_p, c_int]
    iokit.IOHIDManagerSetDeviceMatchingMultiple.argtypes = [c_void_p, c_void_p]
    iokit.IOHIDManagerRegisterInputValueCallback.argtypes = [c_void_p, c_void_p, c_void_p]
    iokit.IOHIDManagerScheduleWithRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
    iokit.IOHIDManagerUnscheduleFromRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
    iokit.IOHIDManagerOpen.restype = c_int
    iokit.IOHIDManagerOpen.argtypes = [c_void_p, c_int]
    iokit.IOHIDManagerClose.restype = c_int
    iokit.IOHIDManagerClose.argtypes = [c_void_p, c_int]
    iokit.IOHIDManagerCopyDevices.restype = c_void_p
    iokit.IOHIDManagerCopyDevices.argtypes = [c_void_p]
    iokit.IOHIDValueGetElement.restype = c_void_p
    iokit.IOHIDValueGetElement.argtypes = [c_void_p]
    iokit.IOHIDElementGetUsagePage.restype = c_uint32
    iokit.IOHIDElementGetUsagePage.argtypes = [c_void_p]
    iokit.IOHIDElementGetUsage.restype = c_uint32
    iokit.IOHIDElementGetUsage.argtypes = [c_void_p]
    iokit.IOHIDValueGetIntegerValue.restype = c_long
    iokit.IOHIDValueGetIntegerValue.argtypes = [c_void_p]
    return iokit, cf


def ctypes_addr(struct: Structure) -> int:
    from ctypes import addressof

    return addressof(struct)


def matching_criteria() -> list[list[tuple[str, int]]]:
    base = [("VendorID", VID), ("ProductID", PID), ("PrimaryUsagePage", KEYBOARD_USAGE_PAGE)]
    return [
        [*base, ("PrimaryUsage", KEYBOARD_USAGE)],
        [*base, ("PrimaryUsage", KEYPAD_USAGE)],
    ]


def _matching_array(cf: Any) -> int:  # pragma: no cover
    key_cbs = _CFDictKeyCBs.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")
    val_cbs = _CFDictValCBs.in_dll(cf, "kCFTypeDictionaryValueCallBacks")
    arr_cbs = _CFArrayCBs.in_dll(cf, "kCFTypeArrayCallBacks")
    dicts: list[int] = []
    held: list[c_int] = []
    for pairs in matching_criteria():
        n = len(pairs)
        keys = (c_void_p * n)()
        vals = (c_void_p * n)()
        for i, (name, number) in enumerate(pairs):
            keys[i] = cf.CFStringCreateWithCString(None, name.encode(), kCFStringEncodingUTF8)
            iv = c_int(number)
            held.append(iv)
            vals[i] = cf.CFNumberCreate(None, kCFNumberSInt32Type, byref(iv))
        d = cf.CFDictionaryCreate(
            None,
            keys,
            vals,
            n,
            ctypes_addr(key_cbs),
            ctypes_addr(val_cbs),
        )
        if not d:
            raise RuntimeError("CFDictionaryCreate failed")
        dicts.append(d)
    values = (c_void_p * len(dicts))(*dicts)
    arr = cf.CFArrayCreate(None, values, len(dicts), ctypes_addr(arr_cbs))
    if not arr:
        raise RuntimeError("CFArrayCreate failed")
    return arr


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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hid_to_cell = identity_hid_map()
        self._code_cell: dict[int, tuple[int, int]] = {}
        self._last: dict[tuple[int, int], tuple[bool, float]] = {}
        self._mgr: Any = None
        self._rl: Any = None
        self._cb: Any = None
        self._iokit: Any = None
        self._cf: Any = None
        self._mode: str | None = None
        self._seized = False

    def start(self) -> None:
        if self._try_iokit():
            self._mode = "iokit"
            self._thread = threading.Thread(target=self._iokit_loop, name="c100-pad", daemon=True)
            self._thread.start()
            return
        if self.via is None:
            raise RuntimeError(
                "could not grab the C100 keyboard; grant Input Monitoring to this process "
                "(System Settings → Privacy & Security → Input Monitoring)"
            )
        log.warning(
            "Input Monitoring not granted; using VIA matrix poll "
            "(pad keys may type into the focused app)"
        )
        self._mode = "matrix"
        self._thread = threading.Thread(target=self._matrix_loop, name="c100-pad", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._rl is not None and self._cf is not None:
            try:
                self._cf.CFRunLoopStop(self._rl)
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1.5)
        self._close_iokit()

    def _try_iokit(self) -> bool:  # pragma: no cover
        try:
            iokit, cf = _frameworks()
        except OSError as e:
            log.debug("IOKit unavailable: %s", e)
            return False
        granted = hid_listen_granted()
        if granted is False:
            request_hid_listen()
        try:
            mgr = iokit.IOHIDManagerCreate(None, kIOHIDOptionsTypeNone)
            if not mgr:
                return False
            matching = _matching_array(cf)
            iokit.IOHIDManagerSetDeviceMatchingMultiple(mgr, matching)
            cf.CFRelease(matching)

            def _on_value(_ctx: int, _result: int, _sender: int, value: int) -> None:
                try:
                    self._on_hid_value(value)
                except Exception:
                    log.exception("HID value callback")

            cb = _ValueCallback(_on_value)
            iokit.IOHIDManagerRegisterInputValueCallback(mgr, cb, None)
            self._mgr = mgr
            self._iokit = iokit
            self._cf = cf
            self._cb = cb  # keep the callback pointer alive
            return True
        except Exception:
            log.exception("IOHID manager setup failed")
            return False

    def _iokit_loop(self) -> None:  # pragma: no cover
        assert self._iokit and self._cf and self._mgr
        iokit, cf, mgr = self._iokit, self._cf, self._mgr
        mode = c_void_p.in_dll(cf, "kCFRunLoopDefaultMode")
        self._rl = cf.CFRunLoopGetCurrent()
        iokit.IOHIDManagerScheduleWithRunLoop(mgr, self._rl, mode)
        seize_rc = iokit.IOHIDManagerOpen(mgr, kIOHIDOptionsTypeSeizeDevice)
        seized = seize_rc == kIOReturnSuccess
        rc = seize_rc
        if not seized:
            log.info("seize C100 keyboard failed (%s); trying shared open", seize_rc)
            rc = iokit.IOHIDManagerOpen(mgr, kIOHIDOptionsTypeNone)
        if rc != kIOReturnSuccess:
            log.warning("IOHIDManagerOpen failed (%s); falling back to VIA matrix", rc)
            self._close_iokit()
            if self.via is not None:
                self._mode = "matrix"
                self._matrix_loop()
            return
        self._seized = seized
        log.info("C100 keyboard opened via IOHID (seize=%s)", seized)
        if not seized:
            log.warning("pad keys may type into the focused app until Input Monitoring seize succeeds")
        while not self._stop.is_set():
            cf.CFRunLoopRunInMode(mode, 0.25, False)

    def _close_iokit(self) -> None:  # pragma: no cover
        if self._mgr is None:
            return
        try:
            if self._iokit and self._cf and self._rl is not None:
                mode = c_void_p.in_dll(self._cf, "kCFRunLoopDefaultMode")
                self._iokit.IOHIDManagerUnscheduleFromRunLoop(self._mgr, self._rl, mode)
        except OSError:
            pass
        try:
            if self._iokit:
                self._iokit.IOHIDManagerClose(self._mgr, kIOHIDOptionsTypeNone)
        except OSError:
            pass
        try:
            if self._cf:
                self._cf.CFRelease(self._mgr)
        except OSError:
            pass
        self._mgr = None
        self._rl = None
        self._seized = False

    def _on_hid_value(self, value: int) -> None:  # pragma: no cover
        if not value or not self._iokit:
            return
        element = self._iokit.IOHIDValueGetElement(value)
        if not element:
            return
        page = int(self._iokit.IOHIDElementGetUsagePage(element))
        usage = int(self._iokit.IOHIDElementGetUsage(element))
        if page != kHIDPage_KeyboardOrKeypad or usage < 4:
            return
        pressed = int(self._iokit.IOHIDValueGetIntegerValue(value)) != 0
        self._handle_usage(usage, pressed)

    def _handle_usage(self, usage: int, pressed: bool) -> None:
        cell = self._hid_to_cell.get(usage)
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
                self._code_cell[usage] = cell
        elif cell is None:
            cell = self._code_cell.pop(usage, None)
        else:
            self._code_cell.pop(usage, None)
        if cell is None:
            log.debug("unmapped HID usage 0x%02x", usage)
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

    def _matrix_loop(self) -> None:
        prev: set[tuple[int, int]] = set()
        while not self._stop.is_set():
            self._poll_matrix(prev)
            time.sleep(0.008)

    def _poll_matrix(self, prev: set[tuple[int, int]]) -> None:
        if not self.via:
            return
        try:
            found = self.via.matrix_pressed(10, 10)
        except Exception as e:
            log.debug("matrix poll failed: %s", e)
            return
        now = set(found)
        for cell in now - prev:
            self._emit(cell, True)
        for cell in prev - now:
            self._emit(cell, False)
        prev.clear()
        prev.update(now)

    def _emit(self, cell: tuple[int, int], pressed: bool) -> None:
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
