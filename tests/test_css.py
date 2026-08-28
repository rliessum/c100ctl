import unittest

from c100ctl.css import APP_CSS


class CssTest(unittest.TestCase):
    def test_has_keycap_rules(self):
        self.assertIn(".keycap", APP_CSS)
        self.assertIn("bound-app", APP_CSS)
        self.assertIn("zone-0", APP_CSS)
