#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Re-detect the screens (Mod+P).
#
#  autorandr's udev rule handles a projector being plugged in on its own. This
#  is the manual one, for when it does not fire - a dock that presents the
#  output late, a cable swapped mid-class, or a machine where the rule never
#  installed - and it is bound to a key because "nothing happened when I
#  plugged it in" needs an answer someone can be told over the phone.
#
#  There is a plain xrandr fallback so that the key does something useful even
#  if autorandr is missing.
#
#  The bar is restarted afterwards either way: it draws one instance per
#  output, so a screen that appears while it is running has no bar until it is.
# ─────────────────────────────────────────────────────────────────────────────
set -u

notify() {
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a STYLUS -t 3000 "Telas" "$1"
}

# Pressed on a machine with one screen, this should re-enable that screen at
# its preferred mode and stop - not hand the job to autorandr, whose
# "horizontal" profile is for arranging several and which on one screen only
# risks changing a resolution that was fine.
connected_count=$(xrandr --query 2>/dev/null | grep -c ' connected')

if (( connected_count > 1 )) && command -v autorandr >/dev/null 2>&1; then
    # --skip-options gamma: gammastep owns the colour temperature, and letting
    # autorandr restore a saved gamma undoes the night warmth every time a
    # screen changes.
    autorandr --change --default horizontal --skip-options gamma >/dev/null 2>&1
else
    # No autorandr: enable every connected output, left to right, in the order
    # xrandr lists them, with the first one primary.
    mapfile -t connected < <(
        xrandr --query 2>/dev/null | sed -n 's/^\([^ ]*\) connected.*/\1/p'
    )
    (( ${#connected[@]} )) || { notify "Nenhuma tela detectada."; exit 0; }

    args=(--output "${connected[0]}" --auto --primary)
    previous=${connected[0]}
    for out in "${connected[@]:1}"; do
        args+=(--output "$out" --auto --right-of "$previous")
        previous=$out
    done
    # Anything connected earlier and now gone must be switched off, or its
    # workspaces stay on a screen that is not there.
    mapfile -t known < <(xrandr --query 2>/dev/null | sed -n 's/^\([^ ]*\) \(dis\)\?connected.*/\1/p')
    for out in "${known[@]}"; do
        found=0
        for live in "${connected[@]}"; do [[ $out == "$live" ]] && found=1; done
        (( found )) || args+=(--output "$out" --off)
    done
    xrandr "${args[@]}" 2>/dev/null
fi

# ── Is the screen running at everything it can do? ───────────────────────────
#  `--auto` picks the mode the monitor marks preferred, which is normally its
#  native one - but not always. A screen driven over a cable that cannot carry
#  its full resolution, or one whose EDID was not read, offers a shorter list
#  and the preferred entry in that list is smaller than the panel. The result
#  is a 1440p or 4K monitor quietly running at 1080, which looks like a setting
#  nobody changed rather than like a fault.
#
#  xrandr already knows the largest mode each output can do. If the current one
#  is smaller, say so - and offer to use it, since that is a decision for the
#  person looking at the screen, not for a script that runs at every login.
best_mode() {   # best_mode <output> -> "WIDTHxHEIGHT" with the most pixels
    xrandr --query 2>/dev/null | awk -v want="$1" '
        $1 == want { inblock = 1; next }
        /^[^ \t]/   { inblock = 0 }
        inblock && $1 ~ /^[0-9]+x[0-9]+$/ {
            split($1, d, "x")
            if (d[1] * d[2] > best) { best = d[1] * d[2]; mode = $1 }
        }
        END { if (mode != "") print mode }'
}

current_mode() {   # current_mode <output>
    xrandr --query 2>/dev/null |
        sed -n "s/^$1 connected\( primary\)\? \([0-9]*x[0-9]*\).*/\2/p" | head -1
}

primary=$(xrandr --query 2>/dev/null |
          sed -n 's/^\([^ ]*\) connected primary .*/\1/p' | head -1)
[[ -z $primary ]] && primary=$(xrandr --query 2>/dev/null |
          sed -n 's/^\([^ ]*\) connected .*/\1/p' | head -1)

if [[ -n ${primary:-} ]]; then
    now=$(current_mode "$primary")
    best=$(best_mode "$primary")
    if [[ -n $now && -n $best && $now != "$best" ]]; then
        now_px=$(( ${now%x*} * ${now#*x} ))
        best_px=$(( ${best%x*} * ${best#*x} ))
        if (( best_px > now_px )); then
            if [[ ${1:-} == --use-best ]]; then
                xrandr --output "$primary" --mode "$best" 2>/dev/null &&
                    notify "$primary agora em $best."
            else
                notify "$primary está em $now, mas aceita $best. Mod+P de novo com --use-best, ou use o Monitores no lançador."
            fi
        fi
    fi
fi

count=$(xrandr --query 2>/dev/null | grep -c ' connected')
notify "$count tela(s) em uso."

# One bar per output, so the bars have to be restarted once the outputs settle.
[[ -x $HOME/.config/polybar/launch.sh ]] && "$HOME/.config/polybar/launch.sh"
