#!/usr/bin/env python3
"""Monta a lista de um disco — ou de uma PLAYLIST — do Qobuz, sem baixar.

POR QUE ISTO EXISTE
-------------------
A assinatura do Qobuz já estava paga e o sistema só sabia fazer uma coisa com
ela: baixar. Ouvir um disco que você ainda não sabe se quer guardar exigia
gastar quatro gigabytes e depois apagar — ou abrir o site num navegador, que é
sair do sistema inteiro para fazer a única coisa que ele existe para fazer.

O Qobuz entrega um endereço assinado por faixa, e o mpv toca endereço. Então
transmitir é montar a lista certa e entregar ao MESMO tocador que toca a
estante — com as mesmas travas de áudio, pela mesma placa, aparecendo no
mesmo polybar, contado pelo mesmo scrobble.

O que sai daqui é o caminho de um .m3u. Quem toca é o `stylus qobuz tocar`.

UMA PLAYLIST NÃO É UM DISCO
---------------------------
Ela entra pelo mesmo cano — mesma pasta de cache, mesmo m3u, mesmo disco.json
— com duas diferenças que importam:

* **Um lado só.** O sistema inteiro existe para dizer "o lado acabou, vira o
  disco", e isso é verdade sobre um disco. Uma playlist de 853 faixas viraria
  quarenta lados, e o aviso que é a tese do projeto viraria um alarme a cada
  vinte minutos. O disco.json diz `continuo: true` e o vinyl não corta.
* **Tem teto.** Cada faixa custa um endereço ASSINADO, e assinar 853 é meia
  hora de pedidos para uma assinatura que expira em uma. O padrão são as
  primeiras 200 (mudável no STYLUS_QOBUZ_MAX), assinadas em paralelo, e o
  programa DIZ quantas pegou — em vez de parecer que a playlist é menor.
* **E por isso ela pode vir SORTEADA** (`--sortear`). Com teto, "as
  primeiras 200" são sempre as MESMAS 200: uma playlist de 853 faixas tinha
  653 que este sistema nunca tocaria, e a pessoa não tinha como saber. O
  sorteio embaralha a lista inteira ANTES de cortar, então o que entra é uma
  amostra de tudo, diferente a cada vez que se põe. Um DISCO nunca é
  sorteado — a ordem de um disco é uma escolha de quem o fez.

DUAS COISAS QUE ISTO TEM QUE RESPEITAR
--------------------------------------
1. Os endereços EXPIRAM. São assinados na hora e valem cerca de uma hora, o
   que cobre um disco inteiro com folga — mas não cobre pôr o disco, sair
   para almoçar e voltar. Por isso a lista é montada no instante em que se
   aperta tocar, e não guardada para depois.
2. O `#EXTINF` não é enfeite. Sem ele o mpv anuncia o ENDEREÇO como título, e
   o endereço é uma linha de duzentos caracteres com uma assinatura dentro —
   que é o que apareceria no polybar, na notificação de troca de faixa e em
   qualquer coisa que leia MPRIS.
"""
import json
import os
import random
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qobuz_conta import campo, ler                             # noqa: E402

CACHE = os.path.expanduser("~/.cache/stylus/qobuz")
# 27 = 24 bit até 192 kHz. O Qobuz devolve o melhor que a assinatura E o
# disco derem; pedir menos é jogar fora hi-res num sistema cuja tese inteira é
# não reamostrar.
QUALIDADE = int(os.environ.get("STYLUS_QOBUZ_QUALITY", "27"))
# O teto de faixas de uma playlist. 200 é ~13 horas: mais do que a assinatura
# de uma hora dos endereços cobre de qualquer jeito.
TETO = int(os.environ.get("STYLUS_QOBUZ_MAX", "200"))


