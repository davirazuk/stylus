#!/usr/bin/env python3
"""O Qobuz na ESTANTE — capas baixadas, uma linha TSV por disco.

A estante do `Mod+M` é uma grade de capas, e essa é a coisa toda: você passa
o olho e alguma capa chama. A loja do Qobuz, até aqui, só existia dentro da
tela cheia, em texto. Uma assinatura com 87 discos favoritados e nenhum deles
aparecendo onde você procura disco é a mesma coisa que não ter.

    qobuz_shelf.py favoritos [N]
    qobuz_shelf.py buscar TERMOS

Sai TSV no stdout, no MESMO formato do índice local da estante:

    artista <TAB> título <TAB> caminho da capa <TAB> qobuz:ID

O quarto campo é o que separa os dois mundos: caminho de pasta toca da
estante, `qobuz:` transmite. Erro vai para o stderr e o processo sai != 0 —
o stdout aqui alimenta um menu, e uma mensagem de erro no meio dele vira um
disco com nome de erro.

AS CAPAS
--------
Vêm por HTTP e são pequenas (~30 KB), mas são 25 a 60 de uma vez: em série
isso é meio minuto de menu parado. Vão num punhado de threads, com prazo
curto, e ficam guardadas por id — a segunda abertura é instantânea. Capa que
não veio não impede o disco de aparecer: ele entra sem ícone, que é o mesmo
que a estante local já faz com pasta sem cover.jpg.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qobuz_busca import Recusa, cliente, disco                 # noqa: E402

CAPAS = os.path.expanduser("~/.cache/stylus/qobuz-capas")
PRAZO = 8


def morre(msg):
    print("stylus: %s" % msg, file=sys.stderr)
    raise SystemExit(1)


def capa(item):
    """Baixa a capa deste disco e devolve o caminho. "" quando não deu."""
    url = item.get("cover") or ""
    ident = str(item.get("id") or "")
    if not url or not ident:
        return ""
    # O id do Qobuz é alfanumérico, mas ele vem da rede: um "/" ou ".." aí
    # dentro escreveria fora da pasta de cache. Fica só o que é seguro.
    seguro = "".join(c for c in ident if c.isalnum() or c in "-_")
    if not seguro:
        return ""
    destino = os.path.join(CAPAS, seguro + ".jpg")
    if os.path.isfile(destino) and os.path.getsize(destino) > 0:
        return destino
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=PRAZO) as r:
            dados = r.read()
    except Exception:                                    # noqa: BLE001
        return ""
    if not dados:
        return ""
    # Pelo temporário: um menu que abre no meio de um download mostraria uma
    # capa pela metade, e o rofi guarda em cache o que leu — a capa quebrada
    # ficaria quebrada até alguém apagar o arquivo à mão.
    tmp = destino + ".parcial"
    try:
        with open(tmp, "wb") as fh:
            fh.write(dados)
        os.replace(tmp, destino)
    except OSError:
        return ""
    return destino


def linhas(itens):
    os.makedirs(CAPAS, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        capas = list(pool.map(capa, itens))
    saida = []
    for item, cap in zip(itens, capas):
        artista = (item.get("display_subtitle") or "?").replace("\t", " ")
        titulo = (item.get("display_title") or "?").replace("\t", " ")
        ano = item.get("release_year") or ""
        if ano:
            titulo = "%s (%s)" % (titulo, ano)
        saida.append("%s\t%s\t%s\tqobuz:%s" % (artista, titulo, cap, item["id"]))
    return saida


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        cl = cliente()
    except Recusa as e:
        morre(str(e))
    if modo in ("favoritos", "favorites"):
        try:
            quantos = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        except ValueError:
            quantos = 100
        try:
            # Assinado à mão porque o get_favorite_albums do qobuz-dl chama o
            # api_call sem o `sec` e estoura com KeyError ao assinar.
            dados = cl.api_call("favorite/getUserFavorites", type="albums",
                                offset=0, limit=quantos, sec=cl.sec)
        except Exception as e:                           # noqa: BLE001
            morre("não deu para ler os seus favoritos: %s" % e)
    elif modo in ("buscar", "search"):
        termo = " ".join(sys.argv[2:]).strip()
        if not termo:
            morre("busca vazia")
        try:
            dados = cl.search_albums(termo, limit=30)
        except Exception as e:                           # noqa: BLE001
            morre("a busca falhou: %s" % e)
    else:
        morre("uso: qobuz_shelf.py favoritos [N] | buscar TERMOS")

    itens = dados.get("albums", {})
    if isinstance(itens, dict):
        itens = itens.get("items", [])
    if not isinstance(itens, list):
        itens = []
    for ln in linhas([disco(i) for i in itens]):
        print(ln)


if __name__ == "__main__":
    main()
