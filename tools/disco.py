#!/usr/bin/env python3
"""Confere que o DISCO não é um círculo chapado.

    ./tools/disco.py PNG-DO-DECK [--cd]

Sai 0 em silêncio quando passa; 1 e uma linha por medida reprovada.

POR QUE ISTO EXISTE:

O dono disse, nesta ordem e mais de uma vez: "the vinyl looks like a black
circle and the cd a white circle". As duas vezes o desenho ESTAVA lá — sulcos,
lustro, vãos de faixa, aro. O que faltava era DISTÂNCIA entre os tons.

Medindo o que o código compunha, todo traço do vinil ficava entre 1,27 e
1,53:1 contra o corpo, e todo traço do CD entre 1,04 e 1,13:1. O LCD do Vita
2000, cujo preto é um cinza aceso (ver tools/contraste.py), não separa nada
disso: o disco chega achatado. E o PNG do preview APROVAVA, porque o monitor
de quem revisa separa 1,3:1 sem esforço — a mesma armadilha do tamanho da
letra, que já custou um "text is kind of illegible".

Então a conferência não olha o código: olha o PIXEL QUE SAIU. Varre raios
dentro do anel gravado e pergunta quanto o mais claro se distingue do mais
escuro. Um disco chapado responde ~1,0.
"""

import math
import sys

try:
    from PIL import Image
except ImportError:
    print("disco.py: PULA (sem Pillow)")
    sys.exit(0)

# do ui_layout.c, ui_deck_geom(960, 544)
CX, CY, R = 266.08, 292.0, 153.6

# o anel GRAVADO: fora do rótulo, dentro do aro
R0, R1 = 0.40, 0.93

ALVOS = {
    "modulacao": 1.35,   # sulco vizinho contra sulco vizinho: há textura
    "silhueta":  1.35,   # corpo vs tela: o disco é um objeto pousado no fundo
}


def lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(p):
    return 0.2126 * lin(p[0]) + 0.7152 * lin(p[1]) + 0.0722 * lin(p[2])


def cr(a, b):
    la, lb = lum(a), lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[2])
        return 2
    im = Image.open(args[0]).convert("RGB")
    px = im.load()
    w, h = im.size

    def amostra(ang, t):
        rr = R * (R0 + t * (R1 - R0))
        x = int(round(CX + math.cos(ang) * rr))
        y = int(round(CY + math.sin(ang) * rr))
        if 0 <= x < w and 0 <= y < h:
            return px[x, y]
        return None

    # MODULAÇÃO: é TEXTURA, e textura é coisa LOCAL.
    #
    # A primeira versão desta medida pegava o claro e o escuro do percurso
    # inteiro — e por isso não media nada: o aro, o anel âmbar da faixa que
    # toca e o espectro entram na conta e dão um número alto mesmo com a
    # superfície completamente lisa. Conferido: com os alfas antigos, que são
    # exatamente os que produziram "black circle", ela devolvia 2,74 — mais
    # que a versão consertada. Uma conferência que aprova o defeito que
    # existe para pegar é pior que nenhuma.
    #
    # O que separa "superfície com sulco" de "prato liso" é a diferença entre
    # ANÉIS VIZINHOS. Então: janela deslizante de poucos pixels ao longo do
    # raio, contraste dentro dela, e a MEDIANA de todas as janelas de todos os
    # ângulos. Um traço grande e isolado não move a mediana; sulco, sim.
    passo = 1.0 / max(1.0, R * (R1 - R0))     # ~1 px por amostra
    JANELA = 7
    mods = []
    for k in range(24):
        ang = k * (2 * math.pi / 24)
        vals, t = [], 0.0
        while t <= 1.0:
            v = amostra(ang, t)
            if v:
                vals.append(v)
            t += passo
        for i in range(0, len(vals) - JANELA):
            jan = vals[i:i + JANELA]
            mods.append(cr(max(jan, key=lum), min(jan, key=lum)))
    mods.sort()
    modulacao = mods[len(mods) // 2] if mods else 0.0

    # SILHUETA: o disco separa da tela em ALGUM ponto da borda — ou no
    # corpo junto ao aro, ou no próprio aro. Um vinil PRETO de verdade tem
    # o corpo colado no fundo escuro por desenho (a separação é o aro aceso
    # + os sulcos); medir só o corpo reprovaria o disco certo. Então vale o
    # MÁXIMO das duas separações — e um círculo chapado sem aro reprova nas
    # duas, que é o defeito que isto existe para pegar.
    dentro, aro, fora = [], [], []
    for k in range(36):
        ang = k * (2 * math.pi / 36)
        for rr, saco in ((R * 0.88, dentro), (R * 0.99, aro),
                         (R * 1.10, fora)):
            x = int(round(CX + math.cos(ang) * rr))
            y = int(round(CY + math.sin(ang) * rr))
            if 0 <= x < w and 0 <= y < h:
                saco.append(px[x, y])
    med = lambda s: sorted(s, key=lum)[len(s) // 2] if s else (0, 0, 0)
    silhueta = max(cr(med(dentro), med(fora)), cr(med(aro), med(fora)))

    medido = {"modulacao": modulacao, "silhueta": silhueta}
    ruim = 0
    for nome, alvo in ALVOS.items():
        if medido[nome] < alvo:
            ruim += 1
            print(f"{nome}: {medido[nome]:.2f}:1 — abaixo de {alvo:.2f}:1 "
                  f"(no LCD do aparelho isto chega achatado)")
    if ruim == 0 and "-v" in sys.argv:
        print(f"modulação {modulacao:.2f}:1   silhueta {silhueta:.2f}:1")
    return 1 if ruim else 0


if __name__ == "__main__":
    sys.exit(main())
