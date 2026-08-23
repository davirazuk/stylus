#!/usr/bin/env bash
# STYLUS power menu — replaces i3's unconfirmed "$mod+Shift+e kills your session".
set -u

# Font Awesome 4.7, the block JetBrainsMono Nerd Font carries and the same one
# the bar uses - its power button is this same glyph. Every label here was two
# spaces and a word: no icon had ever been committed, so the menu was a list of
# bare English words on a Portuguese system.
lock="  Bloquear"
logout="  Sair da sessão"
suspend="  Suspender"
reboot="  Reiniciar"
shutdown="  Desligar"

chosen=$(printf '%s\n' "$lock" "$logout" "$suspend" "$reboot" "$shutdown" |
    rofi -dmenu -i -p "Energia" -theme-str 'listview { lines: 5; } window { width: 320px; }')

case "$chosen" in
    "$lock")     ~/.config/i3/scripts/lock.sh ;;
    "$logout")   i3-msg exit ;;
    "$suspend")  systemctl suspend ;;
    "$reboot")   systemctl reboot ;;
    "$shutdown") systemctl poweroff ;;
esac
