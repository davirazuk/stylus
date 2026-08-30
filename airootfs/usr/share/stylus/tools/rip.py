#!/usr/bin/env python3
"""stylus rip — rasga o CD da gaveta direto para a estante.

Usa o whipper, que confere o resultado contra o AccurateRip: é a diferença
entre "um arquivo" e "uma cópia que você pode confiar". Um arranhão que o
leitor corrigiu errado passa despercebido em qualquer outro rasgador.

    stylus rip                para a estante, em FLAC
    stylus rip --drive /dev/sr1
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, "/usr/share/stylus/lib")
import vinyl  # noqa: E402

D = "\033[2m"; A = "\033[38;5;117m"; W = "\033[38;5;215m"; O = "\033[0m"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", default=None)
    args = ap.parse_args()
    if not shutil.which("whipper"):
        print(f"\n  {W}o whipper não está instalado.{O}\n")
        return 1
    raiz = vinyl.library_root()
    os.makedirs(raiz, exist_ok=True)
    print(f"\n  {A}rasgando para {raiz}{O}")
    print(f"  {D}a primeira vez pede para calibrar o leitor "
          f"(whipper drive analyze) — deixe fazer.{O}\n")
    cmd = ["whipper", "cd", "rip",
           "-O", raiz,
           "--track-template", "%A/%d/%t - %n",
           "--disc-template", "%A/%d/%A - %d"]
    if args.drive:
        cmd[2:2] = ["-d", args.drive]
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
