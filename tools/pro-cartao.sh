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

# As chaves do Qobuz. Sem elas a tela de Qobuz existe mas não serve para nada,
# porque a alternativa é digitar um segredo de 32 dígitos no teclado da tela —
# e o cartão passou semanas sem nenhum qobuz.config justamente por isso.
if [ -f "$HOME/.config/qobuz-dl/config.ini" ]; then
	echo "── as chaves do Qobuz ──"
	./tools/qobuz-chaves.py "$CARTAO" || echo "  (segue sem Qobuz)"
fi

# O HOSPEDEIRO DE EXTENSÕES vai junto, e NÃO está no repositório (ver o
# .gitignore). Fica em ux0:spotiflac/ — no cartão, que é o que o dono carrega.
# Vai o interpretador e nada mais: nenhum registro, nenhuma extensão. A fonte
# é dele e ele a aponta com `repo add`.
if [ -f tools/spotiflac.js ]; then
	# O client_id do SoundCloud, pelo mesmo motivo das chaves do Qobuz: ele mora
# no JavaScript do site e raspá-lo é trabalho de PC, não de aparelho.
echo "── a chave do SoundCloud ──"
./tools/soundcloud-chaves.py "$CARTAO" || echo "  (segue sem SoundCloud)"

echo "── o hospedeiro de extensões ──"
	mkdir -p "$CARTAO/spotiflac"
	cp tools/spotiflac.js "$CARTAO/spotiflac/"
	# as extensões que já estão instaladas nesta máquina viajam junto; a pasta
	# nasce vazia numa máquina limpa, e é assim que tem de ser
	SFH="$HOME/.local/share/vitastylus/spotiflac"
	if [ -d "$SFH/extensions" ]; then
		cp -r "$SFH/extensions" "$CARTAO/spotiflac/" 2>/dev/null || true
	fi
	# O REGISTRO VAI JUNTO. Sem ele a cópia do cartão instala e remove, mas
	# não atualiza nem descobre nada — e `repo add` de novo, na outra máquina,
	# é a configuração que este arquivo existe para evitar.
	[ -f "$SFH/repos.json" ] && cp "$SFH/repos.json" "$CARTAO/spotiflac/" 2>/dev/null || true
	n=$(ls "$CARTAO/spotiflac/extensions" 2>/dev/null | wc -l)
	echo "  $CARTAO/spotiflac/spotiflac.js  ($n extensão(ões) junto)"
	echo "  roda no PC (precisa de node); o Vita não executa JavaScript."
fi

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
