import unittest

from c100ctl import COLS, LOCKED_KEYS, ROWS
from c100ctl.identity import (
    FACTORY_FILL,
    RGB_NEXT,
    RGB_PREV,
    identity_evdev_map,
    identity_qmk_map,
    layer_with_identity,
    looks_factory,
    programmable_cells,
)


class IdentityTest(unittest.TestCase):
    def test_programmable_count(self):
        cells = programmable_cells()
        self.assertEqual(len(cells), 96)
        self.assertNotIn((0, 0), cells)
        self.assertNotIn((9, 9), cells)
        self.assertEqual(len(LOCKED_KEYS), 4)

    def test_identity_unique(self):
        qmap = identity_qmk_map()
        self.assertEqual(len(qmap), 96)
        self.assertEqual(len(set(qmap.values())), 96)
        ev = identity_evdev_map()
        self.assertEqual(len(ev), 96)
        self.assertEqual(len(set(ev.values())), 96)
        self.assertTrue(all(name.startswith("KEY_") for name in ev))

    def test_factory_detect(self):
        layer = [[FACTORY_FILL for _ in range(COLS)] for _ in range(ROWS)]
        layer[0][0] = 0x7822
        layer[0][9] = 0x7822
        layer[9][0] = 0x7821
        layer[9][9] = 0x7821
        self.assertTrue(looks_factory(layer))
        ident = layer_with_identity(layer)
        self.assertEqual(ident[0][0], 0x7822)
        self.assertNotEqual(ident[1][1], FACTORY_FILL)
        self.assertFalse(looks_factory(ident))
        for r, c in LOCKED_KEYS:
            self.assertIn(ident[r][c], (0x7821, 0x7822))

    def test_factory_all_zero(self):
        layer = [[0 for _ in range(COLS)] for _ in range(ROWS)]
        self.assertTrue(looks_factory(layer))

    def test_not_factory_mixed(self):
        layer = [[FACTORY_FILL for _ in range(COLS)] for _ in range(ROWS)]
        layer[1][1] = 0x0004
        self.assertFalse(looks_factory(layer))

    def test_layer_without_existing(self):
        ident = layer_with_identity(None)
        self.assertEqual(ident[0][0], RGB_PREV)
        self.assertEqual(ident[9][9], RGB_NEXT)
        self.assertEqual(len(ident), ROWS)
        self.assertEqual(len(ident[0]), COLS)

    def test_layer_zero_corners_filled(self):
        layer = [[0 for _ in range(COLS)] for _ in range(ROWS)]
        ident = layer_with_identity(layer)
        self.assertEqual(ident[0][0], RGB_PREV)
        self.assertEqual(ident[9][0], RGB_NEXT)
