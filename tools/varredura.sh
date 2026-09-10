#!/bin/sh
# Aperta TUDO em toda tela, sob AddressSanitizer, e desenha depois de cada
# aperto. É a única ferramenta deste projeto que caça travamento sem aparelho.
#
#   ./tools/varredura.sh [raiz-de-musica]            completa, com ASAN (~12 min)
#   ./tools/varredura.sh --rapido [raiz-de-musica]   o que cabe no check.sh
#
# Roda o ui.c DE VERDADE contra o shim do vita2d — a mesma montagem do
# preview.sh, com um driver diferente. As ressalvas do shim continuam valendo
# (a fonte é outra, a largura de texto não bate), mas nenhuma delas afeta o
# que esta ferramenta procura: acesso a memória solta e custo de quadro.
set -e
cd "$(dirname "$0")/.."

RAPIDO=""
if [ "$1" = "--rapido" ]; then RAPIDO="--rapido"; shift; fi
MUSIC="${1:-$HOME/staging-vita/vita-mp3/}"
OUT="${TMPDIR:-/tmp}/vitastylus-varredura$RAPIDO"
BIN="$OUT/varredura"

[ -d "$MUSIC" ] || { echo "não achei a coleção: $MUSIC" >&2; exit 1; }
for p in freetype2 libpng flac vorbisfile opusfile libmpg123; do
	pkg-config --exists "$p" || { echo "falta $p" >&2; exit 1; }
done

mkdir -p "$OUT"

# A COLEÇÃO COM CAPA. A de verdade deste PC não tem nenhuma, e sem capa o
# cache de capas do ui.c nunca enche nem despeja — foi por esse buraco que
# passou uma semana de GPUCRASH com a varredura verde. Ver o cabeçalho do
# capas-de-mentira.sh.
CAPAS="$OUT/com-capa"
./tools/capas-de-mentira.sh "$CAPAS" 24 || {
	echo "não deu para montar a coleção com capa (falta ffmpeg?)" >&2
	CAPAS=""
}
# O sanitizador custa umas quatro vezes o tempo, e é ele que pega o uso de
# memória solta — o defeito que o cemitério de texturas do ui.c existe para
# impedir. Na rápida ele sai: ali o que se procura é tela que some e quadro
# caro, e o preço tem de caber num check.sh.
# -O1 e não -O2: com o sanitizador ligado, o que se quer é a pilha legível
# quando ele reclamar, não o binário rápido.
[ -n "$RAPIDO" ] && SAN="" || SAN="-fsanitize=address,undefined -fno-omit-frame-pointer"
# shellcheck disable=SC2086
gcc -std=gnu11 -Wall -Wextra -O1 -g $SAN \
	-o "$BIN" \
	tests/hostgfx/varredura.c tests/hostgfx/vita2d_host.c \
	tests/hostgfx/player_stub.c \
	src/library.c src/fsutil.c src/rec.c src/playlist.c src/ui.c \
	src/ui_layout.c src/decoder.c src/fonte.c src/sides.c src/lyrics.c src/scrobble.c \
	src/ime.c src/lastfm.c src/md5.c src/net.c src/qobuz.c src/soundcloud.c \
	-Isrc -Itests/hostgfx/include \
	$(pkg-config --cflags --libs freetype2 libpng libcurl) \
	$(pkg-config --cflags --libs libmpg123 flac vorbisfile opusfile) \
	-ljpeg -lm

# `detect_leaks=0`: o que interessa aqui é o acesso indevido, não a memória
# que o programa legitimamente segura até sair. Vazamento de TEXTURA — o que
# custa no Vita — a própria varredura conta, com o número da VRAM.
ASAN_OPTIONS=detect_leaks=0:abort_on_error=0:halt_on_error=1 \
UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1 \
	"$BIN" $RAPIDO --capas "$CAPAS" "$MUSIC"
