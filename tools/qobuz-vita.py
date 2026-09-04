#!/usr/bin/env python3
"""Qobuz -> cartão do Vita, com a qualidade à sua escolha.

O QUE É VERDADE SOBRE O QOBUZ (conferido ao vivo, não suposto)
--------------------------------------------------------------
O `track/getFileUrl` devolve uma URL **HTTPS comum**, assinada e com validade
de cerca de uma hora. O `private_key`/`sec` do config assina o PEDIDO (um MD5),
ele **não** criptografa o áudio. (O CLAUDE.md deste repo afirmava que portar
exigiria "decriptografia dos streams"; está errado, e isso muda a conta.)

As qualidades, medidas na conta Studio deste PC:

    fmt  5  MP3 320       44,1 kHz / 16 bit
    fmt  6  FLAC          44,1 kHz / 16 bit     <- lossless E compatível c/ BGM
    fmt  7  FLAC          até 96 kHz / 24 bit
    fmt 27  FLAC          até 192 kHz / 24 bit

O QUE O VITA TOCA
-----------------
**MP3, FLAC, Vorbis, Opus e WAV** — o src/decoder.c cuida dos cinco. FLAC
toca, e toca bem: o teste de host compara amostra a amostra com o original.

O que ainda LIMITA é outra coisa, e não é o formato: o SDL2 do Vita só abre a
porta de áudio como BGM — a que segura a música dentro de um jogo — com taxa
**<= 47999 Hz**. Acima disso a porta é MAIN e o som morre ao sair do app.

    fmt  5  MP3 320       44,1 kHz  -> toca e segura o 2º plano
    fmt  6  FLAC 16/44,1  44,1 kHz  -> toca e segura o 2º plano  <- o melhor
    fmt  7  FLAC 24/<=96  96 kHz    -> toca, mas PERDE o 2º plano
    fmt 27  FLAC 24/<=192 96 kHz    -> toca, mas PERDE o 2º plano

O MP3 acima do teto é reamostrado na abertura (o mpg123 faz por nós); o FLAC
não, porque não há reamostrador aqui. O deck mostra "2º plano: sim/não" para
não ser preciso adivinhar.

POR ISSO O PADRÃO É MP3, E O FLAC RECOMENDADO É O fmt 6
-------------------------------------------------------
    qobuz-vita.py buscar radiohead in rainbows
    qobuz-vita.py baixar 0060254724091                    # MP3 320 -> cartão
    qobuz-vita.py baixar 0060254724091 --formato flac     # FLAC 16/44,1
    qobuz-vita.py baixar ID --formato flac --hires        # 24 bits, se houver
    qobuz-vita.py baixar ID --destino ~/Qobuz --formato flac

FLAC vai para onde você mandar; se for o cartão, o script AVISA que o Vita
não vai tocar. Guardar FLAC no PC e mandar MP3 pro cartão é o uso que fecha
com a limitação de espaço.

Não usa o CLI do qobuz-dl (que está quebrado nesta máquina, ver README);
fala direto com a biblioteca `qobuz_dl.qopy`, que é o caminho que funciona.
Nenhum segredo é impresso nem gravado por este script.
"""

import argparse
import configparser
import logging
import os
import re
import sys

CONFIG = os.path.expanduser("~/.config/qobuz-dl/config.ini")
DESTINO_PADRAO = "/run/media/davirazuk/VITASD/music"
TAXA_MAX_BGM = 47999

FORMATOS = {
    "mp3":        (5,  "MP3 320 kbps, 44,1 kHz — toca e segura o 2º plano"),
    "flac":       (6,  "FLAC 16 bits / 44,1 kHz — lossless E segura o 2º plano"),
    "flac-hires": (7,  "FLAC 24 bits / até 96 kHz — perde o 2º plano"),
    "flac-max":   (27, "FLAC 24 bits / até 192 kHz — perde o 2º plano"),
}


# saída linha a linha: baixar um disco leva minutos e um cano guardaria
# tudo até o fim (ver a nota igual no para-vita.py)
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


def erro(m):
    print(f"  !! {m}", file=sys.stderr)


