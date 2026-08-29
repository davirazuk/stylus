"""Põe a capa e a letra dentro dos próprios arquivos de áudio.

Por quê: capa e letra vinham morando como arquivos ao lado (o cover.jpg da
pasta, um .lrc por faixa). Muitos tocadores leem isso — mas a etiqueta
embutida é o que VIAJA junto com o arquivo: para o celular, para outro
tocador, para qualquer lugar aonde a pasta não vá junto. Isto preenche as
etiquetas sem mexer no que já estiver lá.

De onde tira, na ordem de preferência:
  capa    a que já estiver embutida (fica como está) → o cover.jpg/png da
          pasta → outra faixa da mesma pasta que tenha capa embutida
  letra   a que já estiver embutida (fica como está) → o .lrc ao lado da
          faixa → consulta ao LRCLIB por artista/título/álbum/duração

O que ele nunca faz:
  * escrever por cima de capa ou letra já embutida;
  * apagar os arquivos ao lado — eles continuam sendo a fonte;
  * tocar no áudio: só as etiquetas são escritas;
  * parar por causa do LRCLIB — as consultas são espaçadas e falha ali não
    interrompe o resto.

Uso:
  stylus tags                         só mostra o que faria, na coleção toda
  stylus tags --apply                 escreve as etiquetas
  stylus tags --apply --no-fetch      só o que está ao lado, sem rede
  stylus tags --apply CAMINHO/DISCO   só naquele disco

Limitar a um disco importa na passada que roda depois de um download:
percorrer os milhares de arquivos e reconsultar o LRCLIB para cada faixa
que nunca terá letra leva muitos minutos e repete as mesmas consultas
fracassadas toda vez.
"""
import os
import sys
import time

import requests
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, USLT, error as id3error

from _raiz import raiz, audio_ext   # a coleção e o que é música: um lugar só

ROOT = raiz()
TODOS = audio_ext()          # o que é música (ver o _raiz)
# O que esta ferramenta sabe ESCREVER — que é outra pergunta. Ela grava capa
# e letra dentro do arquivo, e as duas rotinas que fazem isso (`read_state` e
# o que vem depois) só existem para o FLAC e o MP3. Widenar esta lista sem
# escrever as rotinas seria prometer um conserto que não acontece; o que ela
# faz é DIZER quantas faixas ficaram de fora, no fim.
ESCREVIVEIS = (".flac", ".mp3")
COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg")
UA = {"User-Agent": "stylus-tool/1.0"}
LRCLIB_DELAY = 0.25          # be polite to a free community API


def folder_cover(dirpath, _cache={}):
    """Bytes da capa desta pasta — e, faltando, a da PASTA DE CIMA.

    Álbum de mais de um disco guarda as faixas em "Disc 01"/"Disc 02" e a
    cover.jpg fica no álbum, um nível acima. Procurando só ao lado do arquivo,
    esses álbuns relatavam "nenhuma capa disponível em lugar nenhum" com a
    capa ali do lado — 51 faixas do Duster ficaram sem arte por causa disto.

    Sobe no máximo um nível: dois já sairia do álbum e pegaria a capa de outro
    disco do mesmo artista, que é pior do que não achar nada.
    """
    if dirpath in _cache:
        return _cache[dirpath]
    found = None
    for base in (dirpath, os.path.dirname(dirpath.rstrip(os.sep))):
        if not base or not os.path.isdir(base):
            continue
        for name in COVER_NAMES:
            p = os.path.join(base, name)
            if os.path.isfile(p):
                mime = "image/png" if name.lower().endswith(".png") else "image/jpeg"
                with open(p, "rb") as f:
                    found = (f.read(), mime)
                break
        if found:
            break
    _cache[dirpath] = found
    return found


