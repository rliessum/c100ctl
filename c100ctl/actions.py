"""Run a binding: app, command, combo, macro, text, profile."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .session import graphical_env, hyprctl_available
from .uinput_kb import VirtualKeyboard

log = logging.getLogger("c100ctl.actions")


class ActionError(RuntimeError):
    pass


class Executor:
    def __init__(self, switch_profile: Callable[[str], None] | None = None):
        self.env = graphical_env()
        self._kb: VirtualKeyboard | None = None
        self.switch_profile = switch_profile

    def keyboard(self) -> VirtualKeyboard:
        if self._kb is None:
            self._kb = VirtualKeyboard()
        return self._kb

    def close(self) -> None:
        if self._kb is not None:
            self._kb.close()
            self._kb = None

    def run(self, binding: dict[str, Any]) -> None:
        kind = binding.get("type")
        if kind == "app":
            self.launch_app(binding)
        elif kind == "command":
            self.run_command(binding.get("command", ""))
        elif kind == "combo":
            self.keyboard().play_combo_text(binding.get("combo", ""))
        elif kind == "macro":
            self.keyboard().play_macro_text(binding.get("macro", ""))
        elif kind == "text":
            self.keyboard().type_text(binding.get("text", ""))
        elif kind == "profile":
            name = binding.get("profile")
            if not name:
                raise ActionError("profile binding missing name")
            if not self.switch_profile:
                raise ActionError("profile switching is not available")
            self.switch_profile(name)
        else:
            raise ActionError(f"unknown binding type {kind!r}")

    def launch_app(self, binding: dict[str, Any]) -> None:
        desktop_id = (binding.get("desktop_id") or "").strip()
        command = (binding.get("command") or "").strip()
        if desktop_id:
            if desktop_id.endswith(".desktop"):
                ident = desktop_id
            else:
                ident = f"{desktop_id}.desktop"
            exec_line = _desktop_exec(ident)
            if self._hypr_exec(exec_line or ident):
                return
            if self._gtk_launch(ident):
                return
            if exec_line:
                self.run_command(exec_line)
                return
            raise ActionError(f"could not launch {ident}")
        if command:
            self.run_command(command)
            return
        raise ActionError("app binding needs desktop_id or command")

    def run_command(self, command: str) -> None:
        command = command.strip()
        if not command:
            raise ActionError("empty command")
        subprocess.Popen(
            ["bash", "-lc", command],
            env=self.env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _gtk_launch(self, desktop_id: str) -> bool:
        gtk_launch = shutil.which("gtk-launch", path=self.env.get("PATH"))
        if not gtk_launch:
            return False
        try:
            subprocess.Popen(
                [gtk_launch, desktop_id],
                env=self.env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as e:
            log.warning("gtk-launch failed: %s", e)
            return False

    def _hypr_exec(self, command: str) -> bool:
        if not command or not hyprctl_available(self.env):
            return False
        try:
            subprocess.Popen(
                ["hyprctl", "dispatch", "exec", command],
                env=self.env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as e:
            log.warning("hyprctl exec failed: %s", e)
            return False


def _desktop_exec(desktop_id: str) -> str | None:
    name = desktop_id if desktop_id.endswith(".desktop") else f"{desktop_id}.desktop"
    search = [
        Path.home() / ".local/share/applications" / name,
        Path("/usr/local/share/applications") / name,
        Path("/usr/share/applications") / name,
    ]
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        search.insert(0, Path(xdg) / "applications" / name)
    for path in search:
        if not path.is_file():
            continue
        exec_line = None
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Exec="):
                    exec_line = line[5:].strip()
                    break
        except OSError:
            continue
        if not exec_line:
            continue
        # Desktop Exec field codes.
        for code in ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%k", "%v", "%m"):
            exec_line = exec_line.replace(code, "")
        exec_line = exec_line.replace("%c", path.stem).replace("%i", "")
        return exec_line.strip()
    return None


def list_desktop_apps() -> list[dict[str, str]]:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError):
        return _scan_desktop_files()

    apps = []
    seen: set[str] = set()
    for info in Gio.AppInfo.get_all():
        if not info.should_show():
            continue
        ident = info.get_id() or ""
        if not ident or ident in seen:
            continue
        seen.add(ident)
        apps.append(
            {
                "id": ident,
                "name": info.get_name() or ident,
                "command": info.get_commandline() or "",
                "icon": info.get_icon().to_string() if info.get_icon() else "",
            }
        )
    apps.sort(key=lambda a: a["name"].lower())
    return apps


def _scan_desktop_files() -> list[dict[str, str]]:
    apps: list[dict[str, str]] = []
    seen: set[str] = set()
    dirs = [
        Path.home() / ".local/share/applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    ]
    for folder in dirs:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.desktop"):
            if path.name in seen:
                continue
            data: dict[str, str] = {}
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if "=" not in line or line.startswith("#"):
                        continue
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
            except OSError:
                continue
            if data.get("NoDisplay", "").lower() == "true":
                continue
            if data.get("Hidden", "").lower() == "true":
                continue
            if "Desktop Entry" not in path.read_text(encoding="utf-8", errors="replace")[:40] and not data.get("Name"):
                continue
            seen.add(path.name)
            apps.append(
                {
                    "id": path.name,
                    "name": data.get("Name", path.stem),
                    "command": data.get("Exec", ""),
                    "icon": data.get("Icon", ""),
                }
            )
    apps.sort(key=lambda a: a["name"].lower())
    return apps
