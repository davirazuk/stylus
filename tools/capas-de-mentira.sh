#!/bin/sh
# Monta uma coleção PEQUENA em que TODO disco tem capa embutida.
#
#   ./tools/capas-de-mentira.sh <pasta>     (idempotente: pula o que já existe)
#
# POR QUE ISTO EXISTE
#
# A coleção de teste deste PC não tem UMA capa — nem arquivo solto, nem arte
# embutida. E o cache de capas do ui.c só faz alguma coisa quando há capa: sem
# nenhuma, ele nunca enche, nunca despeja e nunca solta textura.
#
# Foi por aí que passou o defeito mais caro deste projeto. O cache tinha DEZ
# lugares e a tela de ARTISTS desenha DOZE círculos: no aparelho ele debulhava
# a cada quadro, soltando textura que a GPU ainda estava lendo, e o cartão
# enchia de psp2core-*-GPUCRASH. Aqui a varredura passava VERDE, todos os dias,
# porque sem capa aquele código nunca rodava.
#
# Tela medida vazia não é tela medida. Vinte e quatro discos bastam: é mais que
# qualquer tela desenha de uma vez, que é a condição em que o cache quebra.
set -e
ALVO="${1:?uso: capas-de-mentira.sh <pasta>}"
N="${2:-24}"

command -v ffmpeg >/dev/null 2>&1 || { echo "falta ffmpeg" >&2; exit 1; }

if [ -f "$ALVO/.pronto" ]; then exit 0; fi
mkdir -p "$ALVO"
TMP="$ALVO/.tmp"
mkdir -p "$TMP"

# A CAPA: 500x500, que é o tamanho REAL das do cartão do aparelho (postas
# pelo musica-para-o-vita.py). O conteúdo não importa — o que se exercita é
# decodificar, guardar e soltar uma textura, não olhar para ela — mas o
# TAMANHO importa muito: é ele que decide quanta memória de vídeo o cache
# ocupa, e medir com uma capa pequena dá um número que aprova qualquer coisa.
ffmpeg -v error -y -f lavfi -i color=c=0x4488cc:s=500x500 -frames:v 1 "$TMP/capa.jpg"
# Dois segundos de silêncio: o teste não ouve nada, só varre.
ffmpeg -v error -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 2 \
       -c:a libmp3lame -b:a 64k "$TMP/mudo.mp3"

i=1
while [ "$i" -le "$N" ]; do
	d=$(printf '%s/Artista %02d/Disco de Mentira %02d' "$ALVO" "$i" "$i")
	mkdir -p "$d"
	# a capa vai DENTRO do arquivo: é de lá que o album_load_cover a tira
	# (ele não olha para cover.jpg solto — conferido no library.c)
	ffmpeg -v error -y -i "$TMP/mudo.mp3" -i "$TMP/capa.jpg" \
	       -map 0:a -map 1:v -c copy -id3v2_version 3 \
	       -metadata:s:v title="Album cover" \
	       -metadata:s:v comment="Cover (front)" \
	       -metadata artist="Artista $i" \
	       -metadata album="Disco de Mentira $i" \
	       -metadata title="Faixa 1" \
	       "$d/01 faixa.mp3"
	# METADE com a capa SÓ em arquivo, metade só embutida: são dois
	# caminhos diferentes no album_load_cover e os dois precisam rodar.
	# (O de arquivo foi acrescentado depois e é o que faz 87% desta
	# coleção ter arte — ver a nota no library.c.)
	if [ $((i % 2)) -eq 0 ]; then
		cp "$TMP/capa.jpg" "$d/cover.jpg"
		ffmpeg -v error -y -i "$d/01 faixa.mp3" -map 0:a -c copy \
		       "$d/.sem-arte.mp3" && mv "$d/.sem-arte.mp3" "$d/01 faixa.mp3"
	fi
	i=$((i + 1))
done
rm -rf "$TMP"
: > "$ALVO/.pronto"
