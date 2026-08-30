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

PY=python3
export PYTHONPATH=/usr/share/stylus/lib

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
#
# **Sintoma:** aqui estava `${XDG_MUSIC_DIR:-$HOME/Music}`, e o XDG_MUSIC_DIR
# não é variável de ambiente — é uma LINHA dentro do ~/.config/user-dirs.dirs,
# que só o `xdg-user-dir` sabe ler. Num sistema em português, onde a pasta se
# chama "Músicas", a variável vinha vazia e o fallback criava um "~/Music" em
# inglês. A pessoa abria o gerenciador de arquivos, via "Músicas", punha os
# discos ali — e o STYLUS olhava para a outra pasta e ficava vazio para
# sempre, sem nada explicando.
#
# Duas armadilhas do xdg-user-dirs, as duas medidas aqui antes de escrever
# esta linha:
#
#   nunca rodar o `xdg-user-dirs-update` por cima de um user-dirs.dirs que já
#   existe. Se as pastas localizadas ainda não foram criadas, ele REESCREVE a
#   entrada como `XDG_MUSIC_DIR="$HOME/"` — e a estante passaria a ser a casa
#   inteira. Só numa conta nova, onde o arquivo não existe, ele ajuda.
#
#   o `xdg-user-dir` devolve a própria casa quando não sabe, e devolve COM
#   barra no fim: comparar com "$HOME" pelado não pega. Tira-se a barra.
if [[ ! -f ${XDG_CONFIG_HOME:-$HOME/.config}/user-dirs.dirs ]]; then
    command -v xdg-user-dirs-update >/dev/null 2>&1 && \
        xdg-user-dirs-update >/dev/null 2>&1 || true
fi
alvo=$(xdg-user-dir MUSIC 2>/dev/null || true)
alvo=${alvo%/}
if [[ -z $alvo || $alvo == "$HOME" ]]; then
    # Sem resposta do xdg: o nome da pasta segue o idioma da máquina, que é
    # o que a pessoa vai ver no gerenciador de arquivos.
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
        pt*) alvo="$HOME/Músicas" ;;
        *)   alvo="$HOME/Music" ;;
    esac
fi
mkdir -p "$alvo"
printf '%s\n' "$alvo" > "$CONF"
command -v notify-send >/dev/null && notify-send --app-name=STYLUS \
    "onde fica a sua coleção?" \
    "por enquanto: $alvo — mude com \`stylus library <pasta>\`" 2>/dev/null || true
exit 0
