import unittest

from c100ctl.via import (
    _led_green,
    heatmap_hex,
    heatmap_rgb,
    hsv255_to_rgb,
    parse_hex_color,
    poll_div_from_hz,
    poll_hz_from_div,
    rgb_to_hex,
    rgb_to_hsv255,
)


class ColorTest(unittest.TestCase):
    def test_hex_roundtrip(self):
        self.assertEqual(parse_hex_color("#ff0000"), (255, 0, 0))
        self.assertEqual(parse_hex_color("0f0"), (0, 255, 0))
        self.assertEqual(parse_hex_color("AABBCC"), (0xAA, 0xBB, 0xCC))
        self.assertEqual(rgb_to_hex(0, 0, 255), "#0000ff")

    def test_invalid_hex(self):
        with self.assertRaises(ValueError):
            parse_hex_color("#gg0000")
        with self.assertRaises(ValueError):
            parse_hex_color("12")
        with self.assertRaises(ValueError):
            parse_hex_color("#12345")

    def test_hsv_red(self):
        self.assertEqual(rgb_to_hsv255(255, 0, 0), (0, 255, 255))
        r, g, b = hsv255_to_rgb(0, 255, 255)
        self.assertEqual((r, g, b), (255, 0, 0))

    def test_hsv_green(self):
        h, s, v = rgb_to_hsv255(0, 255, 0)
        self.assertAlmostEqual(h, 85, delta=1)
        self.assertEqual((s, v), (255, 255))

    def test_white_and_black(self):
        self.assertEqual(rgb_to_hsv255(0, 0, 0)[2], 0)
        h, s, v = rgb_to_hsv255(255, 255, 255)
        self.assertEqual(s, 0)
        self.assertEqual(v, 255)

    def test_mint_green_reads_as_green_on_leds(self):
        h, s, v = rgb_to_hsv255(0x34, 0xC7, 0x59)
        self.assertGreaterEqual(h, 75)
        self.assertLessEqual(h, 90)
        self.assertEqual(s, 255)

    def test_teal_not_pulled_into_green(self):
        h, s, v = rgb_to_hsv255(0x00, 0xC7, 0xBE)
        self.assertGreater(h, 115)

    def test_led_green_ignores_low_sat(self):
        self.assertEqual(_led_green(96, 10), (96, 10))
        self.assertEqual(_led_green(20, 255), (20, 255))

    def test_heatmap_off_is_black(self):
        self.assertEqual(heatmap_rgb(0), (0, 0, 0))
        self.assertIsNone(heatmap_hex(0))

    def test_heatmap_hotter_with_more_hits(self):
        cold = heatmap_rgb(1)
        mid = heatmap_rgb(4)
        hot = heatmap_rgb(12)
        self.assertNotEqual(cold, (0, 0, 0))
        self.assertNotEqual(cold, mid)
        self.assertNotEqual(mid, hot)
        self.assertEqual(heatmap_rgb(99), heatmap_rgb(12))
        self.assertTrue(heatmap_hex(1).startswith("#"))
        # hue ramp: first hits are blue-ish, later hits red-ish
        self.assertGreater(cold[2], cold[0])
        self.assertGreater(hot[0], hot[2])

    def test_poll_div(self):
        self.assertEqual(poll_hz_from_div(0), 8000)
        self.assertEqual(poll_hz_from_div(3), 1000)
        self.assertEqual(poll_hz_from_div(6), 125)
        self.assertEqual(poll_hz_from_div(99), 125)
        self.assertEqual(poll_div_from_hz(8000), 0)
        self.assertEqual(poll_div_from_hz(1000), 3)
        self.assertEqual(poll_div_from_hz(900), 3)

    def test_rect_cells(self):
        r0, r1 = min(1, 3), max(1, 3)
        c0, c1 = min(2, 4), max(2, 4)
        cells = {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
        self.assertEqual(len(cells), 9)
        self.assertIn((1, 2), cells)
        self.assertIn((3, 4), cells)
