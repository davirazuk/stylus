#!/usr/bin/env python3
"""Desenha a identidade visual do STYLUS: papel de parede, tela de login,
GRUB, Plymouth e o logotipo em texto.

    python3 tools/gen-art.py [--out airootfs]

O MOTIVO É UM SÓ e ele se repete em tudo: sulcos. Um disco visto muito de
perto, com o centro fora do quadro, e uma linha reta cruzando — a agulha.
Nada de logotipo redondo com nome dentro; a imagem é o objeto de que o
sistema trata.

Tudo é composto em RGBA e depois achatado. Desenhar RGBA direto num RGB faz o
PIL descartar o alfa em silêncio, e aí toda transparência "sutil" sai opaca —
que é como uma grade discreta vira uma grade berrante sem ninguém entender
por quê.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    sys.exit("precisa do Pillow:  pip install --user Pillow")

INK = (7, 8, 11)
INK2 = (13, 16, 22)
GROOVE = (34, 41, 55)
GROOVE_HI = (78, 95, 122)
BLUE = (91, 206, 250)
PINK = (245, 169, 184)
LAV = (183, 160, 255)


def base(w, h):
    """Um fundo que escurece para os cantos, sem ser um degradê óbvio."""
    img = Image.new("RGB", (w, h), INK)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(INK[i] + (INK2[i] - INK[i]) * (1 - abs(t - 0.35) * 1.4))
                  for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    return img


def grooves(img, cx, cy, r0, r1, n, largura=1, cor=GROOVE, brilho=None):
    """Os sulcos. Espaçamento levemente irregular de propósito.

    Anéis perfeitamente equidistantes leem como alvo de tiro; um disco de
    verdade tem passo variável porque a densidade da gravação muda, e é essa
    irregularidade que faz o olho aceitar como sulco.
    """
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(n):
        t = i / max(1, n - 1)
        r = r0 + (r1 - r0) * (t ** 1.04)
        wob = math.sin(i * 0.7) * (r1 - r0) * 0.0018
        rr = r + wob
        a = 150 if (i % 9) else 210
        c = brilho if (brilho and i % 23 == 0) else cor
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=c + (a,), width=largura)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def agulha(img, x0, y0, x1, y1, cor=BLUE, brilho=True):
    """A agulha: uma reta só, e é a única coisa clara na imagem."""
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.line([(x0, y0), (x1, y1)], fill=cor + (235,), width=3)
    d.ellipse([x1 - 7, y1 - 7, x1 + 7, y1 + 7], fill=cor + (255,))
    out = Image.alpha_composite(img.convert("RGBA"), ov)
    if brilho:
        g = out.filter(ImageFilter.GaussianBlur(16))
        out = Image.blend(out, Image.alpha_composite(out, g), 0.55)
    return out.convert("RGB")


def vinheta(img, forca=0.85):
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([-w * 0.35, -h * 0.55, w * 1.35, h * 1.55], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(min(w, h) // 7))
    escuro = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, escuro, forca), m)


def parede(w=3840, h=2160):
    """O papel de parede. Centro do disco fora do quadro, embaixo à
    esquerda: o que se vê é uma FATIA de um objeto grande demais para caber,
    que lê como textura em vez de ler como ilustração de um disco."""
    img = base(w, h)
    # O centro fica logo abaixo do canto, e não muito longe: com ele longe
    # demais os arcos viram retas paralelas e a imagem lê como uma grade, não
    # como um disco. Perto assim a curvatura aparece e a coisa se explica
    # sozinha ao bater o olho.
    cx, cy = -w * 0.10, h * 1.16
    img = grooves(img, cx, cy, h * 0.30, h * 2.10, 460, 2, GROOVE, GROOVE_HI)
    ang = math.radians(-31)
    x0, y0 = w * 0.62, h * 0.06
    x1, y1 = x0 + math.cos(ang) * w * 0.30, y0 - math.sin(ang) * w * 0.30
    img = agulha(img, x0, y0, x1, y1)
    return vinheta(img, 0.55)


def login(w=1920, h=1080):
    img = base(w, h)
    img = grooves(img, w * 0.5, h * 0.52, h * 0.10, h * 1.5, 260, 2,
                  GROOVE, GROOVE_HI)
    return vinheta(img, 0.82)


def grub_bg(w=1920, h=1080):
    img = base(w, h)
    img = grooves(img, w * 1.12, h * 0.5, h * 0.2, h * 1.6, 220, 2, GROOVE)
    return vinheta(img, 0.86)


def logo(size=320):
    """A marca: um punhado de sulcos e a agulha cruzando. Sem letra nenhuma —
    o nome já está escrito embaixo em todo lugar onde isto aparece."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = s / 2
    for i in range(16):
        r = s * 0.10 + i * s * 0.026
        a = 90 + i * 8
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=GROOVE_HI + (min(255, a),), width=max(2, s // 260))
    d.ellipse([cx - s * 0.055, cy - s * 0.055, cx + s * 0.055, cy + s * 0.055],
              fill=INK2 + (255,))
    d.ellipse([cx - s * 0.012, cy - s * 0.012, cx + s * 0.012, cy + s * 0.012],
              fill=(0, 0, 0, 255))
    ang = math.radians(-38)
    x0 = cx + math.cos(ang) * s * 0.60
    y0 = cy - math.sin(ang) * s * 0.60
    x1 = cx + math.cos(ang) * s * 0.20
    y1 = cy - math.sin(ang) * s * 0.20
    d.line([(x0, y0), (x1, y1)], fill=BLUE + (255,), width=max(3, s // 150))
    d.ellipse([x1 - s * 0.02, y1 - s * 0.02, x1 + s * 0.02, y1 + s * 0.02],
              fill=BLUE + (255,))
    return img.resize((size, size), Image.LANCZOS)


ASCII = r"""
        ▁▁▁▁▁▁▁▁▁
     ▗▄▟▀▔     ▔▀▙▄▖
   ▗▟▀▘  ▁▄▄▄▄▁  ▝▀▙▖        S T Y L U S
  ▟▘   ▟▀▘    ▝▀▙   ▝▙
 ▐▘  ▗▛   ▗▄▖   ▜▖  ▝▌      a agulha é o único ponto
 ▐   ▐▌  ▐▛▀▜▌  ▐▌   ▌      em que um objeto vira som
 ▐▖  ▝▙   ▝▀▘   ▟▘  ▗▌
  ▜▖   ▜▄▖    ▗▄▛   ▟▘
   ▝▜▄▖  ▔▀▀▀▀▔  ▗▄▛▘
     ▝▀▜▄▖    ▗▄▛▀▘
        ▔▔▔▔▔▔▔▔
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="airootfs")
    args = ap.parse_args()
    out = args.out

    def salva(img, caminho):
        p = os.path.join(out, caminho)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        img.save(p)
        print(f"  {p}  {img.size[0]}x{img.size[1]}")

    print("desenhando:")
    p = parede()
    salva(p, "usr/share/backgrounds/stylus/stylus.png")
    salva(p.resize((1920, 1080), Image.LANCZOS),
          "usr/share/backgrounds/stylus/stylus-1080.png")
    salva(login(), "usr/share/sddm/themes/stylus/background.png")
    salva(grub_bg(), "usr/share/grub/themes/stylus/background.png")
    salva(logo(320), "usr/share/plymouth/themes/stylus/logo.png")
    salva(logo(256), "usr/share/icons/hicolor/256x256/apps/stylus.png")
    salva(logo(64), "usr/share/icons/hicolor/64x64/apps/stylus.png")

    p = os.path.join(out, "usr/share/stylus/logo.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(ASCII.strip("\n") + "\n")
    print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