def cliente():
    """Autentica com o config do qobuz-dl. Devolve (Client, DEFAULT)."""
    if not os.path.isfile(CONFIG):
        erro(f"sem {CONFIG} — rode `stylus qobuz instalar` primeiro")
        return None, None
    logging.getLogger("qopy").setLevel(logging.ERROR)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG)
    d = cfg["DEFAULT"]
    try:
        from qobuz_dl.qopy import Client
    except ImportError:
        erro("falta o pacote python qobuz-dl")
        return None, None
    # PEGADINHA: `secrets` no config é uma STRING com vírgulas; o qopy espera
    # uma LISTA. Passar a string crua dá InvalidAppSecretError.
    secrets = [s for s in d["secrets"].split(",") if s]
    cl = Client(None, None, d["app_id"], secrets, skip_auth=True)
    cl.auth_with_token(d["user_id"], d["user_auth_token"])
    return cl, d


# Quanto cada formato ocupa por MINUTO de música, medido na prática:
#   MP3 320 kbps  = 320 kbit/s      -> 2,4 MB/min
#   FLAC 16/44,1  ~ 900 kbit/s      -> 6,7 MB/min  (compressão ~60% do PCM)
#   FLAC 24/96    ~ 2700 kbit/s     -> 20 MB/min
# É estimativa, e serve pra AVISAR antes de encher o cartão — não pra ser
# exata. O teto padrão é 1 GB porque é o que cabe confortavelmente aqui.
MB_POR_MINUTO = {5: 2.4, 6: 6.7, 7: 20.0, 27: 30.0}
LIMITE_GB_PADRAO = 1.0


def espaco_livre_mb(caminho):
    try:
        p = caminho
        while p and not os.path.isdir(p):
            p = os.path.dirname(p)
        st = os.statvfs(p or "/")
        return st.f_bavail * st.f_frsize / (1 << 20)
    except Exception:
        return None


def uso_mb(caminho):
    """Quanto a pasta já ocupa, em MB."""
    total = 0
    for raiz, _d, arqs in os.walk(caminho):
        for a in arqs:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total / (1 << 20)


def limpa(nome):
    """Nome de pasta/arquivo seguro pro exFAT do cartão."""
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", nome)
    nome = re.sub(r"\s+", " ", nome).strip(" .")
    return nome[:120] or "sem-nome"


def cmd_buscar(cl, termos, limite):
    res = cl.search_albums(" ".join(termos), limite)
    itens = res.get("albums", {}).get("items", [])
    if not itens:
        print("nada encontrado.")
        return 0
    for a in itens:
        hires = " [hi-res]" if a.get("hires_streamable") else ""
        print(f"  {a['id']}  {a['artist']['name']} — {a['title']}"
              f"  ({a.get('tracks_count','?')} faixas){hires}")
    print("\n  baixar:  qobuz-vita.py baixar ID [--formato mp3|flac]")
    return 0


def baixa_url(url, destino):
    """Baixa a URL assinada. requests se houver; senão urllib."""
    tmp = destino + ".parcial"
    try:
        try:
            import requests
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for pedaco in r.iter_content(1 << 16):
                        f.write(pedaco)
        except ImportError:
            import urllib.request
            with urllib.request.urlopen(url, timeout=120) as r, \
                    open(tmp, "wb") as f:
                while True:
                    pedaco = r.read(1 << 16)
                    if not pedaco:
                        break
                    f.write(pedaco)
        os.replace(tmp, destino)
        return True
    except Exception as e:
        erro(f"download falhou: {e}")
        if os.path.isfile(tmp):
            os.remove(tmp)
        return False


