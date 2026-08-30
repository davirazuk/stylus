#!/usr/bin/env python3
"""stylus check — o que está faltando ou quebrado na biblioteca.

Complementa o `stylus gaps`, que procura ÁLBUNS que faltam por artista.
Este olha para dentro: pasta de álbum sem áudio nenhum, arquivo de 0 byte,
arquivo pequeno demais para ser música, e álbum com buraco na numeração.

Nada aqui apaga nem move nada. É só relatório.

Sobre os buracos de numeração: eles NÃO são necessariamente defeito. Baixar
só as faixas que se quer é uma escolha legítima, e a ferramenta não tem como
saber a diferença entre "download pela metade" e "só quis essas". Por isso o
relatório separa os dois casos pelo que dá para afirmar: uma pasta com capa e
encarte e ZERO música é quase certamente download que falhou; um álbum com
5 de 14 faixas pode ser gosto.
"""
import argparse
import os
import re
import sys
from collections import defaultdict

from _raiz import raiz, audio_ext, find_cover, plural   # a coleção, a música, a capa, o plural

# A lista vem do _raiz, que a pega do vinyl: havia quatro cópias dela
# neste diretório e elas já discordavam (esta não tinha .wma).
AUDIO = audio_ext()
SIDECAR = (".jpg", ".jpeg", ".png", ".txt", ".pdf", ".m3u", ".log", ".cue", ".nfo")
LEAD_NUM = re.compile(r"^\s*(\d{1,3})\b")
TINY_KB = 40

c_b = "\033[1m"; c_dim = "\033[2m"; c_yel = "\033[1;33m"
c_red = "\033[1;31m"; c_grn = "\033[1;32m"; c_off = "\033[0m"


def scan(root):
    no_audio, empty, tiny, gaps, sem_capa = [], [], [], [], []
    albums = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if os.path.basename(dirpath).startswith("."):
            continue
        audio = [f for f in filenames if f.lower().endswith(AUDIO)]
        rel = os.path.relpath(dirpath, root)
        if audio:
            albums[dirpath] = audio
            # SEM CAPA é o defeito que se VÊ. A estante, a AGORA, o deck e a
            # notificação de disco novo mostram capa; esta ferramenta se
            # chama "saúde da biblioteca" e era a única que não olhava para
            # a única coisa que a pessoa enxerga o dia inteiro — enquanto o
            # `stylus covers`, que conserta, mora na linha de baixo do menu.
            #
            # A pasta de CIMA também conta: um álbum de dois discos guarda as
            # faixas em "Disc 01"/"Disc 02" e a capa no álbum. Sem isto, todo
            # disco duplo apareceria aqui como problema.
            if not find_cover(dirpath, filenames):
                pai = os.path.dirname(dirpath)
                if not (pai and pai != dirpath and os.path.isdir(pai)
                        and find_cover(pai)):
                    sem_capa.append(rel)
        elif rel != "." and not dirnames:
            # Pasta-folha com material de álbum e nenhuma música. Duas
            # ressalvas para não gritar à toa:
            #  - pasta que só contém subpastas é organização, não álbum;
            #  - pasta cujo PAI já tem música é sub-recurso de um álbum que
            #    funciona ("previous art", "scans", "artwork"), não um álbum
            #    quebrado. Sem esta regra o relatório abre com um falso
            #    positivo, e relatório que começa errado ninguém lê até o fim.
            parent = os.path.dirname(dirpath)
            parent_has_audio = False
            try:
                parent_has_audio = any(f.lower().endswith(AUDIO)
                                       for f in os.listdir(parent))
            except OSError:
                pass
            side = [f for f in filenames if f.lower().endswith(SIDECAR)]
            if side and not parent_has_audio:
                no_audio.append((rel, len(filenames)))
        for f in audio:
            p = os.path.join(dirpath, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            r = os.path.relpath(p, root)
            if sz == 0:
                empty.append(r)
            elif sz < TINY_KB * 1024:
                tiny.append((r, sz))

    for d, files in albums.items():
        nums = sorted({int(m.group(1)) for m in
                       (LEAD_NUM.match(f) for f in files) if m}
                      & set(range(1, 100)))
        if len(nums) < 3 or nums[0] > 2:
            continue
        missing = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
        if missing:
            gaps.append((os.path.relpath(d, root), missing, len(nums), nums[-1]))
    return no_audio, empty, tiny, gaps, sem_capa, len(albums)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=raiz())
    args = ap.parse_args()
    root = os.path.expanduser(args.root)
    if not os.path.isdir(root):
        print(f"não existe: {root}", file=sys.stderr)
        return 1

    no_audio, empty, tiny, gaps, sem_capa, n_albums = scan(root)
    print(f"\n  {c_b}STYLUS — saúde da biblioteca{c_off}\n"
          f"  {c_dim}{root}{c_off}\n")

    print(f"  {c_b}Quase certamente download que falhou{c_off}")
    if no_audio or empty:
        for rel, n in sorted(no_audio):
            print(f"    {c_red}✗{c_off} {rel}")
            print(f"      {c_dim}{plural(n, 'arquivo')}, "
                  f"nenhum de música{c_off}")
        for r in sorted(empty):
            print(f"    {c_red}✗{c_off} {r}  {c_dim}(0 byte){c_off}")
    else:
        print(f"    {c_grn}✓{c_off} nada")

    if tiny:
        print(f"\n  {c_b}Pequeno demais para ser música (<{TINY_KB} KB){c_off}")
        for r, sz in sorted(tiny)[:40]:
            print(f"    {c_yel}!{c_off} {sz/1024:6.1f} KB  {r}")

    print(f"\n  {c_b}Discos sem capa{c_off}")
    print(f"  {c_dim}é o que você vê na estante e na tela cheia{c_off}")
    if sem_capa:
        for rel in sorted(sem_capa)[:40]:
            print(f"    {c_yel}!{c_off} {rel}")
        if len(sem_capa) > 40:
            print(f"    {c_dim}… e mais {len(sem_capa) - 40}{c_off}")
        print(f"    {c_dim}`stylus covers --apply` tira a capa de dentro dos "
              f"arquivos, quando há uma lá;{c_off}")
        print(f"    {c_dim}`stylus covers --buscar --apply` procura na rede "
              f"as que não estão em lugar nenhum.{c_off}")
    else:
        print(f"    {c_grn}✓{c_off} nenhum")

    print(f"\n  {c_b}Álbuns com buraco na numeração{c_off}")
    print(f"  {c_dim}pode ser download pela metade, pode ser só ter querido "
          f"essas faixas — quem sabe é você{c_off}")
    if gaps:
        for rel, miss, have, last in sorted(gaps):
            m = ", ".join(str(x) for x in miss[:8]) + ("…" if len(miss) > 8 else "")
            print(f"    {c_yel}!{c_off} {rel}")
            print(f"      {c_dim}tem {plural(have, 'faixa')}, "
                  f"falta [{m}], numeração vai até {last}{c_off}")
    else:
        print(f"    {c_grn}✓{c_off} nenhum")

    total = len(no_audio) + len(empty)
    print(f"\n  {c_dim}{n_albums} pastas com áudio varridas · "
          f"{plural(total, 'problema')} claro{'' if total == 1 else 's'} · "
          f"{len(sem_capa)} sem capa · "
          f"{plural(len(gaps), 'álbum', 'álbuns')} para você olhar{c_off}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
