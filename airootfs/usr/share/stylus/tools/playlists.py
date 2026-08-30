#!/usr/bin/env python3
"""stylus playlists — as listas .m3u da coleção, e como pôr uma para tocar.

POR QUE ISTO EXISTE
-------------------
O sistema ESCREVIA playlists e não sabia tocar nenhuma. O `stylus suggest`,
o `make_new_playlist` e o `integrate_album` põem .m3u na raiz da coleção —
"Shoegaze & Dreampop.m3u", "Novidades 2026-08-30.m3u", "coleção.m3u" — e não
havia caminho nenhum daqui até o tocador, nem um comando que as listasse. É
a família do `stylus-welcome` que o i3 abria e nunca existiu: a peça está
escrita, o fio não.

Uma playlist não é um disco: entra como um lado só e CONTÍNUO, sem "vire o
disco". O aviso de virar o lado é verdade sobre um objeto que tem dois
lados; numa lista de duzentas faixas viraria um alarme a cada vinte minutos.
"""
import os
import sys

_aqui = os.path.dirname(os.path.abspath(__file__))
for _p in ("/usr/share/stylus/lib", os.path.join(os.path.dirname(_aqui), "lib")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
import vinyl  # noqa: E402

D = "\033[2m"; B = "\033[1m"; A = "\033[38;5;117m"; O = "\033[0m"


def humano(seg):
    seg = int(seg or 0)
    h, m = seg // 3600, (seg % 3600) // 60
    if h:
        return f"{h}h{m:02d}"
    return f"{m} min"


# A regra é a do `vinyl.plural`: uma cópia nova aqui seria a próxima a
# esquecer o caso do 1.
plural = vinyl.plural


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    listas = vinyl.playlists()
    if not listas:
        raizes = ", ".join(vinyl.library_roots()) or "nenhuma pasta configurada"
        print(f"\n  {D}nenhuma playlist em {raizes}.{O}")
        print(f"  {D}`stylus suggest` escreve algumas a partir do que você "
              f"ouve.{O}\n")
        return 0

    # Com argumento: PÕE aquela para tocar. Listar e não poder tocar é
    # metade do caminho, e é justamente a metade que já existia.
    if args:
        querido = " ".join(args).lower()
        alvo = None
        for p in listas:
            nome = os.path.splitext(os.path.basename(p))[0].lower()
            if nome == querido:
                alvo = p
                break
        if alvo is None:
            for p in listas:
                nome = os.path.splitext(os.path.basename(p))[0].lower()
                if querido in nome:
                    alvo = p
                    break
        if alvo is None:
            print(f"\n  não achei nenhuma playlist chamada \"{' '.join(args)}\".\n")
            return 1
        os.execvp("stylus-deck", ["stylus-deck", alvo])

    print(f"\n  {B}playlists{O}\n")
    for p in listas:
        nome = os.path.splitext(os.path.basename(p))[0]
        itens = vinyl.ler_m3u(p)
        # Faixa que não existe mais: a coleção mudou de lugar, o disco foi
        # renomeado. Dizer quantas faltam é a diferença entre "esta lista
        # está velha" e "esta lista está quebrada e você não sabia".
        somem = sum(1 for c, _t, _d in itens
                    if not c.startswith(("http://", "https://"))
                    and not os.path.isfile(c))
        aviso = f"   {D}({plural(somem, 'faixa')} sem arquivo){O}" if somem else ""
        print(f"    {A}{nome[:44]:<46}{O}{D}{plural(len(itens), 'faixa'):>12}{O}"
              f"{aviso}")
    print(f"\n  {D}stylus playlists NOME{O} põe uma para tocar   "
          f"{D}·   stylus suggest{O} escreve novas\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
