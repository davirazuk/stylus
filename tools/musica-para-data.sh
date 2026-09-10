#!/bin/sh
# Move a coleção para dentro de ux0:data, que o app SEMPRE consegue ler.
#
#   ./tools/musica-para-data.sh [/caminho/do/cartao]
#   ./tools/musica-para-data.sh [/caminho/do/cartao] --voltar
#
# QUANDO USAR: só se o relatório do cartão disser que ux0:music não abre com
# 0x80010001 (EPERM) E ligar "Enable unsafe homebrew" no HENkaku Settings não
# tiver resolvido. É a saída de emergência, não o caminho normal.
#
# POR QUE FUNCIONA: no modo "safe" o sandbox do HENkaku só deixa o app ver
# ux0:data e app0:. O ux0:data/vitastylus/music já é uma das raízes que a
# varredura procura sozinha — então basta a música estar lá.
#
# POR QUE É INSTANTÂNEO: é um RENAME dentro do mesmo exFAT. Não copia byte
# nenhum, não importa se são 40 GB, e não há janela em que a coleção exista
# pela metade.
#
# O QUE SE PERDE — leia antes: o app de Música do próprio Vita lê ux0:music e
# mais nada. Com a coleção movida, ele fica vazio, e junto vai embora o
# caminho de ouvir dentro de jogos (sair daqui, abrir o Música, tocar o mesmo
# disco, entrar no jogo com o MusicPremium segurando o som). Se esse caminho
# importa mais que a estante, NÃO mova: ligue o unsafe homebrew.
#
# Dá para desfazer a qualquer momento com --voltar, e também é instantâneo.
set -e

CARTAO="${1:-/run/media/davirazuk/VITASD}"
case "$1" in --voltar) CARTAO="/run/media/davirazuk/VITASD" ;; esac
VOLTAR=no
for a in "$@"; do [ "$a" = "--voltar" ] && VOLTAR=sim; done

ORIG="$CARTAO/music"
DEST="$CARTAO/data/vitastylus/music"

[ -d "$CARTAO" ] || { echo "não achei o cartão em $CARTAO" >&2; exit 1; }

conta() {
	find "$1" -type f \( -iname '*.mp3' -o -iname '*.flac' -o -iname '*.m4a' \
	     -o -iname '*.ogg' -o -iname '*.opus' -o -iname '*.wav' \) 2>/dev/null | wc -l
}

if [ "$VOLTAR" = sim ]; then
	[ -d "$DEST" ] || { echo "não há nada em $DEST para voltar" >&2; exit 1; }
	[ -e "$ORIG" ] && { echo "$ORIG já existe — não vou misturar as duas" >&2; exit 1; }
	n=$(conta "$DEST")
	mv "$DEST" "$ORIG"
	sync
	echo "  de volta em $ORIG — $n arquivos"
	echo "  o app de Música do Vita volta a enxergar a coleção."
	exit 0
fi

[ -d "$ORIG" ] || { echo "não achei $ORIG" >&2; exit 1; }
[ -e "$DEST" ] && { echo "$DEST já existe — não vou escrever por cima" >&2; exit 1; }

n=$(conta "$ORIG")
echo "  movendo $n arquivos de $ORIG"
echo "  para $DEST (rename no mesmo cartão: instantâneo)"
mkdir -p "$CARTAO/data/vitastylus"
mv "$ORIG" "$DEST"
sync
echo "  pronto — $n arquivos em ux0:data/vitastylus/music"
echo
echo "  o app acha isso sozinho: já é uma das raízes padrão."
echo "  o app de Música do Vita, não — desfaça com --voltar se precisar dele."
