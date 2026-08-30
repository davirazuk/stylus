"""Escreve o cover.jpg nas pastas de disco que não têm um, mas cujos arquivos
de áudio já trazem a capa embutida.

Não é conserto de reprodução: todo disco conferido já tinha a capa dentro
do arquivo, e os tocadores sempre estiveram bem. Isto é para o gerenciador
de arquivos, para a miniatura da pasta e para qualquer programa que procure
uma imagem ao lado em vez de ler a etiqueta.

Só acrescenta: nunca escreve por cima de uma capa que já existe e nunca
mexe nos arquivos de áudio.

Com --apply escreve de verdade; sem ele, só mostra o que faria.

E com --buscar vai à REDE atrás das que não estão em lugar nenhum — nem
solta na pasta, nem dentro do arquivo. Sem isso, um disco que chegou sem
capa ficava sem capa para sempre: o `stylus check` dizia "sem capa", esta
ferramenta dizia "sem capa embutida", e não havia terceiro lugar de onde
tirar. A estante é uma grade de capas; um quadrado vazio nela é o defeito
mais visível que este sistema tem.

A fonte é o Cover Art Archive, pela busca do MusicBrainz. Nada disso é
obrigatório: sem rede, cada disco falha sozinho e o resto continua.
"""
import os
import sys
import glob

import base64

import mutagen
from mutagen.flac import Picture

from _raiz import raiz, audio_ext, find_cover, plural
from _raiz import folder_names   # a coleção, a música, a capa, o nome

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


# ── a capa que não está em lugar nenhum ──────────────────────────────────
# O MusicBrainz pede duas coisas de quem consulta, e as duas são regra da
# casa e não gentileza: um User-Agent que diga quem é (com um jeito de
# contato) e no máximo UMA consulta por segundo. Quem ignora leva bloqueio —
# e o bloqueio não cai só sobre quem ignorou.
MB = "https://musicbrainz.org/ws/2/release"
CAA = "https://coverartarchive.org/release/%s/front-500"
UA = "STYLUS/1.0 (https://github.com/davirazuk/stylus)"
_ultima_consulta = [0.0]


def _devagar():
    """Uma consulta por segundo, contada do fim da anterior."""
    import time
    espera = 1.05 - (time.time() - _ultima_consulta[0])
    if espera > 0:
        time.sleep(espera)
    _ultima_consulta[0] = time.time()


def _pega(url, aceita="application/json"):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": aceita})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def capa_da_rede(artista, disco):
    """(bytes, extensão) da capa deste disco, ou None.

    Procura a EDIÇÃO no MusicBrainz e pede a frente dela ao Cover Art
    Archive. Tenta as primeiras edições porque nem toda uma tem imagem: um
    disco famoso tem dezenas de edições e só algumas foram fotografadas.

    Nunca levanta: sem rede, sem resposta, sem imagem — devolve None e quem
    chamou segue para o próximo disco. Uma ferramenta que morre no primeiro
    disco sem capa é pior do que uma que não busca.
    """
    import json
    import urllib.parse
    if not artista or not disco:
        return None
    consulta = 'artist:"%s" AND release:"%s"' % (
        artista.replace('"', ""), disco.replace('"', ""))
    url = "%s?query=%s&fmt=json&limit=5" % (
        MB, urllib.parse.quote(consulta, safe=""))
    try:
        _devagar()
        dados = json.loads(_pega(url).decode("utf-8", "replace"))
    except Exception:                                      # noqa: BLE001
        return None
    for ed in (dados.get("releases") or [])[:5]:
        mbid = ed.get("id")
        if not mbid:
            continue
        try:
            _devagar()
            img = _pega(CAA % mbid, aceita="image/*")
        except Exception:                                  # noqa: BLE001
            continue
        # Uma resposta minúscula não é uma capa: é uma página de erro que
        # veio com código 200. Trinta KiB é menos do que qualquer frente de
        # disco de verdade e mais do que qualquer recado.
        if img and len(img) > 30_000:
            return img, ".png" if img[:4] == b"\x89PNG" else ".jpg"
    return None


def main(apply=False, buscar=False):
    wrote = skipped_have = no_art = da_rede = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        audio = [f for f in filenames if f.lower().endswith(AUDIO)]
        if not audio:
            continue
        # Pelo `find_cover`, que é quem a estante e a tela cheia usam: esta lista
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
        if not found and buscar:
            # O par artista/disco sai do CAMINHO, que é como a estante o lê.
            # Sem `_raiz.folder_names` a pergunta seria feita com o nome da
            # pasta inteiro ("1997 - OK Computer"), que não acha nada.
            artista, nome = folder_names(dirpath)
            achou = capa_da_rede(artista, nome)
            if achou:
                data, ext = achou
                out = os.path.join(dirpath, "cover" + ext)
                if apply:
                    with open(out, "wb") as fh:
                        fh.write(data)
                da_rede += 1
                print(f"  {'baixou' if apply else 'baixaria'}: "
                      f"{os.path.relpath(out, ROOT)} ({len(data)//1024} KiB)")
                continue
        if not found:
            no_art += 1
            print(f"  sem capa {'em lugar nenhum' if buscar else 'embutida'}: "
                  f"{os.path.relpath(dirpath, ROOT)}")
            continue

        data, ext = found
        out = os.path.join(dirpath, "cover" + ext)
        if apply:
            with open(out, "wb") as fh:
                fh.write(data)
        wrote += 1
        print(f"{'escreveu' if apply else 'escreveria'}: "
              f"{os.path.relpath(out, ROOT)} ({len(data)//1024} KiB)")

    print(f"\n{plural(wrote, 'capa')} {'escritas' if apply else 'a escrever'}"
          + (f" · {plural(da_rede, 'capa')} da rede" if buscar else "")
          + f"; {skipped_have} pastas já tinham; "
          + f"{no_art} sem capa {'em lugar nenhum' if buscar else 'embutida'}")
    if not apply:
        print("isto foi só uma olhada — passe --apply para escrever")
    elif not buscar and no_art:
        print("as que sobraram não têm capa dentro do arquivo; "
              "`stylus covers --buscar --apply` procura na rede")


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

    main("--apply" in sys.argv, "--buscar" in sys.argv)
