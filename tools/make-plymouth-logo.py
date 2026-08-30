#!/usr/bin/env python3
"""Desenha o logo.png da tela de arranque — o disco, em luz sobre o preto.

POR QUE ISTO EXISTE
-------------------
O logo era um desenho de linha em AZUL (#4d5e79 nos anéis, o azul do
Catppuccin na agulha), da paleta velha, sobre um fundo VERDE escrito no
stylus.script. Ninguém tinha visto: nada nunca escolheu o tema do plymouth,
então aquela tela nunca apareceu em máquina nenhuma. Quando passou a
aparecer, apareceu contra a §5.5 do CLAUDE.md — luz âmbar no quase-preto, e
o azul é informação, não a cor do objeto.

Gerar em vez de guardar um PNG opaco: quando a paleta mudar, isto roda de
novo e o disco acompanha. É o mesmo motivo de o `palette` existir.

    python3 tools/make-plymouth-logo.py
"""
import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    sys.exit("preciso do python-pillow")

ALVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "airootfs/usr/share/plymouth/themes/stylus/logo.png")
LADO = 320
S = 4                       # supersampling: o plymouth não suaviza nada


def cor(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


# A paleta, escrita aqui como o `palette` a define.
INK_SOFT = "#101219"
LINE = "#343a48"
AMBER = "#f0a030"
AMBER_GLOW = "#ffc850"


def main():
    n = LADO * S
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = n / 2
    r_ext = n * 0.47
    r_lab = n * 0.10

    # OS SULCOS. Cinza frio, e mais acesos perto da borda: a luz do disco vem
    # da própria coisa, não de uma lâmpada fora de quadro (§5.5).
    anéis = 17
    for i in range(anéis):
        f = i / (anéis - 1.0)
        r = r_lab * 1.35 + (r_ext - r_lab * 1.35) * f
        a = int(54 + 108 * f ** 1.6)
        d.ellipse([c - r, c - r, c + r, c + r], outline=cor(LINE, a),
                  width=max(1, S // 2))

    # A BORDA, um fio mais claro: é ela que dá a forma do objeto de longe.
    d.ellipse([c - r_ext, c - r_ext, c + r_ext, c + r_ext],
              outline=cor(LINE, 190), width=S)

    # O SELO no meio, e o furo.
    d.ellipse([c - r_lab, c - r_lab, c + r_lab, c + r_lab],
              fill=cor(INK_SOFT, 255), outline=cor(AMBER, 165), width=S)
    r_furo = n * 0.016
    d.ellipse([c - r_furo, c - r_furo, c + r_furo, c + r_furo],
              fill=(0, 0, 0, 0))

    # A AGULHA: uma cruz curta e quente no sulco, com o braço saindo dela para
    # fora do disco. Quase toda a luz mora na ponta — o braço é só o rastro.
    ang = math.radians(38)
    rx = c + math.cos(ang) * (r_ext * 0.62)
    ry = c + math.sin(ang) * (r_ext * 0.62)
    fim_x = c + math.cos(ang) * (r_ext * 1.18)
    fim_y = c + math.sin(ang) * (r_ext * 1.18)
    braço = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    db = ImageDraw.Draw(braço)
    db.line([rx, ry, fim_x, fim_y], fill=cor(AMBER, 150), width=int(S * 1.6))
    im.alpha_composite(braço)

    # O brilho da ponta, por desfoque: é o mesmo truque do halo da interface.
    brilho = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    dg = ImageDraw.Draw(brilho)
    rp = n * 0.022
    dg.ellipse([rx - rp, ry - rp, rx + rp, ry + rp], fill=cor(AMBER_GLOW, 255))
    brilho = brilho.filter(ImageFilter.GaussianBlur(n * 0.012))
    im.alpha_composite(brilho)
    d.ellipse([rx - rp * 0.42, ry - rp * 0.42, rx + rp * 0.42, ry + rp * 0.42],
              fill=cor(AMBER_GLOW, 255))

    im = im.resize((LADO, LADO), Image.LANCZOS)
    im.save(os.path.normpath(ALVO), "PNG")
    print("escrito: %s" % os.path.normpath(ALVO))


if __name__ == "__main__":
    main()
