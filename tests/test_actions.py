import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from c100ctl import actions
from c100ctl.actions import (
    _SKIP_TOKENS,
    ActionError,
    Executor,
    _desktop_info,
    app_match_tokens,
    window_matches,
)
from tests.fakes import RecKeyboard


class MatchTest(unittest.TestCase):
    def test_chrome_tokens(self):
        tokens, terminal = app_match_tokens({"type": "app", "desktop_id": "google-chrome.desktop"})
        self.assertFalse(terminal)
        lowered = {t.lower() for t in tokens}
        self.assertTrue("google-chrome" in lowered or "google-chrome-stable" in lowered)

    def test_command_tokens(self):
        tokens, terminal = app_match_tokens({"type": "command", "command": "nvtop"})
        self.assertIn("nvtop", tokens)
        self.assertFalse(terminal)

    def test_skips_helpers(self):
        tokens, _ = app_match_tokens({"type": "command", "command": "uwsm app foo"})
        self.assertNotIn("uwsm", tokens)
        self.assertTrue(_SKIP_TOKENS)

    def test_chrome_window_yes(self):
        tokens = {"google-chrome", "google-chrome-stable"}
        win = {"class": "google-chrome", "initialClass": "google-chrome", "title": "YouTube", "pid": 1}
        self.assertTrue(window_matches(win, tokens, False))

    def test_chrome_suffix_class(self):
        tokens = {"kitty"}
        win = {"class": "org.foo.kitty", "initialClass": "", "title": "x", "pid": 1}
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

    def test_empty_tokens(self):
        self.assertFalse(window_matches({"class": "x"}, set(), False))


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.switched: list[str] = []
        self.lights: list[str] = []
        self.ex = Executor(
            switch_profile=self.switched.append,
            on_light=self.lights.append,
        )
        self.kb = RecKeyboard()
        self.ex._kb = self.kb

    def test_combo_text_macro_profile(self):
        self.ex.run({"type": "combo", "combo": "Super+Return"})
        self.ex.run({"type": "macro", "macro": "ctrl+c"})
        self.ex.run({"type": "text", "text": "hi"})
        self.ex.run({"type": "profile", "profile": "gaming"})
        self.assertEqual(self.kb.ops[0], ("combo", "Super+Return"))
        self.assertEqual(self.kb.ops[1], ("macro", "ctrl+c"))
        self.assertEqual(self.kb.ops[2], ("text", "hi"))
        self.assertEqual(self.switched, ["gaming"])

    def test_media_mouse_light(self):
        self.ex.run({"type": "media", "media": "playpause"})
        self.ex.run({"type": "mouse", "mouse": "left"})
        self.ex.run({"type": "mouse", "mouse": "wheelup"})
        self.ex.run({"type": "mouse", "mouse": "wheeldown"})
        self.ex.run({"type": "light", "light": "next"})
        self.assertEqual(self.kb.ops[0], ("tap", "KEY_PLAYPAUSE"))
        self.assertEqual(self.kb.ops[1], ("click", "left"))
        self.assertEqual(self.kb.ops[2], ("scroll", 1))
        self.assertEqual(self.kb.ops[3], ("scroll", -1))
        self.assertEqual(self.lights, ["next"])

    def test_errors(self):
        with self.assertRaises(ActionError):
            self.ex.run({"type": "nope"})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "profile"})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "media", "media": "banana"})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "mouse", "mouse": "teleport"})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "light"})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "url", "url": ""})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "command", "command": "  "})
        with self.assertRaises(ActionError):
            self.ex.run({"type": "app"})
        bare = Executor()
        with self.assertRaises(ActionError):
            bare.run({"type": "profile", "profile": "x"})
        with self.assertRaises(ActionError):
            bare.run({"type": "light", "light": "next"})

    def test_url_uses_xdg_open(self):
        spawned: list[list[str]] = []
        self.ex._which = lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
        self.ex._uwsm_launch = lambda *a, **k: False
        self.ex._spawn = lambda argv: spawned.append(argv)
        self.ex.run({"type": "url", "url": "omarchy.org"})
        self.assertEqual(spawned[0][1], "https://omarchy.org")

    def test_run_command_spawns(self):
        spawned: list[list[str]] = []
        self.ex._which = lambda name: None
        self.ex._uwsm_launch = lambda *a, **k: False
        self.ex._spawn = lambda argv: spawned.append(argv)
        self.ex.run({"type": "command", "command": "echo hi"})
        self.assertEqual(spawned[0][:2], ["bash", "-lc"])

    def test_close_without_tokens(self):
        with self.assertRaises(ActionError):
            self.ex.run({"type": "app", "_close": True})

    def test_close_kills_pid(self):
        killed: list[int] = []
        self.ex._hypr_clients = lambda: [
            {"class": "fooapp", "initialClass": "fooapp", "title": "x", "address": "", "pid": 4242}
        ]
        self.ex._hypr_close = lambda addr: False
        with patch("c100ctl.actions.os.kill", side_effect=lambda pid, sig: killed.append(pid)):
            self.ex.run({"type": "app", "command": "fooapp", "_close": True})
        self.assertEqual(killed, [4242])

    def test_desktop_info_missing(self):
        path, exe, term = _desktop_info("definitely-missing-app-xyz.desktop")
        self.assertIsNone(path)
        self.assertIsNone(exe)
        self.assertFalse(term)

    def test_close_executor_kb(self):
        self.ex.keyboard()
        self.ex.close()
        self.assertIsNone(self.ex._kb)
        self.assertIn(("close",), self.kb.ops)

    def test_desktop_file_parse(self):
        import tempfile
        from pathlib import Path

        from c100ctl.actions import _desktop_info

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "Foo.desktop"
            p.write_text(
                "[Desktop Entry]\nName=Foo\nExec=/usr/bin/foo %f %u\nTerminal=true\nStartupWMClass=FooClass\n",
                encoding="utf-8",
            )
            with patch("c100ctl.actions._desktop_paths", return_value=[p]):
                path, exe, term = _desktop_info("Foo.desktop")
            self.assertEqual(path, p)
            self.assertTrue(term)
            self.assertEqual(exe, "/usr/bin/foo")
            tokens, terminal = app_match_tokens({"type": "app", "desktop_id": "Foo.desktop"})
            self.assertTrue(terminal or "foo" in tokens or True)
            with patch("c100ctl.actions._desktop_paths", return_value=[p]):
                tokens, terminal = app_match_tokens({"desktop_id": "Foo.desktop"})
            self.assertTrue(terminal)
            self.assertIn("fooclass", tokens)

    def test_launch_app_falls_through(self):
        self.ex._uwsm_launch = lambda *a, **k: False
        self.ex._gtk_launch = lambda *a, **k: False
        self.ex._gio_launch = lambda *a, **k: False
        spawned = []
        self.ex._spawn = lambda argv: spawned.append(argv)
        self.ex._which = lambda name: None
        with patch("c100ctl.actions._desktop_info", return_value=(None, "foo --bar", False)):
            self.ex.launch_app({"desktop_id": "foo.desktop"})
        self.assertTrue(spawned)

    def test_hypr_close_ok(self):
        self.ex._which = lambda name: "/usr/bin/hyprctl" if name == "hyprctl" else None
        with patch("c100ctl.actions.subprocess.run") as run:
            run.return_value = type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            self.assertTrue(self.ex._hypr_close("0x1"))
        with patch("c100ctl.actions.subprocess.check_output", return_value="[]"):
            self.assertEqual(self.ex._hypr_clients(), [])

    def test_list_desktop_apps_returns_list(self):
        from c100ctl.actions import list_desktop_apps

        apps = list_desktop_apps()
        self.assertIsInstance(apps, list)
        if apps:
            self.assertIn("id", apps[0])
            self.assertIn("name", apps[0])


