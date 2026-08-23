#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Wi-Fi, from the bar.
#
#  This used to open nm-connection-editor, which is a connection *editor*: it
#  lists saved profiles and their IPv6 settings, and offers no obvious way to do
#  the one thing anybody clicks a network icon for, which is join the network
#  they can see. This lists what is in range, joins on Enter, and asks for a
#  password only when it actually needs one.
#
#  rofi returns the *index* of what was picked, not its text, and the menu is
#  built as two parallel arrays. Reading the network name back out of the
#  displayed line would mean stripping icons and signal bars off it again, which
#  breaks on a name containing the same spacing - and network names in a school
#  are not chosen with a parser in mind.
# ─────────────────────────────────────────────────────────────────────────────
set -u

ROFI=(rofi -dmenu -i -format i -theme-str 'window { width: 480px; } listview { lines: 9; }')

notify() { command -v notify-send >/dev/null 2>&1 && notify-send -a STYLUS -t 4000 "Rede" "$1"; }

if ! command -v nmcli >/dev/null 2>&1; then
    notify "NetworkManager não está instalado."
    exit 0
fi

radio=$(nmcli -t radio wifi 2>/dev/null || echo disabled)

labels=()
actions=()
add() { labels+=("$1"); actions+=("$2"); }

if [[ $radio == enabled ]]; then
    # SSID is asked for last so a colon inside a network name cannot be mistaken
    # for nmcli's own field separator.
    while IFS= read -r line; do
        [[ -n $line ]] || continue
        inuse=${line%%:*};  rest=${line#*:}
        signal=${rest%%:*}; rest=${rest#*:}
        security=${rest%%:*}
        ssid=${rest#*:}
        ssid=${ssid//\\:/:}
        [[ -n ${ssid//[[:space:]]/} ]] || continue      # hidden networks

        if   (( signal >= 75 )); then bars="▂▄▆█"
        elif (( signal >= 50 )); then bars="▂▄▆ "
        elif (( signal >= 25 )); then bars="▂▄  "
        else                          bars="▂   "
        fi

        lock="  "
        [[ -n ${security//[[:space:]]/} && $security != "--" ]] && lock="󰌾 "

        if [[ $inuse == "*" ]]; then
            add "󰸞  ${ssid}   ${bars} ${lock} conectado" "disconnect:${ssid}"
        else
            add "   ${ssid}   ${bars} ${lock}" "connect:${ssid}"
        fi
    done < <(nmcli -t -f IN-USE,SIGNAL,SECURITY,SSID dev wifi list 2>/dev/null)
fi

if [[ $radio == enabled ]]; then
    add "󰖪  Desligar o Wi-Fi" "radio:off"
    add "󰑐  Procurar redes"   "rescan"
else
    add "󰖩  Ligar o Wi-Fi" "radio:on"
fi
add "󰢻  Configurações avançadas" "advanced"

index=$(printf '%s\n' "${labels[@]}" | "${ROFI[@]}" -p "rede")
[[ -n $index && $index =~ ^[0-9]+$ ]] || exit 0
action=${actions[index]:-}
[[ -n $action ]] || exit 0

case $action in
    radio:off)  nmcli radio wifi off && notify "Wi-Fi desligado." ; exit 0 ;;
    radio:on)   nmcli radio wifi on  && notify "Wi-Fi ligado."    ; exit 0 ;;
    rescan)     nmcli dev wifi rescan 2>/dev/null; sleep 2; exec "$0" ;;
    advanced)   exec nm-connection-editor ;;
    disconnect:*)
        ssid=${action#disconnect:}
        nmcli connection down id "$ssid" >/dev/null 2>&1 &&
            notify "Desconectado de ${ssid}."
        exit 0 ;;
esac

ssid=${action#connect:}
notify "Conectando a ${ssid}…"

# A network joined before has a saved profile carrying its password, so try
# that first and only ask when there is nothing to fall back on.
if nmcli -t -f NAME connection show 2>/dev/null | sed 's/\\:/:/g' | grep -qxF "$ssid"; then
    if nmcli connection up id "$ssid" >/dev/null 2>&1; then
        notify "Conectado a ${ssid}."
        exit 0
    fi
fi

# Open networks, and ones NetworkManager can already authenticate, need nothing.
if nmcli dev wifi connect "$ssid" >/dev/null 2>&1; then
    notify "Conectado a ${ssid}."
    exit 0
fi

password=$(: | rofi -dmenu -password -p "senha de ${ssid}" \
    -theme-str 'window { width: 420px; } listview { lines: 0; }')
[[ -n $password ]] || exit 0

if nmcli dev wifi connect "$ssid" password "$password" >/dev/null 2>&1; then
    notify "Conectado a ${ssid}."
else
    notify "Não foi possível conectar a ${ssid}. Verifique a senha."
fi
