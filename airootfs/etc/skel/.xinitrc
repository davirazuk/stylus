#!/bin/sh
# Fallback path: if the display manager is unavailable, `startx` still gets you
# into the STYLUS desktop.

[ -f /etc/xprofile ] && . /etc/xprofile
[ -f "$HOME/.xprofile" ] && . "$HOME/.xprofile"

if [ -d /etc/X11/xinit/xinitrc.d ]; then
    for f in /etc/X11/xinit/xinitrc.d/?*.sh; do
        [ -x "$f" ] && . "$f"
    done
    unset f
fi

exec i3
