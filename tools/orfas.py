#!/usr/bin/env python3
"""Acha função DECLARADA num header que ninguém chama.

POR QUE ISTO EXISTE
-------------------
Um helper sem chamador costuma não ser código morto inofensivo: costuma ser
um RECURSO INTEIRO faltando. Neste projeto já aconteceu duas vezes —
`album_load_cover` existia e nenhuma capa era carregada, e `album_free_cover`
existia e os bytes crus de toda capa vista ficavam na memória para sempre.

A conferência que havia aqui tinha uma lista de nomes escrita à mão. Ela só
pega o que alguém lembrou de escrever nela, e nenhum dos dois defeitos acima
estava na lista — os dois foram achados a olho. Esta deriva a lista dos
próprios headers, então cobre o que existe e não o que se lembrou.

Conta ocorrências do nome em todo o código: 1 é só a definição, 2 é definição
mais protótipo. Chamada de verdade é 3 ou mais.
"""
import os
import re
import sys

# Coisa que um header declara e que, por natureza, ninguém "chama" no código:
# entrada do programa, e o que existe para ser exportado.
ISENTAS = {'main'}


def declaradas(cabecalho):
    """Nomes de função declarados num .h. Regex e não compilador de verdade:
    o objetivo é levantar suspeitas para conferir, não julgar sintaxe."""
    texto = open(cabecalho, encoding='utf-8', errors='replace').read()
    texto = re.sub(r'/\*.*?\*/', ' ', texto, flags=re.S)
    texto = re.sub(r'//[^\n]*', ' ', texto)
    nomes = set()
    # tipo (com * e const) seguido de nome( ... ) ;
    for m in re.finditer(r'\b([A-Za-z_][\w \t\*]*?)\b(\w+)\s*\([^;{]*\)\s*;', texto):
        nome = m.group(2)
        if nome in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
            continue
        nomes.add(nome)
    return nomes


def main(argv):
    if len(argv) < 2:
        print("uso: orfas.py DIR_DE_FONTES [DIR_EXTRA...]", file=sys.stderr)
        return 2
    src = argv[1]
    extras = argv[2:]

    arquivos = []
    for d in [src] + extras:
        for raiz, _sub, arqs in os.walk(d):
            for a in arqs:
                if a.endswith(('.c', '.h')):
                    arquivos.append(os.path.join(raiz, a))

    corpo = {}
    for a in arquivos:
        corpo[a] = open(a, encoding='utf-8', errors='replace').read()

    suspeitas = []
    for h in sorted(a for a in arquivos if a.endswith('.h') and a.startswith(src)):
        for nome in sorted(declaradas(h)):
            if nome in ISENTAS:
                continue
            n = 0
            for txt in corpo.values():
                n += len(re.findall(r'\b%s\b' % re.escape(nome), txt))
            if n <= 2:
                suspeitas.append((os.path.basename(h), nome, n))

    if not suspeitas:
        return 0
    for h, nome, n in suspeitas:
        print(f"  {h}: {nome}() — {n} ocorrência(s), ninguém chama")
    print("  um helper sem chamador costuma ser um recurso inteiro faltando.")
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
