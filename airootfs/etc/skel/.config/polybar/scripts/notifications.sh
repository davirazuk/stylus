#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Notifications, in the bar.
#
#  A notification that times out is gone. Everything the machine has to say -
#  the battery warning, the disk warning, the graphics check, the "reinicie
#  depois de instalar o driver" - appears for eight seconds in a corner and
#  then does not exist anywhere. Somebody who was looking away, or typing, or
#  in a game, never sees it, and there is nothing on the screen that admits a
#  message was ever shown.
#
#  So the bell keeps a count and the history is one click away. The bell also
#  says when notifications are switched off, because the failure it prevents is
#  the opposite one: turning them off before a presentation and forgetting.
#
#  Event-driven. dunst publishes historyLength, waitingLength and paused as
#  D-Bus properties and emits PropertiesChanged when any of them moves, so the
#  bar follows the actual state instead of asking every few seconds. Reading
#  goes through busctl rather than dunstctl, which is a shell script: starting
#  one to read one number is what makes polling expensive.
# ─────────────────────────────────────────────────────────────────────────────
set -u

DEST=org.freedesktop.Notifications
OBJECT=/org/freedesktop/Notifications
IFACE=org.dunstproject.cmd0

ICON_BELL=""       # U+F0F3 — Font Awesome 4.7, carried by both bar fonts
ICON_MUTED=""      # U+F1F6

prop() {   # prop <name> — the value, bare
    busctl --user get-property "$DEST" "$OBJECT" "$IFACE" "$1" 2>/dev/null |
        awk '{print $2}' | tr -d '"'
}

label() {
    local paused count
    paused=$(prop paused)
    count=$(prop historyLength)
    [[ $count =~ ^[0-9]+$ ]] || count=0

    if [[ $paused == true ]]; then
        # Yellow, and it stays on the bar with nothing behind it: silence is
        # a state worth seeing, not the absence of one.
        printf '%%{F#f0bd76}%s%%{F#768094}' "$ICON_MUTED"
        (( count )) && printf ' %s' "$count"
        printf '\n'
        return
    fi

    if (( count )); then
        printf '%%{F#5bcefa}%s%%{F#768094} %s\n' "$ICON_BELL" "$count"
    else
        # Nothing waiting: the bell in the dim colour, so the click target is
        # still there without drawing attention to itself.
        printf '%%{F#768094}%s\n' "$ICON_BELL"
    fi
}

# ── Clicks ───────────────────────────────────────────────────────────────────
case ${1:-} in
    --toggle)
        command -v dunstctl >/dev/null 2>&1 || exit 0
        dunstctl set-paused toggle
        # Said out loud, because switching notifications off silently is how
        # somebody spends a day wondering why nothing ever tells them anything.
        if [[ $(dunstctl is-paused) == true ]]; then
            notify-send -a STYLUS -t 2000 "Notificações desligadas" \
                "Clique de novo no sino para religar." 2>/dev/null
        else
            notify-send -a STYLUS -t 2000 "Notificações ligadas" "" 2>/dev/null
        fi
        exit 0 ;;
esac

# ── Display ──────────────────────────────────────────────────────────────────
command -v busctl >/dev/null 2>&1 || exit 0

last=""
emit() {
    local now; now=$(label)
    [[ $now == "$last" ]] && return 0
    last=$now
    printf '%s\n' "$now"
}

emit

# Without gdbus there is nothing to listen with. Print the one value and stop;
# polybar keeps the last line on the bar, which is better than a blank gap.
command -v gdbus >/dev/null 2>&1 || exit 0

gdbus monitor --session --dest "$DEST" 2>/dev/null |
while IFS= read -r line; do
    case $line in
        # Every one of these moves a count: a new notification, one closed, one
        # dropped into history, or the pause state flipped.
        *PropertiesChanged*|*NotificationClosed*|*Notify*) emit ;;
    esac
done
