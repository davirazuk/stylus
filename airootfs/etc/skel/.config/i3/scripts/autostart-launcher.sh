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
#  Not wanted at all? Delete the matching exec line from ~/.config/i3/config.
#  Nothing else depends on it, and Mod+G still opens the launcher by hand.
# ─────────────────────────────────────────────────────────────────────────────
set -u

command -v stylus-ui >/dev/null || exit 0

# Live media: the desktop mode of the USB stick is where somebody goes to
# partition a disk or look at hardware before installing, so it stays a plain
# desktop. Music mode - which is what the medium actually boots into - is the
# full-screen shelf already.
[[ -d /run/archiso ]] && exit 0

# This used to also require a `welcome-done` stamp, written by a stylus-welcome
# that does not exist in this distribution. The file was therefore never
# created, the test never passed, and the launcher this line exists to open
# never once opened by itself on any machine.
exec stylus-ui
