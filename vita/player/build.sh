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

mkdir -p build
cd build
cmake .. "$@"
make -j"$(nproc 2>/dev/null || echo 2)"
echo "═══ construido ═══"
ls -la *.vpk 2>/dev/null || ls -la *.self
