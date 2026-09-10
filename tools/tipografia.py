#!/usr/bin/env python3
"""Confere que nenhum texto de tela é desenhado com uma escala SOLTA.

    ./tools/tipografia.py src/ui.c

Imprime uma linha por infração e sai com 1; silêncio e 0 quando está limpo.

POR QUE ISTO É CONFERÊNCIA E NÃO REVISÃO:

1. "0,56f" no meio do desenho não diz a ninguém se aquilo dá para ler. A PVF
   do vita2d tem em = 18 px em scale 1,0, então 0,56 são 10 px numa tela de 5
   polegadas — e foi assim que a tela inteira acabou ilegível sem ninguém
   notar lendo o código. Escrito como T_CORPO (17 px), salta aos olhos.

2. MEDIR com uma escala e DESENHAR com outra descentraliza o texto, e isso a
   revisão não pega. Já aconteceu: quatro `text_w()` ANINHADOS dentro do
   argumento x de um `text()` ficaram com a escala velha depois que o desenho
   passou para a nova, e as três linhas da tela de varredura saíram cada uma
   com um centro diferente. Um grep ingênuo também não pega — ele tropeça no
   `cap_l * 0.5f` que é geometria, não letra. Por isso aqui se casa o
   ARGUMENTO certo de cada chamada, e não "um número em algum lugar da linha".

Uma escala em VARIÁVEL (`float sc = cap_l / 52.0f;`) é legítima e passa: é o
caso do rótulo que acompanha o tamanho da capa, e ali medir e desenhar já
compartilham o mesmo valor, que é justamente o que se quer.
"""

import re
import sys

# função -> índice (base 0) do argumento que é a escala
ALVO = {"text": 4, "text_elided": 4, "text_w": 1, "elide": 3}

LITERAL = re.compile(r"\s*[0-9]*\.?[0-9]+f?\s*\Z")


def args_split(s):
    """divide por vírgula de nível zero"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def infracoes(caminho):
    txt = open(caminho, encoding="utf-8").read()
    pat = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(ALVO) + r")\s*\(")
    achados = []
    i = 0
    while True:
        m = pat.search(txt, i)
        if not m:
            return achados
        nome = m.group(1)
        ab = m.end() - 1
        depth, j = 0, ab
        while j < len(txt):
            if txt[j] == "(":
                depth += 1
            elif txt[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1

        partes = args_split(txt[ab + 1:j])
        idx = ALVO[nome]
        if idx < len(partes) and LITERAL.fullmatch(partes[idx]):
            linha = txt.count("\n", 0, m.start()) + 1
            achados.append((linha, nome, partes[idx].strip()))

        # ENTRA na chamada em vez de pular por cima dela: era exatamente o
        # `text_w()` escondido dentro do argumento x de um `text()` que
        # escapou da última vez.
        i = ab + 1


def main():
    ruim = 0
    for caminho in sys.argv[1:]:
        for linha, nome, val in infracoes(caminho):
            print(f"{caminho}:{linha}: {nome}(... {val} ...) — "
                  f"use a escala tipográfica (T_CORPO, T_MIUDO, T_TITULO…)")
            ruim += 1
    return 1 if ruim else 0


if __name__ == "__main__":
    sys.exit(main())
