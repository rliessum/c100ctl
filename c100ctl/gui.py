"""GTK4 + libadwaita control surface for the C100 8K."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import COLS, LOCKED_KEYS, LOCKED_LABELS, ROWS, __version__
from .actions import list_desktop_apps
from .config import BINDING_TYPES, key_id
from .css import APP_CSS
from .daemon import RGB_EFFECTS
from .ipc import IpcClient, daemon_available
from .via import PER_KEY_EFFECT, parse_hex_color, rgb_to_hex

PALETTE = (
    "#ff3b30",
    "#ff9500",
    "#ffcc00",
    "#34c759",
    "#00c7be",
    "#007aff",
    "#5856d6",
    "#af52de",
    "#ff2d55",
    "#ffffff",
    "#8e8e93",
    "#1c1c1e",
)

log = logging.getLogger("c100ctl.gui")

TYPE_LABELS = {
    "app": "Launch app",
    "command": "Run command",
    "combo": "Key combination",
    "macro": "Macro",
    "text": "Type text",
    "profile": "Switch profile",
}


def ensure_daemon() -> None:
    if daemon_available():
        return
    subprocess.Popen(
        [sys.executable, "-m", "c100ctl", "daemon"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(25):
        time.sleep(0.12)
        if daemon_available():
            return
    raise RuntimeError("C100 daemon did not start. Try: c100ctl daemon")


class KeyCap(Gtk.Button):
    def __init__(self, row: int, col: int):
        super().__init__()
        self.row = row
        self.col = col
        self.locked = (row, col) in LOCKED_KEYS
        self.add_css_class("keycap")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0.5)
        self.title.add_css_class("key-label")
        self.title.set_wrap(True)
        self.title.set_max_width_chars(8)
        self.sub = Gtk.Label(xalign=0.5)
        self.sub.add_css_class("key-sub")
        box.append(self.title)
        box.append(self.sub)
        self.set_child(box)
        self.set_can_focus(True)
        if self.locked:
            self.add_css_class("locked")
            self.title.set_text(LOCKED_LABELS[(row, col)])
            self.sub.set_text("firmware")
        else:
            self.title.set_text(f"{row},{col}")
            self.sub.set_text("")

    def apply_binding(self, binding: dict[str, Any] | None) -> None:
        for name in (
            "bound-app",
            "bound-command",
            "bound-combo",
            "bound-macro",
            "bound-text",
            "bound-profile",
        ):
            self.remove_css_class(name)
        if self.locked:
            return
        if not binding:
            self.title.set_text(f"{self.row},{self.col}")
            self.sub.set_text("")
            return
        kind = binding.get("type", "")
        if kind:
            self.add_css_class(f"bound-{kind}")
        label = (binding.get("label") or "").strip()
        if not label:
            if kind == "app":
                label = (binding.get("desktop_id") or "app").replace(".desktop", "")
            elif kind == "command":
                label = (binding.get("command") or "cmd").split()[0]
            elif kind == "combo":
                label = binding.get("combo") or "combo"
            elif kind == "macro":
                label = "macro"
            elif kind == "text":
                label = (binding.get("text") or "text")[:10]
            elif kind == "profile":
                label = binding.get("profile") or "profile"
        self.title.set_text(label)
        self.sub.set_text(kind)

    def apply_led_color(self, hex_color: str | None) -> None:
        if not hasattr(self, "_led_css"):
            self._led_css = Gtk.CssProvider()
            self.get_style_context().add_provider(
                self._led_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        if not hex_color:
            self._led_css.load_from_data(b"")
            return
        try:
            r, g, b = parse_hex_color(hex_color)
        except ValueError:
            self._led_css.load_from_data(b"")
            return
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        fg = "#1a1a1a" if y > 155 else "#f4f1ea"
        css = (
            f".keycap {{ background: {hex_color}; color: {fg}; "
            f"border: 1px solid {hex_color}; }}"
        ).encode()
        self._led_css.load_from_data(css)

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")

    def set_pressed(self, pressed: bool) -> None:
        if pressed:
            self.add_css_class("pressed")
        else:
            self.remove_css_class("pressed")


class C100Window(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="C100 Control")
        self.set_default_size(1180, 860)
        self.add_css_class("main")
        self.client: IpcClient | None = None
        self.config: dict[str, Any] = {}
        self.status: dict[str, Any] = {}
        self.selected: tuple[int, int] | None = None
        self.keys: dict[tuple[int, int], KeyCap] = {}
        self._apps = list_desktop_apps()
        self._building = False

        provider = Gtk.CssProvider()
        provider.load_from_data(APP_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.conn_dot = Gtk.Box()
        self.conn_dot.add_css_class("status-dot")
        self.conn_dot.add_css_class("off")
        self.conn_label = Gtk.Label(label="Disconnected")
        conn_box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        conn_box.append(self.conn_dot)
        conn_box.append(self.conn_label)
        header.set_title_widget(conn_box)

        self.profile_drop = Gtk.DropDown.new_from_strings(["default"])
        self.profile_drop.connect("notify::selected", self._on_profile_changed)
        header.pack_start(self.profile_drop)

        menu = Gio.Menu()
        menu.append("Provision identity map", "win.provision")
        menu.append("New profile", "win.new-profile")
        menu.append("About", "win.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)
        toolbar.add_top_bar(header)

        split = Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END,
            min_sidebar_width=340,
            max_sidebar_width=420,
            show_sidebar=True,
        )
        split.set_content(self._build_pad())
        split.set_sidebar(self._build_editor())
        toolbar.set_content(split)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self.install_action("win.provision", None, self._action_provision)
        self.install_action("win.new-profile", None, self._action_new_profile)
        self.install_action("win.about", None, self._action_about)

        hint = Gtk.Label(
            label="Press a key on the C100 to select it. Corner keys stay on the firmware lighting controls.",
            wrap=True,
        )
        hint.add_css_class("hint")
        # already in pad

        try:
            ensure_daemon()
            self.client = IpcClient()
        except Exception as e:
            self._toast(str(e))
        GLib.timeout_add(80, self._pump)
        GLib.timeout_add(600, self._refresh_status)
        self._reload()

    def _build_pad(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, vexpand=True)
        outer.set_margin_top(12)
        outer.set_margin_bottom(16)
        outer.set_margin_start(16)
        outer.set_margin_end(8)
        self.hint = Gtk.Label(
            label="Press a key on the pad to select it, or click a cell.",
            wrap=True,
            xalign=0,
        )
        self.hint.add_css_class("hint")
        outer.append(self.hint)

        shell = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
        shell.add_css_class("pad-shell")
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.add_css_class("pad-grid")
        for r in range(ROWS):
            for c in range(COLS):
                cap = KeyCap(r, c)
                cap.connect("clicked", self._on_cap_clicked)
                self.keys[(r, c)] = cap
                grid.attach(cap, c, r, 1, 1)
        shell.append(grid)
        outer.append(shell)

        light_row = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        light_row.append(Gtk.Label(label="Brightness"))
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self.bright.set_size_request(180, -1)
        self.bright.set_draw_value(False)
        self.bright.connect("value-changed", self._on_bright)
        light_row.append(self.bright)
        light_row.append(Gtk.Label(label="Effect"))
        self.effect = Gtk.DropDown.new_from_strings(RGB_EFFECTS)
        self.effect.connect("notify::selected", self._on_effect)
        light_row.append(self.effect)
        outer.append(light_row)
        return outer

    def _build_editor(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(16)
        box.set_margin_start(8)
        box.set_margin_end(16)
        self.editor_title = Gtk.Label(xalign=0, label="No key selected")
        self.editor_title.add_css_class("title-3")
        box.append(self.editor_title)

        color_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        dialog = Gtk.ColorDialog()
        dialog.set_with_alpha(False)
        self.color_btn = Gtk.ColorDialogButton(dialog=dialog)
        self.color_btn.connect("notify::rgba", self._on_color)
        color_row.append(self.color_btn)
        clear_color = Gtk.Button(label="Clear")
        clear_color.connect("clicked", self._clear_color)
        color_row.append(clear_color)
        box.append(labeled("Key color", color_row))

        palette = Gtk.Box(spacing=4)
        palette.set_halign(Gtk.Align.START)
        for hex_color in PALETTE:
            swatch = Gtk.Button()
            swatch.add_css_class("color-swatch")
            swatch.set_tooltip_text(hex_color)
            provider = Gtk.CssProvider()
            provider.load_from_data(
                f".color-swatch {{ min-width: 22px; min-height: 22px; padding: 0; "
                f"border-radius: 11px; background: {hex_color}; }}".encode()
            )
            swatch.get_style_context().add_provider(
                provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            swatch.connect("clicked", self._on_swatch, hex_color)
            palette.append(swatch)
        box.append(palette)

        self.type_drop = Gtk.DropDown.new_from_strings([TYPE_LABELS[t] for t in BINDING_TYPES])
        self.type_drop.connect("notify::selected", lambda *_: self._sync_type_fields())
        box.append(labeled("Action", self.type_drop))

        self.label_entry = Gtk.Entry(placeholder_text="Key label")
        box.append(labeled("Label", self.label_entry))

        self.app_search = Gtk.SearchEntry(placeholder_text="Search apps")
        self.app_search.connect("search-changed", self._filter_apps)
        self.app_list = Gtk.ListBox()
        self.app_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.app_list.set_vexpand(True)
        scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=180)
        scroll.set_child(self.app_list)
        self.app_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app_box.append(self.app_search)
        self.app_box.append(scroll)
        box.append(self.app_box)

        self.command_entry = Gtk.Entry(placeholder_text="hyprctl dispatch exec kitty")
        self.command_box = labeled("Command", self.command_entry)
        box.append(self.command_box)

        self.combo_entry = Gtk.Entry(placeholder_text="Super+Return")
        capture = Gtk.Button(label="Capture")
        capture.connect("clicked", self._capture_combo)
        combo_row = Gtk.Box(spacing=6)
        self.combo_entry.set_hexpand(True)
        combo_row.append(self.combo_entry)
        combo_row.append(capture)
        self.combo_box = labeled("Combination", combo_row)
        box.append(self.combo_box)

        self.macro_entry = Gtk.Entry(placeholder_text="ctrl+c, delay:80, ctrl+v")
        self.macro_box = labeled("Macro", self.macro_entry)
        box.append(self.macro_box)

        self.text_entry = Gtk.Entry(placeholder_text="typed text")
        self.text_box = labeled("Text", self.text_entry)
        box.append(self.text_box)

        self.profile_entry = Gtk.Entry(placeholder_text="gaming")
        self.profile_box = labeled("Profile name", self.profile_entry)
        box.append(self.profile_box)

        btn_row = Gtk.Box(spacing=8, homogeneous=True)
        apply_btn = Gtk.Button(label="Bind key")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._apply)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._clear)
        btn_row.append(apply_btn)
        btn_row.append(clear_btn)
        box.append(btn_row)

        self._fill_apps()
        self._sync_type_fields()
        return box

    def _fill_apps(self, query: str = "") -> None:
        while True:
            row = self.app_list.get_row_at_index(0)
            if not row:
                break
            self.app_list.remove(row)
        q = query.lower().strip()
        for app in self._apps:
            if q and q not in app["name"].lower() and q not in app["id"].lower():
                continue
            row = Gtk.ListBoxRow()
            lab = Gtk.Label(label=app["name"], xalign=0)
            lab.set_margin_top(6)
            lab.set_margin_bottom(6)
            lab.set_margin_start(8)
            row.set_child(lab)
            row.app_id = app["id"]  # type: ignore[attr-defined]
            self.app_list.append(row)

    def _filter_apps(self, entry: Gtk.SearchEntry) -> None:
        self._fill_apps(entry.get_text())

    def _sync_type_fields(self) -> None:
        idx = int(self.type_drop.get_selected())
        kind = BINDING_TYPES[idx]
        self.app_box.set_visible(kind == "app")
        self.command_box.set_visible(kind in ("command", "app"))
        self.combo_box.set_visible(kind == "combo")
        self.macro_box.set_visible(kind == "macro")
        self.text_box.set_visible(kind == "text")
        self.profile_box.set_visible(kind == "profile")

    def _on_cap_clicked(self, cap: KeyCap) -> None:
        self._select(cap.row, cap.col)

    def _select(self, row: int, col: int) -> None:
        if self.selected:
            self.keys[self.selected].set_selected(False)
        self.selected = (row, col)
        self.keys[(row, col)].set_selected(True)
        if (row, col) in LOCKED_KEYS:
            self.editor_title.set_text(f"{LOCKED_LABELS[(row, col)]}  ·  lighting")
            self._load_color(row, col)
            return
        self.editor_title.set_text(f"Key {row},{col}")
        keys = self._active_keys()
        binding = keys.get(key_id(row, col))
        self._load_binding(binding)
        self._load_color(row, col)

    def _load_binding(self, binding: dict[str, Any] | None) -> None:
        self._building = True
        if not binding:
            self.label_entry.set_text("")
            self.command_entry.set_text("")
            self.combo_entry.set_text("")
            self.macro_entry.set_text("")
            self.text_entry.set_text("")
            self.profile_entry.set_text("")
            self.type_drop.set_selected(0)
            self._building = False
            self._sync_type_fields()
            return
        kind = binding.get("type", "app")
        if kind in BINDING_TYPES:
            self.type_drop.set_selected(BINDING_TYPES.index(kind))
        self.label_entry.set_text(binding.get("label", ""))
        self.command_entry.set_text(binding.get("command", ""))
        self.combo_entry.set_text(binding.get("combo", ""))
        self.macro_entry.set_text(binding.get("macro", ""))
        self.text_entry.set_text(binding.get("text", ""))
        self.profile_entry.set_text(binding.get("profile", ""))
        desktop = binding.get("desktop_id")
        if desktop:
            i = 0
            while True:
                row = self.app_list.get_row_at_index(i)
                if not row:
                    break
                if getattr(row, "app_id", "") == desktop:
                    self.app_list.select_row(row)
                    break
                i += 1
        self._building = False
        self._sync_type_fields()

    def _key_colors(self) -> dict[str, str]:
        return (self.config.get("lighting") or {}).get("keys") or {}

    def _load_color(self, row: int, col: int) -> None:
        hex_color = self._key_colors().get(key_id(row, col), "#2a2e33")
        self._set_picker_hex(hex_color)

    def _set_picker_hex(self, hex_color: str) -> None:
        try:
            r, g, b = parse_hex_color(hex_color)
        except ValueError:
            r, g, b = 42, 46, 51
        rgba = Gdk.RGBA()
        rgba.red = r / 255
        rgba.green = g / 255
        rgba.blue = b / 255
        rgba.alpha = 1
        was = self._building
        self._building = True
        self.color_btn.set_rgba(rgba)
        self._building = was

    def _on_color(self, *_a: object) -> None:
        if self._building or not self.selected:
            return
        rgba = self.color_btn.get_rgba()
        hex_color = rgb_to_hex(int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
        self._push_color(hex_color)

    def _on_swatch(self, _btn: Gtk.Button, hex_color: str) -> None:
        if not self.selected:
            self._toast("Select a key first")
            return
        self._set_picker_hex(hex_color)
        self._push_color(hex_color)

    def _clear_color(self, *_a: object) -> None:
        if not self.selected:
            return
        self._push_color(None)

    def _push_color(self, hex_color: str | None) -> None:
        if not self.selected:
            return
        row, col = self.selected
        resp = self._rpc("set_key_color", row=row, col=col, color=hex_color)
        if resp and resp.get("ok"):
            lighting = (resp.get("lighting") or self.config.get("lighting") or {})
            self.config.setdefault("lighting", {}).update(lighting)
            if "keys" in lighting:
                self.config["lighting"]["keys"] = lighting["keys"]
            self.keys[(row, col)].apply_led_color(hex_color)
            if int(self.effect.get_selected() or 0) != PER_KEY_EFFECT:
                self._building = True
                self.effect.set_selected(PER_KEY_EFFECT)
                self._building = False

    def _active_keys(self) -> dict[str, Any]:
        profiles = self.config.get("profiles", {})
        name = self.config.get("active_profile", "default")
        return profiles.get(name, {}).get("keys", {})

    def _apply(self, *_a: object) -> None:
        if not self.selected or self.selected in LOCKED_KEYS:
            self._toast("Select a programmable key first")
            return
        kind = BINDING_TYPES[int(self.type_drop.get_selected())]
        binding: dict[str, Any] = {"type": kind, "label": self.label_entry.get_text().strip()}
        if kind == "app":
            row = self.app_list.get_selected_row()
            if row is not None:
                binding["desktop_id"] = getattr(row, "app_id", "")
            cmd = self.command_entry.get_text().strip()
            if cmd:
                binding["command"] = cmd
            if not binding.get("desktop_id") and not binding.get("command"):
                self._toast("Pick an app or enter a command")
                return
            if not binding["label"]:
                binding["label"] = (binding.get("desktop_id") or "app").replace(".desktop", "")
        elif kind == "command":
            binding["command"] = self.command_entry.get_text().strip()
            if not binding["command"]:
                self._toast("Enter a command")
                return
        elif kind == "combo":
            binding["combo"] = self.combo_entry.get_text().strip()
            if not binding["combo"]:
                self._toast("Enter a combination like Super+Return")
                return
        elif kind == "macro":
            binding["macro"] = self.macro_entry.get_text().strip()
            if not binding["macro"]:
                self._toast("Enter a macro")
                return
        elif kind == "text":
            binding["text"] = self.text_entry.get_text()
        elif kind == "profile":
            binding["profile"] = self.profile_entry.get_text().strip()
            if not binding["profile"]:
                self._toast("Enter a profile name")
                return
        self._rpc("set_binding", row=self.selected[0], col=self.selected[1], binding=binding)
        self._reload()

    def _clear(self, *_a: object) -> None:
        if not self.selected or self.selected in LOCKED_KEYS:
            return
        self._rpc("set_binding", row=self.selected[0], col=self.selected[1], binding=None)
        self._reload()

    def _capture_combo(self, button: Gtk.Button) -> None:
        button.set_label("Press keys…")
        ctrl = Gtk.EventControllerKey()

        def on_key(_c, keyval, _code, state):
            names = []
            if state & Gdk.ModifierType.CONTROL_MASK:
                names.append("Ctrl")
            if state & Gdk.ModifierType.SHIFT_MASK:
                names.append("Shift")
            if state & Gdk.ModifierType.ALT_MASK:
                names.append("Alt")
            if state & Gdk.ModifierType.SUPER_MASK:
                names.append("Super")
            key = Gtk.accelerator_name(keyval, 0)
            if key:
                key = key.replace("<", "").replace(">", "")
                if key.lower() not in {"control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "super_l", "super_r", "meta_l", "meta_r"}:
                    names.append(key.upper() if len(key) == 1 else key)
            if names:
                self.combo_entry.set_text("+".join(names))
            button.set_label("Capture")
            self.remove_controller(ctrl)
            return True

        ctrl.connect("key-pressed", on_key)
        self.add_controller(ctrl)
        self.grab_focus()

    def _on_profile_changed(self, *_a: object) -> None:
        if self._building:
            return
        idx = int(self.profile_drop.get_selected())
        names = list(self.config.get("profiles", {}).keys()) or ["default"]
        if idx < 0 or idx >= len(names):
            return
        name = names[idx]
        if name != self.config.get("active_profile"):
            self._rpc("set_profile", name=name)
            self._reload()

    def _on_bright(self, scale: Gtk.Scale) -> None:
        if self._building:
            return
        self._rpc("set_lighting", brightness=int(scale.get_value()))

    def _on_effect(self, *_a: object) -> None:
        if self._building:
            return
        self._rpc("set_lighting", effect=int(self.effect.get_selected()))

    def _action_provision(self, *_a: object) -> None:
        resp = self._rpc("provision", backup=True)
        if resp and resp.get("ok"):
            self._toast("Wrote unique identity keycodes to the pad (previous map backed up)")
        elif resp:
            self._toast(resp.get("error", "provision failed"))

    def _action_new_profile(self, *_a: object) -> None:
        dialog = Adw.AlertDialog(heading="New profile", body="Name this binding profile")
        entry = Gtk.Entry(placeholder_text="gaming")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "Create")
        dialog.set_default_response("ok")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def done(dlg, response):
            if response != "ok":
                return
            name = entry.get_text().strip().replace(" ", "-")
            if not name:
                return
            self._rpc("ensure_profile", name=name, label=name)
            self._rpc("set_profile", name=name)
            self._reload()

        dialog.connect("response", done)
        dialog.present(self)

    def _action_about(self, *_a: object) -> None:
        win = Adw.AboutDialog(
            application_name="C100 Control",
            version=__version__,
            developer_name="Built for Omarchy Linux",
            comments="Host-side Keychron C100 8K controller. Binds keys to apps, commands, combos and macros. Talks VIA over raw HID.",
        )
        win.present(self)

    def _reload(self) -> None:
        if not self.client:
            return
        try:
            cfg = self.client.request("get_config")
            st = self.client.request("status")
        except OSError as e:
            self._toast(f"daemon: {e}")
            return
        if cfg.get("ok"):
            self.config = cfg.get("config") or {}
        self.status = st
        self._apply_status()
        self._apply_config()

    def _apply_status(self) -> None:
        connected = bool(self.status.get("connected"))
        self.conn_dot.remove_css_class("on")
        self.conn_dot.remove_css_class("off")
        self.conn_dot.add_css_class("on" if connected else "off")
        if connected:
            self.conn_label.set_text(f"C100 8K  ·  VIA {self.status.get('protocol')}  ·  {self.status.get('serial', '')[:8]}")
        else:
            self.conn_label.set_text("Waiting for Keychron C100 8K…")
        lighting = self.status.get("lighting") or {}
        self._building = True
        if "brightness" in lighting:
            self.bright.set_value(int(lighting["brightness"]))
        if "effect" in lighting:
            self.effect.set_selected(int(lighting["effect"]))
        self._building = False

    def _apply_config(self) -> None:
        self._building = True
        names = list(self.config.get("profiles", {}).keys()) or ["default"]
        model = Gtk.StringList.new(names)
        self.profile_drop.set_model(model)
        active = self.config.get("active_profile", "default")
        if active in names:
            self.profile_drop.set_selected(names.index(active))
        keys = self._active_keys()
        colors = (self.config.get("lighting") or {}).get("keys") or {}
        for (r, c), cap in self.keys.items():
            cap.apply_binding(keys.get(key_id(r, c)))
            cap.apply_led_color(colors.get(key_id(r, c)))
        self._building = False
        if self.selected:
            self._select(*self.selected)

    def _pump(self) -> bool:
        if not self.client:
            return True
        for _ in range(16):
            try:
                msg = self.client.read_event()
            except Exception:
                break
            if not msg:
                break
            self._on_event(msg)
        return True

    def _refresh_status(self) -> bool:
        if not self.client:
            try:
                ensure_daemon()
                self.client = IpcClient()
            except Exception:
                return True
        try:
            self.status = self.client.request("status")
            self._apply_status()
        except OSError:
            self.client = None
            self.status = {"connected": False}
            self._apply_status()
        return True

    def _on_event(self, msg: dict[str, Any]) -> None:
        ev = msg.get("event")
        if ev == "key":
            cell = (int(msg["row"]), int(msg["col"]))
            cap = self.keys.get(cell)
            if cap:
                cap.set_pressed(bool(msg.get("pressed")))
            if msg.get("pressed"):
                self._select(*cell)
        elif ev in {"connected", "disconnected", "config", "profile", "lighting"}:
            if "config" in msg:
                self.config = msg["config"]
                self._apply_config()
            self._reload()
        elif ev == "error":
            self._toast(msg.get("error", "error"))

    def _rpc(self, op: str, **fields: Any) -> dict[str, Any] | None:
        if not self.client:
            self._toast("daemon is not running")
            return None
        try:
            return self.client.request(op, **fields)
        except OSError as e:
            self._toast(str(e))
            return None

    def _toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text))


def labeled(title: str, child: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    lab = Gtk.Label(label=title, xalign=0)
    lab.add_css_class("caption")
    box.append(lab)
    box.append(child)
    return box


class C100Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.omarchy.c100ctl", flags=Gio.ApplicationFlags.FLAGS_NONE)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    def do_activate(self) -> None:  # noqa: N802
        win = self.props.active_window
        if not win:
            win = C100Window(self)
        win.present()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    return C100Application().run(sys.argv)