def morre(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def cliente():
    # O qobuz_dl escreve "Logging..." e "Membership: Studio" pelo logging dele,
    # em inglês, toda vez que autentica. Aqui isso é ruído: este programa já
    # imprime uma linha em português dizendo o disco, as faixas e a qualidade,
    # e essas duas apareciam ANTES dela, sem contexto nenhum. Baixar o nível
    # do logger é o jeito de calá-lo sem mexer no pacote.
    import logging
    logging.getLogger("qobuz_dl").setLevel(logging.WARNING)
    logging.getLogger("qopy").setLevel(logging.WARNING)
    try:
        from qobuz_dl.qopy import Client
    except ImportError:
        morre("o qobuz-dl não está instalado. Rode:  stylus qobuz instalar")
    c = ler()

    def g(k):
        return campo(c, k)

    if not g("app_id"):
        morre("o qobuz-dl não está configurado. Rode `stylus qobuz entrar`.")

    segredos = [x.strip() for x in g("secrets").split(",") if x.strip()]
    if not (g("user_id") and g("user_auth_token") and g("app_id") and segredos):
        morre("o config.ini do qobuz-dl está incompleto. Entre uma vez pela "
              "interface:  stylus qobuz abrir")
    # O barulho da autenticação ("Logging...", "Membership: Studio") vai para
    # o stderr sozinho — o que este programa imprime no stdout é UM caminho, e
    # quem o lê é um `$(...)` de shell.
    cl = Client(None, None, g("app_id"), segredos, skip_auth=True)
    cl.auth_with_token(g("user_id"), g("user_auth_token"))
    return cl


def limpo(nome):
    """Um nome de pasta que sobrevive a qualquer sistema de arquivos."""
    nome = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", nome or "").strip(" .")
    return (nome or "sem nome")[:120]


def capa(meta, destino):
    """A capa, em arquivo, para quem desenha o disco poder desenhá-lo.

    Sem falha fatal: um disco sem capa toca igual, e morrer aqui seria
    recusar a música por causa da imagem.
    """
    img = meta.get("image") or {}
    url = img.get("large") or img.get("small") or img.get("thumbnail")
    if not url:
        return None
    alvo = os.path.join(destino, "cover.jpg")
    if os.path.exists(alvo):
        return alvo
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            dados = r.read()
        # Pelo .parcial: um download interrompido no meio deixaria um jpeg
        # truncado no cache, e ele ficaria lá para sempre — o `os.path.exists`
        # acima nunca mais tentaria de novo.
        with open(alvo + ".parcial", "wb") as fh:
            fh.write(dados)
        os.replace(alvo + ".parcial", alvo)
        return alvo
    except Exception:                                    # noqa: BLE001
        return None


def assinar(cl, faixas):
    """(url, faixa) para cada faixa que dá para tocar, NA ORDEM.

    Em paralelo porque cada assinatura custa ~0,34 s de ida e volta: 200
    faixas em série é um minuto e meio de tela parada antes do primeiro som.
    Oito de cada vez — o suficiente para esconder a latência sem parecer um
    ataque à API de quem nos vende a assinatura.

    A ordem é preservada pelo `map`, e não pela ordem de chegada: uma playlist
    embaralhada por acidente é pior do que uma que demora.
    """
    def _uma(t):
        if not t.get("streamable", True):
            # Acontece: disco no catálogo, faixa não licenciada aqui. Dizer
            # qual pulou é melhor do que um silêncio de três minutos.
            return None, t, "fora do catálogo daqui"
        try:
            u = cl.get_track_url(t["id"], fmt_id=QUALIDADE)
        except Exception as e:                           # noqa: BLE001
            return None, t, str(e)
        return (u.get("url") or None), t, ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, t, porque in pool.map(_uma, faixas):
            if url is None:
                print("  · %s: %s" % (t.get("title") or "?", porque or "sem endereço"),
                      file=sys.stderr)
                continue
            yield url, t


def rotulo_de(t, artista_padrao):
    """(nome da faixa, quem toca). Numa playlist cada faixa é de um artista."""
    nome = t.get("title") or "faixa %s" % t.get("track_number", "?")
    versao = t.get("version")
    if versao:
        nome = "%s (%s)" % (nome, versao)
    quem = ((t.get("performer") or {}).get("name")
            or ((t.get("album") or {}).get("artist") or {}).get("name")
            or artista_padrao)
    return nome, quem


def escrever(destino, linhas, manifesto, cabecalho):
    os.makedirs(destino, exist_ok=True)
    lista = os.path.join(destino, "lista.m3u")
    with open(lista, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")
    # O disco.json é o que faz um disco transmitido virar um Album de
    # verdade para o resto do sistema — com LADOS, e portanto com o aviso de
    # virar o lado, que é a única coisa que esta máquina faz e mais nenhuma
    # faz. Sem ele, o vinyl.py tentaria descobrir a ordem lendo arquivos de
    # áudio que não existem.
    # Quando esta lista foi assinada. Os endereços do Qobuz valem cerca de
    # uma hora; sem esta marca, nada no sistema tem como saber se a lista que
    # está no disco ainda vale ou se já é papel velho.
    cabecalho.setdefault("assinado_em", int(time.time()))
    cabecalho["tracks"] = manifesto
    with open(os.path.join(destino, "disco.json"), "w", encoding="utf-8") as fh:
        json.dump(cabecalho, fh, ensure_ascii=False, indent=1)
    return lista


def um_disco(cl, album_id):
    try:
        meta = cl.get_album_meta(album_id)
    except Exception as e:                               # noqa: BLE001
        morre("não achei esse disco no Qobuz: %s" % e)

    artista = ((meta.get("artist") or {}).get("name")) or "Vários"
    titulo = meta.get("title") or "sem título"
    faixas = ((meta.get("tracks") or {}).get("items")) or []
    if not faixas:
        morre("esse disco não tem faixa nenhuma para tocar")

    destino = os.path.join(CACHE, limpo(artista), limpo(titulo))
    os.makedirs(destino, exist_ok=True)
    capa(meta, destino)

    linhas, manifesto = ["#EXTM3U"], []
    for url, t in assinar(cl, faixas):
        nome, quem = rotulo_de(t, artista)
        dur = int(t.get("duration") or 0)
        # O EXTINF é o que vira título no MPRIS — polybar, notificação,
        # scrobble. Vírgula e quebra de linha dentro dele desmontariam a
        # própria linha do m3u.
        linhas.append("#EXTINF:%d,%s - %s"
                      % (dur, quem, nome.replace("\n", " ").replace(",", " ")))
        linhas.append(url)
        manifesto.append({"title": nome, "duration": dur, "url": url,
                          "qid": t.get("id")})

    if not manifesto:
        morre("nenhuma faixa deste disco pode ser tocada com esta assinatura")

    ano = str(meta.get("release_date_original")
              or meta.get("release_date_stream") or "")[:4]
    lista = escrever(destino, linhas, manifesto,
                     {"fonte": "qobuz", "id": album_id, "artist": artista,
                      "album": titulo, "year": ano})
    prof = faixas[0].get("maximum_bit_depth") or 16
    taxa = faixas[0].get("maximum_sampling_rate") or 44.1
    print("%s — %s  ·  %d faixas  ·  %sbit/%skHz"
          % (artista, titulo, len(manifesto), prof,
             ("%g" % round(float(taxa), 1)).replace(".", ",")),
          file=sys.stderr)
    return lista


def uma_lista(cl, lista_id, sortear=False):
    # O get_plist_meta é um GERADOR de páginas de 500 — não um dicionário.
    # Tratá-lo como dicionário devolve o objeto do gerador e a playlist
    # aparece vazia, sem erro nenhum.
    try:
        paginas = list(cl.get_plist_meta(lista_id))
    except Exception as e:                               # noqa: BLE001
        morre("não achei essa playlist no Qobuz: %s" % e)
    if not paginas:
        morre("essa playlist veio vazia")

    cabeca = paginas[0]
    nome = cabeca.get("name") or "playlist"
    dono = ((cabeca.get("owner") or {}).get("name")) or "Qobuz"
    faixas = []
    for pag in paginas:
        faixas += ((pag.get("tracks") or {}).get("items")) or []
    if not faixas:
        morre("essa playlist não tem faixa nenhuma")

    total = len(faixas)
    if sortear:
        # ANTES do corte, e é esse o ponto. Sortear depois de cortar
        # embaralharia as mesmas 200 de sempre; sorteando antes, uma playlist
        # de 853 faixas entrega 200 tiradas de todas elas, outras a cada vez.
        random.shuffle(faixas)
    if total > TETO:
        print("  · playlist com %d faixas; pegando %s %d "
              "(STYLUS_QOBUZ_MAX muda isso)"
              % (total, "sorteadas" if sortear else "as primeiras", TETO),
              file=sys.stderr)
        faixas = faixas[:TETO]

    destino = os.path.join(CACHE, "Playlists", limpo("%s — %s" % (dono, nome)))
    os.makedirs(destino, exist_ok=True)
    # A capa de uma playlist é a do primeiro disco dela: o Qobuz manda um
    # mosaico de quatro em `images`, mas o deck desenha UMA capa girando.
    imgs = cabeca.get("images300") or cabeca.get("images150") or cabeca.get("images") or []
    if imgs:
        capa({"image": {"large": imgs[0]}}, destino)

    linhas, manifesto = ["#EXTM3U"], []
    for url, t in assinar(cl, faixas):
        titulo, quem = rotulo_de(t, dono)
        dur = int(t.get("duration") or 0)
        linhas.append("#EXTINF:%d,%s - %s"
                      % (dur, quem, titulo.replace("\n", " ").replace(",", " ")))
        linhas.append(url)
        # Numa playlist o nome da faixa sozinho não diz nada: "Just" é de
        # quem? O disco na tela mostra este título, e ele tem que se
        # sustentar sem um artista de álbum por trás.
        manifesto.append({"title": "%s — %s" % (quem, titulo),
                          "duration": dur, "url": url,
                          # O id da faixa no Qobuz. Não é enfeite: é o que
                          # permite ASSINAR DE NOVO esta mesma faixa quando o
                          # endereço vencer, sem perguntar a playlist inteira
                          # de volta (e, numa lista sorteada, sem perder a
                          # ordem que foi sorteada).
                          "qid": t.get("id")})

    if not manifesto:
        morre("nenhuma faixa desta playlist pode ser tocada com esta assinatura")

    lista = escrever(destino, linhas, manifesto,
                     {"fonte": "qobuz-lista", "id": str(lista_id),
                      "artist": dono, "album": nome, "year": "",
                      "sorteada": bool(sortear),
                      # Um lado só: ver o cabeçalho deste arquivo.
                      "continuo": True})
    horas = sum(m["duration"] for m in manifesto) / 3600.0
    print("%s — %s  ·  %d faixas  ·  %.1f h%s"
          % (dono, nome, len(manifesto), horas,
             "  ·  sorteada" if sortear else ""), file=sys.stderr)
    # Os endereços expiram (ver o cabeçalho). Uma lista de 13 horas assinada
    # com validade de uma é uma promessa que ela não cumpre, e o sintoma —
    # faixas que o mpv pula em silêncio até a lista "acabar" — parece defeito
    # de rede, ou do disco, ou do tocador. Dizer a hora não conserta, mas
    # troca "parou sozinho" por uma frase que a pessoa pode entender.
    if horas > 1.2:
        print("  · atenção: os endereços assinados valem cerca de uma hora, "
              "e isto tem %.1f. Depois disso, `tocar` de novo renova."
              % horas, file=sys.stderr)
    return lista


def renovar(cl, pasta, desde=0):
    """Assina de novo, da faixa `desde` em diante. Devolve o m3u da cauda.

    POR QUE ISTO EXISTE
    -------------------
    Os endereços do Qobuz são assinados e valem cerca de UMA HORA. Uma
    playlist de 200 faixas são treze. O que acontecia depois da primeira hora
    não era um erro: o mpv pedia o endereço seguinte, levava 403, pulava para
    o próximo, levava 403 de novo, e assim até o fim da lista — em silêncio,
    em poucos segundos. Da poltrona isso é "a música parou sozinha", e não há
    nada na tela nem no journal ligando aquilo a uma assinatura vencida.

    A mesma faixa, assinada de novo, é um endereço novo. Por isso o manifesto
    guarda o `qid`: a lista é reassinada sem perguntar a playlist de volta ao
    Qobuz — o que importa numa lista SORTEADA, onde perguntar de novo daria
    outra ordem e outra amostra.

    Escreve dois arquivos: o `lista.m3u` inteiro, atualizado (é o que vale
    para quem puser este disco de novo), e um `cauda.m3u` só com o que foi
    reassinado — que é o que o tocador pendura no fim da fila, com os
    `#EXTINF` no lugar, sem perder o nome das faixas.
    """
    m = manifesto_de(pasta)
    if not m:
        morre("não há disco.json em %s" % pasta)
    faixas = m.get("tracks") or []
    if not faixas:
        morre("esse disco.json não tem faixa nenhuma")
    desde = max(0, min(int(desde), len(faixas)))
    alvo = faixas[desde:]
    if not alvo:
        morre("não há o que reassinar depois da faixa %d" % desde)
    sem_id = [t for t in alvo if not t.get("qid")]
    if sem_id:
        # Listas escritas antes do `qid` existir. Dizer é melhor do que
        # reassinar metade e deixar a outra metade vencida sem avisar.
        morre("esta lista foi montada por uma versão antiga e não guarda o "
              "id das faixas: ponha-a de novo para renovar")

    novos = []
    for t in alvo:
        try:
            u = cl.get_track_url(t["qid"], fmt_id=QUALIDADE)
        except Exception as e:                           # noqa: BLE001
            print("  · %s: %s" % (t.get("title") or "?", e), file=sys.stderr)
            novos.append(None)
            continue
        novos.append((u or {}).get("url") or None)

    linhas_cauda = ["#EXTM3U"]
    trocadas = 0
    for t, url in zip(alvo, novos):
        if url:
            t["url"] = url
            trocadas += 1
        linhas_cauda.append("#EXTINF:%d,%s"
                            % (int(t.get("duration") or 0),
                               (t.get("title") or "").replace("\n", " ")
                               .replace(",", " ")))
        linhas_cauda.append(t["url"])
    if not trocadas:
        morre("nenhuma faixa pôde ser reassinada")

    linhas = ["#EXTM3U"]
    for t in faixas:
        linhas.append("#EXTINF:%d,%s" % (int(t.get("duration") or 0),
                                         (t.get("title") or "")
                                         .replace("\n", " ").replace(",", " ")))
        linhas.append(t["url"])
    cabecalho = {k: v for k, v in m.items() if k != "tracks"}
    cabecalho["assinado_em"] = int(time.time())
    escrever(pasta, linhas, faixas, cabecalho)

    cauda = os.path.join(pasta, "cauda.m3u")
    with open(cauda, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas_cauda) + "\n")
    print("reassinadas %d faixas a partir da %d" % (trocadas, desde + 1),
          file=sys.stderr)
    return cauda


def manifesto_de(pasta):
    """O disco.json da pasta, ou None. (O vinyl tem um igual; aqui não se
    importa o vinyl para não arrastar o deck inteiro para dentro do
    assinador.)"""
    try:
        with open(os.path.join(pasta, "disco.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                    # noqa: BLE001
        return None


# `/playlist/123`, `playlist:123`, `lista:123` — e o `--lista 123` explícito,
# para o id cru, que sozinho não diz se é disco ou playlist.
_LISTA = re.compile(r"(?:/playlist/|playlist:|lista:)(\d+)")
_ALBUM = re.compile(r"/album/(?:[^/]+/)?([A-Za-z0-9]+)/?$")


def main():
    args = [a for a in sys.argv[1:]]
    forcar_lista = False
    sortear = False
    # As opções vêm antes do alvo e em qualquer ordem: `--lista --sortear 123`
    # e `--sortear --lista 123` são a mesma coisa, e quem digita não devia ter
    # que adivinhar qual.
    renova_pasta = None
    desde = 0
    while args and args[0].startswith("--"):
        if args[0] in ("--lista", "--playlist"):
            forcar_lista = True
        elif args[0] in ("--sortear", "--aleatorio", "--shuffle"):
            sortear = True
        elif args[0] == "--renovar":
            if len(args) < 2:
                morre("--renovar precisa da pasta do disco")
            renova_pasta, args = args[1], args[1:]
        elif args[0] == "--desde":
            if len(args) < 2:
                morre("--desde precisa do número da faixa")
            desde, args = int(args[1]), args[1:]
        else:
            morre("não conheço a opção %s" % args[0])
        args = args[1:]
    if renova_pasta:
        print(renovar(cliente(), renova_pasta, desde))
        return
    if not args:
        morre("uso: qobuz_stream.py [--lista] [--sortear] ID|URL\n"
              "       qobuz_stream.py --renovar PASTA [--desde N]")
    alvo = args[0]

    cl = cliente()
    m = _LISTA.search(alvo)
    if m or forcar_lista:
        print(uma_lista(cl, m.group(1) if m else alvo, sortear=sortear))
        return
    if sortear:
        # Um disco tem uma ordem, e ela é uma escolha de quem o fez. Recusar
        # é mais honesto do que sortear em silêncio — e o `[s]` da AGORA
        # embaralha o que já está tocando, para quem quiser mesmo.
        morre("um DISCO não se sorteia: a ordem dele é do disco.\n"
              "       Para embaralhar o que está tocando, use o [s] na AGORA.")
    m = _ALBUM.search(alvo)
    print(um_disco(cl, m.group(1) if m else alvo))


if __name__ == "__main__":
    main()
