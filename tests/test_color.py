import unittest

from c100ctl.via import hsv255_to_rgb, parse_hex_color, rgb_to_hex, rgb_to_hsv255


class ColorTest(unittest.TestCase):
    def test_hex_roundtrip(self):
        self.assertEqual(parse_hex_color("#ff0000"), (255, 0, 0))
        self.assertEqual(parse_hex_color("0f0"), (0, 255, 0))
        self.assertEqual(rgb_to_hex(0, 0, 255), "#0000ff")

    def test_hsv_red(self):
        self.assertEqual(rgb_to_hsv255(255, 0, 0), (0, 255, 255))
        r, g, b = hsv255_to_rgb(0, 255, 255)
        self.assertEqual((r, g, b), (255, 0, 0))

    def test_hsv_green(self):
        h, s, v = rgb_to_hsv255(0, 255, 0)
        self.assertAlmostEqual(h, 85, delta=1)
        self.assertEqual((s, v), (255, 255))

    def test_mint_green_reads_as_green_on_leds(self):
        h, s, v = rgb_to_hsv255(0x34, 0xC7, 0x59)
        self.assertGreaterEqual(h, 75)
        self.assertLessEqual(h, 90)
        self.assertEqual(s, 255)

    def test_teal_not_pulled_into_green(self):
        h, s, v = rgb_to_hsv255(0x00, 0xC7, 0xBE)
        self.assertGreater(h, 115)

    def test_rect_cells(self):
        r0, r1 = min(1, 3), max(1, 3)
        c0, c1 = min(2, 4), max(2, 4)
        cells = {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
        self.assertEqual(len(cells), 9)
        self.assertIn((1, 2), cells)
        self.assertIn((3, 4), cells)
