"""Virtual keyboard used to inject combos, macros, and typed text."""

from __future__ import annotations

import time
from typing import Iterable

from evdev import UInput, ecodes

from .keycodes import Combo, MacroStep, chars_to_taps, parse_combo, parse_macro

_KEY_CODES: list[int] = []
for name, value in ecodes.ecodes.items():
    if not name.startswith("KEY_"):
        continue
    if isinstance(value, int):
        _KEY_CODES.append(value)

_CAP = {ecodes.EV_KEY: sorted(set(_KEY_CODES))}


def _code(name: str) -> int:
    if not name.startswith("KEY_"):
        name = f"KEY_{name}"
    value = getattr(ecodes, name, None)
    if not isinstance(value, int):
        raise ValueError(f"unknown key {name}")
    return value


class VirtualKeyboard:
    def __init__(self) -> None:
        self._ui = UInput(_CAP, name="C100 Control", vendor=0x3434, product=0x042C)

    def close(self) -> None:
        self._ui.close()

    def tap(self, key: str, hold_s: float = 0.012) -> None:
        self.down(key)
        time.sleep(hold_s)
        self.up(key)

    def down(self, key: str) -> None:
        self._ui.write(ecodes.EV_KEY, _code(key), 1)
        self._ui.syn()

    def up(self, key: str) -> None:
        self._ui.write(ecodes.EV_KEY, _code(key), 0)
        self._ui.syn()

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