def read_state(path):
    """(has_art, has_lyrics, tagobj, kind) or None if unreadable."""
    try:
        if path.lower().endswith(".flac"):
            a = FLAC(path)
            return (bool(a.pictures),
                    bool(a.get("lyrics") or a.get("unsyncedlyrics")),
                    a, "flac")
        audio = MP3(path, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        t = audio.tags
        return (bool(t.getall("APIC")), bool(t.getall("USLT")), audio, "mp3")
    except Exception:
        return None


def lrclib_lookup(artist, title, album, duration):
    try:
        r = requests.get("https://lrclib.net/api/get",
                         params={"artist_name": artist, "track_name": title,
                                 "album_name": album, "duration": duration},
                         headers=UA, timeout=12)
        if r.ok:
            j = r.json()
            return j.get("syncedLyrics") or j.get("plainLyrics")
    except Exception:
        pass
    return None


def main(apply=False, fetch=True, root=None):
    art_done = lyr_sidecar = lyr_fetched = 0
    art_missing = lyr_missing = 0
    scanned = 0
    root = root or ROOT

    ignorados = set()
    for dirpath, _dn, filenames in os.walk(root):
        audio_files = sorted(f for f in filenames
                             if f.lower().endswith(ESCREVIVEIS))
        # O que é música e esta ferramenta não sabe ESCREVER. Contar e dizer,
        # em vez de calar: numa coleção em ALAC ou Opus ela varria tudo e
        # terminava com "0 discos", sem uma palavra sobre o motivo — a pessoa
        # conclui que a coleção está bem, e não que a ferramenta não serve
        # para ela.
        for f in filenames:
            baixo = f.lower()
            if baixo.endswith(TODOS) and not baixo.endswith(ESCREVIVEIS):
                ignorados.add(os.path.splitext(baixo)[1])
        if not audio_files:
            continue

        cover = folder_cover(dirpath)
        # Fall back to art already embedded in a sibling track.
        if cover is None:
            for f in audio_files:
                st = read_state(os.path.join(dirpath, f))
                if st and st[0]:
                    a, kind = st[2], st[3]
                    if kind == "flac" and a.pictures:
                        p = a.pictures[0]
                        cover = (p.data, p.mime or "image/jpeg")
                    elif kind == "mp3":
                        ap = a.tags.getall("APIC")
                        if ap:
                            cover = (ap[0].data, ap[0].mime or "image/jpeg")
                    if cover:
                        break

        for fname in audio_files:
            path = os.path.join(dirpath, fname)
            st = read_state(path)
            if st is None:
                continue
            has_art, has_lyr, a, kind = st
            scanned += 1
            changed = False

            if not has_art:
                if cover:
                    data, mime = cover
                    if apply:
                        if kind == "flac":
                            pic = Picture()
                            pic.data, pic.mime, pic.type = data, mime, 3
                            pic.desc = "Cover"
                            a.add_picture(pic)
                        else:
                            a.tags.add(APIC(encoding=3, mime=mime, type=3,
                                            desc="Cover", data=data))
                    art_done += 1
                    changed = True
                else:
                    art_missing += 1

            if not has_lyr:
                text = None
                lrc = os.path.splitext(path)[0] + ".lrc"
                if os.path.isfile(lrc):
                    try:
                        text = open(lrc, encoding="utf-8").read().strip() or None
                        if text:
                            lyr_sidecar += 1
                    except Exception:
                        text = None
                # An empty or unreadable sidecar is not an answer — fall
                # through to LRCLIB rather than recording a false gap.
                if text is None and fetch:
                    try:
                        if kind == "flac":
                            artist = (a.get("artist") or [""])[0]
                            title = (a.get("title") or [""])[0]
                            album = (a.get("album") or [""])[0]
                            dur = int(a.info.length)
                        else:
                            artist = str(a.tags.get("TPE1", ""))
                            title = str(a.tags.get("TIT2", ""))
                            album = str(a.tags.get("TALB", ""))
                            dur = int(a.info.length)
                        if artist and title:
                            time.sleep(LRCLIB_DELAY)
                            text = lrclib_lookup(artist, title, album, dur)
                            if text:
                                lyr_fetched += 1
                                if apply:
                                    with open(lrc, "w", encoding="utf-8") as fh:
                                        fh.write(text)
                    except Exception:
                        text = None

                if text:
                    if apply:
                        if kind == "flac":
                            a["lyrics"] = text
                        else:
                            a.tags.setall("USLT", [USLT(encoding=3, lang="eng",
                                                        desc="", text=text)])
                    changed = True
                else:
                    lyr_missing += 1

            if changed and apply:
                try:
                    a.save()
                except Exception as e:
                    print(f"  NÃO DEU PARA GRAVAR {path}: {e}", flush=True)

            if scanned % 250 == 0:
                print(f"  ...{scanned} lidos "
                      f"(art+{art_done}, lyrics+{lyr_sidecar + lyr_fetched})",
                      flush=True)

    verb = "embuti" if apply else "embutiria"
    print(f"\n{scanned} arquivos lidos")
    print(f"{verb} capa:    {art_done}")
    print(f"{verb} letra:   {lyr_sidecar + lyr_fetched} "
          f"({lyr_sidecar} do .lrc ao lado, {lyr_fetched} do LRCLIB)")
    print(f"ainda sem capa:  {art_missing} (não há capa em lugar nenhum)")
    print(f"ainda sem letra: {lyr_missing} (não achada mesmo — "
          f"instrumental, bootleg, lançamento obscuro)")
    if ignorados:
        # Silêncio aqui vira "a coleção está bem". Ela não está: a ferramenta
        # é que não serve para aqueles arquivos, e isso tem que estar escrito.
        print("\n%s: esta ferramenta grava capa e letra DENTRO de FLAC e MP3."
              % ", ".join(sorted(ignorados)))
        print("As faixas nesses formatos foram puladas — não é que estejam "
              "boas, é que não\ndá para escrever nelas por aqui. O `stylus "
              "covers` lê a capa de todos eles.")
    if not apply:
        print("\nisto foi só uma olhada — passe --apply para gravar as etiquetas")


if __name__ == "__main__":
    # `--help` tem que IMPRIMIR e sair, sempre. Sem esta guarda, um `--help`
    # caía na execução normal: aqui não existe argparse, então a opção não
    # casava com nada e virava "nenhum argumento" — que para estas ferramentas
    # quer dizer "faça o trabalho inteiro". O `stylus tags --help` saía
    # varrendo a coleção toda e consultando a rede faixa por faixa; quem só
    # queria saber o que o comando faz esperava minutos e desistia.
    if {"-h", "--help"} & set(sys.argv[1:]):
        print((__doc__ or "sem ajuda").strip())
        raise SystemExit(0)

    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    main("--apply" in sys.argv, "--no-fetch" not in sys.argv,
         paths[0] if paths else None)
