#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  The battery, in the bar. Silent on machines without one.
#
#  The colour follows the charge. It used to be the same green at 5% as at
#  100%, so the only thing that changed as a laptop ran out was two digits
#  nobody was looking at - and these are mostly old machines whose batteries do
#  not last a class. There is a desktop notification at 15% and 5%
#  (i3/scripts/battery-watch.sh), but that fires once and disappears; the bar
#  is what is on screen the whole time.
#
#  Charging is the accent colour whatever the level: a laptop at 8% on the
#  mains is not a problem, and colouring that red teaches people to ignore red.
# ─────────────────────────────────────────────────────────────────────────────
set -u

bat=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1) || exit 0
[ -n "$bat" ] || exit 0

cap=$(cat "$bat/capacity" 2>/dev/null) || exit 0
status=$(cat "$bat/status" 2>/dev/null)

# along with everything else: accent-2, then yellow, then red.
colour="#768094"

case "$status" in
    Charging) icon="󰂄" ;;
    Full)     icon="󰁹" ;;
    *)
        if   [ "$cap" -ge 90 ]; then icon="󰁹"
        elif [ "$cap" -ge 70 ]; then icon="󰂀"
        elif [ "$cap" -ge 40 ]; then icon="󰁾"
        elif [ "$cap" -ge 15 ]; then icon="󰁻"
        else                         icon="󰁺"
        fi

        if   [ "$cap" -le 10 ]; then colour="#f5a9b8"
        elif [ "$cap" -le 25 ]; then colour="#f0a030"   # AMBER
        fi
        ;;
esac

# Below the threshold the number takes the warning colour too: colouring only
# the icon left the percentage in the same dim green it always was, and the
# percentage is the half of this module people actually read.
#
# Note the endings are identical - `%s%%\n`, which prints one literal percent
# sign. Nothing follows in this module, so neither branch emits a closing
# colour tag; putting a `%{F…}` immediately after a literal `%` is how this
# script once ended up printing "77%%" in the bar.
if [ "$colour" = "#768094" ]; then
    printf '%%{F#768094}%s%%{F#8a95aa} %s%%\n' "$icon" "$cap"
else
    printf '%%{F%s}%s %s%%\n' "$colour" "$icon" "$cap"
fi
