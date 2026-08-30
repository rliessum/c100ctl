"""Quartz / AppKit injection of keyboard, mouse, and media keys on macOS."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable, Sequence
from ctypes import (
    CDLL,
    CFUNCTYPE,
    Structure,
    c_bool,
    c_char_p,
    c_double,
    c_int32,
    c_long,
    c_short,
    c_uint16,
    c_uint32,
    c_ulong,
    c_void_p,
)
from typing import Any

from .keycodes import Combo, MacroStep, chars_to_taps, parse_combo, parse_macro

kCGHIDEventTap = 0
kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp = 2
kCGEventRightMouseDown = 3
kCGEventRightMouseUp = 4
kCGEventOtherMouseDown = 25
kCGEventOtherMouseUp = 26
kCGScrollEventUnitLine = 0
kCGMouseButtonLeft = 0
kCGMouseButtonRight = 1
kCGMouseButtonCenter = 2

NSEventTypeSystemDefined = 14
NX_SUBTYPE_AUX_CONTROL_BUTTONS = 8

# NX_KEYTYPE_*
NX_SOUND_UP = 0
NX_SOUND_DOWN = 1
NX_BRIGHTNESS_UP = 2
NX_BRIGHTNESS_DOWN = 3
NX_MUTE = 7
NX_EJECT = 14
NX_PLAY = 16
NX_NEXT = 17
NX_PREVIOUS = 18

# ANSI virtual keycodes (HIToolbox Events.h).
_VK: dict[str, int] = {
    "KEY_A": 0x00,
    "KEY_S": 0x01,
    "KEY_D": 0x02,
    "KEY_F": 0x03,
    "KEY_H": 0x04,
    "KEY_G": 0x05,
    "KEY_Z": 0x06,
    "KEY_X": 0x07,
    "KEY_C": 0x08,
    "KEY_V": 0x09,
    "KEY_B": 0x0B,
    "KEY_Q": 0x0C,
    "KEY_W": 0x0D,
    "KEY_E": 0x0E,
    "KEY_R": 0x0F,
    "KEY_Y": 0x10,
    "KEY_T": 0x11,
    "KEY_1": 0x12,
    "KEY_2": 0x13,
    "KEY_3": 0x14,
    "KEY_4": 0x15,
    "KEY_6": 0x16,
    "KEY_5": 0x17,
    "KEY_EQUAL": 0x18,
    "KEY_9": 0x19,
    "KEY_7": 0x1A,
    "KEY_MINUS": 0x1B,
    "KEY_8": 0x1C,
    "KEY_0": 0x1D,
    "KEY_RIGHTBRACE": 0x1E,
    "KEY_O": 0x1F,
    "KEY_U": 0x20,
    "KEY_LEFTBRACE": 0x21,
    "KEY_I": 0x22,
    "KEY_P": 0x23,
    "KEY_ENTER": 0x24,
    "KEY_L": 0x25,
    "KEY_J": 0x26,
    "KEY_APOSTROPHE": 0x27,
    "KEY_K": 0x28,
    "KEY_SEMICOLON": 0x29,
    "KEY_BACKSLASH": 0x2A,
    "KEY_COMMA": 0x2B,
    "KEY_SLASH": 0x2C,
    "KEY_N": 0x2D,
    "KEY_M": 0x2E,
    "KEY_DOT": 0x2F,
    "KEY_TAB": 0x30,
    "KEY_SPACE": 0x31,
    "KEY_GRAVE": 0x32,
    "KEY_BACKSPACE": 0x33,
    "KEY_ESC": 0x35,
    "KEY_RIGHTMETA": 0x36,
    "KEY_LEFTMETA": 0x37,
    "KEY_LEFTSHIFT": 0x38,
    "KEY_CAPSLOCK": 0x39,
    "KEY_LEFTALT": 0x3A,
    "KEY_LEFTCTRL": 0x3B,
    "KEY_RIGHTSHIFT": 0x3C,
    "KEY_RIGHTALT": 0x3D,
    "KEY_RIGHTCTRL": 0x3E,
    "KEY_F17": 0x40,
    "KEY_KPDOT": 0x41,
    "KEY_KPASTERISK": 0x43,
    "KEY_KPPLUS": 0x45,
    "KEY_NUMLOCK": 0x47,
    "KEY_VOLUMEUP": 0x48,
    "KEY_VOLUMEDOWN": 0x49,
    "KEY_MUTE": 0x4A,
    "KEY_KPSLASH": 0x4B,
    "KEY_KPENTER": 0x4C,
    "KEY_KPMINUS": 0x4E,
    "KEY_F18": 0x4F,
    "KEY_F19": 0x50,
    "KEY_KP0": 0x52,
    "KEY_KP1": 0x53,
    "KEY_KP2": 0x54,
    "KEY_KP3": 0x55,
    "KEY_KP4": 0x56,
    "KEY_KP5": 0x57,
    "KEY_KP6": 0x58,
    "KEY_KP7": 0x59,
    "KEY_F20": 0x5A,
    "KEY_KP8": 0x5B,
    "KEY_KP9": 0x5C,
    "KEY_F5": 0x60,
    "KEY_F6": 0x61,
    "KEY_F7": 0x62,
    "KEY_F3": 0x63,
    "KEY_F8": 0x64,
    "KEY_F9": 0x65,
    "KEY_F11": 0x67,
    "KEY_F13": 0x69,
    "KEY_F16": 0x6A,
    "KEY_F14": 0x6B,
    "KEY_F10": 0x6D,
    "KEY_F12": 0x6F,
    "KEY_F15": 0x71,
    "KEY_INSERT": 0x72,
    "KEY_HOME": 0x73,
    "KEY_PAGEUP": 0x74,
    "KEY_DELETE": 0x75,
    "KEY_F4": 0x76,
    "KEY_END": 0x77,
    "KEY_F2": 0x78,
    "KEY_PAGEDOWN": 0x79,
    "KEY_F1": 0x7A,
    "KEY_LEFT": 0x7B,
    "KEY_RIGHT": 0x7C,
    "KEY_DOWN": 0x7D,
    "KEY_UP": 0x7E,
}

_NX_MEDIA: dict[str, int] = {
    "KEY_PLAYPAUSE": NX_PLAY,
    "KEY_PLAYCD": NX_PLAY,
    "KEY_PAUSECD": NX_PLAY,
    "KEY_NEXTSONG": NX_NEXT,
    "KEY_PREVIOUSSONG": NX_PREVIOUS,
    "KEY_MUTE": NX_MUTE,
    "KEY_VOLUMEUP": NX_SOUND_UP,
    "KEY_VOLUMEDOWN": NX_SOUND_DOWN,
    "KEY_BRIGHTNESSUP": NX_BRIGHTNESS_UP,
    "KEY_BRIGHTNESSDOWN": NX_BRIGHTNESS_DOWN,
    "KEY_EJECTCD": NX_EJECT,
    "KEY_MICMUTE": NX_MUTE,
}

_OPEN_MEDIA: dict[str, Sequence[str]] = {
    "KEY_WWW": ("open", "https://"),
    "KEY_HOMEPAGE": ("open", "https://"),
    "KEY_MAIL": ("open", "-a", "Mail"),
    "KEY_CALC": ("open", "-a", "Calculator"),
}

_MOUSE_BTN = {
    "left": (kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft),
    "right": (kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight),
    "middle": (kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGMouseButtonCenter),
    "back": (kCGEventOtherMouseDown, kCGEventOtherMouseUp, 3),
    "forward": (kCGEventOtherMouseDown, kCGEventOtherMouseUp, 4),
}


class CGPoint(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class NSPoint(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


_CG: Any = None
_CF: Any = None
_OBJC: Any = None
_MEDIA_MSG: Any = None


def _cg() -> Any:  # pragma: no cover
    global _CG, _CF
    if _CG is None:
        _CG = CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        _CF = CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        _CG.CGEventCreateKeyboardEvent.restype = c_void_p
        _CG.CGEventCreateKeyboardEvent.argtypes = [c_void_p, c_uint16, c_bool]
        _CG.CGEventPost.argtypes = [c_uint32, c_void_p]
        _CG.CGEventCreate.restype = c_void_p
        _CG.CGEventCreate.argtypes = [c_void_p]
        _CG.CGEventGetLocation.restype = CGPoint
        _CG.CGEventGetLocation.argtypes = [c_void_p]
        _CG.CGEventCreateMouseEvent.restype = c_void_p
        _CG.CGEventCreateMouseEvent.argtypes = [c_void_p, c_uint32, CGPoint, c_uint32]
        _CG.CGEventCreateScrollWheelEvent2.restype = c_void_p
        _CG.CGEventCreateScrollWheelEvent2.argtypes = [
            c_void_p,
            c_uint32,
            c_uint32,
            c_int32,
            c_int32,
            c_int32,
        ]
        _CF.CFRelease.argtypes = [c_void_p]
    return _CG


def _cf_release(ref: int | None) -> None:  # pragma: no cover
    if ref:
        _cg()
        _CF.CFRelease(ref)


def _norm(name: str) -> str:
    if not name.startswith("KEY_"):
        name = f"KEY_{name}"
    return name


def virtual_keycode(name: str) -> int:
    key = _norm(name)
    code = _VK.get(key)
    if code is None:
        raise ValueError(f"unknown key {name}")
    return code


def post_key(name: str, down: bool, source: int | None = None) -> None:  # pragma: no cover
    cg = _cg()
    ev = cg.CGEventCreateKeyboardEvent(source, virtual_keycode(name), down)
    if not ev:
        raise RuntimeError("CGEventCreateKeyboardEvent failed")
    try:
        cg.CGEventPost(kCGHIDEventTap, ev)
    finally:
        _cf_release(ev)


def post_mouse(button: str, down: bool, source: int | None = None) -> None:  # pragma: no cover
    spec = _MOUSE_BTN.get(button)
    if not spec:
        raise ValueError(f"unknown mouse button {button!r}")
    down_type, up_type, btn = spec
    cg = _cg()
    probe = cg.CGEventCreate(None)
    loc = CGPoint(0, 0)
    if probe:
        loc = cg.CGEventGetLocation(probe)
        _cf_release(probe)
    ev_type = down_type if down else up_type
    ev = cg.CGEventCreateMouseEvent(source, ev_type, loc, btn)
    if not ev:
        raise RuntimeError("CGEventCreateMouseEvent failed")
    try:
        cg.CGEventPost(kCGHIDEventTap, ev)
    finally:
        _cf_release(ev)


def post_scroll(amount: int, source: int | None = None) -> None:  # pragma: no cover
    cg = _cg()
    ev = cg.CGEventCreateScrollWheelEvent2(
        source, kCGScrollEventUnitLine, 1, int(amount), 0, 0
    )
    if not ev:
        raise RuntimeError("CGEventCreateScrollWheelEvent2 failed")
    try:
        cg.CGEventPost(kCGHIDEventTap, ev)
    finally:
        _cf_release(ev)


def _media_msg() -> Any:  # pragma: no cover
    global _OBJC, _MEDIA_MSG
    if _MEDIA_MSG is not None:
        return _MEDIA_MSG
    CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    _OBJC = CDLL("/usr/lib/libobjc.A.dylib")
    _OBJC.objc_getClass.restype = c_void_p
    _OBJC.objc_getClass.argtypes = [c_char_p]
    _OBJC.sel_registerName.restype = c_void_p
    _OBJC.sel_registerName.argtypes = [c_char_p]
    _MEDIA_MSG = CFUNCTYPE(
        c_void_p,
        c_void_p,
        c_void_p,
        c_ulong,
        NSPoint,
        c_ulong,
        c_double,
        c_long,
        c_void_p,
        c_short,
        c_long,
        c_long,
    )(("objc_msgSend", _OBJC))
    return _MEDIA_MSG


def post_media(nx_key: int, down: bool) -> None:  # pragma: no cover
    msg = _media_msg()
    nsevent = _OBJC.objc_getClass(b"NSEvent")
    sel = _OBJC.sel_registerName(
        b"otherEventWithType:location:modifierFlags:timestamp:windowNumber:context:subtype:data1:data2:"
    )
    state = 0xA if down else 0xB
    data1 = (int(nx_key) << 16) | (state << 8)
    evt = msg(
        nsevent,
        sel,
        NSEventTypeSystemDefined,
        NSPoint(0, 0),
        0xA00,
        0.0,
        0,
        None,
        NX_SUBTYPE_AUX_CONTROL_BUTTONS,
        data1,
        -1,
    )
    if not evt:
        raise RuntimeError("NSEvent media key failed")
    _OBJC.objc_msgSend.restype = c_void_p
    _OBJC.objc_msgSend.argtypes = [c_void_p, c_void_p]
    cge = _OBJC.objc_msgSend(evt, _OBJC.sel_registerName(b"CGEvent"))
    if not cge:
        raise RuntimeError("NSEvent.CGEvent failed")
    _cg().CGEventPost(kCGHIDEventTap, cge)


def post_open(argv: Sequence[str]) -> None:
    subprocess.Popen(list(argv), start_new_session=True)


def post_screenshot() -> None:  # pragma: no cover
    post_key("KEY_LEFTMETA", True)
    post_key("KEY_LEFTSHIFT", True)
    post_key("KEY_3", True)
    post_key("KEY_3", False)
    post_key("KEY_LEFTSHIFT", False)
    post_key("KEY_LEFTMETA", False)


class VirtualKeyboard:
    def __init__(self) -> None:
        pass

    def close(self) -> None:
        return

    def tap(self, key: str, hold_s: float = 0.012) -> None:
        self.down(key)
        time.sleep(hold_s)
        self.up(key)

    def down(self, key: str) -> None:
        name = _norm(key)
        if name == "KEY_SYSRQ":
            return
        if name in _NX_MEDIA:
            post_media(_NX_MEDIA[name], True)
            return
        if name in _OPEN_MEDIA:
            return
        post_key(name, True)

    def up(self, key: str) -> None:
        name = _norm(key)
        if name == "KEY_SYSRQ":
            post_screenshot()
            return
        if name in _NX_MEDIA:
            post_media(_NX_MEDIA[name], False)
            return
        if name in _OPEN_MEDIA:
            post_open(_OPEN_MEDIA[name])
            return
        post_key(name, False)

    def combo(self, combo: Combo, hold_s: float = 0.018) -> None:
        for mod in combo.modifiers:
            self.down(mod)
        self.down(combo.key)
        time.sleep(hold_s)
        self.up(combo.key)
        for mod in reversed(combo.modifiers):
            self.up(mod)

    def type_text(self, text: str, interval_s: float = 0.008) -> None:
        for key, shift in chars_to_taps(text):
            if shift:
                self.down("KEY_LEFTSHIFT")
            self.tap(key, hold_s=interval_s)
            if shift:
                self.up("KEY_LEFTSHIFT")
            time.sleep(interval_s)

    def play_macro(self, steps: Iterable[MacroStep]) -> None:
        for step in steps:
            if step.kind == "delay":
                time.sleep(max(0, step.delay_ms) / 1000.0)
            elif step.kind == "text":
                self.type_text(step.text)
            elif step.kind == "down":
                self.down(step.key)
            elif step.kind == "up":
                self.up(step.key)
            elif step.kind == "tap":
                self.tap(step.key)
            else:
                raise ValueError(f"unknown macro step {step.kind}")

    def play_combo_text(self, text: str) -> None:
        self.combo(parse_combo(text))

    def play_macro_text(self, text: str) -> None:
        self.play_macro(parse_macro(text))

    def tap_named(self, name: str, hold_s: float = 0.018) -> None:
        self.tap(name, hold_s=hold_s)

    def click_mouse(self, button: str, hold_s: float = 0.03) -> None:
        if button not in _MOUSE_BTN:
            raise ValueError(f"unknown mouse button {button!r}")
        post_mouse(button, True)
        time.sleep(hold_s)
        post_mouse(button, False)

    def scroll(self, amount: int) -> None:
        post_scroll(int(amount))
