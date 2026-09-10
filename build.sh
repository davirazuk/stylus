#!/bin/sh
set -e
cd "$(dirname "$0")"

# Respeita um VITASDK já exportado. Fixar "$HOME/vitasdk" à mão faz o build
# ignorar em silêncio o SDK que a pessoa instalou noutro lugar — e num
# contêiner de CI o HOME nem é o dela.
if [ -z "$VITASDK" ]; then
    for guess in "$HOME/vitasdk" /usr/local/vitasdk /opt/vitasdk; do
        [ -d "$guess" ] && VITASDK="$guess" && break
    done
fi
if [ -z "$VITASDK" ] || [ ! -d "$VITASDK" ]; then
    echo "não achei o VitaSDK. Exporte VITASDK=/caminho/do/sdk" >&2
    exit 1
fi
export VITASDK
export PATH="$VITASDK/bin:$PATH"
echo "VitaSDK: $VITASDK"

# O carimbo do relatório sai de __DATE__/__TIME__ dentro do library.c, e o make
# só recompila quem mudou. SINTOMA: o relatório no cartão dizia "build
# 01:55:06" num binário construído às 02:46, e a sessão seguinte gastou tempo
# checando se o aparelho estava com uma versão velha (não estava — o eboot.bin
# era byte a byte o mesmo). Um carimbo que mente sobre a própria idade
# desqualifica o relatório inteiro.
touch src/library.c

mkdir -p build
cd build
cmake .. "$@"
# `cmake --build` e nao `make`: o diretorio de build guarda o gerador com que
# foi criado, e um build/ feito com Ninja nao tem Makefile nenhum — o `make`
# morria com "Nenhum alvo indicado e nenhum arquivo make encontrado" e levava
# junto o pro-cartao.sh, que chama este script. Assim vale para os dois.
cmake --build . -j "$(nproc 2>/dev/null || echo 2)"
echo "═══ construido ═══"
ls -la *.vpk 2>/dev/null || ls -la *.self
