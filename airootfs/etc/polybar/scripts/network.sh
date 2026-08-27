#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Report the active connection, preferring wireless when both are up.
#
#  NetworkManager is asked first, because it is what actually made the
#  connection and it is installed on both the live medium and an installed
#  system. `iw` is only on the live medium, so an installed machine fell
#  through to printing the interface name: the bar said "wlan0" instead of the
#  name of the network, for everybody who installed STYLUS rather than running it
#  from the USB stick.
#
#  The /sys walk stays as the fallback for a system where NetworkManager is not
#  running, which is the only case it was ever the right answer for.
# ─────────────────────────────────────────────────────────────────────────────
set -u

# nmcli translates its state column, so "connected" comes back as "conectado"
# on the Portuguese systems this is built for. The C locale keeps it matchable.
export LC_ALL=C

if command -v nmcli >/dev/null 2>&1; then
    nm_wired=""
    nm_answered=0

    while IFS= read -r line; do
        [[ -n $line ]] || continue
        nm_answered=1
        # CONNECTION is asked for last so a colon inside a connection name
        # cannot be mistaken for nmcli's own field separator.
        type=${line%%:*};  rest=${line#*:}
        state=${rest%%:*}; rest=${rest#*:}
        device=${rest%%:*}
        name=${rest#*:}
        name=${name//\\:/:}

        [[ $state == connected ]] || continue
        [[ -n ${name//[[:space:]]/} && $name != "--" ]] || name=$device

        case $type in
            wifi)     printf '%%{F#5bcefa}󰖩%%{F#7e899c} %s\n' "$name"; exit 0 ;;
            ethernet) [[ -n $nm_wired ]] || nm_wired=$name ;;
        esac
    done < <(nmcli -t -f TYPE,STATE,DEVICE,CONNECTION device status 2>/dev/null)

    if [[ -n $nm_wired ]]; then
        printf '%%{F#5bcefa}󰈀%%{F#7e899c} %s\n' "$nm_wired"
        exit 0
    fi

    # NetworkManager replied and nothing is connected. That is a real answer,
    # so report it rather than falling through and asking the kernel the same
    # question a second time.
    if (( nm_answered )); then
        printf '%%{F#f5a9b8}󰖪%%{F#7e899c} offline\n'
        exit 0
    fi
fi

# ── No NetworkManager running: read the kernel directly ──────────────────────
for dev in /sys/class/net/*; do
    iface=${dev##*/}
    [ "$iface" = lo ] && continue
    [ "$(cat "$dev/operstate" 2>/dev/null)" = up ] || continue

    if [ -d "$dev/wireless" ]; then
        ssid=""
        command -v iw >/dev/null 2>&1 &&
            ssid=$(iw dev "$iface" link 2>/dev/null | sed -n 's/^\s*SSID: //p')
        printf '%%{F#5bcefa}󰖩%%{F#7e899c} %s\n' "${ssid:-$iface}"
        exit 0
    fi
    wired=$iface
done

if [ -n "${wired:-}" ]; then
    printf '%%{F#5bcefa}󰈀%%{F#7e899c} %s\n' "$wired"
else
    printf '%%{F#f5a9b8}󰖪%%{F#7e899c} offline\n'
fi