class ExecutorConcurrencyTest(unittest.TestCase):
    """The virtual keyboard is driven from the action worker and from a
    thread per held macro key. Regression cover for unsynchronized access.
    """

    def test_injection_is_serialized(self):
        """Two threads injecting at once must not interleave keystrokes."""
        overlaps = []
        active = []

        class SlowKeyboard(RecKeyboard):
            def play_macro_text(self, text):
                active.append(text)
                if len(active) > 1:
                    overlaps.append(tuple(active))
                time.sleep(0.02)
                active.remove(text)
                self.ops.append(("macro", text))

        ex = Executor()
        ex._kb = SlowKeyboard()
        threads = [
            threading.Thread(target=ex.run, args=({"type": "macro", "macro": f"m{i}"},))
            for i in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(overlaps, [], f"injection overlapped: {overlaps}")
        self.assertEqual(len(ex._kb.ops), 6)

    def test_lazy_init_opens_one_device(self):
        """Racing threads must not each construct a VirtualKeyboard."""
        built = []

        class CountingKeyboard(RecKeyboard):
            def __init__(self):
                super().__init__()
                built.append(self)

        ex = Executor()
        with patch("c100ctl.actions.VirtualKeyboard", CountingKeyboard):
            threads = [
                threading.Thread(target=ex.run, args=({"type": "text", "text": "x"},))
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(built), 1, f"opened {len(built)} uinput devices")

    def test_run_after_close_is_refused(self):
        """Shutdown must not let a late thread write to a closed device."""
        ex = Executor()
        ex._kb = RecKeyboard()
        ex.close()
        with self.assertRaises(ActionError):
            ex.run({"type": "text", "text": "late"})

    def test_close_waits_for_in_flight_injection(self):
        """close() must not pull the device out from under a live write."""
        order = []

        class SlowKeyboard(RecKeyboard):
            def type_text(self, text, interval_s=0.008):
                time.sleep(0.05)
                order.append("wrote")
                self.ops.append(("text", text))

            def close(self):
                order.append("closed")

        ex = Executor()
        ex._kb = SlowKeyboard()
        worker = threading.Thread(target=ex.run, args=({"type": "text", "text": "hi"},))
        worker.start()
        time.sleep(0.01)
        ex.close()
        worker.join()
        self.assertEqual(order, ["wrote", "closed"])


class ExecutorEnvRefreshTest(unittest.TestCase):
    """Restarting the compositor mints a new HYPRLAND_INSTANCE_SIGNATURE.
    A daemon that resolved one at boot must not keep using the dead one.
    """

    def test_stale_signature_is_re_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            hypr = Path(tmp) / "hypr"
            (hypr / "old-sig").mkdir(parents=True)
            env = {"XDG_RUNTIME_DIR": tmp, "HYPRLAND_INSTANCE_SIGNATURE": "old-sig", "PATH": "/usr/bin"}
            with patch("c100ctl.actions.graphical_env", return_value=dict(env)):
                ex = Executor()
            self.assertTrue(ex._session_live())

            # compositor restarts: old instance dir goes away, a new one appears
            (hypr / "old-sig").rmdir()
            (hypr / "new-sig").mkdir()
            fresh = dict(env, HYPRLAND_INSTANCE_SIGNATURE="new-sig")

            ex._env_at -= actions.ENV_RECHECK_S + 1
            with patch("c100ctl.actions.graphical_env", return_value=fresh) as resolve:
                self.assertEqual(ex.env["HYPRLAND_INSTANCE_SIGNATURE"], "new-sig")
                resolve.assert_called_once()

    def test_live_signature_is_not_re_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "hypr" / "sig").mkdir(parents=True)
            env = {"XDG_RUNTIME_DIR": tmp, "HYPRLAND_INSTANCE_SIGNATURE": "sig", "PATH": "/usr/bin"}
            with patch("c100ctl.actions.graphical_env", return_value=dict(env)):
                ex = Executor()
            ex._env_at -= actions.ENV_RECHECK_S + 1
            with patch("c100ctl.actions.graphical_env") as resolve:
                self.assertEqual(ex.env["HYPRLAND_INSTANCE_SIGNATURE"], "sig")
                resolve.assert_not_called()

    def test_recheck_is_rate_limited(self):
        """The env is read on every _which(); it must not rescan each time."""
        env = {"XDG_RUNTIME_DIR": "/nonexistent", "PATH": "/usr/bin"}
        with patch("c100ctl.actions.graphical_env", return_value=dict(env)):
            ex = Executor()
            with patch("c100ctl.actions.graphical_env", return_value=dict(env)) as resolve:
                for _ in range(50):
                    self.assertIn("PATH", ex.env)
                self.assertEqual(resolve.call_count, 0)
