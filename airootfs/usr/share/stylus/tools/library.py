#!/usr/bin/env python3
"""stylus library — onde a coleção fica.

    stylus library                mostra as pastas e qual delas é a estante
    stylus library ~/Music        define
    stylus library --add /mnt/hd  acrescenta uma segunda
"""
import argparse
import os
import sys

sys.path.insert(0, "/usr/share/stylus/lib")
import vinyl  # noqa: E402

D = "\033[2m"; A = "\033[38;5;117m"; OK = "\033[38;5;114m"
W = "\033[38;5;215m"; O = "\033[0m"
CONF = os.path.expanduser("~/.config/stylus/library")


def escreve(paths):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as fh:
        fh.write("# uma pasta por linha; a primeira que existir é a estante\n")
        fh.write("\n".join(paths) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta", nargs="?")
    ap.add_argument("--add", metavar="PASTA")
    args = ap.parse_args()

    atuais = []
    if os.path.exists(CONF):
        with open(CONF, encoding="utf-8") as fh:
            atuais = [ln.strip() for ln in fh
                      if ln.strip() and not ln.startswith("#")]

    if args.pasta or args.add:
        novo = os.path.abspath(os.path.expanduser(args.pasta or args.add))
        if not os.path.isdir(novo):
            print(f"  {W}não existe: {novo}{O}")
            return 1
        atuais = ([novo] if args.pasta else atuais + [novo])
        escreve(list(dict.fromkeys(atuais)))
        # Um índice velho apontando para outra estante é pior do que índice
        # nenhum: a interface mostraria discos que já não estão lá.
        cache = os.path.expanduser("~/.cache/stylus/shelf.json")
        if os.path.exists(cache):
            os.remove(cache)
        print(f"  {OK}estante: {vinyl.library_root()}{O}")
        return 0

    print()
    print(f"  {D}estante{O}  {A}{vinyl.library_root()}{O}")
    print(f"  {D}procurando também em:{O}")
    for p in vinyl.music_roots():
        marca = OK + "✓" + O if os.path.isdir(p) else D + "·" + O
        print(f"    {marca} {p}")
    n = len(vinyl.shelf(min_tracks=1))
    print(f"\n  {vinyl.plural(n, 'disco')}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
