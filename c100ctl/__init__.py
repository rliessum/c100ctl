"""C100 Control — Linux host for the Keychron C100 8K macropad."""

__version__ = "1.3.0"

VID = 0x3434
PID = 0x042C
PRODUCT = "Keychron C100 8K"
ROWS = 10
COLS = 10

# Firmware-locked lighting keys (VIA keymap 0x7822 / 0x7821).
LOCKED_KEYS = frozenset({(0, 0), (0, 9), (9, 0), (9, 9)})
LOCKED_LABELS = {
    (0, 0): "RGB −",
    (0, 9): "RGB −",
    (9, 0): "RGB +",
    (9, 9): "RGB +",
}
