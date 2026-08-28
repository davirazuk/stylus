#!/usr/bin/env bash
# Silent when the machine has no bluetooth radio.
set -u

command -v bluetoothctl >/dev/null 2>&1 || exit 0
[ -d /sys/class/bluetooth ] && [ -n "$(ls -A /sys/class/bluetooth 2>/dev/null)" ] || exit 0

if bluetoothctl show 2>/dev/null | grep -q "Powered: yes"; then
    if [ -n "$(bluetoothctl devices Connected 2>/dev/null)" ]; then
        printf '%%{F#5bcefa}󰂱%%{F-}\n'
    else
        printf '%%{F#5bcefa}󰂯%%{F-}\n'
    fi
else
    printf '%%{F#768094}󰂲%%{F-}\n'
fi
