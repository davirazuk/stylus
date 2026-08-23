#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Bluetooth, from the bar.
#
#  blueman-manager is a full device manager - adapters, profiles, a tree of
#  services - when what someone wants from the bar is to turn their headphones
#  on. Paired devices are listed here and connect on Enter; blueman is still one
#  entry away for pairing something new or anything unusual.
#
#  Same index-based selection as the network menu: device names come from the
#  hardware and are not safe to parse back out of a menu line.
# ─────────────────────────────────────────────────────────────────────────────
set -u

ROFI=(rofi -dmenu -i -format i -theme-str 'window { width: 460px; } listview { lines: 8; }')

notify() { command -v notify-send >/dev/null 2>&1 && notify-send -a STYLUS -t 4000 "Bluetooth" "$1"; }

if ! command -v bluetoothctl >/dev/null 2>&1; then
    notify "O bluetoothctl não está instalado."
    exit 0
fi

# No radio at all: say so once rather than opening an empty menu.
if [[ ! -d /sys/class/bluetooth ]] || [[ -z "$(ls -A /sys/class/bluetooth 2>/dev/null)" ]]; then
    notify "Este computador não tem bluetooth."
    exit 0
fi

powered=no
bluetoothctl show 2>/dev/null | grep -q "Powered: yes" && powered=yes

# Four parallel arrays rather than packing fields into one string: a MAC address
# is full of colons and a device name is whatever the manufacturer typed, so
# there is no separator that is safe to split on afterwards.
labels=()
actions=()
macs=()
names=()
add() { labels+=("$1"); actions+=("$2"); macs+=("${3-}"); names+=("${4-}"); }

if [[ $powered == yes ]]; then
    # "Connected" is per-device, so ask about each paired one rather than
    # trusting the order of two separate listings to line up.
    while IFS= read -r line; do
        [[ $line == Device* ]] || continue
        mac=${line#Device }
        name=${mac#* }
        mac=${mac%% *}
        [[ -n $mac ]] || continue

        if bluetoothctl info "$mac" 2>/dev/null | grep -q "Connected: yes"; then
            add "󰂱  ${name}   conectado" disconnect "$mac" "$name"
        else
            add "󰂯  ${name}" connect "$mac" "$name"
        fi
    done < <(bluetoothctl devices Paired 2>/dev/null)

    add "󰂲  Desligar o bluetooth" power-off
    add "󰑐  Procurar dispositivos" scan
else
    add "󰂯  Ligar o bluetooth" power-on
fi
add "󰢻  Gerenciador de dispositivos" manager

index=$(printf '%s\n' "${labels[@]}" | "${ROFI[@]}" -p "bluetooth")
[[ -n $index && $index =~ ^[0-9]+$ ]] || exit 0
action=${actions[index]:-}
[[ -n $action ]] || exit 0

mac=${macs[index]:-}
name=${names[index]:-}

case $action in
    power-on)
        bluetoothctl power on >/dev/null 2>&1 && notify "Bluetooth ligado."
        exit 0 ;;
    power-off)
        bluetoothctl power off >/dev/null 2>&1 && notify "Bluetooth desligado."
        exit 0 ;;
    manager)
        command -v blueman-manager >/dev/null 2>&1 && exec blueman-manager
        notify "O blueman não está instalado."
        exit 0 ;;
    scan)
        # Pairing needs a PIN prompt and an agent; blueman already does that
        # properly, so discovery hands over rather than reimplementing it.
        notify "Procurando dispositivos…"
        bluetoothctl --timeout 10 scan on >/dev/null 2>&1 &
        if command -v blueman-manager >/dev/null 2>&1; then
            exec blueman-manager
        fi
        wait
        exec "$0" ;;
esac

[[ -n $mac ]] || exit 0

case $action in
    connect)
        notify "Conectando a ${name}…"
        if bluetoothctl connect "$mac" >/dev/null 2>&1; then
            notify "Conectado a ${name}."
        else
            notify "Não foi possível conectar a ${name}."
        fi ;;
    disconnect)
        bluetoothctl disconnect "$mac" >/dev/null 2>&1 &&
            notify "Desconectado de ${name}."  ;;
esac
