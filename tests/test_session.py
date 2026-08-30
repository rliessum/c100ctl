import tempfile
import time
import unittest
from pathlib import Path

from c100ctl.session import graphical_env, hyprctl_available


class SessionTest(unittest.TestCase):
    def test_fills_defaults(self):
        env = graphical_env({"HOME": "/tmp", "PATH": "/bin", "XDG_RUNTIME_DIR": "/tmp"})
        self.assertEqual(env["XDG_CURRENT_DESKTOP"], "Hyprland")
        self.assertEqual(env["DISPLAY"], ":0")
        self.assertIn("/usr/bin", env["PATH"])
        self.assertTrue(any(p.endswith(".local/bin") for p in env["PATH"].split(":")))

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
