# ═══════════════════════════════════════════════════════════════════════════
#  venv.sh — o ambiente Python do STYLUS, para o que não vem em pacote
# ═══════════════════════════════════════════════════════════════════════════
#  Não é um executável: é para ser lido com `source /usr/share/stylus/venv.sh`.
#
#  ── Por que isto existe ───────────────────────────────────────────────────
#
#  No Arch, `pip install` NÃO FUNCIONA. O python do sistema é gerido pelo
#  pacman e o pip se recusa a tocar nele:
#
#      error: externally-managed-environment
#
#  Isso não é uma configuração desta máquina, é o padrão do Arch (PEP 668), e
#  vale para `--user` também. Duas partes do STYLUS dependiam de pacotes que
#  só existem no PyPI — o `qobuz-dl` e o `spotipy`, nenhum dos dois nos
#  repositórios oficiais — e as duas mandavam rodar um `pip install` que a
#  máquina recusa. Na prática, o Qobuz e o Spotify nunca funcionaram numa
#  instalação limpa, e a mensagem de erro mandava fazer a coisa impossível.
#
#  A saída ANTERIOR era `--break-system-packages`, e o nome não é exagero: o
#  pacote vai para ~/.local/lib/python3.13, some inteiro na primeira
#  atualização do python para 3.14, e o executável cai em ~/.local/bin, que
#  pode nem estar no PATH. Três formas de quebrar em silêncio.
#
#  Um venv resolve as três: é do usuário (não precisa de root), o pacman não
#  o enxerga, e nós chamamos os executáveis dele pelo caminho inteiro. O
#  `--system-site-packages` faz ele APROVEITAR o que o pacman já instalou —
#  numpy, mutagen, requests — em vez de baixar tudo de novo.
#
#  O venv do deck (/usr/share/stylus/deck/venv) é outra coisa e continua
#  sendo: aquele é do SISTEMA, feito na hora de montar a ISO, e existe porque
#  o PyOpenGL não tem pacote. Este aqui é da PESSOA, feito na primeira vez que
#  ela pede Qobuz ou Spotify.
# ═══════════════════════════════════════════════════════════════════════════

STYLUS_VENV="${STYLUS_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/stylus/venv}"

venv_python() { printf '%s\n' "$STYLUS_VENV/bin/python3"; }
venv_existe() { [[ -x $STYLUS_VENV/bin/python3 ]]; }

# O executável de um pacote instalado aqui dentro. Pelo caminho inteiro de
# propósito: o bin/ do venv não está no PATH de ninguém, e não queremos que
# esteja — pôr um python alternativo na frente do PATH da pessoa é o tipo de
# gentileza que quebra outra coisa três semanas depois.
venv_bin() { local n=$1; [[ -x $STYLUS_VENV/bin/$n ]] && printf '%s\n' "$STYLUS_VENV/bin/$n"; }

# O python que este comando deve usar: o do venv quando existe, senão o do
# sistema. O do sistema resolve tudo que veio pelo pacman.
venv_python_ou_sistema() {
    if venv_existe; then printf '%s\n' "$STYLUS_VENV/bin/python3"
    else printf 'python3\n'; fi
}

venv_tem() {  # venv_tem <módulo>
    "$(venv_python_ou_sistema)" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$1') else 1)" 2>/dev/null
}

venv_criar() {
    venv_existe && return 0
    mkdir -p "$(dirname "$STYLUS_VENV")" 2>/dev/null || return 1
    python3 -m venv --system-site-packages "$STYLUS_VENV" >/dev/null 2>&1 || return 1
    # O pip que vem no venv costuma ser velho o bastante para não entender
    # alguns wheels novos; atualizar uma vez sai mais barato que o erro.
    "$STYLUS_VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
    venv_existe
}

venv_instalar() {  # venv_instalar <pacote|url>...
    venv_criar || return 1
    "$STYLUS_VENV/bin/pip" install --no-cache-dir --upgrade "$@"
}

# A frase que aparece quando falta alguma coisa. Uma só, para os dois
# comandos: quem lê "instale com X" tem que poder copiar o X e funcionar.
venv_recado() {  # venv_recado <comando-do-stylus>
    printf 'falta um pacote Python. Instale com:  stylus %s instalar\n' "$1"
}
