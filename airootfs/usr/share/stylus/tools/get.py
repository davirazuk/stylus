#!/usr/bin/env python3
"""stylus get — traz um disco de fora para dentro da estante.

    stylus get URL              baixa e arquiva (yt-dlp: bandcamp, youtube…)
    stylus get FILA.txt         uma fila de "url|artista|álbum" por linha

Baixa como FLAC quando a fonte tem, e arquiva em Artista/Álbum/NN - Faixa,
que é a forma que todo o resto do sistema espera. Não é um substituto de
comprar o disco; é o que fazer com o que você já comprou e baixou.
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, "/usr/share/stylus/lib")
import vinyl  # noqa: E402

D = "\033[2m"; A = "\033[38;5;117m"; W = "\033[38;5;215m"
OK = "\033[38;5;114m"; O = "\033[0m"


def baixar(url, destino):
    cmd = ["yt-dlp", "-x", "--audio-format", "flac", "--audio-quality", "0",
           "--embed-thumbnail", "--embed-metadata", "--no-playlist-reverse",
           "-o", os.path.join(destino, "%(playlist_index|00)s - %(title)s.%(ext)s"),
           url]
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("alvo")
    ap.add_argument("--artist")
    ap.add_argument("--album")
    args = ap.parse_args()
    if not shutil.which("yt-dlp"):
        print(f"\n  {W}o yt-dlp não está instalado.{O}\n")
        return 1
    raiz = vinyl.library_root()

    if os.path.isfile(args.alvo):
        linhas = [ln.strip() for ln in open(args.alvo, encoding="utf-8")
                  if ln.strip() and not ln.startswith("#")]
    else:
        linhas = [f"{args.alvo}|{args.artist or 'Desconhecido'}|"
                  f"{args.album or 'Sem nome'}"]

    n = 0
    for ln in linhas:
        partes = (ln.split("|") + ["", ""])[:3]
        url, artista, album = [p.strip() for p in partes]
        artista = artista or "Desconhecido"
        album = album or "Sem nome"
        destino = os.path.join(raiz, artista, album)
        os.makedirs(destino, exist_ok=True)
        print(f"\n  {A}{artista} — {album}{O}\n  {D}{url}{O}")
        if baixar(url, destino) == 0:
            n += 1
        else:
            print(f"  {W}falhou.{O}")
    print(f"\n  {OK}{n} de {len(linhas)}.{O}")
    print(f"  {D}`stylus tags` arruma o que vier torto, "
          f"`stylus lyrics` busca as letras.{O}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
