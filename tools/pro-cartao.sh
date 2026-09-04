#!/bin/sh
# Prepara o cartão do Vita numa passada só.
#
#   ./tools/pro-cartao.sh [/caminho/do/cartao] [--capas]
#
# Faz, nesta ordem:
#   1. constrói o VPK (e para se não construir — não adianta copiar o velho);
#   2. confere que os PNG do sce_sys estão em PALETA de 8 bits, que é o que o
#      instalador exige (senão dá 0x8010113D e você só descobre no aparelho);
#   3. copia o VPK para a raiz do cartão;
#   4. diz onde o app vai procurar música e o que há lá;
#   5. com --capas, leva as capas da coleção do PC para os álbuns do cartão
#      que estão sem — sem recodificar áudio nenhum.
#
# NÃO mexe em ux0:tai/ nem no plugin: isso é do aparelho e já está feito.
set -e
cd "$(dirname "$0")/.."

CARTAO="${1:-/run/media/davirazuk/VITASD}"
CAPAS=no
for a in "$@"; do [ "$a" = "--capas" ] && CAPAS=sim; done
REF="$HOME/staging-vita/vita-mp3"

[ -d "$CARTAO" ] || { echo "não achei o cartão em $CARTAO" >&2
                      echo "  (plugue o SD2VITA e confira o caminho)" >&2; exit 1; }

echo "── construindo ──"
./build.sh >/dev/null
VPK=build/vitastylus.vpk
[ -f "$VPK" ] || { echo "o build não deixou o VPK" >&2; exit 1; }

echo "── conferindo o formato dos ícones ──"
ruim=0
for p in sce_sys/icon0.png sce_sys/livearea/contents/bg.png \
         sce_sys/livearea/contents/startup.png; do
	if file "$p" | grep -q "8-bit colormap"; then
		echo "  ok   $p"
	else
		echo "  RUIM $p — $(file -b "$p")" >&2
		ruim=1
	fi
done
if [ "$ruim" = 1 ]; then
	echo "  o instalador recusa isto com 0x8010113D. Rode ./tools/icons.sh" >&2
	exit 1
fi

echo "── copiando ──"
cp "$VPK" "$CARTAO/vitastylus.vpk"
sync
echo "  $CARTAO/vitastylus.vpk  ($(du -h "$VPK" | cut -f1))"

echo "── a música ──"
# As raízes que o app varre, na ordem. A primeira que existir é a que importa.
achou=""
for d in "$CARTAO/music" "$CARTAO/data/vitastylus/music"; do
	if [ -d "$d" ]; then
		n=$(find "$d" -type f \( -iname '*.mp3' -o -iname '*.flac' -o \
		        -iname '*.ogg' -o -iname '*.opus' -o -iname '*.wav' \) | wc -l)
		echo "  $d — $n arquivos tocáveis"
		[ -z "$achou" ] && achou="$d"
	fi
done
if [ -z "$achou" ]; then
	echo "  nenhuma pasta de música no cartão."
	echo "  ponha em ux0:music/Artista/Album/*.mp3 — ou escreva as suas pastas,"
	echo "  uma por linha, em ux0:data/vitastylus/roots.txt"
fi
df -h "$CARTAO" | tail -1 | awk '{print "  espaço: " $3 " usados, " $4 " livres (" $5 ")"}'

if [ "$CAPAS" = sim ] && [ -n "$achou" ]; then
	echo "── capas ──"
	if [ -d "$REF" ]; then
		./tools/para-vita.py --capas-de "$REF" --destino "$achou"
	else
		echo "  não achei a coleção de referência em $REF" >&2
	fi
fi

cat <<'FIM'

── no aparelho ──
  instale ux0:vitastylus.vpk pelo VitaShell.
  o TITLE_ID não muda, então instala por cima da versão anterior.
FIM
