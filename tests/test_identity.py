import unittest

from c100ctl import COLS, LOCKED_KEYS, ROWS
from c100ctl.identity import (
    FACTORY_FILL,
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

    def test_identity_unique(self):
        qmap = identity_qmk_map()
        self.assertEqual(len(qmap), 96)
        self.assertEqual(len(set(qmap.values())), 96)
        ev = identity_evdev_map()
        self.assertEqual(len(ev), 96)
        self.assertEqual(len(set(ev.values())), 96)

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
