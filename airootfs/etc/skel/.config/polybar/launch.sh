#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Start the bar — one per connected screen.
#
#  A barra flutuante do Stylus v2: cantos arredondados, fundo translúcido,
#  largura 96% centrada. O launch.sh detecta cada monitor e inicia uma
#  barra por saída.
# ═══════════════════════════════════════════════════════════════════════════
set -u

killall -q polybar
while pgrep -u "$UID" -x polybar >/dev/null; do sleep 0.5; done

LOG="${XDG_RUNTIME_DIR:-/tmp}/polybar-$UID.log"
: >"$LOG"

# A altura e DPI vêm da densidade da tela. .xprofile exporta antes do i3
# iniciar, mas este script também é chamado à mão e via Mod+Shift+R.
if [[ -z ${STYLUS_BAR_HEIGHT:-} ]] && command -v stylus-scale >/dev/null 2>&1; then
    eval "$(stylus-scale --env 2>/dev/null)"
fi

# polybar -m lista saídas conectadas como "NOME: WxH+X+Y", uma por linha.
# Sem RandR ou sem leitura → barra única no fallback.
mapfile -t outputs < <(polybar -m 2>/dev/null | sed -n 's/^\([^:]*\):.*/\1/p')

if (( ${#outputs[@]} )); then
    for m in "${outputs[@]}"; do
        MONITOR="$m" polybar main >>"$LOG" 2>&1 &
        disown
    done
else
    polybar main >>"$LOG" 2>&1 &
    disown
fi
