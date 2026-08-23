#!/usr/bin/env python3
"""stylus diary — o que você pôs, quando, e quantas vezes.

Uma coleção com memória é o que separa uma estante de uma pasta com
arquivos. O registro é escrito sozinho toda vez que a agulha desce.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, "/usr/share/stylus/deck")
import vinyl  # noqa: E402

D = "\033[2m"; B = "\033[1m"; A = "\033[38;5;117m"; P = "\033[38;5;218m"
O = "\033[0m"


def quando(ts):
    d = (time.time() - ts) / 86400
    if d < 1:
        return "hoje"
    if d < 2:
        return "ontem"
    if d < 30:
        return f"há {int(d)} dias"
    if d < 365:
        return f"há {int(d / 30)} meses"
    return f"há {int(d / 365)} anos"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="?", type=int, default=25)
    ap.add_argument("--esquecidos", action="store_true",
                    help="o contrário: o que faz mais tempo que não toca")
    args = ap.parse_args()

    linhas = sorted(vinyl._play_rows(), key=lambda x: -x[0])
    if not linhas:
        print(f"\n  {D}nada anotado ainda — o sistema anota sozinho "
              f"quando você põe um disco.{O}\n")
        return 0
    contagem, ultima = {}, {}
    for ts, f in linhas:
        k = os.path.normpath(f)
        contagem[k] = contagem.get(k, 0) + 1
        ultima[k] = max(ultima.get(k, 0), ts)

    if args.esquecidos:
        estante = vinyl.shelf()
        alvo = sorted(estante, key=lambda f: ultima.get(os.path.normpath(f), 0))
        print(f"\n  {B}há mais tempo sem tocar{O}\n")
        for f in alvo[:args.n]:
            art, nome = vinyl.folder_names(f)
            ts = ultima.get(os.path.normpath(f), 0)
            print(f"    {D}{quando(ts) if ts else 'nunca':<14}{O}"
                  f"{art[:24]:<26}{A}{nome[:40]}{O}")
        print()
        return 0

    print(f"\n  {B}o que você pôs{O}\n")
    vistos = set()
    for ts, f in linhas:
        k = os.path.normpath(f)
        if k in vistos:
            continue
        vistos.add(k)
        art, nome = vinyl.folder_names(f)
        n = contagem[k]
        print(f"    {D}{quando(ts):<14}{O}{art[:24]:<26}{A}{nome[:38]:<40}{O}"
              f"{P}{n}x{O}" if n > 1 else
              f"    {D}{quando(ts):<14}{O}{art[:24]:<26}{A}{nome[:38]}{O}")
        if len(vistos) >= args.n:
            break
    print(f"\n  {D}{len(vistos)} discos, {len(linhas)} vezes ao todo.{O}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
