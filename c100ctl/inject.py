"""Virtual keyboard used to inject combos, macros, typed text, and mouse."""

from __future__ import annotations

from .host import is_macos

if is_macos():
    from .inject_macos import VirtualKeyboard
else:
    from .uinput_kb import VirtualKeyboard  # type: ignore[assignment]

__all__ = ["VirtualKeyboard"]
