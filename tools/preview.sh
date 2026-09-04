#!/bin/sh
# Renderiza as telas da UI em PNG, no PC, sem Vita.
#
#   ./tools/preview.sh [raiz-de-musica] [dir-de-saida]
#
# Compila o ui.c DE VERDADE (sem alterá-lo) contra um shim das primitivas do
# vita2d em tests/hostgfx/. É aproximação, não emulação: a fonte é Noto Sans
# via FreeType e não a PVF do sistema, então largura de texto e altura de
# linha NÃO batem com o aparelho. Serve para julgar cor, hierarquia e estouro
# grosso — a lista de ressalvas está no topo de tests/hostgfx/vita2d_host.c.
set -e
cd "$(dirname "$0")/.."

MUSIC="${1:-$HOME/staging-vita/vita-mp3/}"
OUT="${2:-/tmp/vitastylus-preview}"
BIN="$OUT/preview"

[ -d "$MUSIC" ] || { echo "não achei a coleção: $MUSIC" >&2; exit 1; }
for p in freetype2 libpng flac vorbisfile opusfile libmpg123; do
	pkg-config --exists "$p" || { echo "falta $p" >&2; exit 1; }
done

mkdir -p "$OUT"
gcc -std=gnu11 -Wall -Wextra -O1 -o "$BIN" \
	tests/hostgfx/preview.c tests/hostgfx/vita2d_host.c \
	tests/hostgfx/player_stub.c \
	src/library.c src/fsutil.c src/rec.c src/playlist.c src/ui.c \
	src/ui_layout.c src/decoder.c src/sides.c src/lyrics.c src/scrobble.c \
	src/ime.c src/lastfm.c src/md5.c src/net.c \
	-Isrc -Itests/hostgfx/include \
	$(pkg-config --cflags --libs freetype2 libpng libcurl) \
	$(pkg-config --cflags --libs libmpg123 flac vorbisfile opusfile) \
	-ljpeg -lm

"$BIN" "$MUSIC" "$OUT"
