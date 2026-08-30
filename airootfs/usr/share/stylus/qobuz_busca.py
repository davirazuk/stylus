#!/usr/bin/env python3
"""O que a loja mostra: uma busca, ou os seus favoritos do Qobuz.

Sai UMA linha de JSON no stdout — {"results":[…]} ou {"error":"…"} — porque
quem lê é a tela cheia. Todo o resto (o barulho de autenticação, um aviso)
vai para o stderr, onde não atrapalha e continua visível para quem estiver
num terminal.

    qobuz_busca.py buscar TERMOS
    qobuz_busca.py favoritos [QUANTOS]
    qobuz_busca.py faixas ID          a ordem do disco, sem baixar nada

POR QUE OS FAVORITOS ESTÃO AQUI
-------------------------------
A loja abria vazia, com um "[/] procura um disco" e mais nada — e a coisa
mais óbvia de se querer ver ao abrir a loja da sua própria assinatura é o que
VOCÊ já marcou lá dentro. São 87 discos que já estavam do outro lado da
conta, e nenhum caminho até eles daqui.

(O `get_favorite_albums` do próprio qobuz-dl não serve: ele chama o api_call
sem passar o `sec`, e o api_call estoura com KeyError ao assinar o pedido. A
chamada crua abaixo é a mesma coisa, com o segredo no lugar.)
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qobuz_conta import campo, ler                             # noqa: E402


class Recusa(Exception):
    """A loja não abre, e o motivo é para MOSTRAR.

    Levanta em vez de imprimir porque `cliente()` tem dois chamadores com
    saídas incompatíveis: aqui o stdout é uma linha de JSON, e no
    `qobuz_shelf.py` é TSV para o rofi. Imprimir JSON de dentro da função
    fazia a estante engolir `{"error": …}` como se fosse um disco chamado
    assim.
    """


def responde(**campos):
    print(json.dumps(campos, ensure_ascii=False))
    raise SystemExit(0 if "results" in campos else 1)


def cliente():
    # O qobuz_dl escreve "Logging..." e "Membership: Studio" pelo logging
    # dele, em inglês. Aqui o stdout é JSON e o stderr é para quem está no
    # terminal; nas duas pontas essas duas linhas são ruído.
    logging.getLogger("qobuz_dl").setLevel(logging.WARNING)
    logging.getLogger("qopy").setLevel(logging.WARNING)
    try:
        from qobuz_dl.qopy import Client
    except ImportError:
        raise Recusa("o qobuz-dl não está instalado. "
                     "Rode:  stylus qobuz instalar")
    c = ler()

    def g(k):
        return campo(c, k)

    segredos = [x.strip() for x in g("secrets").split(",") if x.strip()]
    if not (g("app_id") and segredos and g("user_id") and g("user_auth_token")):
        raise Recusa("o Qobuz ainda não tem conta aqui. [c] entra.")
    try:
        cl = Client(None, None, g("app_id"), segredos, skip_auth=True)
        cl.auth_with_token(g("user_id"), g("user_auth_token"))
    except Exception as e:                               # noqa: BLE001
        raise Recusa("a conta do Qobuz não foi aceita: %s" % e)
    return cl


# O mesmo teto da estante do rofi, e a mesma variável de ambiente: são duas
# telas da MESMA loja e não podem discordar sobre quantos favoritos existem.
TETO = int(os.environ.get("STYLUS_QOBUZ_FAVORITOS", "1000"))


def disco(item):
    """Um item da API vira o disco que a tela desenha."""
    artista = "?"
    a = item.get("artist")
    if isinstance(a, dict):
        artista = a.get("name") or "?"
    elif isinstance(a, str):
        artista = a

    # O maximum_sampling_rate do Qobuz JÁ VEM EM kHz (44.1, 96, 192), não em
    # Hz. Um `rate/1000` aqui transformava todo CD em "16bit/0.0kHz".
    prof = item.get("maximum_bit_depth") or 16
    taxa = item.get("maximum_sampling_rate") or 44.1
    try:
        taxa = float(taxa)
    except (TypeError, ValueError):
        taxa = 44.1
    if taxa > 1000:                       # se um dia mudarem de ideia
        taxa /= 1000.0
    img = item.get("image") or {}
    return {
        "id": item.get("id", ""),
        "display_title": item.get("title", "?"),
        "display_subtitle": artista,
        "release_year": str(item.get("release_date_original")
                            or item.get("release_date_stream") or "")[:4],
        "tracks": item.get("tracks_count", 0),
        "quality": "%dbit/%skHz" % (prof, ("%g" % round(taxa, 1)).replace(".", ",")),
        # Booleano em vez de "tem 'hi' no texto?": a tela marcava o disco de
        # hi-res procurando a palavra dentro da string de qualidade, e no dia
        # em que a string passou a dizer "24bit/96kHz" o losango dourado
        # sumiu de todos os discos de uma vez.
        "hires": bool(prof > 16 or taxa > 48),
        "cover": img.get("large") or img.get("small") or img.get("thumbnail") or "",
        "url": "https://www.qobuz.com/album/%s" % item.get("id", ""),
    }


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        cl = cliente()
    except Recusa as e:
        responde(error=str(e))
    if modo in ("buscar", "search"):
        termo = " ".join(sys.argv[2:]).strip()
        if not termo:
            responde(error="busca vazia")
        try:
            # PAGINADA, pelo mesmo código dos favoritos e da estante do
            # rofi. Eram 25 aqui e 100 lá, e depois 100 nas duas — mas o
            # `album/search` do Qobuz APARA o limite em 50 do lado dele,
            # então as duas telas mostravam cinquenta discos e paravam.
            # "beatles" tem centenas de edições; com cinquenta, a que você
            # procura quase nunca está entre elas.
            from qobuz_shelf import busca_todos
            itens, _total = busca_todos(cl, termo)
            dados = {"albums": {"items": itens}}
        except Exception as e:                           # noqa: BLE001
            responde(error="a busca falhou: %s" % e)
    elif modo in ("favoritos", "favorites"):
        try:
            quantos = int(sys.argv[2]) if len(sys.argv) > 2 else TETO
        except ValueError:
            quantos = TETO
        try:
            # PAGINADO, pelo mesmo código da estante do rofi. Aqui era uma
            # chamada só com limite 60: quem tem 87 favoritos via 60, sem
            # nada dizendo que havia mais — e a estante do rofi, ao lado,
            # mostrava os 87. A mesma loja com duas respostas diferentes.
            from qobuz_shelf import favoritos_todos
            itens, _total = favoritos_todos(cl, quantos)
            dados = {"albums": {"items": itens}}
        except Exception as e:                           # noqa: BLE001
            responde(error="não deu para ler os seus favoritos: %s" % e)
    elif modo == "faixas":
        # A ORDEM DO DISCO, sem baixar nem assinar nada.
        #
        # O `[enter]` da loja se chama "examina" e mostrava capa, ano e
        # qualidade — tudo que já estava no quadradinho da grade. O que se
        # examina num disco é o que tem DENTRO dele: as faixas, quanto dura,
        # e (neste sistema) em quantos LADOS ele cabe. O Qobuz manda isso de
        # graça no `get_album_meta`; era só ninguém estar pedindo.
        ident = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
        if not ident:
            responde(error="faixas de qual disco?")
        try:
            meta = cl.get_album_meta(ident)
        except Exception as e:                           # noqa: BLE001
            responde(error="não achei esse disco no Qobuz: %s" % e)
        faixas = ((meta.get("tracks") or {}).get("items")) or []
        saida = []
        for i, t in enumerate(faixas, 1):
            saida.append({
                "n": t.get("track_number") or i,
                "title": t.get("title") or "?",
                "duration": int(t.get("duration") or 0),
                # Faixa de outro artista dentro de uma coletânea: dizer quem
                # é. Numa coletânea sem isto a lista fica com doze títulos e
                # nenhum nome, que é justamente o disco em que o nome importa.
                "artist": ((t.get("performer") or {}).get("name") or ""),
            })
        responde(results=saida, album=disco(meta))
    else:
        responde(error="uso: qobuz_busca.py buscar TERMOS | favoritos [N] "
                       "| faixas ID")

    itens = dados.get("albums", {})
    if isinstance(itens, dict):
        itens = itens.get("items", [])
    if not isinstance(itens, list):
        itens = []
    responde(results=[disco(i) for i in itens])


if __name__ == "__main__":
    main()
