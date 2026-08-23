#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Screenshots.
#
#      screenshot.sh full      the whole screen  -> file + clipboard
#      screenshot.sh region    select an area    -> file + clipboard
#      screenshot.sh window    the active window -> file + clipboard
#      screenshot.sh clip      select an area    -> clipboard only
#
#  This was three near-identical one-liners inside the i3 config, which is why
#  there was no window mode: adding one meant writing the same chain of mkdir,
#  maim, xclip and notify-send a fourth time inside a bindsym.
#
#  The notification carries the image as its own icon, so dunst shows a
#  thumbnail of what was captured - the quickest way to see you grabbed the
#  wrong window - and offers to open it. dunst is configured to trigger a
#  notification's action on a middle click.
# ─────────────────────────────────────────────────────────────────────────────
set -u

DIR="${XDG_PICTURES_DIR:-$HOME/Pictures}/screenshots"
MODE=${1:-full}

command -v maim >/dev/null 2>&1 || {
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a STYLUS "Captura de tela" "O maim não está instalado."
    exit 1
}

notify() {  # notify <title> <body> [file]
    command -v notify-send >/dev/null 2>&1 || return 0
    local title=$1 body=$2 file=${3:-}
    if [[ -n $file ]]; then
        # --action implies --wait, so this has to run detached or the keypress
        # would appear to hang until the notification times out.
        (
            if [[ $(notify-send --app-name=STYLUS --icon="$file" \
                        --hint=string:x-dunst-stack-tag:stylus-screenshot \
                        --action=open=Abrir "$title" "$body") == open ]]; then
                xdg-open "$file" >/dev/null 2>&1
            fi
        ) >/dev/null 2>&1 &
    else
        notify-send --app-name=STYLUS \
            --hint=string:x-dunst-stack-tag:stylus-screenshot "$title" "$body"
    fi
}

to_clipboard() {
    command -v xclip >/dev/null 2>&1 || return 0
    xclip -selection clipboard -t image/png < "$1"
}

# ── Clipboard only ───────────────────────────────────────────────────────────
if [[ $MODE == clip ]]; then
    tmp=$(mktemp --suffix=.png) || exit 1
    if maim -s "$tmp" 2>/dev/null && [[ -s $tmp ]]; then
        to_clipboard "$tmp"
        notify "Captura de tela" "Copiada para a área de transferência."
    fi
    # xclip needs the data to outlive this script, so it is read into the
    # clipboard above before the file goes; give it a moment, then clean up.
    ( sleep 2; rm -f "$tmp" ) >/dev/null 2>&1 &
    exit 0
fi

# ── Saved to a file ──────────────────────────────────────────────────────────
mkdir -p "$DIR" || exit 1
FILE="$DIR/$(date +%F_%H-%M-%S).png"

case $MODE in
    full)   maim "$FILE" 2>/dev/null ;;
    region) maim -s "$FILE" 2>/dev/null ;;
    window)
        # Fall back to the whole screen when there is no focused window to
        # capture, rather than handing maim an empty -i and having the keypress
        # quietly do nothing.
        win=""
        command -v xdotool >/dev/null 2>&1 && win=$(xdotool getactivewindow 2>/dev/null)
        if [[ -n $win ]]; then
            maim -i "$win" "$FILE" 2>/dev/null
        else
            maim "$FILE" 2>/dev/null
        fi ;;
    *) echo "usage: screenshot.sh {full|region|window|clip}" >&2; exit 1 ;;
esac

# A cancelled selection is not a failure: maim exits non-zero and leaves either
# nothing or an empty file, and there is nothing to report.
[[ -s $FILE ]] || { rm -f "$FILE"; exit 0; }

to_clipboard "$FILE"
# The tilde has to be escaped: unquoted, bash expands it straight back to $HOME
# and the path is printed in full, which is what it was doing.
notify "Captura de tela" "Salva em ${FILE/#$HOME/\~}" "$FILE"
