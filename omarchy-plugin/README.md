# C100 Profiles

An Omarchy bar widget for quick profile switching on the Keychron C100 8K macropad.

## Install

Copy or symlink this folder to your Omarchy plugins directory:

```sh
cp -r omarchy-plugin ~/.config/omarchy/plugins/io.github.rliessum.c100ctl
# or symlink:
ln -s /path/to/c100ctl/omarchy-plugin ~/.config/omarchy/plugins/io.github.rliessum.c100ctl
```

Enable the plugin and reload the shell:

```sh
omarchy plugin enable io.github.rliessum.c100ctl
omarchy-shell shell rescanPlugins
```

## Usage

Click the profile name in the bar to open the panel. Select a profile to switch, or click "Configure pad" to open the full GTK configurator. Press Escape to close.

## Requirements

- The `c100ctl` daemon must be running (`c100ctl daemon` or the systemd user service)
- `c100ctl` must be on your PATH (`~/.local/bin/c100ctl` or `/usr/bin/c100ctl`)

## Configure

Move the widget to a different bar section:

```sh
omarchy bar move io.github.rliessum.c100ctl --section left
```

## Remove

```sh
omarchy plugin remove io.github.rliessum.c100ctl
# or if symlinked:
rm ~/.config/omarchy/plugins/io.github.rliessum.c100ctl
```
