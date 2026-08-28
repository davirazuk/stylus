"""
Embed cover art and lyrics into the audio files themselves.

Why: art and lyrics have been living as sidecar files (folder cover.jpg,
per-track .lrc). Plenty of players read those, but embedded tags are what
travel with the file — onto the phone, into other players, anywhere the
folder structure doesn't come along. This fills in the tags without
disturbing anything already there.

Sources, in order of preference:
  art     existing embedded (left alone) -> folder cover.jpg/png -> another
          track in the same folder that does have embedded art
  lyrics  existing embedded (left alone) -> .lrc sidecar next to the track
          -> LRCLIB lookup by artist/title/album/duration

Safety:
  * Never overwrites art or lyrics that are already embedded.
  * Never deletes sidecars — they stay as the source of truth.
  * Writes tags only; audio streams are untouched.
  * LRCLIB lookups are rate-limited and failures are non-fatal.

Usage:
  python3 embed_metadata.py            # dry run over the whole library
  python3 embed_metadata.py --apply    # write tags
  python3 embed_metadata.py --apply --no-fetch   # sidecars only, no network
  python3 embed_metadata.py --apply /path/to/Artist/Album   # scope to a subtree

Scoping matters for the per-album pass after a download: walking all ~3500
files and re-querying LRCLIB for every permanently-missing track takes many
minutes and repeats the same failed lookups every run.
"""
import os
import sys
import time

import requests
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, USLT, error as id3error

from _raiz import raiz   # onde fica a coleção, decidido num lugar só

ROOT = raiz()
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

    for dirpath, _dn, filenames in os.walk(root):
        audio_files = sorted(f for f in filenames
                             if f.lower().endswith((".flac", ".mp3")))
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
                    print(f"  SAVE FAILED {path}: {e}", flush=True)

            if scanned % 250 == 0:
                print(f"  ...{scanned} scanned "
                      f"(art+{art_done}, lyrics+{lyr_sidecar + lyr_fetched})",
                      flush=True)

    verb = "embedded" if apply else "would embed"
    print(f"\nscanned {scanned} files")
    print(f"{verb} cover art:  {art_done}")
    print(f"{verb} lyrics:     {lyr_sidecar + lyr_fetched} "
          f"({lyr_sidecar} from .lrc, {lyr_fetched} fetched from LRCLIB)")
    print(f"still without art:    {art_missing} (no cover available anywhere)")
    print(f"still without lyrics: {lyr_missing} (genuinely not found — "
          f"instrumentals, bootlegs, obscure releases)")
    if not apply:
        print("\ndry run — pass --apply to write tags")


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
