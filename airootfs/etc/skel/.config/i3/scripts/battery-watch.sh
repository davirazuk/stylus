#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Warn once when the battery gets low, and again when it gets critical.
#
#  polybar shows the level, but nothing told you about it while you were looking
#  at something else. Exits immediately on machines with no battery.
# ─────────────────────────────────────────────────────────────────────────────
set -u

BAT=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1)
[[ -n $BAT ]] || exit 0

warned_low=0
warned_critical=0

while :; do
    capacity=$(cat "$BAT/capacity" 2>/dev/null) || exit 0
    status=$(cat "$BAT/status" 2>/dev/null)

    # An unreadable or empty capacity would be treated as 0 by (( )) and set off
    # a critical warning at "0%" on a perfectly healthy battery.
    [[ $capacity =~ ^[0-9]+$ ]] || { sleep 60; continue; }

    if [[ $status == Discharging ]]; then
        if (( capacity <= 10 )) && (( ! warned_critical )); then
            notify-send --app-name=STYLUS --urgency=critical \
                --hint=string:x-dunst-stack-tag:stylus-battery \
                "󰁺  Bateria crítica — ${capacity}%" \
                "Conecte o carregador agora."
            warned_critical=1
            # Crossing critical means low was crossed too, whether or not that
            # warning ever fired. Without this, a battery that fell past both
            # thresholds inside one 60s tick - or a session started already
            # critical - showed "battery critical" and then, a minute later,
            # the gentler "battery low" at the same percentage, which reads as
            # the battery having recovered.
            warned_low=1
        elif (( capacity <= 20 )) && (( ! warned_low )); then
            notify-send --app-name=STYLUS --urgency=normal \
                --hint=string:x-dunst-stack-tag:stylus-battery \
                "󰁻  Bateria baixa — ${capacity}%" \
                "Convém conectar o carregador."
            warned_low=1
        fi
    else
        # Charging again: re-arm both warnings.
        warned_low=0
        warned_critical=0
    fi

    sleep 60
done
