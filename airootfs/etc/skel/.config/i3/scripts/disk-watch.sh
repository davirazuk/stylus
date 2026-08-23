#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Warn before the disk fills up.
#
#  A full disk does not announce itself. The session stops saving, downloads
#  fail halfway, the browser loses its profile and applications close without
#  a word - and the actual cause is invisible unless somebody thinks to run df.
#  On the small drives these machines have, and with students keeping years of
#  coursework on them, it is worth saying something while there is still room
#  to do anything about it.
#
#  Warns once when space gets low and again when it gets critical, the same
#  shape as battery-watch.sh, and re-arms when space is freed.
# ─────────────────────────────────────────────────────────────────────────────
set -u

LOW_PCT=10        # warn under this much free
CRIT_PCT=5
LOW_MIB=2048      # ...or under this much, whichever happens first: 10% of a
CRIT_MIB=1024     # small disk is not much, and 10% of a large one is plenty
INTERVAL=300

warned_low=0
warned_critical=0

# The root filesystem, plus the home filesystem when it is a separate one.
filesystems() {
    local home_fs root_fs
    root_fs=$(df -P / 2>/dev/null | awk 'NR==2 {print $6}')
    printf '%s\n' "${root_fs:-/}"
    home_fs=$(df -P "$HOME" 2>/dev/null | awk 'NR==2 {print $6}')
    [[ -n $home_fs && $home_fs != "${root_fs:-/}" ]] && printf '%s\n' "$home_fs"
}

human() {   # MiB -> a size a person reads
    local mib=$1
    if (( mib >= 1024 )); then
        printf '%.1f GB' "$(awk "BEGIN{print $mib/1024}")"
    else
        printf '%d MB' "$mib"
    fi
}

notify() {  # notify <urgency> <icon> <title> <body>
    command -v notify-send >/dev/null 2>&1 || return 0
    notify-send --app-name=STYLUS --urgency="$1" \
        --hint=string:x-dunst-stack-tag:stylus-disk \
        "$2  $3" "$4"
}

while :; do
    worst_state=ok
    worst_mount=""
    worst_free_mib=0
    worst_pct=100

    while IFS= read -r mount; do
        [[ -n $mount ]] || continue
        # -P for the portable single-line format; -BM to get plain MiB numbers.
        read -r free_mib pct <<<"$(df -PBM "$mount" 2>/dev/null | awk 'NR==2 {
            gsub(/M/,"",$4); gsub(/%/,"",$5); print $4, 100-$5 }')"
        [[ $free_mib =~ ^[0-9]+$ && $pct =~ ^-?[0-9]+$ ]] || continue

        state=ok
        if (( pct <= CRIT_PCT || free_mib <= CRIT_MIB )); then
            state=critical
        elif (( pct <= LOW_PCT || free_mib <= LOW_MIB )); then
            state=low
        fi

        # Report on whichever filesystem is in the worst shape.
        if [[ $state == critical ]] ||
           { [[ $state == low && $worst_state != critical ]]; }; then
            worst_state=$state; worst_mount=$mount
            worst_free_mib=$free_mib; worst_pct=$pct
        fi
    done < <(filesystems)

    case $worst_state in
        critical)
            if (( ! warned_critical )); then
                notify critical "󰋊" "Disco quase cheio — ${worst_pct}% livre" \
                    "Só restam $(human "$worst_free_mib") em ${worst_mount}. Apague o que não precisa antes que programas parem de salvar."
                warned_critical=1
                # Crossing critical means low was crossed too, whether or not
                # that warning ever fired - otherwise the gentler message
                # arrives after the urgent one and reads as an improvement.
                warned_low=1
            fi
            ;;
        low)
            if (( ! warned_low )); then
                notify normal "󰋊" "Pouco espaço em disco — ${worst_pct}% livre" \
                    "Restam $(human "$worst_free_mib") em ${worst_mount}."
                warned_low=1
            fi
            ;;
        ok)
            warned_low=0
            warned_critical=0
            ;;
    esac

    sleep "$INTERVAL"
done
