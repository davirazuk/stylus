#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  What is playing, in the bar.
#
#      media.sh              follow the player and print each change
#      media.sh toggle       play / pause
#      media.sh next|prev    skip
#
#  Event-driven, not polled. Asking every two seconds meant starting playerctl
#  up to three times a run - around ninety processes a minute, forever, on a
#  machine that is usually playing nothing at all. `playerctl --follow` is one
#  process that blocks until something actually changes, and polybar reads its
#  output with `tail = true`.
#
#  The bar entry also carries `exec-if`, so on a machine with no playerctl this
#  script is never started in the first place.
#
#  Fields are separated by a unit separator (0x1F) rather than a dash or a pipe.
#  Track titles contain every printable character sooner or later, and a song
#  called "Either/Or | Live" should not be able to confuse the split.
# ─────────────────────────────────────────────────────────────────────────────
set -u

MAX=38            # characters before the title is cut short
SEP=$'\x1f'

command -v playerctl >/dev/null 2>&1 || exit 0

case ${1:-show} in
    toggle) playerctl play-pause 2>/dev/null; exit 0 ;;
    next)   playerctl next       2>/dev/null; exit 0 ;;
    prev)   playerctl previous   2>/dev/null; exit 0 ;;
esac

render() {
    local status=$1 artist=$2 title=$3 icon text

    case $status in
        Playing) icon="󰐊" ;;
        Paused)  icon="󰏤" ;;
        *)       printf '\n'; return ;;    # Stopped, or no player: clear the module
    esac

    # Artist is often missing on a video or a stream, so fall back to the title
    # alone rather than printing a stray dash.
    if [[ -n ${artist//[[:space:]]/} ]]; then
        text="${artist} — ${title}"
    else
        text="$title"
    fi

    if [[ -z ${text//[[:space:]]/} ]]; then
        printf '\n'
        return
    fi

    # Trim on characters, not bytes: accented titles are the norm here and
    # cutting mid-character would leave a broken glyph in the bar.
    (( ${#text} > MAX )) && text="${text:0:MAX-1}…"

    printf '%%{F#f0a030}%s%%{F#7e899c} %s\n' "$icon" "$text"
}

# --follow keeps running across players starting and stopping, and prints a
# blank line when the last one goes away, which clears the module.
playerctl --follow --format "{{status}}${SEP}{{artist}}${SEP}{{title}}" metadata 2>/dev/null |
while IFS=$SEP read -r status artist title; do
    render "${status:-}" "${artist:-}" "${title:-}"
done
