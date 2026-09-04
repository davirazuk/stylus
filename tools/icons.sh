#!/bin/sh
# Gera os PNG do sce_sys/ a partir de assets/*.svg.
#
# Os PNG SÃO commitados (o build não exige rsvg-convert); rode isto só depois
# de mexer num .svg. Os tamanhos são fixos pelo Vita e não se inventam:
# icon0 128x128, startup 280x158, bg 840x500, pic0 960x544.
#
# ── O QUE O INSTALADOR EXIGE, E POR QUÊ ISTO NÃO É ÓBVIO ──────────────────
# O VitaShell recusa o pacote com 0x8010113D / 0x9010113d quando os PNG do
# sce_sys não são PNG de PALETA de 8 bits (color type 3). PNG RGB comum
# reprova — foi o que aconteceu aqui.
#
# A doc de referência (github.com/hammerill/livearea-specs e o gist que ela
# aponta como estado atual) manda passar antes por `ffmpeg -pix_fmt ya8`.
# CUIDADO: `ya8` é CINZA + alfa. Seguir essa receita ao pé da letra passa na
# instalação e entrega um ícone SEM COR — foi exatamente o que aconteceu numa
# tentativa anterior aqui: os três PNG saíram em escala de cinza pura e o
# âmbar do projeto sumiu.
#
# O que o Vita quer é 8 bits INDEXADO, não cinza. O `pngquant` sozinho já faz
# isso a partir do RGBA e PRESERVA a cor. Conferido nos dois caminhos:
#   só pngquant   -> 8-bit colormap, cores (11,15,23)  <- certo
#   ya8+pngquant  -> 8-bit colormap, cores (15,15,15)  <- cinza
#
# Regra: pngquant sim, ya8 não.
#
# Duas exceções que a doc registra e valem:
#   * icon0.png NÃO pode ter canal alfa -> achatamos no fundo ao rasterizar.
#   * pic0.png (a tela cheia de carregamento) NÃO passa por pngquant — quer
#     exatamente 256 cores de paleta, via palettegen/paletteuse do ffmpeg. NÃO
#     geramos: é opcional, é o arquivo mais exigente do conjunto, e a saída do
#     paletteuse vinha com alfa (que só o startup pode ter). Um caminho novo e
#     delicado só se valida instalando, e não vale arriscar outra reprovação
#     de instalação por um enfeite. Se um dia entrar, é aqui.
set -e
cd "$(dirname "$0")/.."

for t in rsvg-convert pngquant; do
	command -v "$t" >/dev/null 2>&1 || { echo "falta $t" >&2; exit 1; }
done

mkdir -p sce_sys/livearea/contents
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# $1=svg $2=destino $3=W $4=H $5=achatar-alfa(sim/nao)
gera() {
	if [ "$5" = "sim" ]; then
		rsvg-convert -w "$3" -h "$4" -b '#06080D' "$1" -o "$TMP/r.png"
	else
		rsvg-convert -w "$3" -h "$4" "$1" -o "$TMP/r.png"
	fi
	pngquant --force --strip 256 -o "$2" "$TMP/r.png"
}

gera assets/icon0.svg   sce_sys/icon0.png                     128 128 sim
gera assets/startup.svg sce_sys/livearea/contents/startup.png 280 158 nao
gera assets/bg.svg      sce_sys/livearea/contents/bg.png      840 500 nao

echo "═══ ícones gerados ═══"
file sce_sys/icon0.png sce_sys/livearea/contents/*.png
