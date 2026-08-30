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

# E quantos resultados de BUSCA. Menor que os favoritos de propósito: uma
# busca por "beatles" tem milhares de edições, e ninguém rola mil quadros —
# mas 50, que é onde o servidor apara, é pouco demais para achar a edição
# certa de um disco muito reeditado.
TETO_BUSCA = int(os.environ.get("STYLUS_QOBUZ_BUSCA", "300"))


def _paginado(pedir, chave, teto):
    """(itens, total) — TODAS as páginas, e não a primeira.

    **Sintoma 1:** a loja mostrava 100 discos e parava. Sem recado, sem
    "mostrando 100 de 340" — os outros simplesmente não existiam ali, e a
    pessoa que favoritou 200 discos no celular via metade da própria
    estante. A chamada tinha `offset=0` escrito à mão e nunca uma segunda
    página.

    **Sintoma 2, e é o que trouxe você aqui:** com a paginação escrita, ela
    parava em CINQUENTA. O laço pedia 100 por página e tratava "veio menos do
    que pedi" como fim da lista — mas o `favorite/getUserFavorites` do Qobuz
    APARA o limite em 50 do lado dele. Ou seja: a primeira página já voltava
    curta, por decisão do servidor e não por falta de discos, e o laço
    desistia na hora. O `total` que o próprio Qobuz mandava na mesma resposta
    dizia 213, e ninguém olhava.
    
    A lição é geral: quando a resposta declara QUANTOS existem, é ela quem
    manda parar — não o tamanho da página, que é escolha do servidor. Página
    curta só quer dizer "acabou" quando não há total nenhum para comparar.

    Para de verdade em cinco situações, porque um laço que fala com a rede
    não pode depender de uma só: chegou ao total declarado, veio uma página
    vazia, veio uma página curta E não há total, bateu no teto, ou o offset
    foi ignorado e a mesma página voltou de novo (o que sem esta guarda seria
    um laço infinito somando os mesmos discos para sempre).

    `pedir(offset, limite)` devolve o JSON cru; `chave` é onde a lista mora
    dentro dele ("albums", "playlists").
    """
    itens, total, vistos = [], None, set()
    while len(itens) < teto:
        antes = len(itens)
        pedido = min(POR_PAGINA, teto - antes)
        dados = pedir(antes, pedido)
        bloco = (dados or {}).get(chave) or {}
        pagina = bloco.get("items") or []
        if total is None:
            try:
                total = int(bloco.get("total"))
            except (TypeError, ValueError):
                total = None
        if not pagina:
            break
        # O offset ignorado: sem isto, um servidor que devolve sempre a
        # primeira página faz este laço rodar até o teto repetindo os mesmos
        # discos — que na tela é pior do que mostrar de menos.
        # `if x.get("id") or ...` seria o defeito clássico: o id 0 é FALSO
        # em python, e aí o primeiro disco da lista escapa da guarda toda vez.
        def _chave(it):
            v = it.get("id")
            return str(v) if v is not None else "?%d" % id(it)

        novos = [i for i in pagina if _chave(i) not in vistos]
        for i in pagina:
            vistos.add(_chave(i))
        if not novos:
            break
        itens += novos
        if total is not None and len(itens) >= total:
            break
        # E NÃO existe mais "página curta quer dizer fim".
        #
        # **Sintoma 3:** com o servidor aparando em 50 E sem declarar o
        # total — que acontece —, a primeira página já vinha curta e o laço
        # parava nos 50 outra vez. A regra sobrevivia porque o falso da
        # conferência devolvia os 100 pedidos; com ele aparando como o Qobuz
        # apara, o defeito apareceu na primeira volta.
        #
        # Quem manda parar é a lista, não o tamanho da página: página vazia,
        # página que não traz nada de novo, total atingido ou teto. Custa uma
        # chamada a mais no fim de cada listagem, e é o preço de não inventar
        # uma regra sobre o que o servidor "quis dizer" ao mandar 50.
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


def busca_todos(cl, termo, teto=TETO_BUSCA):
    """Uma busca inteira, e não a primeira página dela. Ver `_paginado`.

    **Sintoma:** a loja mostrava CINQUENTA discos numa busca e parava — as
    duas telas, a de tela cheia e a estante do rofi, porque as duas
    chamavam `cl.search_albums(termo, limit=100)`, uma chamada só. O
    `album/search` do Qobuz apara o limite em 50 do lado dele, exatamente
    como o `favorite/getUserFavorites` fazia: a resposta vinha curta por
    decisão do servidor, o `total` na mesma resposta dizia quantos existem,
    e ninguém olhava.

    É o MESMO defeito dos favoritos, na linha de baixo do mesmo arquivo, e
    ficou para trás quando aquele foi consertado — que é a lição de sempre:
    quando duas chamadas fazem a mesma pergunta ao mesmo servidor, o
    conserto tem que passar pelas duas, ou a resposta tem que ser uma só.
    Agora é uma só: as três passam pelo `_paginado`.

    O `offset` vai com rede de segurança em duas camadas porque a assinatura
    do `search_albums` mudou entre versões do qobuz-dl: primeiro o método,
    depois o `api_call` cru, e só então desiste — voltando à primeira página,
    que é o comportamento de antes e não um erro na cara de quem só queria
    procurar um disco.
    """
    def pedir(off, lim):
        try:
            return cl.search_albums(termo, limit=lim, offset=off)
        except TypeError:
            pass
        try:
            return cl.api_call("album/search", query=termo,
                               offset=off, limit=lim)
        except Exception:                                # noqa: BLE001
            return None if off else cl.search_albums(termo, limit=lim)

    return _paginado(pedir, "albums", teto)


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
            itens, _total = busca_todos(cl, termo)
            dados = {"albums": {"items": itens}}
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
