#!/bin/sh
# Baixa o plugin MusicPremium e o põe no cartão do Vita.
#
#   ./tools/musicpremium.sh [/caminho/do/cartao]
#
# ── POR QUE ESTE PLUGIN ───────────────────────────────────────────────────
# Só ele faz o Vita NÃO suspender o app que está tocando pela porta BGM. Sem
# ele a música para ao abrir um jogo, por mais que o app peça a porta.
#
# O app já faz a parte dele: pede a porta no arranque e mantém a saída em
# taxa <= 47999 Hz, que é o que leva o SDL2 a abrir a porta BGM (ver a nota
# em src/decoder.c). O deck mostra "2º plano: sim/não" cruzando as duas.
#
# ── DE ONDE VEM ───────────────────────────────────────────────────────────
# Do host do próprio autor (cuevavirus, Team CBPS). As fontes que costumavam
# ser citadas morreram: o fórum devchroma virou um GIF de placeholder e os
# espelhos do GameBrew/Brewology estão atrás de Cloudflare. O link vivo está
# no post arquivado no Wayback, e aponta para o host abaixo.
#
# NÃO commitamos o binário: é código de terceiro, e um hash fixado com um
# download reprodutível diz mais sobre a origem do que um arquivo no repo.
set -e

CARTAO="${1:-/run/media/davirazuk/VITASD}"
URL="https://bin.shotatoshounenwachigau.moe/vita/musicpremium/musicpremium-1.0.6.zip"
SHA="931eae6cea6d05d248e3cfa9fd4241df24af1782d258424bcea7bdec1bfbfd7a"

[ -d "$CARTAO" ] || { echo "não achei o cartão em $CARTAO" >&2; exit 1; }
for t in curl unzip sha256sum; do
	command -v "$t" >/dev/null 2>&1 || { echo "falta $t" >&2; exit 1; }
done

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "baixando…"
curl -sSL -o "$TMP/mp.zip" "$URL"
curl -sSL -o "$TMP/mp.zip.asc" "$URL.asc" || true

got=$(sha256sum "$TMP/mp.zip" | cut -d' ' -f1)
if [ "$got" != "$SHA" ]; then
	echo "sha256 NÃO confere — não instalo." >&2
	echo "  esperado: $SHA" >&2
	echo "  veio:     $got" >&2
	exit 1
fi
echo "sha256 confere."

unzip -o -q "$TMP/mp.zip" -d "$TMP"
[ -f "$TMP/music_premium.skprx" ] || { echo "o zip não trouxe o .skprx" >&2; exit 1; }

# Estrutura mínima do módulo, para não copiar qualquer coisa para o aparelho:
# um .skprx é um SCE/SELF com um ELF ET_SCE_RELEXEC (ARM) dentro.
head -c 4 "$TMP/music_premium.skprx" | grep -q "SCE" || {
	echo "não parece um módulo do Vita (sem cabeçalho SCE)" >&2; exit 1; }

mkdir -p "$CARTAO/tai"
cp "$TMP/music_premium.skprx" "$CARTAO/tai/"
[ -f "$TMP/mp.zip.asc" ] && cp "$TMP/mp.zip.asc" "$CARTAO/tai/music_premium.skprx.asc"
sync

cat <<'FIM'

═══ no cartão ═══
  ux0:tai/music_premium.skprx

FALTA UM PASSO, E ELE É NO APARELHO
  A config do taiHEN mora em ur0:tai/config.txt — memória INTERNA, que o PC
  não enxerga pelo cartão. Escolha um:

  1) AutoPlugin2 (mais seguro; já costuma estar no cartão)
     abra, procure MusicPremium, ele escreve o plugin e a config sozinho.

  2) na mão, pelo VitaShell
     copie  ux0:tai/music_premium.skprx  para  ur0:tai/
     edite  ur0:tai/config.txt  e acrescente, sob a seção  *KERNEL :

         ur0:tai/music_premium.skprx

     salve e REINICIE.

  Firmware suportado: retail 3.60 a 3.73.

COMO SABER SE PEGOU
  No deck, a linha do sinal mostra "2º plano: sim". Saia para um jogo — a
  música deve continuar. Se disser "não", olhe a taxa ao lado: acima de
  47999 Hz o áudio de fundo não segura (FLAC 24/96 e 24/192).
FIM
