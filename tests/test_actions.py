import unittest

from c100ctl.actions import app_match_tokens, window_matches


class MatchTest(unittest.TestCase):
    def test_chrome_tokens(self):
        tokens, terminal = app_match_tokens({"type": "app", "desktop_id": "google-chrome.desktop"})
        self.assertFalse(terminal)
        lowered = {t.lower() for t in tokens}
        self.assertTrue("google-chrome" in lowered or "google-chrome-stable" in lowered)

    def test_chrome_window_yes(self):
        tokens = {"google-chrome", "google-chrome-stable"}
        win = {"class": "google-chrome", "initialClass": "google-chrome", "title": "YouTube", "pid": 1}
        self.assertTrue(window_matches(win, tokens, False))

    def test_chrome_does_not_close_pwa(self):
        tokens = {"google-chrome", "google-chrome-stable"}
        win = {
            "class": "chrome-web.whatsapp.com__-Default",
            "initialClass": "chrome-web.whatsapp.com__-Default",
            "title": "web.whatsapp.com",
            "pid": 1,
        }
        self.assertFalse(window_matches(win, tokens, False))

    def test_nvtop_title(self):
        tokens = {"nvtop"}
        win = {"class": "com.mitchellh.ghostty", "title": "nvtop", "initialTitle": "nvtop", "pid": 2}
        self.assertTrue(window_matches(win, tokens, True))
        self.assertFalse(window_matches(win, tokens, False))
