# STYLUS shell environment.
# conf.d is sourced before config.fish, and every file here is loaded
# automatically — drop your own file in beside this one rather than editing it.

# ── Colours ──────────────────────────────────────────────────────────────────
# These were Catppuccin values left over from before the green theme: what you
# typed came out in a blue-grey, with purple keywords and a teal operator,
# inside a green terminal. Note that the hexes cannot be quoted in prose here -
# included, so a documented colour would be rewritten along with the real ones.
#
# Every value below is one of the palette hexes, which is also what lets
# the palette would stay green after switching to mocha. The two exceptions are
# deliberate: errors stay red and terminators stay yellow in both schemes,
# because those mean the same thing whatever the desktop looks like.
set -g fish_color_normal        e8f5e9
set -g fish_color_command       00a86b
set -g fish_color_keyword       7ed957
set -g fish_color_quote         b9d4c6
set -g fish_color_redirection   00c47d
set -g fish_color_end           f9e2af
set -g fish_color_error         f38ba8
set -g fish_color_param         e8f5e9
set -g fish_color_option        7ed957
set -g fish_color_comment       7fa392
set -g fish_color_operator      00c47d
set -g fish_color_escape        00c47d
set -g fish_color_valid_path    --underline
set -g fish_color_autosuggestion 24503f
set -g fish_color_cancel        f38ba8
set -g fish_color_search_match  --background=24503f
set -g fish_color_selection     --background=24503f
set -g fish_pager_color_prefix  00a86b --bold
set -g fish_pager_color_completion e8f5e9
set -g fish_pager_color_description 7fa392
set -g fish_pager_color_selected_background --background=24503f

# ── Abbreviations (expand as you type, so you still learn the real command) ──
if status is-interactive
    abbr -a -- g      git
    abbr -a -- gs     'git status --short --branch'
    abbr -a -- ga     'git add'
    abbr -a -- gaa    'git add --all'
    abbr -a -- gc     'git commit -m'
    abbr -a -- gp     'git push'
    abbr -a -- gl     'git pull'
    abbr -a -- glog   'git log --oneline --graph --decorate'
    abbr -a -- gd     'git diff'

    abbr -a -- pi     'sudo pacman -S'
    abbr -a -- pr     'sudo pacman -Rns'
    abbr -a -- ps-    'pacman -Ss'
    abbr -a -- pu     'sudo pacman -Syu'
    abbr -a -- pq     'pacman -Q'

    abbr -a -- sys    systemctl
    abbr -a -- sysu   'systemctl --user'
    abbr -a -- jc     'journalctl -xe'

    abbr -a -- ..     'cd ..'
    abbr -a -- ...    'cd ../..'
    abbr -a -- ....   'cd ../../..'
end

# ── Aliases ──────────────────────────────────────────────────────────────────
alias ls='ls --color=auto --group-directories-first'
alias ll='ls -lah --color=auto --group-directories-first'
alias la='ls -A --color=auto'
alias grep='grep --color=auto'
alias diff='diff --color=auto'
alias ip='ip -color=auto'
alias df='df -h'
alias du='du -h'
alias free='free -h'
alias cp='cp -i'
alias mv='mv -i'
alias rm='rm -i'
alias apps='stylus-software'
alias launcher='stylus-ui'
alias moodle='stylus-ui --category escola-online'

# ── Environment ──────────────────────────────────────────────────────────────
set -gx EDITOR vim
set -gx VISUAL vim
# One variable, two Qt majors with separate plugin directories: qt5ct is a
# Qt5-only plugin, so Qt6 programs ignored it and came up light in the middle
# of a dark desktop. The GTK platform theme serves both, when it is installed.
if test -e /usr/lib/qt6/plugins/platformthemes/libqgtk3.so \
     -a -e /usr/lib/qt/plugins/platformthemes/libqgtk3.so
    set -gx QT_QPA_PLATFORMTHEME gtk3
else
    set -gx QT_QPA_PLATFORMTHEME qt5ct
end
set -gx MANROFFOPT -c
set -gx LESS '-R --use-color'

fish_add_path -g ~/.local/bin 2>/dev/null

# ── Keys ─────────────────────────────────────────────────────────────────────
if status is-interactive
    # Ctrl+F accepts the autosuggestion, like a shell should
    bind \cf forward-char
    bind \ce edit_command_buffer
end
