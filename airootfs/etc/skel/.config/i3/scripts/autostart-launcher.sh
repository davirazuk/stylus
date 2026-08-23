#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Open the launcher when the desktop session starts.
#
#  Two cases have to be left alone, which is why this is a script rather than a
#  plain exec line in the i3 config:
#
#  Live media. The welcome screen there offers to install STYLUS, and that is the
#  entire point of booting the USB stick. A fullscreen launcher on top of it
#  would bury the installer behind a window most people would not think to
#  close.
#
#  The first login on an installed machine. The welcome screen shows its
#  first-run tips once and then never again; covering it on the one occasion it
#  appears would mean nobody ever reads it. From the second login on, the
#  launcher opens normally.
#
#  Not wanted at all? Delete the matching exec line from ~/.config/i3/config.
#  Nothing else depends on it, and Mod+G still opens the launcher by hand.
# ─────────────────────────────────────────────────────────────────────────────
set -u

command -v stylus-ui >/dev/null || exit 0

# Live media: the installer offer comes first.
[[ -d /run/archiso ]] && exit 0

# First login: let the welcome screen have the screen to itself.
STAMP="${XDG_CONFIG_HOME:-$HOME/.config}/stylus/welcome-done"
[[ -e $STAMP ]] || exit 0

exec stylus-ui
