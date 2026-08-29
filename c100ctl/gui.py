"""GTK4 + libadwaita control surface for the C100 8K."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk  # noqa: E402

from . import COLS, LOCKED_KEYS, LOCKED_LABELS, ROWS, __version__
from .actions import list_desktop_apps
from .catalog import (
    DEBOUNCE_TYPES,
    LIGHT_ACTIONS,
    MEDIA_KEYS,
    MOUSE_ACTIONS,
    PER_KEY_TYPES,
    POLL_RATES,
    light_label,
    media_label,
    mouse_label,
)
from .config import BINDING_TYPES, key_id, parse_key_id
from .css import APP_CSS
from .daemon import RGB_EFFECTS
from .ipc import IpcClient, daemon_available
from .via import MIX_RGB_EFFECT, PER_KEY_EFFECT, heatmap_hex, parse_hex_color, rgb_to_hex

# Firmware ids stay 0–24. Show Per Key RGB / Mix RGB first so they stay
# pickable instead of sitting under 23 animation names.
EFFECT_PICKER: tuple[tuple[int, str], ...] = (
    (PER_KEY_EFFECT, "Per Key RGB"),
    (MIX_RGB_EFFECT, "Mix RGB"),
    *tuple((i, name) for i, name in enumerate(RGB_EFFECTS[:23])),
)
EFFECT_LABELS = tuple(name for _eid, name in EFFECT_PICKER)
EFFECT_IDS = tuple(eid for eid, _name in EFFECT_PICKER)

PALETTE = (
    "#ff3b30",
    "#ff9500",
    "#ffcc00",
    "#00ff00",
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
    "url": "Open URL",
    "media": "Media / system",
    "mouse": "Mouse",
    "light": "Lighting control",
}

HOLD_CHOICES = (
    "None",
    "Switch profile",
    "Momentary profile",
    "Key combination",
    "Media / system",
    "Lighting control",
    "Open URL",
)


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
            "bound-url",
            "bound-media",
            "bound-mouse",
            "bound-light",
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
            elif kind == "url":
                label = binding.get("url") or "url"
            elif kind == "media":
                label = media_label(binding.get("media") or "")
            elif kind == "mouse":
                label = mouse_label(binding.get("mouse") or "")
            elif kind == "light":
                label = light_label(binding.get("light") or "")
        self.title.set_text(label)
        extra = kind
        if isinstance(binding.get("hold"), dict):
            extra = f"{kind}+hold"
        self.sub.set_text(extra)

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
        self.set_default_size(1280, 920)
        self.add_css_class("main")
        self.client: IpcClient | None = None
        self.config: dict[str, Any] = {}
        self.status: dict[str, Any] = {}
        self.selected: tuple[int, int] | None = None
        self.selected_cells: set[tuple[int, int]] = set()
        self.anchor: tuple[int, int] | None = None
        self.keys: dict[tuple[int, int], KeyCap] = {}
        self._color_undo: list[dict[str, str]] = []
        self._color_redo: list[dict[str, str]] = []
        self._mix_zone = 0
        self._record_macro = False
        self._record_last = 0.0
        self._record_parts: list[str] = []
        self.test_hits: dict[tuple[int, int], int] = {}
        self._heatmap_ui = False
        self._apps = list_desktop_apps()
        self._building = False
        self._drag_moved = False
        self._drag_start = (0.0, 0.0)
        self._drag_ctrl = False
        self.pad_grid: Gtk.Grid | None = None

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

        profile_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.profile_drop = Gtk.DropDown.new_from_strings(["default"])
        self.profile_drop.connect("notify::selected", self._on_profile_changed)
        profile_box.append(self.profile_drop)

        new_btn = Gtk.Button(icon_name="list-add-symbolic")
        new_btn.set_tooltip_text("New profile")
        new_btn.connect("clicked", lambda *_: self._action_new_profile(None, None, None))
        profile_box.append(new_btn)

        self.delete_profile_btn = Gtk.Button(icon_name="user-trash-symbolic")
        self.delete_profile_btn.set_tooltip_text("Delete profile")
        self.delete_profile_btn.connect("clicked", lambda *_: self._action_delete_profile(None, None, None))
        self.delete_profile_btn.set_sensitive(False)
        profile_box.append(self.delete_profile_btn)

        header.pack_start(profile_box)

        menu = Gio.Menu()
        menu.append("Provision identity map", "win.provision")
        menu.append("New profile", "win.new-profile")
        menu.append("Delete profile", "win.delete-profile")
        menu.append("Save lighting to profile", "win.save-profile-light")
        menu.append("Import config…", "win.import")
        menu.append("Export config…", "win.export")
        menu.append("Clear all key colors", "win.clear-colors")
        menu.append("About", "win.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)
        toolbar.add_top_bar(header)

        split = Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END,
            min_sidebar_width=360,
            max_sidebar_width=460,
            show_sidebar=True,
        )
        split.set_content(self._build_pad())
        split.set_sidebar(self._build_editor())

        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(split, "keys", "Keys", "input-keyboard-symbolic")
        self.stack.add_titled_with_icon(self._build_mix_page(), "mix", "Mix RGB", "color-select-symbolic")
        self.stack.add_titled_with_icon(self._build_advanced_page(), "advanced", "Advanced", "emblem-system-symbolic")
        self.stack.add_titled_with_icon(self._build_test_page(), "test", "Test", "view-grid-symbolic")
        self.stack.connect("notify::visible-child", self._on_page)

        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shell.append(self.stack)
        switcher = Adw.ViewSwitcherBar()
        switcher.set_stack(self.stack)
        switcher.set_reveal(True)
        shell.append(switcher)
        toolbar.set_content(shell)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self.install_action("win.provision", None, self._action_provision)
        self.install_action("win.new-profile", None, self._action_new_profile)
        self.install_action("win.delete-profile", None, self._action_delete_profile)
        self.install_action("win.save-profile-light", None, self._action_save_profile_light)
        self.install_action("win.import", None, self._action_import)
        self.install_action("win.export", None, self._action_export)
        self.install_action("win.clear-colors", None, self._action_clear_colors)
        self.install_action("win.about", None, self._action_about)

        keys_ctrl = Gtk.EventControllerKey()
        keys_ctrl.connect("key-pressed", self._on_win_key)
        self.add_controller(keys_ctrl)

        hint = Gtk.Label(
            label="Press a key on the C100 to select it. Corner keys stay on the firmware lighting controls.",
            wrap=True,
        )
        hint.add_css_class("hint")
        # already in pad

        self.connect("close-request", self._on_close)
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
            label="Click a key. Ctrl+click adds, Shift+click fills a rectangle, drag to select a block. App keys: tap to launch, double-tap to close.",
            wrap=True,
            xalign=0,
        )
        self.hint.add_css_class("hint")
        outer.append(self.hint)

        shell = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
        shell.add_css_class("pad-shell")
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.add_css_class("pad-grid")
        self.pad_grid = grid
        for r in range(ROWS):
            for c in range(COLS):
                cap = KeyCap(r, c)
                click = Gtk.GestureClick()
                click.set_button(1)
                click.connect("pressed", self._on_cap_pressed, cap)
                cap.add_controller(click)
                self.keys[(r, c)] = cap
                grid.attach(cap, c, r, 1, 1)
        drag = Gtk.GestureDrag()
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        grid.add_controller(drag)
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
        self.effect = Gtk.DropDown.new_from_strings(list(EFFECT_LABELS))
        self.effect.set_size_request(160, -1)
        self.effect.connect("notify::selected", self._on_effect)
        light_row.append(self.effect)
        light_row.append(Gtk.Label(label="Speed"))
        self.speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self.speed.set_size_request(120, -1)
        self.speed.set_draw_value(False)
        self.speed.connect("value-changed", self._on_speed)
        light_row.append(self.speed)
        outer.append(light_row)
        extra = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        extra.append(Gtk.Label(label="Effect color"))
        color_dlg = Gtk.ColorDialog()
        color_dlg.set_with_alpha(False)
        self.global_color = Gtk.ColorDialogButton(dialog=color_dlg)
        self.global_color.connect("notify::rgba", self._on_global_color)
        extra.append(self.global_color)
        extra.append(Gtk.Label(label="Per-key FX"))
        self.per_key_type = Gtk.DropDown.new_from_strings([name for _i, name in PER_KEY_TYPES])
        self.per_key_type.connect("notify::selected", self._on_per_key_type)
        extra.append(self.per_key_type)
        undo = Gtk.Button(label="Undo color")
        undo.connect("clicked", self._undo_color)
        extra.append(undo)
        redo = Gtk.Button(label="Redo")
        redo.connect("clicked", self._redo_color)
        extra.append(redo)
        same = Gtk.Button(label="Select same color")
        same.connect("clicked", self._select_same_color)
        extra.append(same)
        outer.append(extra)
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
        sel_row = Gtk.Box(spacing=8)
        all_btn = Gtk.Button(label="Select all")
        all_btn.connect("clicked", lambda *_: self._commit_selection(set(self.keys)))
        none_btn = Gtk.Button(label="Clear selection")
        none_btn.connect("clicked", lambda *_: self._commit_selection(set()))
        sel_row.append(all_btn)
        sel_row.append(none_btn)
        box.append(sel_row)
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

        self.profile_bind_drop = Gtk.DropDown.new_from_strings(["default"])
        self.profile_box = labeled("Switch to profile", self.profile_bind_drop)
        box.append(self.profile_box)

        self.url_entry = Gtk.Entry(placeholder_text="https://")
        self.url_box = labeled("URL", self.url_entry)
        box.append(self.url_box)

        self.media_drop = Gtk.DropDown.new_from_strings([label for _i, label, _k in MEDIA_KEYS])
        self.media_box = labeled("Media / system key", self.media_drop)
        box.append(self.media_box)

        self.mouse_drop = Gtk.DropDown.new_from_strings([label for _i, label in MOUSE_ACTIONS])
        self.mouse_box = labeled("Mouse action", self.mouse_drop)
        box.append(self.mouse_box)

        self.light_drop = Gtk.DropDown.new_from_strings([label for _i, label in LIGHT_ACTIONS])
        self.light_box = labeled("Lighting action", self.light_drop)
        box.append(self.light_box)

        rec_row = Gtk.Box(spacing=8)
        self.record_btn = Gtk.Button(label="Record macro")
        self.record_btn.connect("clicked", self._toggle_record)
        rec_row.append(self.record_btn)
        self.repeat_hold = Gtk.CheckButton(label="Repeat while held")
        rec_row.append(self.repeat_hold)
        self.macro_box.append(rec_row)

        self.hold_drop = Gtk.DropDown.new_from_strings(list(HOLD_CHOICES))
        self.hold_drop.connect("notify::selected", self._on_hold_type_changed)
        self.hold_profile_drop = Gtk.DropDown.new_from_strings(["default"])
        self.hold_entry = Gtk.Entry(placeholder_text="hold value (combo / url)")
        hold_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hold_col.append(self.hold_drop)
        hold_col.append(self.hold_profile_drop)
        hold_col.append(self.hold_entry)
        box.append(labeled("On hold", hold_col))

        chord_btn = Gtk.Button(label="Bind selected keys as a chord")
        chord_btn.connect("clicked", self._bind_chord)
        box.append(chord_btn)

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

    def _build_mix_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_top(12)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        outer.set_margin_bottom(12)
        hint = Gtk.Label(
            label="Mix RGB: paint keys into Zone 1 or Zone 2, then set a timeline of effects for each zone (1–99 seconds).",
            wrap=True,
            xalign=0,
        )
        hint.add_css_class("hint")
        outer.append(hint)
        zone_row = Gtk.Box(spacing=8)
        self.zone_drop = Gtk.DropDown.new_from_strings(["Zone 1", "Zone 2"])
        self.zone_drop.connect("notify::selected", self._on_zone)
        zone_row.append(self.zone_drop)
        apply_btn = Gtk.Button(label="Write Mix RGB to pad")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._apply_mix)
        zone_row.append(apply_btn)
        outer.append(zone_row)
        grid = Gtk.Grid(column_spacing=4, row_spacing=4, halign=Gtk.Align.CENTER)
        self.mix_keys: dict[tuple[int, int], Gtk.Button] = {}
        for r in range(ROWS):
            for c in range(COLS):
                btn = Gtk.Button(label=f"{r},{c}")
                btn.add_css_class("keycap")
                btn.connect("clicked", self._mix_paint, r, c)
                grid.attach(btn, c, r, 1, 1)
                self.mix_keys[(r, c)] = btn
        outer.append(grid)
        self.mix_slots: list[list[dict[str, Gtk.Widget]]] = []
        for zone in range(2):
            frame = Gtk.Frame(label=f"Zone {zone + 1} timeline")
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            col.set_margin_top(8)
            col.set_margin_start(8)
            col.set_margin_end(8)
            col.set_margin_bottom(8)
            zone_slots: list[dict[str, Gtk.Widget]] = []
            for slot in range(5):
                row = Gtk.Box(spacing=8)
                effect = Gtk.DropDown.new_from_strings(["Off", *RGB_EFFECTS[1:23]])
                hue = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
                hue.set_size_request(100, -1)
                hue.set_draw_value(False)
                sat = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
                sat.set_size_request(80, -1)
                sat.set_draw_value(False)
                sat.set_value(255)
                speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
                speed.set_size_request(80, -1)
                speed.set_draw_value(False)
                speed.set_value(127)
                seconds = Gtk.SpinButton.new_with_range(1, 99, 1)
                seconds.set_value(5)
                row.append(Gtk.Label(label=f"{slot + 1}"))
                row.append(effect)
                row.append(Gtk.Label(label="H"))
                row.append(hue)
                row.append(Gtk.Label(label="S"))
                row.append(sat)
                row.append(Gtk.Label(label="Spd"))
                row.append(speed)
                row.append(Gtk.Label(label="s"))
                row.append(seconds)
                col.append(row)
                zone_slots.append(
                    {"effect": effect, "hue": hue, "sat": sat, "speed": speed, "seconds": seconds}
                )
            self.mix_slots.append(zone_slots)
            frame.set_child(col)
            outer.append(frame)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(outer)
        return scroll

    def _build_advanced_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(20)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_halign(Gtk.Align.CENTER)
        box.set_size_request(520, -1)
        self.fw_label = Gtk.Label(label="Firmware: —", xalign=0)
        box.append(self.fw_label)
        self.poll_drop = Gtk.DropDown.new_from_strings([f"{hz} Hz" for hz in POLL_RATES])
        box.append(labeled("USB polling rate", self.poll_drop))
        self.debounce_drop = Gtk.DropDown.new_from_strings([name for _i, name in DEBOUNCE_TYPES])
        box.append(labeled("Debounce mode", self.debounce_drop))
        self.debounce_ms = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 80, 1)
        self.debounce_ms.set_draw_value(True)
        self.debounce_ms.set_value(5)
        box.append(labeled("Debounce time (ms)", self.debounce_ms))
        self.nkro = Gtk.CheckButton(label="NKRO (n-key rollover)")
        self.nkro.set_active(True)
        box.append(self.nkro)
        self.idle_dim = Gtk.SpinButton.new_with_range(0, 3600, 5)
        self.idle_dim.set_value(0)
        box.append(labeled("Idle dim after seconds (0 = off)", self.idle_dim))
        save = Gtk.Button(label="Apply to pad")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._apply_advanced)
        box.append(save)
        return box

    def _build_test_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_top(16)
        hint = Gtk.Label(
            label="Press keys on the C100. More hits glow hotter here and on the pad. Leave this page (or Done) to restore lighting. Bindings still fire.",
            wrap=True,
        )
        hint.add_css_class("hint")
        outer.append(hint)
        row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        reset = Gtk.Button(label="Reset heatmap")
        reset.connect("clicked", self._reset_test)
        done = Gtk.Button(label="Done — restore lighting")
        done.add_css_class("suggested-action")
        done.connect("clicked", lambda *_: self.stack.set_visible_child_name("keys"))
        row.append(reset)
        row.append(done)
        outer.append(row)
        grid = Gtk.Grid(column_spacing=4, row_spacing=4, halign=Gtk.Align.CENTER)
        self.test_keys: dict[tuple[int, int], KeyCap] = {}
        for r in range(ROWS):
            for c in range(COLS):
                cap = KeyCap(r, c)
                grid.attach(cap, c, r, 1, 1)
                self.test_keys[(r, c)] = cap
        outer.append(grid)
        return outer

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
        self.url_box.set_visible(kind == "url")
        self.media_box.set_visible(kind == "media")
        self.mouse_box.set_visible(kind == "mouse")
        self.light_box.set_visible(kind == "light")
        self._sync_hold_fields()

    def _on_hold_type_changed(self, *_a: object) -> None:
        if not self._building:
            self._sync_hold_fields()

    def _sync_hold_fields(self) -> None:
        """Show/hide hold widgets based on hold type selection."""
        hold_idx = int(self.hold_drop.get_selected() or 0)
        is_profile_hold = hold_idx in (1, 2)
        self.hold_profile_drop.set_visible(is_profile_hold)
        self.hold_entry.set_visible(hold_idx > 2)

    def _on_cap_pressed(self, gesture: Gtk.GestureClick, _n: int, _x: float, _y: float, cap: KeyCap) -> None:
        if self._drag_moved:
            return
        state = gesture.get_current_event_state()
        self._select_click(
            (cap.row, cap.col),
            add=bool(state & Gdk.ModifierType.CONTROL_MASK),
            rect=bool(state & Gdk.ModifierType.SHIFT_MASK),
        )

    def _select(self, row: int, col: int) -> None:
        self._select_click((row, col), add=False, rect=False)

    def _select_click(self, cell: tuple[int, int], *, add: bool = False, rect: bool = False) -> None:
        if rect and self.anchor:
            cells = self._rect_cells(self.anchor, cell)
        elif add:
            cells = set(self.selected_cells)
            if cell in cells:
                cells.discard(cell)
            else:
                cells.add(cell)
        else:
            cells = {cell}
        if not rect:
            self.anchor = cell
        self._commit_selection(cells, primary=cell)

    def _rect_cells(self, a: tuple[int, int], b: tuple[int, int]) -> set[tuple[int, int]]:
        r0, r1 = min(a[0], b[0]), max(a[0], b[0])
        c0, c1 = min(a[1], b[1]), max(a[1], b[1])
        return {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}

    def _commit_selection(
        self,
        cells: set[tuple[int, int]],
        primary: tuple[int, int] | None = None,
    ) -> None:
        self.selected_cells = set(cells)
        if primary in self.selected_cells:
            self.selected = primary
        elif self.selected not in self.selected_cells:
            self.selected = next(iter(sorted(self.selected_cells)), None)
        if self.selected and not self.anchor:
            self.anchor = self.selected
        self._paint_selection(self.selected_cells)
        self._update_editor_for_selection()

    def _paint_selection(self, cells: set[tuple[int, int]], *, preview: bool = False) -> None:
        for cell, cap in self.keys.items():
            cap.set_selected(cell in cells and not preview)
            if preview:
                if cell in cells:
                    cap.add_css_class("drag-preview")
                else:
                    cap.remove_css_class("drag-preview")
            else:
                cap.remove_css_class("drag-preview")

    def _update_editor_for_selection(self) -> None:
        n = len(self.selected_cells)
        if n == 0:
            self.editor_title.set_text("No key selected")
            return
        if n == 1:
            row, col = next(iter(self.selected_cells))
            if (row, col) in LOCKED_KEYS:
                self.editor_title.set_text(f"{LOCKED_LABELS[(row, col)]}  ·  lighting")
            else:
                self.editor_title.set_text(f"Key {row},{col}")
            self._load_binding(self._active_keys().get(key_id(row, col)))
            self._load_color(row, col)
            return
        self.editor_title.set_text(f"{n} keys selected")
        if self.selected:
            self._load_color(*self.selected)

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        self._drag_start = (x, y)
        self._drag_moved = False
        self._drag_ctrl = bool(gesture.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK)

    def _on_drag_update(self, _gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if abs(dx) + abs(dy) < 10:
            return
        self._drag_moved = True
        x0, y0 = self._drag_start
        cells = self._cells_in_rect(x0, y0, x0 + dx, y0 + dy)
        if self._drag_ctrl:
            cells |= self.selected_cells
        self._paint_selection(cells, preview=True)

    def _on_drag_end(self, _gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if not self._drag_moved:
            return
        x0, y0 = self._drag_start
        cells = self._cells_in_rect(x0, y0, x0 + dx, y0 + dy)
        if self._drag_ctrl:
            cells |= self.selected_cells
        hit = self._hit_cell(x0 + dx, y0 + dy) or self._hit_cell(x0, y0)
        self._commit_selection(cells, primary=hit)
        GLib.timeout_add(50, self._clear_drag_flag)

    def _clear_drag_flag(self) -> bool:
        self._drag_moved = False
        return False

    def _hit_cell(self, x: float, y: float) -> tuple[int, int] | None:
        if not self.pad_grid:
            return None
        point = Graphene.Point()
        point.x = x
        point.y = y
        for cell, cap in self.keys.items():
            ok, bounds = cap.compute_bounds(self.pad_grid)
            if ok and bounds.contains_point(point):
                return cell
        return None

    def _cells_in_rect(self, x0: float, y0: float, x1: float, y1: float) -> set[tuple[int, int]]:
        if not self.pad_grid:
            return set()
        left, right = min(x0, x1), max(x0, x1)
        top, bottom = min(y0, y1), max(y0, y1)
        box = Graphene.Rect()
        box.init(left, top, max(1.0, right - left), max(1.0, bottom - top))
        hit: set[tuple[int, int]] = set()
        for cell, cap in self.keys.items():
            ok, bounds = cap.compute_bounds(self.pad_grid)
            if ok and bounds.intersection(box)[0]:
                hit.add(cell)
        return hit

    def _on_win_key(self, _c: Gtk.EventControllerKey, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        focus = self.get_focus()
        editable = isinstance(focus, (Gtk.Entry, Gtk.SearchEntry, Gtk.Text))
        if keyval == Gdk.KEY_Escape:
            self._commit_selection(set())
            return True
        if keyval in (Gdk.KEY_a, Gdk.KEY_A) and state & Gdk.ModifierType.CONTROL_MASK and not editable:
            self._commit_selection(set(self.keys))
            return True
        if self._record_macro:
            names = []
            if state & Gdk.ModifierType.CONTROL_MASK:
                names.append("ctrl")
            if state & Gdk.ModifierType.SHIFT_MASK:
                names.append("shift")
            if state & Gdk.ModifierType.ALT_MASK:
                names.append("alt")
            if state & Gdk.ModifierType.SUPER_MASK:
                names.append("super")
            key = Gtk.accelerator_name(keyval, 0)
            if key:
                key = key.replace("<", "").replace(">", "")
                skip = {"control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "super_l", "super_r"}
                if key.lower() not in skip:
                    names.append(key.lower() if len(key) == 1 else key.lower())
            if names:
                now = time.monotonic()
                delay = int((now - self._record_last) * 1000)
                if self._record_parts and delay > 30:
                    self._record_parts.append(f"delay:{min(delay, 2000)}")
                self._record_last = now
                self._record_parts.append("+".join(names))
                self.macro_entry.set_text(", ".join(self._record_parts))
            return True
        return False

    def _load_binding(self, binding: dict[str, Any] | None) -> None:
        self._building = True
        if not binding:
            self.label_entry.set_text("")
            self.command_entry.set_text("")
            self.combo_entry.set_text("")
            self.macro_entry.set_text("")
            self.text_entry.set_text("")
            self.profile_bind_drop.set_selected(0)
            self.url_entry.set_text("")
            self.media_drop.set_selected(0)
            self.mouse_drop.set_selected(0)
            self.light_drop.set_selected(0)
            self.hold_drop.set_selected(0)
            self.hold_profile_drop.set_selected(0)
            self.hold_entry.set_text("")
            self.repeat_hold.set_active(False)
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
        self._select_profile_drop(self.profile_bind_drop, binding.get("profile"))
        self.url_entry.set_text(binding.get("url", ""))
        self._select_catalog(self.media_drop, [i for i, _l, _k in MEDIA_KEYS], binding.get("media"))
        self._select_catalog(self.mouse_drop, [i for i, _l in MOUSE_ACTIONS], binding.get("mouse"))
        self._select_catalog(self.light_drop, [i for i, _l in LIGHT_ACTIONS], binding.get("light"))
        hold = binding.get("hold") if isinstance(binding.get("hold"), dict) else None
        self.hold_drop.set_selected(self._hold_index(hold))
        self._select_profile_drop(self.hold_profile_drop, self._hold_profile_value(hold))
        self.hold_entry.set_text(self._hold_entry_value(hold))
        self.repeat_hold.set_active(str(binding.get("repeat") or "") in {"hold", "while_held"})
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

    def _select_profile_drop(self, drop: Gtk.DropDown, name: str | None) -> None:
        """Select a profile by name in the given dropdown."""
        if not name:
            drop.set_selected(0)
            return
        model = drop.get_model()
        if not model:
            return
        for i in range(model.get_n_items()):
            item = model.get_item(i)
            if item and item.get_string() == name:
                drop.set_selected(i)
                return
        drop.set_selected(0)

    def _get_profile_drop_value(self, drop: Gtk.DropDown) -> str:
        """Get the selected profile name from a dropdown."""
        model = drop.get_model()
        if not model:
            return "default"
        idx = int(drop.get_selected() or 0)
        if idx < model.get_n_items():
            item = model.get_item(idx)
            if item:
                return item.get_string()
        return "default"

    def _hold_profile_value(self, hold: dict[str, Any] | None) -> str:
        """Get profile name from hold binding if it's a profile type."""
        if not hold:
            return ""
        if hold.get("type") == "profile":
            return hold.get("profile", "")
        return ""

    def _hold_entry_value(self, hold: dict[str, Any] | None) -> str:
        """Get non-profile hold value for the text entry."""
        if not hold:
            return ""
        kind = hold.get("type")
        if kind == "profile":
            return ""
        for key in ("combo", "media", "light", "url"):
            if hold.get(key):
                return str(hold[key])
        return ""

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
        if self._building or not self.selected_cells:
            return
        rgba = self.color_btn.get_rgba()
        hex_color = rgb_to_hex(int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
        self._push_color(hex_color)

    def _on_swatch(self, _btn: Gtk.Button, hex_color: str) -> None:
        if not self.selected_cells:
            self._toast("Select one or more keys first")
            return
        self._set_picker_hex(hex_color)
        self._push_color(hex_color)

    def _clear_color(self, *_a: object) -> None:
        if not self.selected_cells:
            return
        self._push_color(None)

    def _push_color(self, hex_color: str | None) -> None:
        self._color_undo.append(self._snapshot_colors())
        self._color_redo.clear()
        cells = list(self.selected_cells)
        if not cells and self.selected:
            cells = [self.selected]
        if not cells:
            self._toast("Select one or more keys first")
            return
        payload = [{"row": r, "col": c, "color": hex_color} for r, c in cells]
        resp = self._rpc("set_key_colors", keys=payload)
        if resp and resp.get("ok"):
            lighting = (resp.get("lighting") or self.config.get("lighting") or {})
            self.config.setdefault("lighting", {}).update(lighting)
            if "keys" in lighting:
                self.config["lighting"]["keys"] = lighting["keys"]
            for cell in cells:
                self.keys[cell].apply_led_color(hex_color)
            if self._selected_effect_id() != PER_KEY_EFFECT:
                self._building = True
                self._set_effect_id(PER_KEY_EFFECT)
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
            if self.repeat_hold.get_active():
                binding["repeat"] = "hold"
        elif kind == "text":
            binding["text"] = self.text_entry.get_text()
        elif kind == "profile":
            binding["profile"] = self._get_profile_drop_value(self.profile_bind_drop)
            if not binding["profile"]:
                self._toast("Select a profile")
                return
            if not binding["label"]:
                binding["label"] = binding["profile"]
        elif kind == "url":
            binding["url"] = self.url_entry.get_text().strip()
            if not binding["url"]:
                self._toast("Enter a URL")
                return
            if not binding["label"]:
                binding["label"] = binding["url"].split("://")[-1][:18]
        elif kind == "media":
            ident = MEDIA_KEYS[int(self.media_drop.get_selected() or 0)][0]
            binding["media"] = ident
            if not binding["label"]:
                binding["label"] = media_label(ident)
        elif kind == "mouse":
            ident = MOUSE_ACTIONS[int(self.mouse_drop.get_selected() or 0)][0]
            binding["mouse"] = ident
            if not binding["label"]:
                binding["label"] = mouse_label(ident)
        elif kind == "light":
            ident = LIGHT_ACTIONS[int(self.light_drop.get_selected() or 0)][0]
            binding["light"] = ident
            if not binding["label"]:
                binding["label"] = light_label(ident)
        hold = self._hold_binding()
        if hold:
            binding["hold"] = hold
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
        if "default" in names:
            names.remove("default")
            names.insert(0, "default")
        if idx < 0 or idx >= len(names):
            return
        name = names[idx]
        self.delete_profile_btn.set_sensitive(name != "default")
        if name != self.config.get("active_profile"):
            self._rpc("set_profile", name=name)
            self._reload()

    def _on_bright(self, scale: Gtk.Scale) -> None:
        if self._building:
            return
        self._rpc("set_lighting", brightness=int(scale.get_value()))

    def _selected_effect_id(self) -> int:
        idx = int(self.effect.get_selected() or 0)
        if 0 <= idx < len(EFFECT_IDS):
            return EFFECT_IDS[idx]
        return 1

    def _set_effect_id(self, effect_id: int) -> None:
        try:
            self.effect.set_selected(EFFECT_IDS.index(int(effect_id)))
        except ValueError:
            pass

    def _on_effect(self, *_a: object) -> None:
        if self._building:
            return
        self._rpc("set_lighting", effect=self._selected_effect_id())

    def _on_speed(self, scale: Gtk.Scale) -> None:
        if self._building:
            return
        self._rpc("set_lighting", speed=int(scale.get_value()))

    def _on_global_color(self, *_a: object) -> None:
        if self._building:
            return
        rgba = self.global_color.get_rgba()
        hex_color = rgb_to_hex(int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
        self._rpc("set_lighting", color=hex_color)

    def _on_per_key_type(self, *_a: object) -> None:
        if self._building:
            return
        self._building = True
        self._set_effect_id(PER_KEY_EFFECT)
        self._building = False
        self._rpc("set_lighting", per_key_type=int(self.per_key_type.get_selected() or 0), effect=PER_KEY_EFFECT)

    def _snapshot_colors(self) -> dict[str, str]:
        keys = (self.config.get("lighting") or {}).get("keys") or {}
        return dict(keys)

    def _undo_color(self, *_a: object) -> None:
        if not self._color_undo:
            return
        current = self._snapshot_colors()
        prev = self._color_undo.pop()
        self._color_redo.append(current)
        self._restore_colors(prev)

    def _redo_color(self, *_a: object) -> None:
        if not self._color_redo:
            return
        current = self._snapshot_colors()
        nxt = self._color_redo.pop()
        self._color_undo.append(current)
        self._restore_colors(nxt)

    def _restore_colors(self, keys: dict[str, str]) -> None:
        payload = []
        current = self._snapshot_colors()
        cells = set(current) | set(keys)
        for kid in cells:
            r, c = (int(x) for x in kid.split(",", 1))
            payload.append({"row": r, "col": c, "color": keys.get(kid)})
        if payload:
            self._rpc("set_key_colors", keys=payload)
            self._reload()

    def _select_same_color(self, *_a: object) -> None:
        if not self.selected:
            return
        target = self._key_colors().get(key_id(*self.selected))
        if not target:
            return
        cells = {parse_key_id(k) for k, v in self._key_colors().items() if v == target}
        if cells:
            self._commit_selection(cells, primary=self.selected)

    def _on_zone(self, *_a: object) -> None:
        self._mix_zone = int(self.zone_drop.get_selected() or 0)

    def _mix_paint(self, _btn: Gtk.Button, row: int, col: int) -> None:
        mix = ((self.config.get("lighting") or {}).get("mix") or {})
        regions = list(mix.get("regions") or [0] * 100)
        if len(regions) < 100:
            regions += [0] * (100 - len(regions))
        regions[row * COLS + col] = self._mix_zone
        self._rpc("set_mix", regions=regions)
        self._paint_mix()

    def _apply_mix(self, *_a: object) -> None:
        slots = []
        for zone in self.mix_slots:
            layer = []
            for slot in zone:
                idx = int(slot["effect"].get_selected() or 0)
                layer.append(
                    {
                        "effect": idx,
                        "hue": int(slot["hue"].get_value()),
                        "sat": int(slot["sat"].get_value()),
                        "speed": int(slot["speed"].get_value()),
                        "time_ms": int(slot["seconds"].get_value()) * 1000,
                    }
                )
            slots.append(layer)
        mix = ((self.config.get("lighting") or {}).get("mix") or {})
        self._rpc("set_mix", regions=mix.get("regions") or [0] * 100, slots=slots)
        self._toast("Mix RGB written")

    def _paint_mix(self) -> None:
        mix = ((self.config.get("lighting") or {}).get("mix") or {})
        regions = mix.get("regions") or [0] * 100
        for (r, c), btn in self.mix_keys.items():
            btn.remove_css_class("zone-0")
            btn.remove_css_class("zone-1")
            zone = int(regions[r * COLS + c]) if r * COLS + c < len(regions) else 0
            btn.add_css_class(f"zone-{zone}")
        slots = mix.get("slots") or []
        self._building = True
        for zi, zone in enumerate(self.mix_slots):
            layer = slots[zi] if zi < len(slots) else []
            for si, slot in enumerate(zone):
                data = layer[si] if si < len(layer) else {}
                slot["effect"].set_selected(int(data.get("effect") or 0))
                slot["hue"].set_value(int(data.get("hue") or 0))
                slot["sat"].set_value(int(data.get("sat") or 255))
                slot["speed"].set_value(int(data.get("speed") or 127))
                slot["seconds"].set_value(max(1, int(data.get("time_ms") or 5000) // 1000))
        self._building = False

    def _apply_advanced(self, *_a: object) -> None:
        hz = POLL_RATES[int(self.poll_drop.get_selected() or 0)]
        dtype = DEBOUNCE_TYPES[int(self.debounce_drop.get_selected() or 0)][0]
        self._rpc(
            "set_advanced",
            poll_hz=hz,
            debounce_type=dtype,
            debounce_ms=int(self.debounce_ms.get_value()),
            nkro=bool(self.nkro.get_active()),
            idle_dim_s=int(self.idle_dim.get_value()),
        )
        self._toast("Advanced settings written")

    def _on_page(self, *_a: object) -> None:
        want = self.stack.get_visible_child_name() == "test"
        if want == self._heatmap_ui:
            return
        self._heatmap_ui = want
        if want:
            resp = self._rpc("heatmap", active=True)
            self._apply_heatmap_hits((resp or {}).get("hits") or {})
        else:
            self._rpc("heatmap", active=False)

    def _on_close(self, *_a: object) -> bool:
        if self._heatmap_ui:
            self._heatmap_ui = False
            self._rpc("heatmap", active=False)
        return False

    def _apply_heatmap_hits(self, hits: dict[str, Any]) -> None:
        parsed: dict[tuple[int, int], int] = {}
        for kid, n in hits.items():
            try:
                parsed[parse_key_id(str(kid))] = int(n)
            except (ValueError, TypeError):
                continue
        self.test_hits = parsed
        for cell, cap in self.test_keys.items():
            self._paint_test_cell(cell, parsed.get(cell, 0), cap)

    def _paint_test_cell(self, cell: tuple[int, int], hits: int, cap: KeyCap | None = None) -> None:
        cap = cap or self.test_keys.get(cell)
        if not cap:
            return
        cap.apply_led_color(heatmap_hex(hits))
        if cap.locked:
            return
        cap.sub.set_text(str(hits) if hits else "")

    def _reset_test(self, *_a: object) -> None:
        resp = self._rpc("heatmap", reset=True)
        if resp and resp.get("ok"):
            self._apply_heatmap_hits(resp.get("hits") or {})
            return
        self.test_hits.clear()
        for cell, cap in self.test_keys.items():
            self._paint_test_cell(cell, 0, cap)

    def _toggle_record(self, *_a: object) -> None:
        self._record_macro = not self._record_macro
        if self._record_macro:
            self._record_parts = []
            self._record_last = time.monotonic()
            self.record_btn.set_label("Stop recording")
            self._toast("Recording — type on this window")
        else:
            self.record_btn.set_label("Record macro")
            if self._record_parts:
                self.macro_entry.set_text(", ".join(self._record_parts))

    def _hold_binding(self) -> dict[str, Any] | None:
        idx = int(self.hold_drop.get_selected() or 0)
        if idx <= 0:
            return None
        if idx == 1:
            profile = self._get_profile_drop_value(self.hold_profile_drop)
            return {"type": "profile", "profile": profile, "label": profile} if profile else None
        if idx == 2:
            profile = self._get_profile_drop_value(self.hold_profile_drop)
            return {"type": "profile", "profile": profile, "momentary": True, "label": profile} if profile else None
        value = self.hold_entry.get_text().strip()
        if idx == 3:
            return {"type": "combo", "combo": value, "label": value} if value else None
        if idx == 4:
            return {"type": "media", "media": value or "playpause", "label": value or "media"}
        if idx == 5:
            return {"type": "light", "light": value or "next", "label": value or "light"}
        if idx == 6:
            return {"type": "url", "url": value, "label": value} if value else None
        return None

    def _hold_index(self, hold: dict[str, Any] | None) -> int:
        if not hold:
            return 0
        kind = hold.get("type")
        if kind == "profile":
            return 2 if hold.get("momentary") else 1
        return {"combo": 3, "media": 4, "light": 5, "url": 6}.get(kind, 0)


    def _select_catalog(self, drop: Gtk.DropDown, idents: list[str], value: Any) -> None:
        if value in idents:
            drop.set_selected(idents.index(value))

    def _bind_chord(self, *_a: object) -> None:
        cells = sorted(self.selected_cells)
        if len(cells) < 2:
            self._toast("Select two or more keys first")
            return
        kind = BINDING_TYPES[int(self.type_drop.get_selected())]
        binding: dict[str, Any] = {"type": kind, "label": self.label_entry.get_text().strip() or "chord"}
        if kind == "combo":
            binding["combo"] = self.combo_entry.get_text().strip()
        elif kind == "macro":
            binding["macro"] = self.macro_entry.get_text().strip()
        elif kind == "text":
            binding["text"] = self.text_entry.get_text()
        elif kind == "media":
            binding["media"] = MEDIA_KEYS[int(self.media_drop.get_selected() or 0)][0]
        elif kind == "url":
            binding["url"] = self.url_entry.get_text().strip()
        elif kind == "command":
            binding["command"] = self.command_entry.get_text().strip()
        elif kind == "app":
            row = self.app_list.get_selected_row()
            if row is not None:
                binding["desktop_id"] = getattr(row, "app_id", "")
        else:
            self._toast("Pick combo, macro, media, url, app, or command for the chord")
            return
        chords = list(self.config.get("chords") or [])
        chords.append({"keys": [key_id(r, c) for r, c in cells], "binding": binding})
        self._rpc("set_chords", chords=chords)
        self._toast(f"Chord on {len(cells)} keys")

    def _action_save_profile_light(self, *_a: object) -> None:
        self._rpc("save_profile_lighting")
        self._toast("Lighting saved into this profile")

    def _action_clear_colors(self, *_a: object) -> None:
        self._color_undo.append(self._snapshot_colors())
        self._rpc("clear_key_colors")
        self._reload()

    def _action_export(self, *_a: object) -> None:
        dialog = Gtk.FileDialog(title="Export c100ctl config", initial_name="c100ctl.json")
        dialog.save(self, None, self._export_done)

    def _export_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        if not file:
            return
        path = file.get_path()
        if path:
            Path(path).write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
            self._toast("Exported")

    def _action_import(self, *_a: object) -> None:
        dialog = Gtk.FileDialog(title="Import c100ctl config")
        dialog.open(self, None, self._import_done)

    def _import_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if not file or not file.get_path():
            return
        try:
            data = json.loads(Path(file.get_path()).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self._toast(str(e))
            return
        if not isinstance(data, dict):
            self._toast("Not a config object")
            return
        self._rpc("import_config", config=data)
        self._reload()
        self._toast("Imported")

    def _action_provision(self, *_a: object) -> None:
        resp = self._rpc("provision", backup=True)
        if resp and resp.get("ok"):
            self._toast("Wrote unique identity keycodes to the pad (previous map backed up)")
        elif resp:
            self._toast(resp.get("error", "provision failed"))

    def _action_new_profile(self, *_a: object) -> None:
        dialog = Adw.AlertDialog(
            heading="New profile",
            body="Create a new profile cloned from the current one.",
        )
        entry = Gtk.Entry(placeholder_text="gaming")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "Create")
        dialog.set_default_response("ok")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def done(dlg, response):
            if response != "ok":
                return
            name = entry.get_text().strip().replace(" ", "-").lower()
            if not name:
                return
            if name in self.config.get("profiles", {}):
                self._toast(f"Profile '{name}' already exists")
                return
            self._rpc("ensure_profile", name=name, label=name, clone_from="__current__")
            self._rpc("set_profile", name=name)
            self._reload()
            self._toast(f"Created profile '{name}'")

        dialog.connect("response", done)
        dialog.present(self)

    def _action_delete_profile(self, *_a: object) -> None:
        active = self.config.get("active_profile", "default")
        if active == "default":
            self._toast("Cannot delete the default profile")
            return
        dialog = Adw.AlertDialog(
            heading="Delete profile",
            body=f"Delete the '{active}' profile? This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(dlg, response):
            if response != "delete":
                return
            resp = self._rpc("delete_profile", name=active)
            if resp and resp.get("ok"):
                self._reload()
                self._toast(f"Deleted profile '{active}'")
            else:
                self._toast(resp.get("error", "Delete failed") if resp else "Delete failed")

        dialog.connect("response", done)
        dialog.present(self)

    def _action_about(self, *_a: object) -> None:
        win = Adw.AboutDialog(
            application_name="C100 Control",
            version=__version__,
            developer_name="Built for Omarchy Linux",
            comments="Host-side Keychron C100 8K controller. Binds keys to apps, macros, URLs, media and lighting. Talks VIA over raw HID.",
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
            fw = (self.status.get("hardware") or {}).get("firmware") or ""
            extra = f"  ·  {fw}" if fw else ""
            self.conn_label.set_text(
                f"C100 8K  ·  VIA {self.status.get('protocol')}  ·  {self.status.get('serial', '')[:8]}{extra}"
            )
        else:
            self.conn_label.set_text("Waiting for Keychron C100 8K…")
        lighting = self.status.get("lighting") or {}
        self._building = True
        if "brightness" in lighting:
            self.bright.set_value(int(lighting["brightness"]))
        if "effect" in lighting:
            self._set_effect_id(int(lighting["effect"]))
        if "speed" in lighting:
            self.speed.set_value(int(lighting["speed"]))
        if lighting.get("color"):
            try:
                r, g, b = parse_hex_color(str(lighting["color"]))
                rgba = Gdk.RGBA()
                rgba.red, rgba.green, rgba.blue, rgba.alpha = r / 255, g / 255, b / 255, 1
                self.global_color.set_rgba(rgba)
            except ValueError:
                pass
        if "per_key_type" in lighting:
            self.per_key_type.set_selected(int(lighting["per_key_type"] or 0))
        self._building = False
        hw = self.status.get("hardware") or {}
        if hasattr(self, "fw_label"):
            self.fw_label.set_text(f"Firmware: {hw.get('firmware') or '—'}")
        adv = self.status.get("advanced") or self.config.get("advanced") or {}
        if hasattr(self, "poll_drop"):
            hz = int(adv.get("poll_hz") or 8000)
            if hz in POLL_RATES:
                self.poll_drop.set_selected(POLL_RATES.index(hz))
            self.debounce_drop.set_selected(int(adv.get("debounce_type") or 4))
            self.debounce_ms.set_value(int(adv.get("debounce_ms") or 5))
            self.nkro.set_active(bool(adv.get("nkro", True)))
            self.idle_dim.set_value(int(adv.get("idle_dim_s") or 0))

    def _apply_config(self) -> None:
        self._building = True
        names = list(self.config.get("profiles", {}).keys()) or ["default"]
        if "default" in names:
            names.remove("default")
            names.insert(0, "default")
        model = Gtk.StringList.new(names)
        self.profile_drop.set_model(model)
        active = self.config.get("active_profile", "default")
        if active in names:
            self.profile_drop.set_selected(names.index(active))
        self._refresh_profile_dropdowns(names)
        self.delete_profile_btn.set_sensitive(active != "default")
        keys = self._active_keys()
        colors = (self.config.get("lighting") or {}).get("keys") or {}
        for (r, c), cap in self.keys.items():
            cap.apply_binding(keys.get(key_id(r, c)))
            cap.apply_led_color(colors.get(key_id(r, c)))
        self._building = False
        saved = set(self.selected_cells)
        primary = self.selected
        if saved:
            self._commit_selection(saved, primary=primary)
        elif primary:
            self._commit_selection({primary}, primary=primary)
        if hasattr(self, "mix_keys"):
            self._paint_mix()

    def _refresh_profile_dropdowns(self, names: list[str]) -> None:
        """Update the bind and hold profile dropdowns with current profile names."""
        bind_model = Gtk.StringList.new(names)
        hold_model = Gtk.StringList.new(names)
        prev_bind = self._get_profile_drop_value(self.profile_bind_drop)
        prev_hold = self._get_profile_drop_value(self.hold_profile_drop)
        self.profile_bind_drop.set_model(bind_model)
        self.hold_profile_drop.set_model(hold_model)
        self._select_profile_drop(self.profile_bind_drop, prev_bind)
        self._select_profile_drop(self.hold_profile_drop, prev_hold)

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
            if self._heatmap_ui and not self.status.get("heatmap"):
                resp = self.client.request("heatmap", active=True)
                self._apply_heatmap_hits((resp or {}).get("hits") or {})
            elif not self._heatmap_ui and self.status.get("heatmap"):
                self.client.request("heatmap", active=False)
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
                visible = self.stack.get_visible_child_name() if hasattr(self, "stack") else "keys"
                if visible != "test":
                    self._select_click(cell, add=False, rect=False)
        elif ev == "heatmap":
            cell = (int(msg["row"]), int(msg["col"]))
            n = int(msg.get("count") or 0)
            self.test_hits[cell] = n
            self._paint_test_cell(cell, n)
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
