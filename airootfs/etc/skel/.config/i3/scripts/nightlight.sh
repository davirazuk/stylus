#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Turn the night light on and off (Mod+N).
#
#  It runs on its own from login, so this exists for the times it is in the
#  way: judging colours in a photo, a design class, or somebody who simply does
#  not like it. Killing gammastep leaves the screen warm, so the reset has to be
#  explicit - otherwise turning it "off" leaves it exactly as it was, which
#  reads as the key not working.
# ─────────────────────────────────────────────────────────────────────────────
set -u

notify() {
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a STYLUS -t 2000 \
            --hint=string:x-dunst-stack-tag:stylus-nightlight "Luz noturna" "$1"
}

command -v gammastep >/dev/null 2>&1 || exit 0

CFG="${XDG_CONFIG_HOME:-$HOME/.config}/gammastep/config.ini"

if pgrep -x gammastep >/dev/null 2>&1; then
    pkill -x gammastep
    # -x restores the screen to its normal temperature and exits.
    gammastep -x >/dev/null 2>&1
    notify "desligada"
else
    if [[ -f $CFG ]]; then
        gammastep -c "$CFG" >/dev/null 2>&1 &
    else
        gammastep >/dev/null 2>&1 &
    fi
    notify "ligada"
fi
