"""Stable per-key identity map written to C100 firmware layer 0."""

from __future__ import annotations

from . import COLS, LOCKED_KEYS, ROWS
from .keycodes import EVDEV, QMK

# 96 unique basic keycodes. Order is row-major over programmable cells.
_IDENTITY_NAMES: tuple[str, ...] = (
    *(f"KC_F{n}" for n in range(13, 25)),  # 12
    *(f"KC_{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),  # 26
    *(f"KC_{n}" for n in "1234567890"),  # 10
    *(f"KC_F{n}" for n in range(1, 13)),  # 12
    *(f"KC_P{n}" for n in "1234567890"),  # 10
    "KC_PDOT",
    "KC_PPLS",
    "KC_PMNS",
    "KC_PAST",
    "KC_PSLS",
    "KC_PENT",
    "KC_ENTER",
    "KC_ESC",
    "KC_BSPC",
    "KC_TAB",
    "KC_SPC",
    "KC_MINS",
    "KC_EQL",
    "KC_LBRC",
    "KC_RBRC",
    "KC_BSLS",
    "KC_SCLN",
    "KC_QUOT",
    "KC_GRV",
    "KC_COMM",
    "KC_DOT",
    "KC_SLSH",
    "KC_INS",
    "KC_HOME",
    "KC_PGUP",
    "KC_DEL",
)

assert len(_IDENTITY_NAMES) == 96
assert len(set(_IDENTITY_NAMES)) == 96

FACTORY_FILL = 0x001E  # KC_1 — stock C100 programmable keys
RGB_PREV = 0x7822
RGB_NEXT = 0x7821


def programmable_cells() -> list[tuple[int, int]]:
    return [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in LOCKED_KEYS]


def identity_qmk_map() -> dict[tuple[int, int], int]:
    cells = programmable_cells()
    return {cell: QMK[name] for cell, name in zip(cells, _IDENTITY_NAMES, strict=True)}


def identity_evdev_map() -> dict[str, tuple[int, int]]:
    qmap = identity_qmk_map()
    out: dict[str, tuple[int, int]] = {}
    name_by_code = {QMK[n]: n for n in _IDENTITY_NAMES}
    for cell, code in qmap.items():
        ev = EVDEV[name_by_code[code]]
        out[ev] = cell
    return out


def looks_factory(layer0: list[list[int]]) -> bool:
    """True if programmable keys are all KC_NO or all KC_1."""
    values = []
    for r in range(ROWS):
        for c in range(COLS):
            if (r, c) in LOCKED_KEYS:
                continue
            values.append(layer0[r][c])
    if not values:
        return False
    return all(v in (0x0000, FACTORY_FILL) for v in values)


def layer_with_identity(existing: list[list[int]] | None = None) -> list[list[int]]:
    matrix = [
        [existing[r][c] if existing else 0 for c in range(COLS)] for r in range(ROWS)
    ]
    if existing:
        matrix[0][0] = existing[0][0] or RGB_PREV
        matrix[0][9] = existing[0][9] or RGB_PREV
        matrix[9][0] = existing[9][0] or RGB_NEXT
        matrix[9][9] = existing[9][9] or RGB_NEXT
    else:
        matrix[0][0] = RGB_PREV
        matrix[0][9] = RGB_PREV
        matrix[9][0] = RGB_NEXT
        matrix[9][9] = RGB_NEXT
    for cell, code in identity_qmk_map().items():
        r, c = cell
        matrix[r][c] = code
    return matrix
