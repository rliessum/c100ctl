"""Run a binding: app, command, combo, macro, text, profile, url, media, mouse, light."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable

from .catalog import media_evdev
from .session import graphical_env
from .uinput_kb import VirtualKeyboard

log = logging.getLogger("c100ctl.actions")


class ActionError(RuntimeError):
    pass


class Executor:
    def __init__(
        self,
        switch_profile: Callable[[str], None] | None = None,
        on_light: Callable[[str], None] | None = None,
    ):
        self.env = graphical_env()
        self._kb: VirtualKeyboard | None = None
        self.switch_profile = switch_profile
        self.on_light = on_light

    def keyboard(self) -> VirtualKeyboard:
        if self._kb is None:
            self._kb = VirtualKeyboard()
        return self._kb

    def close(self) -> None:
        if self._kb is not None:
            self._kb.close()
            self._kb = None

    def run(self, binding: dict[str, Any]) -> None:
        if binding.get("_close"):
            self.close_app(binding)
            return
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
        elif kind == "url":
            self.open_url(binding.get("url") or binding.get("command") or "")
        elif kind == "media":
            self.media(binding.get("media") or "")
        elif kind == "mouse":
            self.mouse(binding.get("mouse") or "")
        elif kind == "light":
            action = (binding.get("light") or "").strip()
            if not action:
                raise ActionError("light binding missing action")
            if not self.on_light:
                raise ActionError("lighting control is not available")
            self.on_light(action)
        else:
            raise ActionError(f"unknown binding type {kind!r}")

    def open_url(self, url: str) -> None:
        url = url.strip()
        if not url:
            raise ActionError("empty url")
        if "://" not in url:
            url = "https://" + url
        opener = self._which("xdg-open")
        if not opener:
            raise ActionError("xdg-open is not available")
        if not self._uwsm_launch(opener, extra=[opener, url]):
            self._spawn([opener, url])

    def media(self, name: str) -> None:
        key = media_evdev(name.strip().lower())
        if not key:
            raise ActionError(f"unknown media action {name!r}")
        self.keyboard().tap_named(key)

    def mouse(self, name: str) -> None:
        name = name.strip().lower()
        if name in {"wheelup", "scrollup"}:
            self.keyboard().scroll(1)
            return
        if name in {"wheeldown", "scrolldown"}:
            self.keyboard().scroll(-1)
            return
        try:
            self.keyboard().click_mouse(name)
        except ValueError as e:
            raise ActionError(str(e)) from e

    def launch_app(self, binding: dict[str, Any]) -> None:
        desktop_id = (binding.get("desktop_id") or "").strip()
        command = (binding.get("command") or "").strip()
        if desktop_id:
            ident = desktop_id if desktop_id.endswith(".desktop") else f"{desktop_id}.desktop"
            path, exec_line, terminal = _desktop_info(ident)
            if self._uwsm_launch(path or ident, terminal=terminal):
                return
            if not terminal and self._gtk_launch(ident):
                return
            if path and self._gio_launch(path):
                return
            if exec_line:
                if terminal:
                    self._launch_tui(exec_line)
                else:
                    self.run_command(exec_line)
                return
            raise ActionError(f"could not launch {ident}")
        if command:
            if self._omarchy_terminal_alias(command):
                return
            self.run_command(command)
            return
        raise ActionError("app binding needs desktop_id or command")

    def run_command(self, command: str) -> None:
        command = command.strip()
        if not command:
            raise ActionError("empty command")
        if self._omarchy_terminal_alias(command):
            return
        argv = ["bash", "-lc", command]
        if not self._uwsm_launch(argv[0], extra=argv, terminal=False):
            self._spawn(argv)

    def _which(self, name: str) -> str | None:
        return shutil.which(name, path=self.env.get("PATH"))

    def _spawn(self, argv: list[str]) -> None:
        log.info("spawn %s", argv)
        subprocess.Popen(argv, env=self.env, start_new_session=True)

    def _uwsm_launch(self, target: str | Path, terminal: bool = False, extra: list[str] | None = None) -> bool:
        uwsm = self._which("uwsm")
        if not uwsm:
            return False
        argv = [uwsm, "app"]
        if terminal:
            argv.append("-T")
        if extra:
            argv.append("--")
            argv.extend(extra)
        else:
            argv.append(str(target))
        try:
            self._spawn(argv)
            return True
        except OSError as e:
            log.warning("uwsm app failed: %s", e)
            return False

    def _gtk_launch(self, desktop_id: str) -> bool:
        gtk_launch = self._which("gtk-launch")
        if not gtk_launch:
            return False
        try:
            self._spawn([gtk_launch, desktop_id])
            return True
        except OSError as e:
            log.warning("gtk-launch failed: %s", e)
            return False

    def _gio_launch(self, path: Path) -> bool:
        gio = self._which("gio")
        if not gio:
            return False
        try:
            self._spawn([gio, "launch", str(path)])
            return True
        except OSError as e:
            log.warning("gio launch failed: %s", e)
            return False

    def _launch_tui(self, command: str) -> None:
        if self._uwsm_launch(command, terminal=True, extra=["bash", "-lc", command]):
            return
        term = self._which("xdg-terminal-exec") or self._which("kitty") or self._which("alacritty")
        if not term:
            raise ActionError(f"no terminal to launch {command!r}")
        if term.endswith("xdg-terminal-exec"):
            self._spawn([term, "bash", "-lc", command])
        else:
            self._spawn([term, "-e", "bash", "-lc", command])

    def close_app(self, binding: dict[str, Any]) -> None:
        tokens, terminal = app_match_tokens(binding)
        if not tokens:
            raise ActionError("cannot close: no app identity")
        clients = self._hypr_clients()
        hits = [c for c in clients if window_matches(c, tokens, terminal)]
        if not hits:
            log.info("no open window matching %s", sorted(tokens))
            return
        closed = 0
        for win in hits:
            addr = str(win.get("address") or "")
            if addr and self._hypr_close(addr):
                closed += 1
                continue
            pid = int(win.get("pid") or 0)
            if pid > 1:
                try:
                    os.kill(pid, signal.SIGTERM)
                    closed += 1
                except OSError as e:
                    log.warning("kill %s: %s", pid, e)
        log.info("closed %s window(s) for %s", closed, sorted(tokens))

    def _hypr_clients(self) -> list[dict[str, Any]]:
        hyprctl = self._which("hyprctl")
        if not hyprctl:
            return []
        try:
            raw = subprocess.check_output(
                [hyprctl, "clients", "-j"],
                env=self.env,
                text=True,
                timeout=2,
            )
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            log.warning("hyprctl clients: %s", e)
            return []

    def _hypr_close(self, address: str) -> bool:
        hyprctl = self._which("hyprctl")
        if not hyprctl or not address:
            return False
        expr = f'hl.dsp.window.close({{ window = "address:{address}" }})'
        try:
            r = subprocess.run(
                [hyprctl, "dispatch", expr],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("hyprctl close: %s", e)
            return False
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "error" not in out.lower():
            return True
        log.warning("hyprctl close %s: %s", address, out.strip())
        return False

    def _omarchy_terminal_alias(self, command: str) -> bool:
        token = command.strip().split()[0] if command.strip() else ""
        if not token:
            return False
        helper = self._which(f"omarchy-launch-terminal-{token}")
        if helper:
            self._spawn([helper, *command.strip().split()[1:]])
            return True
        return False


def _desktop_paths(desktop_id: str) -> list[Path]:
    name = desktop_id if desktop_id.endswith(".desktop") else f"{desktop_id}.desktop"
    search = [
        Path.home() / ".local/share/applications" / name,
        Path("/usr/local/share/applications") / name,
        Path("/usr/share/applications") / name,
    ]
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        search.insert(0, Path(xdg) / "applications" / name)
    return search


def _desktop_info(desktop_id: str) -> tuple[Path | None, str | None, bool]:
    """Return (desktop path, Exec line, Terminal=true)."""
    for path in _desktop_paths(desktop_id):
        if not path.is_file():
            continue
        exec_line = None
        terminal = False
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Exec=") and exec_line is None:
                    exec_line = line[5:].strip()
                elif line.startswith("Terminal="):
                    terminal = line.split("=", 1)[1].strip().lower() in {"true", "1", "yes"}
        except OSError:
            continue
        if not exec_line:
            continue
        for code in ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%k", "%v", "%m"):
            exec_line = exec_line.replace(code, "")
        exec_line = exec_line.replace("%c", path.stem).replace("%i", "").strip()
        return path, exec_line, terminal
    return None, None, False


def _desktop_exec(desktop_id: str) -> str | None:
    return _desktop_info(desktop_id)[1]


_SKIP_TOKENS = {
    "bash",
    "sh",
    "env",
    "uwsm",
    "flatpak",
    "python",
    "python3",
    "perl",
    "ruby",
    "app",
    "gtk-launch",
    "gio",
}


def app_match_tokens(binding: dict[str, Any]) -> tuple[set[str], bool]:
    """Window-class / title tokens used to find a launched app."""
    tokens: set[str] = set()
    terminal = False
    desktop_id = (binding.get("desktop_id") or "").strip()
    command = (binding.get("command") or "").strip()
    if desktop_id:
        ident = desktop_id if desktop_id.endswith(".desktop") else f"{desktop_id}.desktop"
        tokens.add(Path(ident).stem.lower())
        path, exec_line, terminal = _desktop_info(ident)
        if path and path.is_file():
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("StartupWMClass="):
                        tokens.add(line.split("=", 1)[1].strip().lower())
            except OSError:
                pass
        if exec_line:
            exe = exec_line.split()[0]
            tokens.add(Path(exe).name.lower())
            tokens.add(Path(exe).stem.lower())
    if command:
        exe = command.split()[0]
        tokens.add(Path(exe).name.lower())
        tokens.add(Path(exe).stem.lower())
    tokens = {t for t in tokens if t and t not in _SKIP_TOKENS}
    return tokens, terminal


def window_matches(client: dict[str, Any], tokens: set[str], terminal: bool = False) -> bool:
    cls = (client.get("class") or "").lower()
    icls = (client.get("initialClass") or "").lower()
    title = client.get("title") or ""
    ititle = client.get("initialTitle") or ""
    for tok in tokens:
        t = tok.lower()
        if not t:
            continue
        if cls == t or icls == t:
            return True
        if cls.endswith("." + t) or icls.endswith("." + t):
            return True
        if terminal and (_word_in(title, t) or _word_in(ititle, t)):
            return True
    return False


def _word_in(text: str, token: str) -> bool:
    return re.search(r"(?i)\b" + re.escape(token) + r"\b", text or "") is not None


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
