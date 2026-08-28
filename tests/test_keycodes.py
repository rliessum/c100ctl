import unittest

from c100ctl.keycodes import parse_combo, parse_macro, qmk_name, resolve_key_name


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

    def test_macro_copy_paste(self):
        steps = parse_macro("ctrl+c, delay:80, ctrl+v")
        kinds = [s.kind for s in steps]
        self.assertIn("delay", kinds)
        self.assertTrue(any(s.delay_ms == 80 for s in steps))

    def test_resolve_letters(self):
        self.assertEqual(resolve_key_name("a"), "KEY_A")
        self.assertEqual(resolve_key_name("F13"), "KEY_F13")
        self.assertEqual(resolve_key_name("KC_ESC"), "KEY_ESC")

    def test_qmk_name(self):
        self.assertEqual(qmk_name(0x0004), "KC_A")
        self.assertEqual(qmk_name(0x001E), "KC_1")
