#!/usr/bin/env python3
"""Confere que a cor de TEXTO da tela se lê no aparelho.

    ./tools/contraste.py src/ui.c

Imprime uma linha por cor reprovada e sai com 1; silêncio e 0 quando passa.

POR QUE ISTO É CONFERÊNCIA E NÃO OLHO:

O Vita 2000 — que é o aparelho deste app — tem tela de LCD, não de OLED. O
preto dele não é preto: é um cinza aceso por trás. A paleta do projeto é de
fósforo (âmbar sobre quase-preto), que é uma lei feita para o OLED, onde o
fundo some de verdade. No LCD o fundo sobe, e a distância entre ele e um
cinza escuro encolhe justamente onde mora o texto secundário.

Medindo, a paleta antiga tinha COL_TEXT_FAINT a 1,91:1 e COL_TEXT_DIM a
3,14:1 contra o fundo — o primeiro é invisível e o segundo está abaixo do
mínimo de 4,5 da WCAG para texto. E não era pouco texto: o DIM leva o nome do
artista em cada card da estante, as contagens e a fila de dicas do rodapé.

Olhar o PNG do preview não pega isso: o monitor de quem revisa tem contraste
melhor que o LCD do aparelho, então no PC "dá para ler". É a mesma família do
tamanho de letra — o preview aprova o que o aparelho reprova.

Os alvos são deliberadamente FOLGADOS em relação à WCAG: o preto levantado do
LCD come contraste que a conta não enxerga.
"""

import re
import sys

# Cada TEMA declara o próprio fundo (VINYL_FUNDO, VITA_FUNDO...), e cada um é
# conferido contra o SEU. Um tema novo entra na conferência só por existir no
# ui.c — que é o ponto: a paleta virou escolha do usuário, e a promessa de
# legibilidade no LCD do Vita 2000 vale para todas as escolhas, não só para a
# primeira. Sem fundo declarado, cai neste, que é o histórico.
FUNDO_PADRAO = (10, 14, 21)

# cor -> contraste mínimo. Só as que carregam TEXTO: COL_COLD é filete e halo,
# nunca letra, e exigir 3:1 dele apagaria o desenho que ele existe para fazer.
ALVOS = {
    "COL_TEXT":         7.0,   # corpo
    "COL_TEXT_DIM":     4.5,   # segunda linha, contagens, dicas
    "COL_TEXT_FAINT":   3.0,   # ajuda de canto
    "COL_AMBER":        4.5,   # títulos e seleção
    "COL_AMBER_BRIGHT": 4.5,
    "COL_ALARM":        4.5,   # erro: o que MAIS precisa ser lido
}


def lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb):
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contraste(fg, bg):
    a, b = lum(fg), lum(bg)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


def cores(caminho):
    """acha `#define NOME RGBA8(r, g, b, a)`"""
    txt = open(caminho, encoding="utf-8").read()
    pat = re.compile(
        r"#define\s+(\w+)\s+RGBA8\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
    return {m.group(1): tuple(int(m.group(i)) for i in (2, 3, 4))
            for m in pat.finditer(txt)}


def temas(achadas):
    """Agrupa as cores por PREFIXO de tema: VINYL_COL_TEXT -> ("VINYL", "COL_TEXT")."""
    fora = {}
    for nome, rgb in achadas.items():
        if nome.endswith("_FUNDO"):
            fora.setdefault(nome[: -len("_FUNDO")], {})["FUNDO"] = rgb
    for nome, rgb in achadas.items():
        for pref in fora:
            if nome.startswith(pref + "_"):
                fora[pref][nome[len(pref) + 1:]] = rgb
    return fora


def main():
    ruim = 0
    for caminho in sys.argv[1:]:
        achadas = cores(caminho)
        grupos = temas(achadas)
        if not grupos:
            print(f"{caminho}: nenhum tema achado — o ui.c deve declarar "
                  f"pelo menos um <NOME>_FUNDO")
            return 1
        for tema in sorted(grupos):
            paleta = grupos[tema]
            fundo = paleta.get("FUNDO", FUNDO_PADRAO)
            for nome, alvo in ALVOS.items():
                if nome not in paleta:
                    print(f"{caminho}: tema {tema}: {nome} sumiu da paleta — "
                          f"o alvo de contraste ficou órfão")
                    ruim += 1
                    continue
                r = contraste(paleta[nome], fundo)
                if r + 0.005 < alvo:
                    print(f"{caminho}: tema {tema}: {nome} = {paleta[nome]} dá "
                          f"{r:.2f}:1 contra o fundo {fundo}, precisa de "
                          f"{alvo:.1f}:1 — no LCD do Vita 2000 isso não se lê")
                    ruim += 1
    return 1 if ruim else 0


if __name__ == "__main__":
    sys.exit(main())
