#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  STYLUS — central de notificações
#
#  dunst keeps a history and has always been able to show it again, through
#  `dunstctl history-pop`, which pops the most recent one. That is not a place
#  to read what the machine said an hour ago: it is a command nobody knows,
#  which reveals one message at a time, in reverse, with no way to look at the
#  list.
#
#  This is the list. Every notification still in history, newest first, with
#  the application and how long ago it arrived - and above them the two things
#  a person actually wants from a notification centre: silence, and a way to
#  clear the lot.
#
#  Picking one shows it again, so its buttons work: the graphics check sends a
#  notification whose action opens the repair, and that action is still there
#  after the notification has timed out.
# ─────────────────────────────────────────────────────────────────────────────
set -u

command -v dunstctl >/dev/null 2>&1 || {
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a STYLUS "Central de notificações" "O dunst não está em execução."
    exit 1
}

ICON_MUTE=""       # U+F186 moon — silence
ICON_UNMUTE=""     # U+F0F3 bell
ICON_CLEAR=""      # U+F1F8 trash

paused=$(dunstctl is-paused 2>/dev/null)

if [[ $paused == true ]]; then
    toggle_label="  $ICON_UNMUTE  Religar as notificações"
else
    toggle_label="  $ICON_MUTE  Não perturbe"
fi
clear_label="  $ICON_CLEAR  Limpar o histórico"

# ── The history ──────────────────────────────────────────────────────────────
#  dunstctl answers in JSON. Parsed with python rather than jq, which is not
#  installed and would be a dependency for one command; python is already here
#  for the launcher. One line per notification, tab-separated: the id is what
#  gets popped, the rest is what gets read.
entries=$(dunstctl history 2>/dev/null | python3 -c '
import json, sys, time

try:
    data = json.load(sys.stdin)
except (ValueError, OSError):
    sys.exit(0)

# {"type":"aa{sv}","data":[[ {...}, {...} ]]}
rows = []
for group in data.get("data", []):
    rows.extend(group)


def value(entry, key):
    """dunst wraps every field as {"type": ..., "data": ...}."""
    field = entry.get(key)
    if isinstance(field, dict):
        return field.get("data", "")
    return field if field is not None else ""


def ago(microseconds):
    """dunst timestamps are microseconds since boot, not since the epoch."""
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            uptime = float(handle.read().split()[0])
    except (OSError, ValueError):
        return ""
    seconds = int(uptime - microseconds / 1_000_000)
    if seconds < 0:
        return ""
    if seconds < 60:
        return "agora"
    if seconds < 3600:
        return "%d min" % (seconds // 60)
    if seconds < 86400:
        return "%d h" % (seconds // 3600)
    return "%d d" % (seconds // 86400)


def flatten(text):
    """One line, and no markup: dunst bodies may carry Pango tags."""
    import re
    text = re.sub(r"<[^>]+>", "", str(text))
    return " ".join(text.split())


for entry in rows:
    ident = value(entry, "id")
    summary = flatten(value(entry, "summary"))
    body = flatten(value(entry, "body"))
    appname = flatten(value(entry, "appname"))
    when = ago(value(entry, "timestamp") or 0)
    if not summary and not body:
        continue
    print("\t".join(str(x) for x in (ident, when, appname, summary, body)))
' 2>/dev/null)

menu=$(printf '%s\n' "$toggle_label" "$clear_label")

if [[ -n $entries ]]; then
    # A blank separator row, so the two commands do not read as the first two
    # notifications. It is selectable and does nothing, which is the price of
    # rofi having no separator.
    menu+=$'\n'"────────────────────────────"
    while IFS=$'\t' read -r _id when appname summary body; do
        [[ -n $summary || -n $body ]] || continue
        line="$summary"
        [[ -n $body ]] && line+=" — $body"
        # Long enough to recognise, short enough not to make the menu as wide
        # as the screen.
        (( ${#line} > 90 )) && line="${line:0:89}…"
        prefix="$when"
        [[ -n $appname && $appname != "STYLUS" ]] && prefix="$when · $appname"
        menu+=$'\n'"  ${prefix}   $line"
    done <<<"$entries"
else
    menu+=$'\n'"────────────────────────────"$'\n'"  Nada por aqui."
fi

chosen=$(printf '%s\n' "$menu" |
    rofi -dmenu -i -p "Notificações" \
         -theme-str 'listview { lines: 12; } window { width: 720px; }')

[[ -n $chosen ]] || exit 0

case $chosen in
    "$toggle_label")
        dunstctl set-paused toggle
        exit 0 ;;
    "$clear_label")
        dunstctl history-clear
        exit 0 ;;
    "────────────────────────────"|"  Nada por aqui.")
        exit 0 ;;
esac

# A notification was picked: show it again, by id, so its actions come back
# with it. Matched on the line rather than kept in an array, because rofi hands
# back text and nothing else.
while IFS=$'\t' read -r id when appname summary body; do
    line="$summary"
    [[ -n $body ]] && line+=" — $body"
    (( ${#line} > 90 )) && line="${line:0:89}…"
    prefix="$when"
    [[ -n $appname && $appname != "STYLUS" ]] && prefix="$when · $appname"
    if [[ $chosen == "  ${prefix}   $line" ]]; then
        dunstctl history-pop "$id" 2>/dev/null || dunstctl history-pop
        exit 0
    fi
done <<<"$entries"
