#!/usr/bin/env python3
"""Prepara pastas de álbum para o cartão do Vita.

POR QUE ISTO EXISTE
-------------------
O tocador do Vita decodifica com mpg123: **só MP3**. E o SDL2 do vdpm só abre
a porta de áudio como BGM (a que o plugin de CFW mantém viva em segundo plano)
quando a taxa é <= 47999 Hz. Ou seja, o que serve no aparelho é bem estreito:

    MP3, 44100 Hz, com a capa embutida.

Três coisas quebram isso na prática:

1. O Qobuz baixa FLAC — e com `default_quality = 27` é FLAC 24 bits/192 kHz.
   No cartão isso vira um disco que aparece na estante e não toca. (O app
   agora ignora não-MP3 e diz quantos ignorou, mas o arquivo continua inútil.)
2. Arquivos de 48 kHz caem na porta MAIN e perdem o áudio de fundo. O player
   reamostra na hora, mas gastar CPU do Vita a cada faixa é pior que resolver
   aqui, uma vez.
3. A cópia que está hoje no cartão PERDEU a arte embutida: a coleção em
   ~/staging-vita/vita-mp3/ tem capa em 339 de 405 álbuns; a do cartão, em 4.
   Quem copiou descartou os quadros APIC.

Este script resolve os três de uma vez e é idempotente: o que já está no
formato certo ele não reprocessa.

USO
---
    tools/para-vita.py PASTA_DO_ALBUM [PASTA...]
    tools/para-vita.py --todos ~/staging-vita/vita-mp3/
    tools/para-vita.py --destino /tmp/teste PASTA      # sem tocar no cartão
    tools/para-vita.py --dry-run --todos ~/staging-vita/vita-mp3/

Fluxo do Qobuz (o download é do PC, que é onde o Qobuz funciona de verdade):

    stylus qobuz buscar TERMOS
    stylus qobuz baixar ID
    tools/para-vita.py ~/Qobuz\\ Downloads/Artista/Album

NUNCA apaga nada na origem nem no destino: só escreve.
"""

import argparse
import os
import shutil
import subprocess
import sys

# O que o Vita aceita. Ver a nota grande em src/player.c (open_track).
TAXA_ALVO = 44100
TAXA_MAX_BGM = 47999
BITRATE = "320k"

FONTES = (".flac", ".mp3", ".ogg", ".m4a", ".wav", ".opus", ".aiff", ".wv")
CAPAS = ("cover.jpg", "folder.jpg", "front.jpg", "cover.png", "folder.png",
         "Cover.jpg", "Folder.jpg", "Front.jpg")

DESTINO_PADRAO = "/run/media/davirazuk/VITASD/music"


def erro(msg):
    print(f"  !! {msg}", file=sys.stderr)


def ffprobe(caminho, entrada):
    """Uma propriedade do arquivo, via ffprobe. None se não der."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
             "-show_entries", entrada, "-of", "default=nw=1:nk=1", caminho],
            capture_output=True, text=True, timeout=60)
        v = out.stdout.strip().splitlines()
        return v[0] if v else None
    except Exception:
        return None


def taxa_de(caminho):
    v = ffprobe(caminho, "stream=sample_rate")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def codec_de(caminho):
    return ffprobe(caminho, "stream=codec_name")


def tem_arte(caminho):
    """True se o MP3 já tem um APIC embutido."""
    try:
        from mutagen.id3 import ID3
        tags = ID3(caminho)
        return any(k.startswith("APIC") for k in tags.keys())
    except Exception:
        return False


def arte_da_pasta(pasta):
    for nome in CAPAS:
        p = os.path.join(pasta, nome)
        if os.path.isfile(p):
            return p
    return None


def extrai_arte(origem, saida_jpg):
    """Tira a capa embutida da origem para um .jpg. True se conseguiu."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "quiet", "-y", "-i", origem,
             "-an", "-vcodec", "copy", saida_jpg],
            capture_output=True, timeout=120)
        return r.returncode == 0 and os.path.getsize(saida_jpg) > 0
    except Exception:
        return False


def embute_arte(mp3, jpg):
    """Põe o jpg como capa frontal do mp3 (mutagen; o ffmpeg é chato com isso)."""
    try:
        from mutagen.id3 import ID3, APIC, error as ID3Error
        try:
            tags = ID3(mp3)
        except ID3Error:
            tags = ID3()
        with open(jpg, "rb") as f:
            dados = f.read()
        mime = "image/png" if jpg.lower().endswith(".png") else "image/jpeg"
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=dados))
        tags.save(mp3)
        return True
    except Exception as e:
        erro(f"não embuti a capa em {os.path.basename(mp3)}: {e}")
        return False


def ja_serve(caminho):
    """O arquivo já é MP3 44,1k (ou pelo menos <= o teto do BGM) com capa?"""
    if not caminho.lower().endswith(".mp3"):
        return False
    taxa = taxa_de(caminho)
    if taxa is None or taxa > TAXA_MAX_BGM:
        return False
    return tem_arte(caminho)


