# C100 Control

Linux controller for the **Keychron C100 8K** 10×10 macropad. Built for [Omarchy](https://omarchy.org/) (Hyprland / Wayland), usable on any Linux desktop that can run GTK4.

Keychron Launcher remaps firmware keys in a browser. Keychron Assistant (Windows/macOS only) can launch apps. This fills the Linux gap: a native app that binds each key to an **app**, **command**, **key combination**, **macro**, or **typed text**, and keeps working after you close the window.

![C100 Control](docs/screenshot.png)

## What it talks to

The C100 enumerates as USB `3434:042c` and speaks **VIA protocol 12** on HID usage page `0xFF60`. Four corner keys are firmware lighting controls and stay that way. The other 96 keys are yours.

```
C100 8K ── USB ──► kernel hidraw / evdev
                      │
                      ├─ VIA raw HID     firmware keymap + RGB
                      └─ evdev grab      host bindings (apps / combos / macros)
```

The daemon **exclusively grabs** the C100 input nodes so pad keys never leak into the focused window (and never collide with another Keychron, such as a Q1). Combos and typed text are injected through a virtual `uinput` keyboard.

On first connect, if the pad still has the factory map (every programmable key = `KC_1`), the daemon writes a unique identity keycode to each of the 96 keys so it can tell them apart. The previous map is saved under `~/.config/c100ctl/backups/`.

## Install

Omarchy already has the Python/GTK stack. On Arch-like systems:

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita python-evdev python-pyudev hidapi
```

Then:

```bash
git clone https://github.com/rliessum/c100ctl.git
cd c100ctl
bash install.sh
```

That installs:

- `c100ctl` on your PATH (`~/.local/bin`)
- a desktop entry in the app launcher
- a systemd **user** service that starts with the graphical session

You need write access to `/dev/uinput` and to Keychron `/dev/hidraw*` nodes. A udev example lives in [`packaging/70-c100ctl.rules`](packaging/70-c100ctl.rules):

```bash
sudo cp packaging/70-c100ctl.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and replug the pad (or log out and back in if `uaccess` needs a new session).

```bash
c100ctl doctor    # hidraw, VIA, evdev, uinput, Wayland
```

## Use

```bash
c100ctl              # GUI
c100ctl status
c100ctl list

c100ctl bind 2 3 --app kitty.desktop --label Kitty
c100ctl bind 0 1 --combo 'Super+Return' --label Terminal
c100ctl bind 0 2 --command 'omarchy launch browser' --label Browser
c100ctl bind 4 4 --macro 'ctrl+c, delay:80, ctrl+v' --label Paste
c100ctl bind 5 0 --text 'hello' --label Hi
c100ctl bind 2 3 --clear

c100ctl light --brightness 200 --effect 1
c100ctl profile --create gaming
c100ctl profile --use gaming
```

In the GUI: click a cell or **press the physical key** to select it, pick an action, bind. Corner keys are locked on purpose.

Macro syntax is comma-separated steps:

- `ctrl+c` — combo
- `delay:80` — milliseconds
- `text:hello` or a bare word — typed text
- `down:shift` / `up:shift` — hold

## Files

| Path | Purpose |
|------|---------|
| `~/.config/c100ctl/config.json` | bindings and profiles |
| `~/.config/c100ctl/backups/` | VIA keymap snapshots |
| `$XDG_RUNTIME_DIR/c100ctl/c100ctl.sock` | GUI/CLI ↔ daemon |

## Uninstall

```bash
systemctl --user disable --now c100ctl.service
rm -f ~/.local/bin/c100ctl
rm -rf ~/.local/share/c100ctl
rm -f ~/.local/share/applications/c100ctl.desktop
rm -f ~/.config/systemd/user/c100ctl.service
```

## License

MIT. Keychron is a trademark of its respective owner; this project is not affiliated with Keychron.
