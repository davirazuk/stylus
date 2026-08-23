#!/usr/bin/env python3
"""Testes do integrate_album — o passo que já apagou download pronto.

Por que existem: o integrate_album apagava a origem INCONDICIONALMENTE, então
um álbum de mais de um disco (que ele não sabia ler) era baixado inteiro e
destruído em seguida, com um "Integrated: ... (0 tracks)" que parecia
sucesso. Foi assim que nasceram as pastas com capa, encarte e nenhuma música.
Um defeito que apaga dados em silêncio merece teste, e este é ele.

Roda contra pastas de mentira: não fala com o Qobuz, não toca na biblioteca
de verdade — QOBUZ_DIR e LIB_ROOT são reapontados para um diretório
temporário.

    python3 test_integrate.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

PASS = FAIL = 0


def check(desc, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"    \033[1;32m✓\033[0m {desc}")
    else:
        FAIL += 1
        print(f"    \033[1;31m✗\033[0m {desc}")


def case(n):
    print(f"\n  \033[2m{n}\033[0m")


def flac(path, num, title, disc=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "quiet", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.2",
                    "-c:a", "flac", path], check=True)
    from mutagen.flac import FLAC
    a = FLAC(path)
    a["tracknumber"] = str(num)
    a["title"] = title
    if disc:
        a["discnumber"] = str(disc)
    a.save()


def main():
    if not shutil.which("ffmpeg"):
        print("  (sem ffmpeg; não dá para gerar flac de teste)")
        return 0

    tmp = tempfile.mkdtemp(prefix="stylus-integrate-")
    qob = os.path.join(tmp, "qobuz")
    lib = os.path.join(tmp, "lib")
    os.makedirs(qob, exist_ok=True)
    os.makedirs(lib, exist_ok=True)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import integrate_album as ia
    ia.QOBUZ_DIR = qob
    ia.LIB_ROOT = lib

    case("álbum de um disco só")
    src = os.path.join(qob, "A - Um Disco (2020)")
    flac(os.path.join(src, "01. Uma.flac"), 1, "Uma")
    flac(os.path.join(src, "02. Outra.flac"), 2, "Outra")
    open(os.path.join(src, "cover.jpg"), "wb").write(b"\xff\xd8")
    res = ia.integrate("A - Um Disco (2020)", "A", "Um Disco")
    dest = os.path.join(lib, "A", "Um Disco")
    check("integra as duas faixas", len(res) == 2)
    check("renomeia para 'NN - Título'", os.path.isfile(os.path.join(dest, "01 - Uma.flac")))
    check("leva a capa junto", os.path.isfile(os.path.join(dest, "cover.jpg")))
    check("apaga a origem, que ficou vazia", not os.path.isdir(src))
    check("não cria subpasta de disco à toa", not os.path.isdir(os.path.join(dest, "Disc 01")))

    case("álbum de MAIS DE UM disco — o caso que se perdia")
    src2 = os.path.join(qob, "B - Dois Discos (2021)")
    #  Nomes como o qobuz-dl entrega de verdade: disco embutido no número.
    flac(os.path.join(src2, "Disc 01", "101 - Primeira.flac"), 1, "Primeira", 1)
    flac(os.path.join(src2, "Disc 01", "102 - Segunda.flac"), 2, "Segunda", 1)
    flac(os.path.join(src2, "Disc 02", "201 - Terceira.flac"), 1, "Terceira", 2)
    res2 = ia.integrate("B - Dois Discos (2021)", "B", "Dois Discos")
    d2 = os.path.join(lib, "B", "Dois Discos")
    check("acha as faixas dentro das pastas de disco", len(res2) == 3)
    check("preserva Disc 01", os.path.isfile(os.path.join(d2, "Disc 01", "01 - Primeira.flac")))
    check("preserva Disc 02", os.path.isfile(os.path.join(d2, "Disc 02", "01 - Terceira.flac")))
    check("numera por disco, não corrido", os.path.isfile(os.path.join(d2, "Disc 02", "01 - Terceira.flac")))
    check("origem apagada só porque esvaziou", not os.path.isdir(src2))

    case("nada para integrar NÃO pode apagar a origem")
    #  Esta é a verificação que dá nome ao conserto: era aqui que um download
    #  pronto virava pasta vazia.
    src3 = os.path.join(qob, "C - Sem Flac (2022)")
    os.makedirs(src3, exist_ok=True)
    open(os.path.join(src3, "cover.jpg"), "wb").write(b"\xff\xd8")
    open(os.path.join(src3, "faixa.mp3"), "wb").write(b"\x00" * 16)
    res3 = ia.integrate("C - Sem Flac (2022)", "C", "Sem Flac")
    check("integra zero", len(res3) == 0)
    check("PRESERVA a origem", os.path.isdir(src3))
    check("e o arquivo de áudio continua lá",
          os.path.isfile(os.path.join(src3, "faixa.mp3")))

    case("pasta que não existe")
    check("não estoura", ia.integrate("D - Não Existe", "D", "Não Existe") == [])

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n  \033[1;32m{PASS} passaram\033[0m" +
          (f", \033[1;31m{FAIL} falharam\033[0m" if FAIL else "") + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
