#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  What is playing, in the bar.
#
#      media.sh              follow the player and print each change
#      media.sh toggle       play / pause
#      media.sh next|prev    skip
#
#  Event-driven, not polled. Asking every two seconds meant starting playerctl
#  up to three times a run - around ninety processes a minute, forever, on a
#  machine that is usually playing nothing at all. `playerctl --follow` is one
#  process that blocks until something actually changes, and polybar reads its
#  output with `tail = true`.
#
#  The bar entry also carries `exec-if`, so on a machine with no playerctl this
#  script is never started in the first place.
#
#  Fields are separated by a unit separator (0x1F) rather than a dash or a pipe.
#  Track titles contain every printable character sooner or later, and a song
#  called "Either/Or | Live" should not be able to confuse the split.
# ─────────────────────────────────────────────────────────────────────────────
set -u

MAX=38            # characters before the title is cut short
SEP=$'\x1f'

# ${#text} e ${text:0:N} contam CARACTERES só quando o locale é UTF-8; com
# LANG=C eles contam BYTES, e cortar no meio de um "ç" põe meio caractere na
# barra — o defeito aparece como acento errado, não como falta de fonte. A
# sessão já garante isto, mas este script também roda sozinho (`media.sh
# next`) e a barra é onde o estrago aparece.
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8|*utf-8|*UTF8|*utf8) : ;;
    # unset LC_ALL antes: LC_ALL ganha de LC_CTYPE, e sem tirá-lo do caminho
    # a linha seguinte não muda nada.
    *) unset LC_ALL; export LC_CTYPE=C.UTF-8 ;;
esac

command -v playerctl >/dev/null 2>&1 || exit 0

case ${1:-show} in
    toggle) playerctl play-pause 2>/dev/null; exit 0 ;;
    next)   playerctl next       2>/dev/null; exit 0 ;;
    prev)   playerctl previous   2>/dev/null; exit 0 ;;
esac

render() {
    local status=$1 artist=$2 title=$3 icon text

    case $status in
        Playing) icon="󰐊" ;;
        Paused)  icon="󰏤" ;;
        *)       printf '\n'; return ;;    # Stopped, or no player: clear the module
    esac

    # Artist is often missing on a video or a stream, so fall back to the title
    # alone rather than printing a stray dash.
    if [[ -n ${artist//[[:space:]]/} ]]; then
        text="${artist} — ${title}"
    else
        text="$title"
    fi

    if [[ -z ${text//[[:space:]]/} ]]; then
        printf '\n'
        return
    fi

    # Trim on characters, not bytes: accented titles are the norm here and
    # cutting mid-character would leave a broken glyph in the bar.
    (( ${#text} > MAX )) && text="${text:0:MAX-1}…"

    printf '%%{F#5bcefa}%s%%{F#7e899c} %s\n' "$icon" "$text"
}

# --follow keeps running across players starting and stopping, and prints a
# blank line when the last one goes away, which clears the module.
#
# Faixa nova, capa nova: uma notificação com o cover.jpg do disco como ícone
# é o mais perto de "arte do álbum na barra" que a polybar consegue — módulo
# dela não desenha imagem nenhuma. Empilha por tag (x-dunst-stack-tag), então
# pular dez faixas não deixa dez balões; deixa um. Só quando há capa e o
# player está tocando, e dedup contra a última faixa vista porque o follow
# repete a linha em qualquer mudança de metadata.
playerctl --follow --format "{{status}}${SEP}{{artist}}${SEP}{{title}}" metadata 2>/dev/null |
while IFS=$SEP read -r status artist title; do
    # Faixa nova, capa nova: uma notificação com o cover.jpg do disco como
    # ícone é o mais perto de "arte do álbum na barra" que a polybar consegue
    # — módulo dela não desenha imagem nenhuma. Empilha por tag
    # (x-dunst-stack-tag), então pular dez faixas não deixa dez balões; deixa
    # um. Dedup contra a última faixa vista: o follow repete a linha em
    # qualquer mudança de metadata, não só em troca de faixa.
    if [[ ${status:-} == Playing && -n ${title//[[:space:]]/} \
          && $title != "${last_notified:-}" ]] \
        && command -v notify-send >/dev/null 2>&1; then
        last_notified=$title
        url=$(playerctl metadata --format '{{xesam:url}}' 2>/dev/null || true)
        arq=$(python3 -c '
import os, sys, urllib.parse
u = sys.argv[1] if len(sys.argv) > 1 else ""
if u.startswith("file://"):
    d = os.path.dirname(urllib.parse.unquote(u[7:]))
    for c in ("cover.jpg", "cover.png", "folder.jpg", "front.jpg",
              "cover.jpeg"):
        f = os.path.join(d, c)
        if os.path.isfile(f):
            print(f)
            break
' "$url" 2>/dev/null || true)
        [[ -n ${arq:-} ]] && notify-send \
            -h string:x-dunst-stack-tag:stylus-media -t 4000 \
            -i "$arq" "${artist:-STYLUS}" "$title" 2>/dev/null
    fi
    render "${status:-}" "${artist:-}" "${title:-}"
done
