#!/usr/bin/env python3
"""stylus now — onde você está no DISCO, não na faixa.

O que um tocador diz é o nome da música. O que um disco te diz, e nenhum
tocador diz, é em que lado você está e quanto falta para ter que levantar.
Essa informação existe (as durações estão nos arquivos) e é ela que faz um
álbum ser um álbum em vez de uma fila.

    --bar   uma linha só, para a barra do desktop
"""
import argparse
import os
import sys
import time

sys.path.insert(0, "/usr/share/stylus/lib")
import vinyl  # noqa: E402

D = "\033[2m"; B = "\033[1m"; A = "\033[38;5;117m"; P = "\033[38;5;218m"
O = "\033[0m"


def humano(seg):
    m = int(max(0, seg) // 60)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else (f"{m}min" if m else "<1min")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bar", action="store_true")
    args = ap.parse_args()

    ses = vinyl.Session()
    # O Session pesquisa numa thread; sem esta espera a primeira leitura sai
    # vazia e parece que nada está tocando.
    for _ in range(24):
        if (ses.snapshot().get("path") or "").strip():
            break
        time.sleep(0.15)
    snap = ses.snapshot()
    path = snap.get("path") or ""
    if not path or not os.path.isfile(path):
        if not args.bar:
            print(f"\n  {D}nada tocando.{O}")
            print(f"  {D}`stylus record` sorteia um disco da estante.{O}\n")
        return 0
    folder = vinyl.resolve_album(path, snap.get("artist", ""), snap.get("album", ""))
    if not folder:
        if not args.bar:
            print(f"\n  {snap.get('artist','?')} — {snap.get('title','?')}")
            print(f"  {D}(fora da estante){O}\n")
        return 0
    al = vinyl.Album(folder, envelope=False)
    idx = vinyl.track_index_for(al, snap)
    pos, _d = ses.position()
    t_abs = al.album_time(idx, pos)
    si, side = al.side_for(t_abs)
    if side is None:
        return 0
    resta = max(0.0, side["end"] - t_abs)
    ultimo = si >= len(al.sides) - 1
    rotulo = side["label"].replace("SIDE", "LADO")
    nf = side["tracks"].index(idx) + 1 if idx in side.get("tracks", []) else 1

    if args.bar:
        print(f"%{{F#5bcefa}}󰀥%{{F-}} {rotulo} %{{F#6e7887}}·%{{F-}} "
              f"{nf}/{len(side.get('tracks', []))} %{{F#6e7887}}·%{{F-}} "
              f"{'fim' if ultimo else 'vira'} {humano(resta)}")
        return 0

    faixa = al.tracks[idx] if 0 <= idx < len(al.tracks) else {}
    print()
    print(f"  {B}{al.artist}{O}")
    print(f"  {A}{al.name}{O}" + (f"  {D}{al.year}{O}" if al.year else ""))
    print()
    print(f"  {P}{rotulo}{O}  {D}faixa {nf} de "
          f"{len(side.get('tracks', []))}{O}")
    print(f"  {faixa.get('title', '')}")
    print()
    largura = 46
    frac = (t_abs - side["start"]) / max(1e-6, side["end"] - side["start"])
    cheio = int(largura * min(1.0, max(0.0, frac)))
    print(f"  {A}{'━' * cheio}{D}{'─' * (largura - cheio)}{O}  "
          f"{'acaba' if ultimo else 'vira'} em {humano(resta)}")
    hist = f"{al.plays}ª vez" if al.plays else "primeira vez"
    print(f"\n  {D}{hist}{O}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
