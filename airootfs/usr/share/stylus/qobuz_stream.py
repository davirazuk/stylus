#!/usr/bin/env python3
"""Monta a lista de um disco do Qobuz para tocar SEM baixar.

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
import configparser
import json
import os
import re
import sys
import urllib.request

CACHE = os.path.expanduser("~/.cache/stylus/qobuz")
# 27 = 24 bit até 192 kHz. O Qobuz devolve o melhor que a assinatura E o
# disco derem; pedir menos é jogar fora hi-res num sistema cuja tese inteira é
# não reamostrar.
QUALIDADE = int(os.environ.get("STYLUS_QOBUZ_QUALITY", "27"))


def morre(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def cliente():
    try:
        from qobuz_dl.qopy import Client
    except ImportError:
        morre("o qobuz-dl não está instalado. Rode:  stylus qobuz instalar")
    cfg = os.path.expanduser("~/.config/qobuz-dl/config.ini")
    if not os.path.isfile(cfg):
        morre("o qobuz-dl não está configurado. Rode `stylus qobuz abrir` e "
              "entre uma vez.")
    c = configparser.ConfigParser()
    c.read(cfg, encoding="utf-8")

    def g(k):
        return c.get("DEFAULT", k, fallback="").strip()

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


def main():
    if len(sys.argv) < 2:
        morre("uso: qobuz_stream.py ID|URL")
    alvo = sys.argv[1]
    m = re.search(r"/album/(?:[^/]+/)?([A-Za-z0-9]+)/?$", alvo)
    album_id = m.group(1) if m else alvo

    cl = cliente()
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

    linhas = ["#EXTM3U"]
    tocaveis = 0
    for t in faixas:
        if not t.get("streamable", True):
            # Acontece: disco no catálogo, faixa não licenciada aqui. Dizer
            # qual pulou é melhor do que um silêncio de três minutos.
            print("  · fora do catálogo daqui: %s" % (t.get("title") or "?"),
                  file=sys.stderr)
            continue
        try:
            u = cl.get_track_url(t["id"], fmt_id=QUALIDADE)
        except Exception as e:                           # noqa: BLE001
            print("  · sem endereço para %s: %s" % (t.get("title") or "?", e),
                  file=sys.stderr)
            continue
        url = u.get("url")
        if not url:
            continue
        nome = t.get("title") or "faixa %s" % t.get("track_number", "?")
        versao = t.get("version")
        if versao:
            nome = "%s (%s)" % (nome, versao)
        dur = int(t.get("duration") or u.get("duration") or 0)
        # O EXTINF é o que vira título no MPRIS — polybar, notificação,
        # scrobble. Vírgula e quebra de linha dentro dele desmontariam a
        # própria linha do m3u.
        rotulo = "%s - %s" % (artista, nome.replace("\n", " ").replace(",", " "))
        linhas.append("#EXTINF:%d,%s" % (dur, rotulo))
        linhas.append(url)
        tocaveis += 1

    if not tocaveis:
        morre("nenhuma faixa deste disco pode ser tocada com esta assinatura")

    lista = os.path.join(destino, "lista.m3u")
    with open(lista, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")

    prof = faixas[0].get("maximum_bit_depth") or 16
    taxa = faixas[0].get("maximum_sampling_rate") or 44.1
    print("%s — %s  ·  %d faixas  ·  %sbit/%skHz"
          % (artista, titulo, tocaveis, prof,
             ("%g" % round(float(taxa), 1)).replace(".", ",")),
          file=sys.stderr)
    print(lista)


if __name__ == "__main__":
    main()
