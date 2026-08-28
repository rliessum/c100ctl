"""Shared fakes for unit tests — no hardware, no GTK."""

from __future__ import annotations

from typing import Any


class RecKeyboard:
    def __init__(self) -> None:
        self.ops: list[tuple] = []

    def tap_named(self, name: str, hold_s: float = 0.018) -> None:
        self.ops.append(("tap", name))

    def click_mouse(self, button: str, hold_s: float = 0.03) -> None:
        if button not in {"left", "right", "middle", "back", "forward"}:
            raise ValueError(f"unknown mouse button {button!r}")
        self.ops.append(("click", button))

    def scroll(self, amount: int) -> None:
        self.ops.append(("scroll", amount))

    def play_combo_text(self, text: str) -> None:
        self.ops.append(("combo", text))

    def play_macro_text(self, text: str) -> None:
        self.ops.append(("macro", text))

    def type_text(self, text: str, interval_s: float = 0.008) -> None:
        self.ops.append(("text", text))

    def close(self) -> None:
        self.ops.append(("close",))


class RecExecutor:
    def __init__(self, switch=None) -> None:
        self.runs: list[dict[str, Any]] = []
        self.switch = switch

    def run(self, binding: dict[str, Any]) -> None:
        self.runs.append(dict(binding))
        if binding.get("type") == "profile" and self.switch and binding.get("profile"):
            self.switch(binding["profile"])

    def close(self) -> None:
        pass


class FakeHid:
    """Scripted hidraw stand-in. Replies are 32-byte payloads (no report id)."""

    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.writes: list[bytes] = []
        self.replies = list(replies or [])
        self.closed = False
        self.echo = True

    def write(self, pkt: bytes) -> int:
        self.writes.append(pkt)
        return len(pkt)

    def read(self, n: int, timeout_ms: int = 500) -> bytes:
        if self.replies:
            return self.replies.pop(0)[:n]
        if self.echo and self.writes:
            body = self.writes[-1][1:1 + n]
            return body.ljust(n, b"\x00")
        return b""

    def close(self) -> None:
        self.closed = True


class FakeVia:
    def __init__(self) -> None:
        self.path = "/dev/hidraw-fake"
        self.calls: list[tuple] = []
        self._brightness = 200
        self._effect = 1
        self._speed = 127
        self._color = (0, 255)
        self._per_key_type = 0
        self._poll_div = 0
        self._debounce = (4, 5)
        self._nkro = (True, True)
        self.regions = [0] * 100
        self.slots: dict[int, list[dict[str, int]]] = {}
        self.hsv_writes: list[tuple] = []

    def close(self) -> None:
        self.calls.append(("close",))

    def set_brightness(self, value: int, save: bool = True) -> None:
        self._brightness = value
        self.calls.append(("set_brightness", value, save))

    def brightness(self) -> int:
        return self._brightness

    def set_effect(self, value: int, save: bool = True) -> None:
        self._effect = value
        self.calls.append(("set_effect", value, save))

    def effect(self) -> int:
        return self._effect

    def set_speed(self, value: int, save: bool = True) -> None:
        self._speed = value
        self.calls.append(("set_speed", value, save))

    def speed(self) -> int:
        return self._speed

    def set_color_hsv(self, hue: int, sat: int, save: bool = True) -> None:
        self._color = (hue, sat)
        self.calls.append(("set_color_hsv", hue, sat, save))

    def enable_per_key(self, save: bool = True) -> None:
        self.calls.append(("enable_per_key", save))

    def set_per_key_type(self, type_id: int) -> None:
        self._per_key_type = type_id
        self.calls.append(("set_per_key_type", type_id))

    def save_leds(self) -> None:
        self.calls.append(("save_leds",))

    def set_led_hsv(self, index: int, hsv: tuple[int, int, int]) -> None:
        self.hsv_writes.append((index, hsv))

    def set_leds_hsv(self, start: int, colors: list) -> None:
        for i, hsv in enumerate(colors):
            self.hsv_writes.append((start + i, tuple(hsv)))

    def write_all_rgb(self, colors, save: bool = True) -> None:
        self.calls.append(("write_all_rgb", len(list(colors)), save))

    def set_mix_regions(self, regions) -> None:
        self.regions = list(regions)
        self.calls.append(("set_mix_regions", len(self.regions)))

    def set_mix_slots(self, layer: int, slots) -> None:
        self.slots[layer] = list(slots)
        self.calls.append(("set_mix_slots", layer, len(list(slots))))

    def set_poll_div(self, div: int) -> bool:
        self._poll_div = div
        self.calls.append(("set_poll_div", div))
        return True

    def set_debounce(self, type_id: int, ms: int) -> bool:
        self._debounce = (type_id, ms)
        self.calls.append(("set_debounce", type_id, ms))
        return True

    def set_nkro(self, enabled: bool) -> bool:
        self._nkro = (enabled, True)
        self.calls.append(("set_nkro", enabled))
        return True

    def firmware_string(self) -> str:
        return "v1.0.1 test"

    def get_poll_div(self) -> int:
        return self._poll_div

    def get_debounce(self) -> tuple[int, int]:
        return self._debounce

    def get_nkro(self) -> tuple[bool, bool]:
        return self._nkro

    def led_map(self, rows: int = 10, cols: int = 10) -> list[list[int]]:
        return [[r * cols + c for c in range(cols)] for r in range(rows)]
