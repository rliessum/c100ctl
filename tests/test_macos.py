"""macOS host paths — run on every OS with Quartz/IOKit mocked out."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from c100ctl.identity import identity_hid_map
from c100ctl.inject_macos import VirtualKeyboard, virtual_keycode
from c100ctl.pad_macos import PadGrab, matching_criteria
from c100ctl.via import UNSUPPORTED, _strip_report_id
from tests.fakes import RecKeyboard


class ViaReportIdTest(unittest.TestCase):
    def test_passthrough(self):
        raw = bytes([0x01, 0x00, 0x0C]) + bytes(29)
        self.assertEqual(_strip_report_id(raw, 0x01)[0], 0x01)

    def test_strip_zero_prefix(self):
        raw = bytes([0x00, 0x01, 0x00, 0x0C]) + bytes(28)
        self.assertEqual(_strip_report_id(raw, 0x01)[0], 0x01)

    def test_unsupported_kept(self):
        raw = bytes([UNSUPPORTED]) + bytes(31)
        self.assertEqual(_strip_report_id(raw, 0x01)[0], UNSUPPORTED)

    def test_empty(self):
        self.assertEqual(_strip_report_id(b"", 0x01), b"")


class InjectMacosTest(unittest.TestCase):
    def setUp(self):
        self.kb = VirtualKeyboard()

    def tearDown(self):
        self.kb.close()

    def test_virtual_keycode_map(self):
        self.assertEqual(virtual_keycode("KEY_A"), 0x00)
        self.assertEqual(virtual_keycode("A"), 0x00)
        self.assertEqual(virtual_keycode("KEY_LEFTMETA"), 0x37)
        self.assertEqual(virtual_keycode("KEY_ENTER"), 0x24)
        with self.assertRaises(ValueError):
            virtual_keycode("NOT_A_KEY")

    def test_tap_combo_text_macro_mouse(self):
        with (
            patch("c100ctl.inject_macos.post_key") as key,
            patch("c100ctl.inject_macos.post_media") as media,
            patch("c100ctl.inject_macos.post_mouse") as mouse,
            patch("c100ctl.inject_macos.post_scroll") as scroll,
            patch("c100ctl.inject_macos.post_open") as opener,
            patch("c100ctl.inject_macos.post_screenshot") as shot,
        ):
            self.kb.tap("KEY_A")
            self.kb.play_combo_text("ctrl+c")
            self.kb.type_text("Hi")
            self.kb.play_macro_text("delay:1, text:a, down:shift, up:shift, enter")
            self.kb.click_mouse("left")
            self.kb.scroll(-1)
            self.kb.tap_named("KEY_PLAYPAUSE")
            self.kb.tap_named("KEY_WWW")
            self.kb.tap_named("KEY_SYSRQ")
            with self.assertRaises(ValueError):
                self.kb.click_mouse("sideways")
            with self.assertRaises(ValueError):
                from c100ctl.keycodes import MacroStep

                self.kb.play_macro([MacroStep("nope")])
        self.assertTrue(key.called)
        self.assertTrue(mouse.called)
        self.assertTrue(scroll.called)
        self.assertTrue(media.called)
        self.assertTrue(opener.called)
        self.assertTrue(shot.called)


class PadMacosTest(unittest.TestCase):
    def setUp(self):
        self.hits = []
        self.pad = PadGrab([], on_key=lambda r, c, p: self.hits.append((r, c, p)))
        # KC_A is 0x04 — identity map includes A on a programmable cell.
        self.a_usage = 0x04
        self.a_cell = identity_hid_map()[self.a_usage]

    def test_press_and_release(self):
        self.pad._handle_usage(self.a_usage, True)
        self.pad._handle_usage(self.a_usage, False)
        self.assertEqual(self.hits, [(*self.a_cell, True), (*self.a_cell, False)])

    def test_debounce_duplicate(self):
        self.pad._handle_usage(self.a_usage, True)
        self.pad._handle_usage(self.a_usage, True)
        self.assertEqual(self.hits, [(*self.a_cell, True)])

    def test_matrix_fallback(self):
        via = MagicMock()
        via.matrix_pressed.return_value = [(8, 8)]
        self.pad.via = via
        self.pad._handle_usage(0x01, True)  # error rollover, ignored
        unknown = 0x90
        while unknown in identity_hid_map():
            unknown += 1
        self.pad._handle_usage(unknown, True)
        self.assertEqual(self.hits, [(8, 8, True)])

    def test_matrix_fallback_release(self):
        via = MagicMock()
        via.matrix_pressed.return_value = [(8, 8)]
        self.pad.via = via
        unknown = 0x90
        self.pad._handle_usage(unknown, True)
        via.matrix_pressed.return_value = []
        self.pad._handle_usage(unknown, False)
        self.assertEqual(self.hits, [(8, 8, True), (8, 8, False)])
        via.matrix_pressed.assert_called_once()

    def test_unmapped_without_via(self):
        self.pad._handle_usage(0x90, True)
        self.assertEqual(self.hits, [])

    def test_on_key_exception_swallowed(self):
        self.pad.on_key = MagicMock(side_effect=RuntimeError("boom"))
        self.pad._handle_usage(self.a_usage, True)

    def test_matrix_poll_emits_edges(self):
        via = MagicMock()
        via.matrix_pressed.return_value = [(2, 3)]
        self.pad.via = via
        prev: set[tuple[int, int]] = set()
        self.pad._poll_matrix(prev)
        self.assertEqual(self.hits, [(2, 3, True)])
        via.matrix_pressed.return_value = []
        self.pad._poll_matrix(prev)
        self.assertEqual(self.hits[-1], (2, 3, False))

    def test_start_without_iokit_or_via_raises(self):
        with patch.object(self.pad, "_try_iokit", return_value=False):
            with self.assertRaises(RuntimeError):
                self.pad.start()

    def test_start_falls_back_to_matrix(self):
        via = MagicMock()
        via.matrix_pressed.return_value = []
        pad = PadGrab([], via=via, on_key=lambda *a: None)
        with patch.object(pad, "_try_iokit", return_value=False):
            pad.start()
            self.assertEqual(pad._mode, "matrix")
            pad.stop()

    def test_matrix_poll_error_and_debounce(self):
        via = MagicMock()
        via.matrix_pressed.side_effect = RuntimeError("x")
        self.pad.via = via
        prev: set[tuple[int, int]] = set()
        self.pad._poll_matrix(prev)
        self.assertEqual(self.hits, [])
        self.pad.via = None
        self.pad._poll_matrix(prev)
        self.pad._emit(self.a_cell, True)
        self.pad._emit(self.a_cell, True)
        self.assertEqual(self.hits, [(*self.a_cell, True)])

    def test_matching_criteria_is_c100_keyboard(self):
        crit = matching_criteria()
        self.assertEqual(len(crit), 2)
        for item in crit:
            as_dict = dict(item)
            self.assertEqual(as_dict["VendorID"], 0x3434)
            self.assertEqual(as_dict["ProductID"], 0x042C)


class MacosActionsTest(unittest.TestCase):
    def test_open_url_uses_open(self):
        from c100ctl.actions import Executor

        ex = Executor()
        spawned: list[list[str]] = []
        ex._kb = RecKeyboard()
        ex._which = lambda name: "/usr/bin/open" if name == "open" else None
        ex._spawn = lambda argv: spawned.append(argv)
        with patch("c100ctl.actions.is_macos", return_value=True):
            ex.run({"type": "url", "url": "omarchy.org"})
        self.assertEqual(spawned[0], ["/usr/bin/open", "https://omarchy.org"])

    def test_macos_launch_bundle_and_app(self):
        from c100ctl.actions import Executor

        ex = Executor()
        spawned: list[list[str]] = []
        ex._spawn = lambda argv: spawned.append(argv)
        with patch("c100ctl.actions.is_macos", return_value=True):
            self.assertTrue(ex._macos_launch({"desktop_id": "com.apple.Safari"}))
            self.assertTrue(ex._macos_launch({"desktop_id": "Kitty.app"}))
            self.assertTrue(ex._macos_launch({"desktop_id": "Music"}))
        self.assertEqual(spawned[0], ["open", "-b", "com.apple.Safari"])
        self.assertEqual(spawned[1], ["open", "-a", "Kitty.app"])
        self.assertEqual(spawned[2], ["open", "-a", "Music"])

    def test_macos_close_quits_matching_process(self):
        from c100ctl.actions import Executor

        ex = Executor()
        with (
            patch("c100ctl.actions.is_macos", return_value=True),
            patch(
                "c100ctl.actions.subprocess.check_output",
                return_value="Safari, Terminal, Finder",
            ),
            patch("c100ctl.actions.subprocess.run") as run,
        ):
            run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            ex.close_app({"type": "app", "desktop_id": "com.apple.Safari"})
        self.assertTrue(run.called)
        self.assertIn("Safari", run.call_args[0][0][-1])

    def test_bundle_tokens(self):
        from c100ctl.actions import app_match_tokens

        with patch("c100ctl.actions.is_macos", return_value=True):
            tokens, terminal = app_match_tokens({"desktop_id": "com.apple.Safari"})
        self.assertFalse(terminal)
        self.assertIn("safari", tokens)
        self.assertIn("com.apple.safari", tokens)

    def _write_app(self, root: Path, folder: str, plist: bytes) -> None:
        info = root / folder / "Contents"
        info.mkdir(parents=True)
        (info / "Info.plist").write_bytes(plist)

    def test_scan_macos_apps_from_plist(self):
        from c100ctl.actions import _scan_macos_apps

        with tempfile.TemporaryDirectory() as tmp:
            self._write_app(
                Path(tmp),
                "FakeApp.app",
                b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>dev.example.FakeApp</string>
  <key>CFBundleName</key><string>FakeApp</string>
</dict></plist>
""",
            )
            with patch("c100ctl.actions._macos_app_roots", return_value=[Path(tmp)]):
                apps = _scan_macos_apps()
        self.assertEqual(apps[0]["id"], "dev.example.FakeApp")
        self.assertEqual(apps[0]["name"], "FakeApp")

    def test_scan_macos_apps_skips_broken_plists(self):
        from c100ctl.actions import _load_macos_plist, _scan_macos_apps

        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>dev.example.Good</string>
  <key>CFBundleName</key><string>Good</string>
</dict></plist>
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_app(root, "Good.app", xml)
            # SteamVR-style trailing NULs used to raise ExpatError and kill the GUI.
            self._write_app(root, "SteamVR.app", xml + b"\x00\x00")
            self._write_app(root, "Junk.app", b"not a plist at all")
            (root / "Empty.app" / "Contents").mkdir(parents=True)
            with patch("c100ctl.actions._macos_app_roots", return_value=[root]):
                apps = _scan_macos_apps()
            ids = {a["id"] for a in apps}
            self.assertIn("dev.example.Good", ids)
            steam = _load_macos_plist(root / "SteamVR.app" / "Contents" / "Info.plist")
            self.assertEqual(steam["CFBundleName"], "Good")
            self.assertEqual(_load_macos_plist(root / "Junk.app" / "Contents" / "Info.plist"), {})
            self.assertEqual(_load_macos_plist(root / "Empty.app" / "Contents" / "Info.plist"), {})
            self.assertEqual(_load_macos_plist(root / "Missing.app" / "Contents" / "Info.plist"), {})
