#!/usr/bin/env python3
"""O Qobuz na ESTANTE — capas baixadas, uma linha TSV por disco.

A estante do `Mod+M` é uma grade de capas, e essa é a coisa toda: você passa
o olho e alguma capa chama. A loja do Qobuz, até aqui, só existia dentro da
tela cheia, em texto. Uma assinatura com 87 discos favoritados e nenhum deles
aparecendo onde você procura disco é a mesma coisa que não ter.

    qobuz_shelf.py favoritos [N]
    qobuz_shelf.py buscar TERMOS
    qobuz_shelf.py listas

Sai TSV no stdout, no MESMO formato do índice local da estante:

    artista <TAB> título <TAB> caminho da capa <TAB> qobuz:ID

O quarto campo é o que separa os mundos: caminho de pasta toca da estante,
`qobuz:` transmite um disco, `qobuz-lista:` transmite uma playlist. Erro vai para o stderr e o processo sai != 0 —
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


def mosaico(urls, destino):
    """As quatro capas de uma playlist, numa imagem só.

    Playlist não tem capa: o Qobuz manda as capas dos quatro primeiros discos
    e o site monta o quadrado. Usar só a primeira faria a playlist parecer um
    disco daquele artista na grade — e é o contrário do que ela é. Quatro
    quadrantes leem como "coletânea" de longe, que é a informação certa.
    """
    if os.path.isfile(destino) and os.path.getsize(destino) > 0:
        return destino
    try:
        from PIL import Image
    except ImportError:
        return ""
    import io
    import urllib.request
    lado = 300
    tela = Image.new("RGB", (lado, lado), (13, 15, 20))
    postos = [(0, 0), (lado // 2, 0), (0, lado // 2), (lado // 2, lado // 2)]
    postas = 0
    for url, (x, y) in zip(urls[:4], postos):
        try:
            with urllib.request.urlopen(url, timeout=PRAZO) as r:
                im = Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception:                                # noqa: BLE001
            continue
        tela.paste(im.resize((lado // 2, lado // 2), Image.LANCZOS), (x, y))
        postas += 1
    if not postas:
        return ""
    tmp = destino + ".parcial"
    try:
        tela.save(tmp, "JPEG", quality=88)
        os.replace(tmp, destino)
    except OSError:
        return ""
    return destino


def linha_de_lista(pl):
    """Uma playlist do Qobuz, no mesmo TSV dos discos."""
    ident = "".join(c for c in str(pl.get("id") or "") if c.isalnum())
    if not ident:
        return None
    nome = (pl.get("name") or "playlist").replace("\t", " ")
    dono = ((pl.get("owner") or {}).get("name") or "Qobuz").replace("\t", " ")
    n = pl.get("tracks_count") or 0
    urls = (pl.get("images300") or pl.get("images150") or pl.get("images") or [])
    cap = mosaico(urls, os.path.join(CAPAS, "lista-%s.jpg" % ident)) if urls else ""
    return "%s\t%s (%s faixas)\t%s\tqobuz-lista:%s" % (dono, nome, n, cap, ident)


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


# Quantos discos favoritos, no máximo. Não é o limite de uma CHAMADA — é o
# teto da coleção inteira, e as chamadas vão de 100 em 100 até chegar lá.
TETO_FAVORITOS = int(os.environ.get("STYLUS_QOBUZ_FAVORITOS", "1000"))
POR_PAGINA = 100


# E quantas playlists. Mesmo raciocínio: teto da coleção, não da chamada.
TETO_LISTAS = int(os.environ.get("STYLUS_QOBUZ_LISTAS", "500"))


def _paginado(pedir, chave, teto):
    """(itens, total) — TODAS as páginas, e não a primeira.

    **Sintoma:** a loja mostrava 100 discos e parava. Sem recado, sem
    "mostrando 100 de 340" — os outros simplesmente não existiam ali, e a
    pessoa que favoritou 200 discos no celular via metade da própria
    estante. A chamada tinha `offset=0` escrito à mão e nunca uma segunda
    página.

    Para de verdade em quatro situações, porque um laço que fala com a rede
    não pode depender de uma só: chegou ao total que o Qobuz declarou, veio
    uma página curta, veio uma página vazia, ou bateu no teto.

    `pedir(offset, limite)` devolve o JSON cru; `chave` é onde a lista mora
    dentro dele ("albums", "playlists").
    """
    itens, total = [], None
    while len(itens) < teto:
        dados = pedir(len(itens), min(POR_PAGINA, teto - len(itens)))
        bloco = (dados or {}).get(chave) or {}
        pagina = bloco.get("items") or []
        if total is None:
            try:
                total = int(bloco.get("total"))
            except (TypeError, ValueError):
                total = None
        if not pagina:
            break
        itens += pagina
        if total is not None and len(itens) >= total:
            break
        if len(pagina) < POR_PAGINA:
            break
    return itens, total


def favoritos_todos(cl, teto=TETO_FAVORITOS):
    """Todos os discos favoritados. Ver `_paginado`."""
    # Assinado à mão porque o get_favorite_albums do qobuz-dl chama o
    # api_call sem o `sec` e estoura com KeyError ao assinar.
    return _paginado(
        lambda off, lim: cl.api_call("favorite/getUserFavorites",
                                     type="albums", offset=off, limit=lim,
                                     sec=cl.sec),
        "albums", teto)


def listas_todas(cl, teto=TETO_LISTAS):
    """Todas as suas playlists. Ver `_paginado`.

    Tinha o MESMO defeito dos favoritos, escrito ao lado dele: um
    `limit=100` fixo e nenhuma segunda página. Passou despercebido porque
    cem playlists é muita playlist — mas é o mesmo defeito, e quem tem
    passa a ver metade da própria lista sem nada explicando.

    O `offset` vai num try: se a versão do qobuz-dl instalada não aceitar o
    argumento, é melhor voltar ao comportamento de antes (a primeira página)
    do que o comando inteiro estourar.
    """
    def pedir(off, lim):
        try:
            return cl.get_user_playlists(limit=lim, offset=off)
        except TypeError:
            return None if off else cl.get_user_playlists(limit=lim)

    return _paginado(pedir, "playlists", teto)


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        cl = cliente()
    except Recusa as e:
        morre(str(e))
    if modo in ("favoritos", "favorites"):
        try:
            quantos = int(sys.argv[2]) if len(sys.argv) > 2 else TETO_FAVORITOS
        except ValueError:
            quantos = TETO_FAVORITOS
        try:
            itens, total = favoritos_todos(cl, quantos)
        except Exception as e:                           # noqa: BLE001
            morre("não deu para ler os seus favoritos: %s" % e)
        if total and len(itens) < total:
            # Se o teto cortou, DIZER — pelo stderr, que não entra no menu.
            # Uma lista curta sem explicação é indistinguível de uma coleção
            # pequena, que foi o defeito original.
            print("  · mostrando %d dos %d favoritos "
                  "(STYLUS_QOBUZ_FAVORITOS muda o teto)" % (len(itens), total),
                  file=sys.stderr)
        for ln in linhas([disco(i) for i in itens]):
            print(ln)
        return
    elif modo in ("listas", "playlists"):
        os.makedirs(CAPAS, exist_ok=True)
        try:
            pls, total = listas_todas(cl)
        except Exception as e:                           # noqa: BLE001
            morre("não deu para ler as suas playlists: %s" % e)
        if total and len(pls) < total:
            print("  · mostrando %d das %d listas "
                  "(STYLUS_QOBUZ_LISTAS muda o teto)" % (len(pls), total),
                  file=sys.stderr)
        # Os mosaicos em paralelo: quatro capas cada, e em série cinco
        # playlists já são vinte downloads seguidos.
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ln in pool.map(linha_de_lista, pls):
                if ln:
                    print(ln)
        return
    elif modo in ("buscar", "search"):
        termo = " ".join(sys.argv[2:]).strip()
        if not termo:
            morre("busca vazia")
        try:
            # 30 era pouco para uma busca larga ("beatles" tem centenas de
            # edições) e a tela não tinha como pedir mais.
            dados = cl.search_albums(termo, limit=100)
        except Exception as e:                           # noqa: BLE001
            morre("a busca falhou: %s" % e)
    else:
        morre("uso: qobuz_shelf.py favoritos [N] | buscar TERMOS | listas")

    itens = dados.get("albums", {})
    if isinstance(itens, dict):
        itens = itens.get("items", [])
    if not isinstance(itens, list):
        itens = []
    for ln in linhas([disco(i) for i in itens]):
        print(ln)


if __name__ == "__main__":
    main()
