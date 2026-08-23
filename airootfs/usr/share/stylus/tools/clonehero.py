#!/usr/bin/env python3
"""stylus charted — cruza o Clone Hero do celular com a biblioteca.

A ideia: as músicas que você CHARTEIA são uma declaração de gosto tão honesta
quanto a biblioteca, e as duas listas não são a mesma. Onde elas divergem tem
informação — artista que você toca dezenas de vezes no jogo e do qual não tem
um disco sequer.

Não baixa nada e não mexe em nada. É relatório, e a decisão continua sendo
sua: muita coisa charteável é popular por ser charteável, não por ser o que
você ouviria.

    stylus charted            o que você charteia e não tem
    stylus charted --min 15   sobe o corte
    stylus charted --have     o contrário: o que tem e charteia
"""
import argparse
import collections
import os
import re
import subprocess
import sys
import unicodedata

from _raiz import raiz   # onde fica a coleção, decidido num lugar só

CH_DIR = "/sdcard/Documents/Clone Hero/Songs"
ROOTS = [raiz()]

c_b = "\033[1m"; c_dim = "\033[2m"; c_acc = "\033[38;5;117m"
c_pink = "\033[38;5;218m"; c_off = "\033[0m"


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    # O Clone Hero troca "/" por "⧸" no nome do arquivo (o "/" não pode em
    # nome de arquivo), e "and"/"&" alternam entre as duas fontes.
    s = s.replace("⧸", "/").replace(" and ", " & ")
    return re.sub(r"[^a-z0-9]+", "", s)


def do_celular():
    try:
        r = subprocess.run(["adb", "shell", f'ls "{CH_DIR}"'],
                           capture_output=True, text=True, timeout=300)
    except Exception as e:
        sys.exit(f"não consegui falar com o celular: {e}")
    linhas = [l.strip() for l in r.stdout.replace("\r", "").splitlines() if l.strip()]
    if not linhas:
        sys.exit("nenhuma música encontrada — o celular está plugado e autorizado?")
    return linhas


def artista(linha):
    linha = re.sub(r"\.(sng|zip)$", "", linha.strip())
    return linha.split(" - ")[0].strip() if " - " in linha else None


def biblioteca():
    tenho = set()
    for raiz in ROOTS:
        if not os.path.isdir(raiz):
            continue
        for d in os.listdir(raiz):
            if os.path.isdir(os.path.join(raiz, d)):
                tenho.add(norm(d))
    return tenho


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=10)
    ap.add_argument("--have", action="store_true")
    args = ap.parse_args()

    linhas = do_celular()
    cnt = collections.Counter(a for a in (artista(l) for l in linhas) if a)
    tenho = biblioteca()

    print(f"\n  {c_b}Clone Hero × biblioteca{c_off}")
    print(f"  {c_dim}{len(linhas)} músicas charteadas · {len(cnt)} artistas · "
          f"{len(tenho)} pastas de artista no disco{c_off}\n")

    if args.have:
        lista = [(a, n) for a, n in cnt.most_common() if norm(a) in tenho][:40]
        print(f"  {c_b}Charteia e TEM{c_off}  {c_dim}(a interseção){c_off}")
    else:
        lista = [(a, n) for a, n in cnt.most_common()
                 if norm(a) not in tenho and n >= args.min]
        print(f"  {c_b}Charteia e NÃO tem{c_off}  "
              f"{c_dim}(corte de {args.min} músicas · {len(lista)} artistas){c_off}")
    print()
    for a, n in lista[:40]:
        barra = "▇" * min(24, max(1, n // 2))
        print(f"  {c_acc}{n:>4}{c_off}  {c_pink}{barra}{c_off} {a}")
    if not lista:
        print(f"  {c_dim}(nada acima do corte){c_off}")
    print(f"\n  {c_dim}baixar um destes:  stylus gaps \"NOME\"{c_off}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