def marca(caminho, faixa, alb, capa_bytes):
    """Grava tags + capa. Sem isto a estante do Vita fica sem título nem arte."""
    try:
        import mutagen
        from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK, error as ID3Err
        from mutagen.flac import FLAC, Picture
    except ImportError:
        return
    titulo = faixa.get("title", "")
    artista = (faixa.get("performer") or {}).get("name") or \
              (alb.get("artist") or {}).get("name", "")
    album = alb.get("title", "")
    num = str(faixa.get("track_number", ""))
    try:
        if caminho.lower().endswith(".flac"):
            f = FLAC(caminho)
            f["title"] = titulo; f["artist"] = artista
            f["album"] = album;  f["tracknumber"] = num
            if capa_bytes:
                p = Picture(); p.type = 3; p.mime = "image/jpeg"; p.data = capa_bytes
                f.clear_pictures(); f.add_picture(p)
            f.save()
        else:
            try:
                t = ID3(caminho)
            except ID3Err:
                t = ID3()
            t.add(TIT2(encoding=3, text=titulo))
            t.add(TPE1(encoding=3, text=artista))
            t.add(TALB(encoding=3, text=album))
            t.add(TRCK(encoding=3, text=num))
            if capa_bytes:
                t.delall("APIC")
                t.add(APIC(encoding=3, mime="image/jpeg", type=3,
                           desc="Cover", data=capa_bytes))
            t.save(caminho, v2_version=3)
    except Exception as e:
        erro(f"tags falharam em {os.path.basename(caminho)}: {e}")


