"""
Write cover.jpg into album folders that don't have one but whose audio files
already carry embedded art.

Not a playback fix — every album checked already had embedded art, so players
were always fine. This is for file managers, folder thumbnails, and any tool
that looks for a sidecar image rather than reading tags. Purely additive:
never overwrites an existing cover, never modifies audio files.

Run with --apply to actually write; default is a dry run.
"""
import os
import sys
import glob

from mutagen.flac import FLAC
from mutagen.id3 import ID3

from _raiz import raiz   # onde fica a coleção, decidido num lugar só

ROOT = raiz()
COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg")


def embedded_art(path):
    """Return (bytes, ext) of the first embedded picture, or None."""
    try:
        if path.lower().endswith(".flac"):
            pics = FLAC(path).pictures
            if pics:
                p = pics[0]
                return p.data, ".png" if "png" in (p.mime or "").lower() else ".jpg"
        elif path.lower().endswith(".mp3"):
            apics = ID3(path).getall("APIC")
            if apics:
                a = apics[0]
                return a.data, ".png" if "png" in (a.mime or "").lower() else ".jpg"
    except Exception:
        pass
    return None


def main(apply=False):
    wrote = skipped_have = no_art = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        audio = [f for f in filenames if f.lower().endswith((".flac", ".mp3"))]
        if not audio:
            continue
        if any(c in (f.lower() for f in filenames) for c in COVER_NAMES):
            skipped_have += 1
            continue

        found = None
        for f in sorted(audio):
            found = embedded_art(os.path.join(dirpath, f))
            if found:
                break
        if not found:
            no_art += 1
            print(f"  no embedded art: {os.path.relpath(dirpath, ROOT)}")
            continue

        data, ext = found
        out = os.path.join(dirpath, "cover" + ext)
        if apply:
            with open(out, "wb") as fh:
                fh.write(data)
        wrote += 1
        print(f"{'wrote' if apply else 'would write'}: "
              f"{os.path.relpath(out, ROOT)} ({len(data)//1024} KiB)")

    print(f"\n{wrote} covers {'written' if apply else 'to write'}; "
          f"{skipped_have} folders already had one; {no_art} had no embedded art")
    if not apply:
        print("dry run — pass --apply to write")


if __name__ == "__main__":
    # `--help` tem que IMPRIMIR e sair, sempre. Sem esta guarda, um `--help`
    # caía na execução normal: aqui não existe argparse, então a opção não
    # casava com nada e virava "nenhum argumento" — que para estas ferramentas
    # quer dizer "faça o trabalho inteiro". O `stylus tags --help` saía
    # varrendo a coleção toda e consultando a rede faixa por faixa; quem só
    # queria saber o que o comando faz esperava minutos e desistia.
    if {"-h", "--help"} & set(sys.argv[1:]):
        print((__doc__ or "sem ajuda").strip())
        raise SystemExit(0)

    main("--apply" in sys.argv)
