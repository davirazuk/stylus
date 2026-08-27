#!/usr/bin/env bash
# STYLUS power menu — replaces i3's unconfirmed "$mod+Shift+e kills your session".
set -u

# O MODO MÚSICA vem primeiro, e antes de "Bloquear", porque não é uma forma
# de encerrar: é a outra metade da máquina. Este menu é onde se procura
# "sair da aqui", e voltar para a música É sair daqui.
musica="  Modo música"
lock="  Bloquear"
logout="  Sair da sessão"
suspend="  Suspender"
reboot="  Reiniciar"
shutdown="  Desligar"

chosen=$(printf '%s\n' "$musica" "$lock" "$logout" "$suspend" "$reboot" "$shutdown" |
    rofi -dmenu -i -p "Sessão" -theme ~/.config/rofi/stylus.rasi \
    -theme-str 'listview { lines: 6; } window { width: 320px; }')

case "$chosen" in
    "$musica")   exec stylus-mode music ;;
    "$lock")     ~/.config/i3/scripts/lock.sh ;;
    "$logout")   i3-msg exit ;;
    "$suspend")  systemctl suspend ;;
    "$reboot")   systemctl reboot ;;
    "$shutdown") systemctl poweroff ;;
esac
