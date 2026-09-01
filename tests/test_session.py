import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from c100ctl.session import (
    graphical_env,
    gtk_argv,
    hyprctl_available,
    prepare_gtk_environment,
)


class SessionTest(unittest.TestCase):
    def test_fills_defaults(self):
        env = graphical_env({"HOME": "/tmp", "PATH": "/bin", "XDG_RUNTIME_DIR": "/tmp"})
        self.assertIn("/usr/bin", env["PATH"])
        self.assertTrue(any(p.endswith(".local/bin") for p in env["PATH"].split(":")))
        if sys.platform == "darwin":
            self.assertNotEqual(env.get("XDG_CURRENT_DESKTOP"), "Hyprland")
            self.assertIn("/opt/homebrew/bin", env["PATH"])
        else:
            self.assertEqual(env["XDG_CURRENT_DESKTOP"], "Hyprland")
            self.assertEqual(env["DISPLAY"], ":0")

    def test_wayland_and_hypr_from_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "wayland-1").touch()
            hypr = Path(tmp) / "hypr" / "sig-abc"
            hypr.mkdir(parents=True)
            Path(tmp, "bus").touch()
            env = graphical_env({"HOME": tmp, "PATH": "/bin", "XDG_RUNTIME_DIR": tmp})
            self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-1")
            self.assertEqual(env["HYPRLAND_INSTANCE_SIGNATURE"], "sig-abc")
            self.assertTrue(env["DBUS_SESSION_BUS_ADDRESS"].endswith("/bus"))

    def test_hypr_signature_uses_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            hypr = Path(tmp) / "hypr"
            old = hypr / "zzzz_stale"
            new = hypr / "aaaa_live"
            old.mkdir(parents=True)
            time.sleep(0.02)
            new.mkdir()
            env = graphical_env({"HOME": tmp, "PATH": "/bin", "XDG_RUNTIME_DIR": tmp})
            self.assertEqual(env["HYPRLAND_INSTANCE_SIGNATURE"], "aaaa_live")

    def test_hyprctl_available(self):
        self.assertFalse(hyprctl_available({"PATH": "/nope", "XDG_RUNTIME_DIR": "/nope"}))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "hypr" / "s1").mkdir(parents=True)
            fake = Path(tmp) / "hyprctl"
            fake.write_text("#!/bin/sh\n")
            fake.chmod(0o755)
            env = {
                "PATH": tmp,
                "XDG_RUNTIME_DIR": tmp,
                "HOME": tmp,
            }
            self.assertTrue(hyprctl_available(env))


class GtkHostEnvTest(unittest.TestCase):
    def test_gtk_argv_strips_gui_token(self):
        self.assertEqual(gtk_argv(["/usr/bin/c100ctl", "gui"]), ["/usr/bin/c100ctl"])
        self.assertEqual(gtk_argv(["__main__.py", "--gui"]), ["__main__.py"])
        self.assertEqual(gtk_argv(["c100ctl"]), ["c100ctl"])
        self.assertEqual(gtk_argv([]), ["c100ctl"])

    def test_prepare_gtk_environment_prepends_homebrew_share(self):
        env = {
            "XDG_DATA_DIRS": "/usr/local/share:/usr/share:/Applications/Ghostty.app/share",
            "GI_TYPELIB_PATH": "/old/typelib",
        }
        with (
            patch("c100ctl.session.is_macos", return_value=True),
            patch("c100ctl.session.homebrew_prefixes", return_value=["/opt/homebrew"]),
        ):
            out = prepare_gtk_environment(env)
        self.assertTrue(out["XDG_DATA_DIRS"].startswith("/opt/homebrew/share:"))
        self.assertIn("/Applications/Ghostty.app/share", out["XDG_DATA_DIRS"])
        self.assertTrue(out["GI_TYPELIB_PATH"].startswith("/opt/homebrew/lib/girepository-1.0:"))
        self.assertIn("/opt/homebrew/lib", out["DYLD_FALLBACK_LIBRARY_PATH"])

    def test_prepare_gtk_environment_noop_on_linux(self):
        env = {"XDG_DATA_DIRS": "/usr/share"}
        with patch("c100ctl.session.is_macos", return_value=False):
            out = prepare_gtk_environment(env)
        self.assertEqual(out["XDG_DATA_DIRS"], "/usr/share")
        self.assertNotIn("GI_TYPELIB_PATH", out)