def converte(origem, destino, jpg):
    """origem -> MP3 320 CBR 44,1k, mantendo as tags. jpg (ou None) vira capa."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", origem,
           "-map", "0:a:0",              # só o áudio; a capa entra depois
           "-map_metadata", "0",
           "-codec:a", "libmp3lame", "-b:a", BITRATE,
           "-ar", str(TAXA_ALVO),
           "-id3v2_version", "3",
           destino]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        erro(f"ffmpeg falhou em {os.path.basename(origem)}: {r.stderr.strip()[:200]}")
        return False
    if jpg:
        embute_arte(destino, jpg)
    return True


def faixas_de(pasta):
    return sorted(f for f in os.listdir(pasta)
                  if f.lower().endswith(FONTES)
                  and os.path.isfile(os.path.join(pasta, f)))


def processa_album(pasta, destino_raiz, dry_run):
    pasta = os.path.abspath(pasta.rstrip("/"))
    nome = os.path.basename(pasta)
    faixas = faixas_de(pasta)
    if not faixas:
        return None

    destino = os.path.join(destino_raiz, nome)
    print(f"\n  {nome}  ({len(faixas)} faixas)")

    # a capa: preferimos a embutida da 1ª faixa; senão uma imagem na pasta
    jpg = None
    tmp_jpg = os.path.join("/tmp", f"para-vita-capa-{os.getpid()}.jpg")
    if extrai_arte(os.path.join(pasta, faixas[0]), tmp_jpg):
        jpg = tmp_jpg
    else:
        jpg = arte_da_pasta(pasta)
    if not jpg:
        print("    (sem capa: nem embutida nem arquivo na pasta)")

    if dry_run:
        conv = sum(1 for f in faixas if not ja_serve(os.path.join(pasta, f)))
        print(f"    [dry-run] converteria {conv}, copiaria {len(faixas) - conv}")
        return (len(faixas), conv, 0)

    os.makedirs(destino, exist_ok=True)
    feitas = convertidas = puladas = 0
    for f in faixas:
        src = os.path.join(pasta, f)
        base = os.path.splitext(f)[0]
        dst = os.path.join(destino, base + ".mp3")

        if os.path.isfile(dst) and ja_serve(dst):
            puladas += 1
            feitas += 1
            continue

        if ja_serve(src):
            # já está no formato certo: cópia direta, sem recodificar
            shutil.copy2(src, dst)
            feitas += 1
            continue

        if converte(src, dst, jpg):
            convertidas += 1
            feitas += 1

    print(f"    {feitas}/{len(faixas)} prontas "
          f"({convertidas} convertidas, {puladas} já estavam)")
    if jpg == tmp_jpg and os.path.isfile(tmp_jpg):
        os.remove(tmp_jpg)
    return (len(faixas), convertidas, puladas)


def confere(destino_raiz, limite=400):
    """Confere o que ficou no destino: MP3? taxa boa? capa?"""
    ruins_taxa = sem_capa = total = 0
    for raiz, _dirs, arqs in os.walk(destino_raiz):
        for f in arqs:
            if not f.lower().endswith(".mp3"):
                continue
            total += 1
            if total > limite:
                break
            p = os.path.join(raiz, f)
            taxa = taxa_de(p)
            if taxa is None or taxa > TAXA_MAX_BGM:
                ruins_taxa += 1
            if not tem_arte(p):
                sem_capa += 1
    print(f"\n  conferência ({min(total, limite)} de {total} arquivos):")
    print(f"    taxa acima de {TAXA_MAX_BGM} Hz (perderiam o BGM): {ruins_taxa}")
    print(f"    sem capa embutida: {sem_capa}")


def main():
    ap = argparse.ArgumentParser(
        description="Prepara álbuns para o cartão do Vita (MP3 44,1k com capa).")
    ap.add_argument("pastas", nargs="*", help="pastas de álbum")
    ap.add_argument("--todos", metavar="RAIZ",
                    help="processa todas as subpastas com áudio dentro de RAIZ")
    ap.add_argument("--destino", default=DESTINO_PADRAO,
                    help=f"onde escrever (padrão: {DESTINO_PADRAO})")
    ap.add_argument("--dry-run", action="store_true",
                    help="só diz o que faria")
    ap.add_argument("--conferir", action="store_true",
                    help="confere o destino no fim")
    args = ap.parse_args()

    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            erro(f"falta {exe}")
            return 1
    try:
        import mutagen  # noqa: F401
    except ImportError:
        erro("falta o módulo python 'mutagen' (pip install mutagen)")
        return 1

    alvos = list(args.pastas)
    if args.todos:
        raiz = os.path.abspath(args.todos)
        for d, _sub, arqs in os.walk(raiz):
            if d != raiz and any(a.lower().endswith(FONTES) for a in arqs):
                alvos.append(d)
    if not alvos:
        ap.print_help()
        return 2

    if not args.dry_run:
        os.makedirs(args.destino, exist_ok=True)
    print(f"destino: {args.destino}")
    print(f"álbuns: {len(alvos)}")

    tot_f = tot_c = tot_p = 0
    for pasta in sorted(alvos):
        r = processa_album(pasta, args.destino, args.dry_run)
        if r:
            tot_f += r[0]; tot_c += r[1]; tot_p += r[2]

    print(f"\n═══ {tot_f} faixas · {tot_c} convertidas · {tot_p} já prontas ═══")
    if args.conferir and not args.dry_run:
        confere(args.destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
