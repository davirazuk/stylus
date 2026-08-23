#!/usr/bin/env python3
"""A parede: cada álbum da biblioteca desenhado como o disco que ele seria.

Não é decoração e não é o mesmo disco com capas diferentes. Cada anel é a
intensidade MEDIDA daquele instante daquele álbum, e cada anel claro é uma
fronteira de faixa de verdade — então um disco denso e alto do começo ao fim
e um disco de dinâmica larga saem visivelmente diferentes, e dá para achar a
faixa quieta de um álbum olhando de longe. É a mesma ideia do modo ritual,
espalhada pela biblioteca inteira: a impressão digital de cada disco.

    ./venv/bin/python tools/vinyl_wall.py "Artista/Álbum" "Artista/Álbum" ...
    ./venv/bin/python tools/vinyl_wall.py --cols 4 --tile 700 ...
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import vinyl
from vinyl_preview import draw_strip, draw_fill, label_image, SS, OUT_DIR

BG = (7, 9, 13)
ROOT = vinyl.library_root()


def portrait(album, size, at=0.55):
    """Um disco, centrado, sem braço — o objeto, não a cena."""
    w = h = size * SS
    iso = (1.0, 1.0)                      # quadro quadrado: sem correção
    cx = cy = 0.0
    radius = 0.90
    light = math.radians(-38.0)
    rot = at * 7.0

    img = Image.new("RGB", (w, h), BG)
    side_idx, side = album.side_for((album.total or 0) * at)
    if side is None:
        side = {"label": "SIDE A", "start": 0.0, "end": max(1.0, album.total or 1.0),
                "tracks": list(range(len(album.tracks)))}
    span = max(1e-6, side["end"] - side["start"])
    frac = float(np.clip(((album.total or 0) * at - side["start"]) / span, 0.0, 1.0))

    for strip in vinyl.disc_body(cx, cy, radius, iso, light):
        draw_fill(img, strip, w, h)
    dr = ImageDraw.Draw(img)

    env = album.envelope_snapshot()
    tracks = [album.tracks[i] for i in side.get("tracks", [])]
    for pts, cols, wd in vinyl.groove_rings(cx, cy, radius, iso, side, env, tracks,
                                            light, played_ring=int(frac * (vinyl.N_RINGS - 1))):
        draw_strip(dr, pts, cols, wd, w, h)
    br = vinyl.boundary_ring(cx, cy, radius, iso, side, env, frac, light)
    if br:
        draw_strip(dr, br[0], br[1], br[2], w, h)
    for pts, cols, wd in vinyl.edge_and_label_rings(cx, cy, radius, iso, light):
        draw_strip(dr, pts, cols, wd, w, h)

    glow = img.filter(ImageFilter.GaussianBlur(radius=8 * SS))
    img = Image.fromarray(np.clip(
        np.asarray(img, np.int16) + np.asarray(glow, np.int16) * 0.7, 0, 255).astype(np.uint8))

    lab = label_image(album.cover, int(vinyl.R_LABEL * radius * (h / 2) * 2), rot)
    if lab is not None:
        img.paste(lab, (int(w / 2 - lab.width / 2), int(h / 2 - lab.height / 2)), lab)
        d2 = ImageDraw.Draw(img)
        hr = max(2, int(vinyl.R_SPINDLE * radius * (h / 2)))
        d2.ellipse((w / 2 - hr, h / 2 - hr, w / 2 + hr, h / 2 + hr), fill=BG)
    return img.resize((size, size), Image.LANCZOS)


def font(sz):
    for p in ("/usr/share/fonts/TTF/JetBrainsMonoNLNerdFont-Light.ttf",
              "/usr/share/fonts/TTF/DejaVuSansMono.ttf"):
        if os.path.isfile(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("albums", nargs="*")
    ap.add_argument("--from-file", help="um caminho de álbum por linha")
    ap.add_argument("--bare", action="store_true",
                    help="sem legendas: a parede densa, só os discos")
    ap.add_argument("--title", default="A BIBLIOTECA COMO DISCOS")
    ap.add_argument("--min-tracks", type=int, default=0)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--tile", type=int, default=700)
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "wall.png"))
    ap.add_argument("--at", type=float, default=0.55)
    args = ap.parse_args()

    specs = list(args.albums)
    if args.from_file:
        with open(os.path.expanduser(args.from_file)) as fh:
            specs += [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    if not specs:
        ap.error("passe álbuns ou --from-file")

    cards = []
    for spec in specs:
        folder = spec if os.path.isdir(spec) else os.path.join(ROOT, spec)
        folder = os.path.expanduser(folder)
        if not os.path.isdir(folder):
            print(f"  pulei (não existe): {spec}")
            continue
        # Álbum de mais de um disco guarda as faixas em "Disc 01", "Disc 02".
        # Isso não é defeito do vinyl.py: para ele um disco É um disco, e o
        # resolve_album já cai na subpasta certa quando o tocador entrega o
        # caminho do arquivo. Aqui a pasta vem do nome do álbum, então quem
        # tem que descer é este script — e desce só no primeiro, porque a
        # parede mostra um disco por álbum.
        def _has_audio(d):
            try:
                return any(n.lower().endswith(vinyl.AUDIO_EXT) for n in os.listdir(d))
            except OSError:
                return False

        if not _has_audio(folder):
            subs = sorted(os.path.join(folder, n) for n in os.listdir(folder)
                          if os.path.isdir(os.path.join(folder, n)))
            sub = next((d for d in subs if _has_audio(d)), None)
            if sub is None:
                print(f"  pulei (sem áudio em lugar nenhum): {spec}")
                continue
            print(f"  (multi-disco) usando {os.path.basename(sub)} de {spec}")
            folder = sub
        alb = vinyl.Album(folder)
        t0 = time.time()
        while not alb.env_ready and time.time() - t0 < 240:
            time.sleep(0.2)
        if not alb.tracks or len(alb.tracks) < args.min_tracks:
            print(f"  pulei ({len(alb.tracks)} faixa(s)): {spec}")
            continue
        print(f"  {alb.artist} — {alb.name}: {len(alb.tracks)} faixas, "
              f"{(alb.total or 0)/60:.0f} min, {len(alb.sides)} lado(s), "
              f"envelope={'ok' if alb.env_ready else 'FALTOU'}", flush=True)
        cards.append((portrait(alb, args.tile, args.at), alb))

    if not cards:
        print("nada para desenhar"); return 1

    cols = min(args.cols, len(cards))
    rows = (len(cards) + cols - 1) // cols
    if args.bare:
        # Numa parede de centenas de discos a legenda vira ruído cinza: o
        # rótulo de cada um já é a capa, e o ponto aqui é a MASSA — ver a
        # coleção inteira de uma vez e as diferenças de textura entre discos.
        pad, cap, top = 10, 0, 150
    else:
        pad, cap, top = 42, 96, 190
    W = cols * args.tile + (cols + 1) * pad
    H = top + rows * (args.tile + cap) + rows * pad + pad

    out = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(out)
    f_title, f_sub = font(52), font(26)
    f_a, f_n = font(27), font(23)
    d.text((pad + 6, 54), args.title, font=f_title, fill=(228, 232, 238))
    d.text((pad + 8, 118),
           "cada anel é a intensidade medida daquele instante — nenhum disco é igual a outro",
           font=f_sub, fill=(110, 124, 144))

    for i, (im, alb) in enumerate(cards):
        r, c = divmod(i, cols)
        x = pad + c * (args.tile + pad)
        y = top + r * (args.tile + cap + pad)
        out.paste(im, (x, y))
        if not args.bare:
            d.text((x + 4, y + args.tile + 16), (alb.artist or "").upper(),
                   font=f_a, fill=(140, 156, 178))
            name = alb.name or ""
            if len(name) > 30:
                name = name[:29] + "…"
            d.text((x + 4, y + args.tile + 50), name, font=f_n, fill=(224, 230, 238))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    out.save(args.out)
    print(f"\nescrevi {args.out}  ({W}x{H}, {len(cards)} discos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