def cmd_baixar(cl, album_id, formato, destino, limite_faixas, dry_run,
               limite_gb, forcar):
    fmt_id, desc = FORMATOS[formato]
    # Um id que não existe (ou que a loja aposentou) devolvia um traceback de
    # requests na cara de quem usa. O id vem de `buscar`, e ele muda.
    try:
        meta = cl.get_album_meta(album_id)
    except Exception as e:
        codigo = getattr(getattr(e, "response", None), "status_code", None)
        if codigo == 404:
            erro(f"o Qobuz não conhece o álbum {album_id}")
            print("     os ids mudam; pegue um novo com:", file=sys.stderr)
            print("       qobuz-vita.py buscar TERMOS", file=sys.stderr)
        else:
            erro(f"não consegui os dados do álbum: {type(e).__name__}: {e}")
        return 1
    artista = (meta.get("artist") or {}).get("name", "?")
    titulo = meta.get("title", "?")
    faixas = meta.get("tracks", {}).get("items", [])
    if limite_faixas:
        faixas = faixas[:limite_faixas]

    pasta = os.path.join(destino, limpa(f"{artista} - {titulo}"))
    ext = ".mp3" if fmt_id == 5 else ".flac"

    print(f"\n  {artista} — {titulo}")
    print(f"  formato: {desc}")
    print(f"  destino: {pasta}")

    # ---- espaço: avisar ANTES, não depois de encher o cartão ----
    segundos = sum(f.get("duration", 0) or 0 for f in faixas)
    est_mb = (segundos / 60.0) * MB_POR_MINUTO.get(fmt_id, 7.0)
    livre = espaco_livre_mb(destino)
    ja = uso_mb(destino) if os.path.isdir(destino) else 0.0
    limite_mb = limite_gb * 1024.0

    print(f"  tamanho estimado: {est_mb:.0f} MB "
          f"({segundos // 60} min em {ext[1:]})  ·  teto {limite_mb:.0f} MB")
    print(f"  destino já tem {ja / 1024:.1f} GB"
          + (f"  ·  livre no disco: {livre / 1024:.1f} GB" if livre else ""))

    if fmt_id != 5:
        mp3_mb = (segundos / 60.0) * MB_POR_MINUTO[5]
        print(f"  (em MP3 320 seriam {mp3_mb:.0f} MB — {est_mb / max(mp3_mb, 1):.1f}x menos)")

    # O teto vale para ESTE download, não para o acervo que já está lá: o
    # cartão pode ter dezenas de GB de música antiga e ainda assim caber mais
    # um disco. Somar o que já existe faria a ferramenta recusar tudo.
    estouro = est_mb > limite_mb
    sem_espaco = livre is not None and est_mb > livre
    if (estouro or sem_espaco) and not forcar and not dry_run:
        if sem_espaco:
            erro(f"não cabe: precisa de ~{est_mb:.0f} MB e há {livre:.0f} MB livres")
        else:
            erro(f"este disco sozinho passaria do teto: "
                 f"{est_mb:.0f} MB > {limite_mb:.0f} MB")
        print("     use --formato mp3 (bem menor), --limite-gb N ou --forcar",
              file=sys.stderr)
        return 1

    no_cartao = os.path.abspath(destino).startswith(
        os.path.abspath(DESTINO_PADRAO).rsplit("/music", 1)[0])
    if fmt_id in (7, 27):
        print(f"  ATENÇÃO: acima de {TAXA_MAX_BGM} Hz o SDL2 abre a porta MAIN e o")
        print("           áudio em segundo plano NÃO segura. Toca normal, mas sai")
        print("           do jogo. Para 2º plano com lossless, use --formato flac")
        print("           (fmt 6: 16 bits / 44,1 kHz).")

    # capa do álbum, uma vez pro disco inteiro
    capa = None
    url_capa = (meta.get("image") or {}).get("large")
    if url_capa and not dry_run:
        try:
            import urllib.request
            with urllib.request.urlopen(url_capa, timeout=60) as r:
                capa = r.read()
        except Exception:
            pass

    if dry_run:
        print(f"  [dry-run] baixaria {len(faixas)} faixas em {ext}")
        return 0

    os.makedirs(pasta, exist_ok=True)
    ok = 0
    for f in faixas:
        n = f.get("track_number", 0)
        nome = limpa(f"{n:02d} - {f.get('title','faixa')}") + ext
        alvo = os.path.join(pasta, nome)
        if os.path.isfile(alvo) and os.path.getsize(alvo) > 0:
            print(f"    · {nome}  (já estava)")
            ok += 1
            continue
        try:
            r = cl.get_track_url(f["id"], fmt_id)
            url = r.get("url")
        except Exception as e:
            erro(f"{nome}: sem URL ({type(e).__name__})")
            continue
        if not url:
            erro(f"{nome}: sem URL (faixa indisponível nesta qualidade?)")
            continue
        if baixa_url(url, alvo):
            marca(alvo, f, meta, capa)
            mb = os.path.getsize(alvo) / (1 << 20)
            print(f"    ✓ {nome}  ({mb:.1f} MB)")
            ok += 1
    print(f"\n  {ok}/{len(faixas)} faixas")
    if ok:
        print("  pronto pro Vita." + ("" if fmt_id in (5, 6)
              else "  (2º plano não segura nesta taxa — ver acima.)"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(
        description="Baixa do Qobuz na qualidade que você escolher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="formatos:\n" + "\n".join(
            f"  {k:<11} fmt {v[0]:<3} {v[1]}" for k, v in FORMATOS.items()))
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("buscar", help="procura álbuns")
    b.add_argument("termos", nargs="+")
    b.add_argument("--limite", type=int, default=10)

    d = sub.add_parser("baixar", help="baixa um álbum")
    d.add_argument("album_id")
    d.add_argument("--formato", choices=list(FORMATOS), default="mp3")
    d.add_argument("--hires", action="store_true",
                   help="com --formato flac, sobe pra 24 bits (fmt 7)")
    d.add_argument("--destino", default=DESTINO_PADRAO)
    d.add_argument("--faixas", type=int, default=0,
                   help="baixa só as N primeiras (pra testar)")
    d.add_argument("--limite-gb", type=float, default=LIMITE_GB_PADRAO,
                   help=f"teto de ocupação no destino (padrão {LIMITE_GB_PADRAO} GB)")
    d.add_argument("--forcar", action="store_true",
                   help="baixa mesmo passando do teto")
    d.add_argument("--dry-run", action="store_true")

    e = sub.add_parser("espaco", help="quanto o destino já ocupa")
    e.add_argument("--destino", default=DESTINO_PADRAO)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 2

    # `espaco` não precisa da conta do Qobuz
    if args.cmd == "espaco":
        usado = uso_mb(args.destino) if os.path.isdir(args.destino) else 0.0
        livre = espaco_livre_mb(args.destino)
        print(f"{args.destino}")
        print(f"  ocupado: {usado:.0f} MB ({usado / 1024:.2f} GB)")
        if livre is not None:
            print(f"  livre no disco: {livre:.0f} MB ({livre / 1024:.2f} GB)")
        return 0

    cl, _ = cliente()
    if cl is None:
        return 1
    print(f"conta: {getattr(cl, 'label', '?')}")

    if args.cmd == "buscar":
        return cmd_buscar(cl, args.termos, args.limite)

    formato = args.formato
    if args.hires and formato == "flac":
        formato = "flac-hires"
    return cmd_baixar(cl, args.album_id, formato, args.destino,
                      args.faixas, args.dry_run, args.limite_gb, args.forcar)


if __name__ == "__main__":
    sys.exit(main())
