#!/usr/bin/env python3
"""Papel de parede feito a partir da SUA música — não de uma imagem qualquer.

A ideia é a mesma do modo ritual, esticada para a tela inteira: a forma vem
da intensidade medida de um álbum de verdade, então o papel de parede não é
decoração genérica, é aquele disco. Dois discos diferentes dão dois papéis
de parede diferentes, e o seu não existe na máquina de mais ninguém.

  --style groove   sulcos gigantes varrendo a tela, centro fora do quadro.
                   Lê como textura, não como objeto: funciona atrás de
                   janelas, que é onde papel de parede passa a vida.
  --style ridges   linhas empilhadas, a intensidade do álbum como relevo.
                   O parente óbvio é a capa do Unknown Pleasures; a
                   diferença é que estes números são do SEU disco.

    ./venv/bin/python tools/vinyl_wallpaper.py --album "Radiohead/Kid A" \
        --style groove --out ~/.local/share/backgrounds/gerado.png
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import vinyl

ROOT = vinyl.library_root()
# A paleta viva desta máquina: fundo quase preto, azul estrutural, rosa de
# acento. Ver ~/.config/stylus/themes/radiohead.theme.
BG = (10, 12, 16)
BLUE = (91, 206, 250)
PINK = (245, 169, 184)
DIM = (110, 124, 144)


def load(spec):
    folder = spec if os.path.isdir(spec) else os.path.join(ROOT, spec)
    folder = os.path.expanduser(folder)
    if not os.path.isdir(folder):
        sys.exit(f"não existe: {spec}")
    if not any(n.lower().endswith(vinyl.AUDIO_EXT) for n in os.listdir(folder)):
        subs = sorted(os.path.join(folder, n) for n in os.listdir(folder)
                      if os.path.isdir(os.path.join(folder, n)))
        folder = next((d for d in subs
                       if any(n.lower().endswith(vinyl.AUDIO_EXT) for n in os.listdir(d))), folder)
    alb = vinyl.Album(folder)
    t0 = time.time()
    while not alb.env_ready and time.time() - t0 < 300:
        time.sleep(0.2)
    env = alb.envelope_snapshot()
    if env is None or not len(env):
        sys.exit("não consegui medir a intensidade deste álbum")
    print(f"  {alb.artist} — {alb.name}: "
          f"{vinyl.plural(len(alb.tracks), 'faixa')}, "
          f"{len(env)} amostras de intensidade")
    return alb, np.asarray(env, dtype=np.float64)


def norm(e):
    e = np.asarray(e, dtype=np.float64)
    lo, hi = np.percentile(e, 2), np.percentile(e, 98)
    return np.clip((e - lo) / max(1e-9, hi - lo), 0.0, 1.0)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def style_groove(env, W, H, turns):
    """Sulcos gigantes, centro fora do quadro. Textura, não objeto."""
    SS = 2
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(img)
    e = norm(env)
    # Centro bem fora, embaixo à esquerda: o que entra no quadro é um pedaço
    # de disco, e um pedaço de disco lê como paisagem em vez de logotipo.
    cx, cy = -w * 0.35, h * 1.30
    r_max = math.hypot(w - cx, cy) * 1.02
    r_min = r_max * 0.18
    n = turns
    for i in range(n):
        t = i / max(1, n - 1)
        r = r_min + (r_max - r_min) * t
        # O tempo do disco corre de fora para dentro, como num LP.
        amp = e[int((1.0 - t) * (len(e) - 1))]
        col = lerp(lerp(BG, DIM, 0.55), BLUE, amp ** 1.4)
        if amp > 0.82:
            col = lerp(col, PINK, (amp - 0.82) / 0.18 * 0.5)
        wd = 1 + int(round(amp * 2.2))
        dr.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=col, width=wd)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6 * SS))
    return img.resize((W, H), Image.LANCZOS)


def style_ridges(env, W, H, rows):
    """Linhas empilhadas: a intensidade do álbum como relevo."""
    SS = 2
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(img)
    e = norm(env)
    per = max(8, len(e) // rows)
    top, bot = h * 0.10, h * 0.92
    step = (bot - top) / max(1, rows - 1)
    amp_px = step * 3.1
    for r in range(rows):
        seg = e[r * per:(r + 1) * per]
        if len(seg) < 4:
            break
        # Reamostra a linha para a largura da tela e alisa: um relevo é uma
        # crista, não um serrilhado.
        x = np.linspace(0, len(seg) - 1, w)
        y = np.interp(x, np.arange(len(seg)), seg)
        k = np.hanning(41); k /= k.sum()
        y = np.convolve(np.pad(y, 20, mode="edge"), k, mode="same")[20:-20]
        base = top + r * step
        pts = [(i, base - y[i] * amp_px) for i in range(0, w, 2)]
        t = r / max(1, rows - 1)
        col = lerp(BLUE, PINK, t * 0.75)
        strength = float(y.max())
        col = lerp(lerp(BG, DIM, 0.5), col, min(1.0, 0.25 + strength))
        # Preenche por baixo com o fundo para a crista de cima esconder a de
        # baixo — é isso que dá a leitura de relevo em vez de emaranhado.
        dr.polygon(pts + [(w, h), (0, h)], fill=BG)
        dr.line(pts, fill=col, width=max(1, SS))
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5 * SS))
    return img.resize((W, H), Image.LANCZOS)


def _default_album(arg):
    """Sem --album, tira um disco da estante configurada.

    O padrão antigo era a pasta de um álbum específico na casa de quem
    escreveu isto. Num sistema, o padrão tem que ser "o que houver aí".
    """
    if arg:
        return os.path.expanduser(arg)
    import vinyl as _v
    return _v.draw_record() or _v.library_root()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", default=None,
                    help="pasta do disco; sem isto, sorteia um da estante")
    ap.add_argument("--style", choices=("groove", "ridges"), default="groove")
    ap.add_argument("--res", default="2560x1600")
    ap.add_argument("--turns", type=int, default=190)
    ap.add_argument("--rows", type=int, default=34)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    W, H = (int(v) for v in args.res.split("x"))
    _alb, env = load(_default_album(args.album))
    img = (style_groove(env, W, H, args.turns) if args.style == "groove"
           else style_ridges(env, W, H, args.rows))
    out = os.path.expanduser(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print(f"  escrevi {out} ({W}x{H}, estilo {args.style})")


if __name__ == "__main__":
    sys.exit(main())
