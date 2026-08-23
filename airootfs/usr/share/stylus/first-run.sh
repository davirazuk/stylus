#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  first-run.sh — a única pergunta que o sistema precisa fazer
# ═══════════════════════════════════════════════════════════════════════════
#  Roda uma vez por conta, antes da sessão subir. Não é um assistente de
#  boas-vindas com seis telas: é uma pergunta só, e ela é "onde está a sua
#  coleção", porque tudo aqui é inútil sem essa resposta e nada aqui consegue
#  adivinhá-la com certeza.
#
#  E mesmo essa ele tenta responder sozinho primeiro. Só pergunta se procurar
#  não deu em nada.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail
CONF="$HOME/.config/stylus/library"
[[ -s $CONF ]] && exit 0
mkdir -p "$(dirname "$CONF")"

PY=/usr/share/stylus/deck/venv/bin/python3
[[ -x $PY ]] || PY=python3
export PYTHONPATH=/usr/share/stylus/deck

achado=$("$PY" -c '
import vinyl
r, n = vinyl.best_root()
print(f"{r}\t{n}" if r and n >= 3 else "")' 2>/dev/null)

if [[ -n $achado ]]; then
    pasta=${achado%%$'\t'*}
    n=${achado##*$'\t'}
    printf '# achado sozinho na primeira execução: %s discos\n%s\n' "$n" "$pasta" > "$CONF"
    command -v notify-send >/dev/null && notify-send --app-name=STYLUS \
        "coleção encontrada" "$n discos em $pasta" 2>/dev/null || true
    exit 0
fi

# Não achou nada. Cria o lugar padrão e diz onde é, em vez de deixar a
# interface abrir vazia sem explicação — que é o pior primeiro contato
# possível com um sistema cujo assunto inteiro é a coleção.
alvo="${XDG_MUSIC_DIR:-$HOME/Music}"
mkdir -p "$alvo"
printf '%s\n' "$alvo" > "$CONF"
command -v notify-send >/dev/null && notify-send --app-name=STYLUS \
    "onde fica a sua coleção?" \
    "por enquanto: $alvo — mude com \`stylus library <pasta>\`" 2>/dev/null || true
exit 0
