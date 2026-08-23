#!/usr/bin/env bash
# STYLUS power menu — replaces i3's unconfirmed "$mod+Shift+e kills your session".
set -u

# Font Awesome 4.7, the block JetBrainsMono Nerd Font carries and the same one
# the bar uses - its power button is this same glyph. Every label here was two
# spaces and a word: no icon had ever been committed, so the menu was a list of
# bare English words on a Portuguese system.
# O MODO MÚSICA vem primeiro, e antes de "Bloquear", porque não é uma forma
# de encerrar: é a outra metade da máquina. Estava só num atalho de três
# teclas (Mod+Ctrl+M) e num ícone sem legenda na barra — escondido de quem
# não leu o código. Este menu é onde se procura "sair daqui", e voltar para
# a música É sair daqui.
musica="  Modo música"
lock="  Bloquear"
logout="  Sair da sessão"
suspend="  Suspender"
reboot="  Reiniciar"
shutdown="  Desligar"

chosen=$(printf '%s\n' "$musica" "$lock" "$logout" "$suspend" "$reboot" "$shutdown" |
    rofi -dmenu -i -p "Sessão" -theme-str 'listview { lines: 6; } window { width: 320px; }')

case "$chosen" in
    "$musica")   exec stylus-mode music ;;
    "$lock")     ~/.config/i3/scripts/lock.sh ;;
    "$logout")   i3-msg exit ;;
    "$suspend")  systemctl suspend ;;
    "$reboot")   systemctl reboot ;;
    "$shutdown") systemctl poweroff ;;
esac
