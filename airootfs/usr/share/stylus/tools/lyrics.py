#!/usr/bin/env python3
"""stylus lyrics — a letra ao lado do arquivo, em .lrc.

Por que .lrc e não tag: um .lrc é sincronizado, e sincronizado é o que faz a
letra aparecer na linha certa enquanto o disco toca — na tela cheia, na barra e na
tela cheia. Letra em tag é um bloco de texto que ninguém lê.

    stylus lyrics                 o disco que está tocando
    stylus lyrics DISCO           esse
    stylus lyrics --all           todos os que não têm
    stylus lyrics --print         imprime a do momento (para o rofi)

A busca usa o lrclib.net, que é aberto, não pede chave e devolve .lrc
sincronizado. Quando ele não tem, não inventa: fica sem, e sem é honesto.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, "/usr/share/stylus/lib")
import vinyl  # noqa: E402
from vinyl import plural  # noqa: E402

D = "\033[2m"; A = "\033[38;5;117m"; OK = "\033[38;5;114m"
W = "\033[38;5;215m"; O = "\033[0m"
API = "https://lrclib.net/api/get"
UA = "stylus/1.0 (https://github.com/davirazuk/stylus)"


def buscar(artista, titulo, album, dur):
    q = urllib.parse.urlencode({
        "artist_name": artista, "track_name": titulo,
        "album_name": album or "", "duration": int(dur or 0)})
    try:
        req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.load(r)
        return d.get("syncedLyrics") or None
    except Exception:                     # noqa: BLE001 — sem letra não é erro
        return None


def disco(folder, forcar=False):
    al = vinyl.Album(folder, envelope=False)
    achou = pulou = 0
    print(f"\n  {A}{al.artist} — {al.name}{O}")
    for t in al.tracks:
        lrc = os.path.splitext(t["path"])[0] + ".lrc"
        if os.path.exists(lrc) and not forcar:
            pulou += 1
            continue
        letra = buscar(al.artist, t.get("title") or "", al.name,
                       t.get("duration") or 0)
        nome = (t.get("title") or os.path.basename(t["path"]))[:46]
        if letra:
            with open(lrc, "w", encoding="utf-8") as fh:
                fh.write(letra)
            achou += 1
            print(f"    {OK}✓{O} {nome}")
        else:
            print(f"    {D}·{O} {D}{nome}{O}")
    print(f"  {D}{plural(achou, 'nova')}, {pulou} já tinham.{O}")
    return achou


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--print", dest="imprimir", action="store_true")
    args = ap.parse_args()

    if args.imprimir:
        ses = vinyl.Session()
        import time
        for _ in range(20):
            if ses.snapshot().get("path"):
                break
            time.sleep(0.15)
        p = ses.snapshot().get("path") or ""
        lrc = os.path.splitext(p)[0] + ".lrc"
        if os.path.isfile(lrc):
            for t, txt in vinyl.parse_lrc(lrc):
                if txt.strip():
                    print(txt)
        return 0

    if args.all:
        alvos = vinyl.shelf(min_tracks=1)
    elif args.alvo:
        alvos = [os.path.expanduser(args.alvo)]
    else:
        ses = vinyl.Session()
        import time
        for _ in range(20):
            if ses.snapshot().get("path"):
                break
            time.sleep(0.15)
        s = ses.snapshot()
        f = vinyl.resolve_album(s.get("path"), s.get("artist", ""),
                                s.get("album", ""))
        if not f:
            print(f"\n  {W}nada tocando. passe um disco ou use --all.{O}\n")
            return 1
        alvos = [f]

    total = 0
    for f in alvos:
        try:
            total += disco(f, args.force)
        except KeyboardInterrupt:
            break
        except Exception as e:            # noqa: BLE001
            print(f"    {W}{type(e).__name__}: {e}{O}")
    print(f"\n  {OK}{plural(total, 'letra')} nova"
          f"{'' if total == 1 else 's'}.{O}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
