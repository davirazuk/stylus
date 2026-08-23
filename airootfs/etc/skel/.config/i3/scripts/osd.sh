#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  On-screen display for the hardware keys.
#
#  The volume and brightness keys used to work silently - you pressed them and
#  nothing on screen acknowledged it. This adjusts the value and then replaces
#  a single stacked notification with a progress bar, the way a desktop
#  environment does.
# ─────────────────────────────────────────────────────────────────────────────
set -u

notify() {   # notify <tag> <icon> <label> [value]
    local tag=$1 icon=$2 label=$3 value=${4:-}
    local -a args=(
        --app-name=STYLUS
        --urgency=low
        --hint="string:x-dunst-stack-tag:$tag"
        --expire-time=2500
    )
    [[ -n $value ]] && args+=(--hint="int:value:$value")
    notify-send "${args[@]}" "$icon  $label"
}

# Font Awesome 4.7 codepoints, the same block the bar and fastfetch use, and
# one JetBrainsMono Nerd Font carries. Every one of these used to be an empty
# string: pressing a volume key produced a notification that began with a blank
# space where the icon belongs. Font Awesome has three speaker glyphs, not
# five, so the quiet levels share one - mute is told apart by its label
# ("Som mudo") rather than by having its own picture.
ICON_VOL_OFF=''      # volume-off
ICON_VOL_LOW=''      # volume-down
ICON_VOL_HIGH=''     # volume-up
ICON_MIC_ON=''       # microphone
ICON_MIC_OFF=''      # microphone-slash
ICON_BRIGHT=''       # sun

volume_icon() {
    local v=$1 muted=$2
    if [[ $muted == true ]]; then printf '%s' "$ICON_VOL_OFF"
    elif   (( v == 0 ));   then printf '%s' "$ICON_VOL_OFF"
    elif   (( v < 67 ));   then printf '%s' "$ICON_VOL_LOW"
    else                        printf '%s' "$ICON_VOL_HIGH"
    fi
}

case ${1:-} in
    vol-up)    pamixer --allow-boost -i 5 ;;
    vol-down)  pamixer --allow-boost -d 5 ;;
    vol-mute)  pamixer -t ;;
    mic-mute)  pamixer --default-source -t ;;
    bright-up)   brightnessctl -q set 5%+ ;;
    bright-down) brightnessctl -q set 5%- ;;
    *) echo "usage: osd.sh {vol-up|vol-down|vol-mute|mic-mute|bright-up|bright-down}" >&2
       exit 1 ;;
esac

case ${1} in
    vol-*|mic-mute)
        if [[ $1 == mic-mute ]]; then
            muted=$(pamixer --default-source --get-mute 2>/dev/null || echo false)
            if [[ $muted == true ]]; then
                notify stylus-osd-mic "$ICON_MIC_OFF" "Microfone mudo"
            else
                notify stylus-osd-mic "$ICON_MIC_ON" "Microfone ligado"
            fi
            exit 0
        fi
        vol=$(pamixer --get-volume 2>/dev/null || echo 0)
        muted=$(pamixer --get-mute 2>/dev/null || echo false)
        if [[ $muted == true ]]; then
            notify stylus-osd-vol "$(volume_icon "$vol" true)" "Som mudo" 0
        else
            notify stylus-osd-vol "$(volume_icon "$vol" false)" "Volume  ${vol}%" "$vol"
        fi
        ;;
    bright-*)
        # brightnessctl reports raw values; turn them into a percentage.
        cur=$(brightnessctl -m 2>/dev/null | cut -d, -f4 | tr -d '%')
        [[ -z $cur ]] && cur=0
        notify stylus-osd-bright "$ICON_BRIGHT" "Brilho  ${cur}%" "$cur"
        ;;
esac
