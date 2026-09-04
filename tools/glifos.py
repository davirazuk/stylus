#!/usr/bin/env python3
"""Confere que a UI só usa caracteres que a fonte do aparelho desenha.

POR QUE ISTO EXISTE
-------------------
Um caractere que a fonte não tem NÃO some: vira um quadradinho na tela, e
ninguém que leia o código percebe — no editor ele aparece perfeito. Aconteceu
com uma seta "→" na linha do caminho do sinal, que é justamente a linha que
promete contar a verdade sem enfeite.

A conferência é sobre o CONJUNTO permitido, não sobre uma fonte específica:
o Vita usa a PVF do sistema, que não temos aqui para consultar. Então a
regra é conservadora — ASCII, o latim acentuado que o português pede, e uma
lista curta de pontuação tipográfica que se conferiu existir. Precisou de um
símbolo novo? Confira na fonte ANTES e acrescente aqui, com o motivo.
"""
import re
import sys
import unicodedata

# Pontuação tipográfica conferida na Noto Sans e de uso corrente em fonte de
# interface. Setas (U+2190..U+21FF) NÃO entram: a Noto Sans não as tem, e uma
# fonte de UI raramente tem.
EXTRA_OK = {
    '·',  # ponto médio, o separador do projeto inteiro
    '—',  # travessão
    '–',  # meia-risca
    '…',  # reticências
    '«', '»',  # aspas angulares
    '°',  # grau
    'º', 'ª',  # ordinais — "2º plano" aparece na linha do sinal
    '¹', '²', '³',
}


def sem_comentarios(fonte):
    """Tira comentários antes de olhar as strings.

    Sem isto, um comentário que EXPLICA um caractere proibido — como a nota
    que conta por que a seta saiu — era lido como se o código ainda o usasse.
    A conferência acusava a si mesma."""
    fora = []
    i, n = 0, len(fonte)
    while i < n:
        c = fonte[i]
        if c == '/' and i + 1 < n and fonte[i + 1] == '*':
            j = fonte.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c == '/' and i + 1 < n and fonte[i + 1] == '/':
            j = fonte.find('\n', i)
            i = n if j < 0 else j
        elif c == '"':                      # pula a string inteira, com escapes
            j = i + 1
            while j < n and fonte[j] != '"':
                j += 2 if fonte[j] == '\\' else 1
            fora.append(fonte[i:j + 1])
            i = j + 1
        else:
            i += 1
    return ''.join(fora)


def permitido(ch):
    o = ord(ch)
    if o < 0x80:
        return True                      # ASCII
    if 0xC0 <= o <= 0x17F:
        return True                      # latim acentuado (pt, es, fr…)
    return ch in EXTRA_OK


def main(argv):
    ruins = []
    for caminho in argv[1:]:
        try:
            fonte = open(caminho, encoding='utf-8').read()
        except OSError as e:
            print(f"  não li {caminho}: {e}", file=sys.stderr)
            return 2
        # só o conteúdo das strings literais de C, e fora dos comentários
        for lit in re.findall(r'"((?:[^"\\]|\\.)*)"', sem_comentarios(fonte)):
            for ch in lit:
                if not permitido(ch):
                    try:
                        nome = unicodedata.name(ch)
                    except ValueError:
                        nome = '?'
                    ruins.append((caminho, ch, nome))
    if not ruins:
        return 0
    vistos = set()
    for caminho, ch, nome in ruins:
        chave = (caminho, ch)
        if chave in vistos:
            continue
        vistos.add(chave)
        print(f"  {caminho}: U+{ord(ch):04X} {ch!r} ({nome})")
    print("  a fonte do aparelho pode não ter estes — viram quadradinho na tela.")
    print("  confira na fonte e, se existir mesmo, acrescente em tools/glifos.py")
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
