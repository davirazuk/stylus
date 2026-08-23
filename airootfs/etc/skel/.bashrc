#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias ll='ls -lah --color=auto'
alias grep='grep --color=auto'
alias update='sudo pacman -Syu'
alias install='sudo pacman -S'
alias search='pacman -Ss'

PS1='[\u@\h \W]\$ '

# Qt applications follow the same dark theme as GTK ones. One variable, two Qt
# majors with separate plugin directories: "qt5ct" is a Qt5-only plugin, so
# every Qt6 program ignored it and came up light. The GTK platform theme serves
# both, when it is installed. Session-wide values live in ~/.xprofile; these
# cover terminal-launched apps.
if [ -e /usr/lib/qt6/plugins/platformthemes/libqgtk3.so ] &&
   [ -e /usr/lib/qt/plugins/platformthemes/libqgtk3.so ]; then
    export QT_QPA_PLATFORMTHEME=gtk3
else
    export QT_QPA_PLATFORMTHEME=qt5ct
fi
export EDITOR=vim
export VISUAL=vim

[[ -f /usr/share/bash-completion/bash_completion ]] && . /usr/share/bash-completion/bash_completion

command -v fastfetch >/dev/null && fastfetch
