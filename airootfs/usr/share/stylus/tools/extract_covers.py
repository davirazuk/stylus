"""Escreve o cover.jpg nas pastas de disco que não têm um, mas cujos arquivos
de áudio já trazem a capa embutida.

Não é conserto de reprodução: todo disco conferido já tinha a capa dentro
do arquivo, e os tocadores sempre estiveram bem. Isto é para o gerenciador
de arquivos, para a miniatura da pasta e para qualquer programa que procure
uma imagem ao lado em vez de ler a etiqueta.

Só acrescenta: nunca escreve por cima de uma capa que já existe e nunca
mexe nos arquivos de áudio.

Com --apply escreve de verdade; sem ele, só mostra o que faria.
"""
import os
import sys
import glob

import base64

import mutagen
from mutagen.flac import Picture

from _raiz import raiz, audio_ext, find_cover   # a coleção, a música, a capa

ROOT = raiz()
AUDIO = audio_ext()


def _ext_de(mime):
    return ".png" if "png" in (mime or "").lower() else ".jpg"


def embedded_art(path):
    """(bytes, extensão) da primeira capa embutida, ou None.

    Pelo `mutagen.File` e não por um `if` na extensão do nome. Antes só
    respondia a .flac e .mp3, e cada formato guarda a capa num lugar
    diferente:

      FLAC/Ogg FLAC   blocos PICTURE (`.pictures`)
      MP3             o quadro APIC do ID3
      MP4/M4A/ALAC    o átomo `covr`, que diz o formato num inteiro
      Ogg Vorbis/Opus `metadata_block_picture`: um bloco PICTURE do FLAC
                      em base64, dentro de uma tag de texto

    Numa coleção em ALAC ou Opus a ferramenta inteira não fazia nada e
    dizia "0 não têm capa embutida", que é pior do que um erro.
    """
    try:
        arq = mutagen.File(path)
    except Exception:                                       # noqa: BLE001
        return None
    if arq is None:
        return None

    # FLAC (e Ogg FLAC): blocos PICTURE de verdade.
    pics = getattr(arq, "pictures", None)
    if pics:
        return pics[0].data, _ext_de(pics[0].mime)

    tags = getattr(arq, "tags", None)
    if not tags:
        return None

    # MP3: o quadro APIC.
    try:
        apics = tags.getall("APIC")
        if apics:
            return apics[0].data, _ext_de(apics[0].mime)
    except AttributeError:
        pass

    # MP4/M4A: o átomo `covr`. O formato vem num inteiro, não num mime.
    try:
        covr = tags.get("covr")
    except Exception:                                       # noqa: BLE001
        covr = None
    if covr:
        capa = covr[0]
        fmt = getattr(capa, "imageformat", None)
        png = getattr(type(capa), "FORMAT_PNG", 14)
        return bytes(capa), (".png" if fmt == png else ".jpg")

    # Ogg Vorbis / Opus: bloco PICTURE do FLAC, em base64, numa tag de texto.
    try:
        blocos = tags.get("metadata_block_picture")
    except Exception:                                       # noqa: BLE001
        blocos = None
    for bloco in (blocos or []):
        try:
            p = Picture(base64.b64decode(bloco))
        except Exception:                                   # noqa: BLE001
            continue
        if p.data:
            return p.data, _ext_de(p.mime)
    return None


def main(apply=False):
    wrote = skipped_have = no_art = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        audio = [f for f in filenames if f.lower().endswith(AUDIO)]
        if not audio:
            continue
        # Pelo `find_cover`, que é quem a estante e o deck usam: esta lista
        # era diferente das outras três (tinha `folder.png` e não tinha
        # `cover.jpeg`) e comparava só minúsculas. O estrago: numa pasta com
        # `Cover.jpg` do Windows, esta ferramenta escrevia um `cover.jpg`
        # NOVO ao lado do que já estava lá.
        if find_cover(dirpath, filenames):
            skipped_have += 1
            continue

        found = None
        for f in sorted(audio):
            found = embedded_art(os.path.join(dirpath, f))
            if found:
                break
        if not found:
            no_art += 1
            print(f"  sem capa embutida: {os.path.relpath(dirpath, ROOT)}")
            continue

        data, ext = found
        out = os.path.join(dirpath, "cover" + ext)
        if apply:
            with open(out, "wb") as fh:
                fh.write(data)
        wrote += 1
        print(f"{'escreveu' if apply else 'escreveria'}: "
              f"{os.path.relpath(out, ROOT)} ({len(data)//1024} KiB)")

    print(f"\n{wrote} capas {'escritas' if apply else 'a escrever'}; "
          f"{skipped_have} pastas já tinham; {no_art} não têm capa embutida")
    if not apply:
        print("isto foi só uma olhada — passe --apply para escrever")


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
