import unittest

from c100ctl.keycodes import (
    chars_to_taps,
    parse_combo,
    parse_macro,
    qmk_name,
    resolve_key_name,
)


class KeycodeTest(unittest.TestCase):
    def test_combo_super_return(self):
        c = parse_combo("Super+Return")
        self.assertEqual(c.modifiers, ("KEY_LEFTMETA",))
        self.assertEqual(c.key, "KEY_ENTER")
        self.assertIn("Super", c.as_text())

    def test_combo_ctrl_shift_c(self):
        c = parse_combo("ctrl+shift+c")
        self.assertEqual(c.key, "KEY_C")
        self.assertIn("KEY_LEFTCTRL", c.modifiers)
        self.assertIn("KEY_LEFTSHIFT", c.modifiers)
        self.assertEqual(c.as_text(), "Ctrl+Shift+C")

    def test_combo_dashes(self):
        c = parse_combo("alt-tab")
        self.assertEqual(c.key, "KEY_TAB")
        self.assertEqual(c.modifiers, ("KEY_LEFTALT",))

    def test_combo_mod_only(self):
        c = parse_combo("ctrl")
        self.assertEqual(c.key, "KEY_LEFTCTRL")
        self.assertEqual(c.modifiers, ())

    def test_empty_combo(self):
        with self.assertRaises(ValueError):
            parse_combo("")
        with self.assertRaises(ValueError):
            parse_combo("   ")

    def test_macro_copy_paste(self):
        steps = parse_macro("ctrl+c, delay:80, ctrl+v")
        kinds = [s.kind for s in steps]
        self.assertIn("delay", kinds)
        self.assertTrue(any(s.delay_ms == 80 for s in steps))

    def test_macro_text_down_up(self):
        steps = parse_macro("text:hi, down:shift, a, up:shift, wait:10, hello")
        kinds = [s.kind for s in steps]
        self.assertIn("text", kinds)
        self.assertIn("down", kinds)
        self.assertIn("up", kinds)
        self.assertTrue(any(s.text == "hi" for s in steps))
        self.assertTrue(any(s.delay_ms == 10 for s in steps))

    def test_macro_skips_empty(self):
        steps = parse_macro("a,,enter")
        self.assertGreaterEqual(len(steps), 2)

    def test_resolve_letters(self):
        self.assertEqual(resolve_key_name("a"), "KEY_A")
        self.assertEqual(resolve_key_name("F13"), "KEY_F13")
        self.assertEqual(resolve_key_name("KC_ESC"), "KEY_ESC")
        self.assertEqual(resolve_key_name("KEY_SPACE"), "KEY_SPACE")
        self.assertEqual(resolve_key_name("pageup"), "KEY_PAGEUP")

    def test_resolve_empty(self):
        with self.assertRaises(ValueError):
            resolve_key_name("")
        with self.assertRaises(ValueError):
            resolve_key_name("KC_NOTAREALKEY")

    def test_qmk_name(self):
        self.assertEqual(qmk_name(0x0004), "KC_A")
        self.assertEqual(qmk_name(0x001E), "KC_1")
        self.assertEqual(qmk_name(0x7702), "MACRO2")
        self.assertTrue(qmk_name(0xABCD).startswith("0x"))

    def test_chars_to_taps(self):
        taps = chars_to_taps("Hi!")
        self.assertEqual(taps[0], ("KEY_H", True))
        self.assertEqual(taps[1], ("KEY_I", False))
        self.assertEqual(taps[2], ("KEY_1", True))
        with self.assertRaises(ValueError):
            chars_to_taps("é")
