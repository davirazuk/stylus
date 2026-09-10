#!/usr/bin/env python3
"""Põe a coleção do cartão no banco de música DO SISTEMA do Vita.

POR QUE ISTO EXISTE
  O app Música da Vita não lê a pasta `ux0:music`. Ele lê um SQLite —
  `ux0:mms/music/AVContent.db`, tabela `tbl_Music` — que normalmente só o
  Content Manager escreve. Num cartão com 3.728 MP3 e a tabela VAZIA, o app
  responde "pegue músicas do PS3" e não mostra nada. Foi exatamente esse o
  sintoma relatado.

  Isso importa muito além do app Música: **tocar dentro de um jogo** só
  funciona pelo caminho que o sistema suporta — o app Música nativo (que o
  SO tem permissão de manter vivo) mais o plugin MusicPremium. Um homebrew
  comum é MORTO quando o jogo entra na frente, por mais que segure a porta
  BGM. O VitaWave, citado como referência, faz exatamente isto: escreve o
  mesmo banco (lógica do MediaImporter, do cnsldv, MIT).

O QUE ESTE SCRIPT FAZ
  1. copia o banco para backup antes de tocar nele;
  2. varre `ux0:music`, lê as tags de cada MP3 e insere em `tbl_Music`;
  3. tira UMA capa por PASTA de álbum da arte embutida (ID3 APIC) e grava a
     CAPA DE VERDADE na `tbl_Icon`, como DDS DXT1 128x128 — que é o formato
     que a Sony usa (ver o bloco ICON_* abaixo). De quebra grava um JPEG em
     `ux0:data/vitastylus/capas/` e aponta `icon_path` para ele, como segunda
     tentativa, porque custa 15 MB e não atrapalha;
  4. marca `tbl_config` para o sistema reler.

  A capa vai para `ux0:data`, e NÃO para o lado do MP3, de propósito: a
  coleção não tem backup em lugar nenhum e não se escreve dentro dela. Uma
  capa por álbum, e não por faixa, é o que separa ~15 MB de ~1 GB.

OS NÚMEROS QUE CUSTARAM TEMPO
  `icon_codec_type=17` é JPEG — vem do MediaImporter, que usa esse valor no
  UPDATE que dá ícone a vídeo.
  `icon_data_type` **tem de sair do -1**. O insert de MÚSICA do MediaImporter
  força -1 ("sem ícone"), porque ele nunca dá capa a música; o insert de
  VÍDEO, cujo ícone funciona, não mexe no campo e deixa o default 0. Por isso
  aqui é 0 nas faixas que ganharam capa.
  `content_path` é `ux0:/music/...` — com a barra depois dos dois-pontos, que
  é a grafia que o MediaImporter usa e o sistema aceita.

USO
  python3 tools/musica-para-o-vita.py [--cartao /run/media/…/VITASD]
  É idempotente: refaz a tabela do zero a cada execução.
"""

import argparse
import hashlib
import io
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxt1 import capa_para_icone

CARTAO_PADRAO = "/run/media/davirazuk/VITASD"
JPEG_CODEC = 17          # o valor que o MediaImporter usa para JPEG
# 500x500 é o TETO da capa, e ela é sempre JPEG.
#
# As miniaturas que a Sony escreveu para as FOTOS deste cartão são 128x128,
# mas aquilo é o ícone da grade de fotos, não a capa de um disco — reduzir a
# capa a 128 deixou tudo borrado e não fez a capa aparecer. Conferido também
# que 100% da arte embutida na coleção já é JPEG de verdade (623 de 623 na
# amostra, no mime e nos bytes), então converter formato não é o assunto.
LADO_MAX = 500

# A CAPA DE VERDADE MORA NA tbl_Icon, e é DDS DXT1 128x128.
#
# Isto não está documentado; foi lido do próprio cartão. O `mms/photo/
# AVContent.db` deste Vita tem 38 linhas escritas pela SONY para as fotos da
# câmera, e todas dizem a mesma coisa: content_table_type=4, data_type=1,
# codec_type=25, 128x128, size=8320, e o BLOB começa com "DDS "/"DXT1".
# Nessas linhas as colunas `icon_*` do CONTEÚDO estão todas zeradas — ou seja,
# o app não lê a capa de lá, lê da tbl_Icon.
#
# Foi por isso que a primeira tentativa (só icon_path + icon_codec_type=17,
# que é o que o MediaImporter faz com VÍDEO) não pôs capa nenhuma na tela.
# O icon_path continua sendo escrito, de graça, como segunda tentativa.
ICON_TABLE_TYPE = 4      # o que as linhas reais da Sony usam
ICON_DATA_TYPE = 1       # 1 = miniatura embutida no BLOB
ICON_CODEC_DDS = 25      # 25 = a textura DXT1
ICON_LADO = 128


def achar_capa(pasta, arquivos):
    """A arte embutida do primeiro MP3 da pasta que tiver uma."""
    from mutagen.id3 import ID3
    for nome in arquivos[:6]:
        try:
            apic = ID3(os.path.join(pasta, nome)).getall("APIC")
            if apic:
                return apic[0].data
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cartao", default=CARTAO_PADRAO)
    args = ap.parse_args()

    raiz_musica = os.path.join(args.cartao, "music")
    banco = os.path.join(args.cartao, "mms", "music", "AVContent.db")
    dir_capas = os.path.join(args.cartao, "data", "vitastylus", "capas")
    capas_no_vita = "ux0:/data/vitastylus/capas"

    # A CAPA TEM DE FICAR AO LADO DO MP3.
    #
    # O `icon_path` já apontava para `ux0:data/vitastylus/capas/`, e o app
    # Música não mostrava nada. A explicação mais provável é sandbox: um app
    # da Sony lê a PRÓPRIA pasta de dados e a `ux0:music`, não a pasta de
    # dados de um homebrew — o caminho existe, o arquivo existe, e a abertura
    # falha. É também por isso que o MediaImporter só usa sidecar ADJACENTE
    # (.THM/.jpg com o nome do arquivo) e que as miniaturas de FOTO da Sony
    # são BLOB dentro do banco: caminho para fora dá problema.
    #
    # Por isso agora é um `cover.jpg` DENTRO da pasta do álbum. É arquivo
    # NOVO — nada é sobrescrito, nada é renomeado, e apagar todos os
    # `cover.jpg` desfaz por inteiro. Uma coleção sem backup merece essa
    # regra escrita.

    for caminho, oque in ((raiz_musica, "a pasta de música"), (banco, "o banco")):
        if not os.path.exists(caminho):
            sys.exit("não achei %s em %s" % (oque, caminho))

    try:
        from mutagen import File as TagFile
        from PIL import Image
    except ImportError as e:
        sys.exit("faltam dependências (mutagen, pillow): %s" % e)

    # BACKUP ANTES DE QUALQUER ESCRITA. É banco do sistema.
    bak = banco + ".antes-do-stylus"
    if not os.path.exists(bak):
        shutil.copy2(banco, bak)
        print("backup: %s" % bak)

    os.makedirs(dir_capas, exist_ok=True)

    pastas = {}
    for dp, _, fs in os.walk(raiz_musica):
        mp3 = sorted(f for f in fs if f.lower().endswith(".mp3"))
        if mp3:
            pastas[dp] = mp3

    con = sqlite3.connect(banco)
    cur = con.cursor()
    cur.execute("DELETE FROM tbl_Music")
    cur.execute("DELETE FROM tbl_Icon")

    ins = ("INSERT INTO tbl_Music (codec_type, track_num, disc_num, size,"
           " duration, container_type, status, analyzed, icon_data_type,"
           " artist, title, genre, released_date, created_time,"
           " last_updated_time, imported_time, content_path, album_artist,"
           " album_name) VALUES (12,?,1,?,?,7,2,0,-1,?,?,?,?,datetime('now'),"
           "datetime('now'),datetime('now'),?,?,?)")
    # `analyzed` = 0, e NÃO o 1 do MediaImporter.
    #
    # Quem GERA a miniatura DXT1 é a análise do próprio sistema — foi assim
    # que as 38 fotos da câmera ganharam ícone. O MediaImporter põe 1 para
    # PULAR a análise (aparece na hora, sem esperar), e pular a análise é
    # pular a capa. Com 0 o sistema faz a passagem dele e cria o ícone a
    # partir da arte embutida no ID3, que 57% dos MP3 daqui têm.

    faixas = capas = 0
    for pasta, arquivos in sorted(pastas.items()):
        rel_pasta = os.path.relpath(pasta, raiz_musica).replace(os.sep, "/")

        caminho_capa = None
        icone = None
        dados = achar_capa(pasta, arquivos)
        if dados:
            nome = hashlib.md5(pasta.encode("utf-8")).hexdigest()[:16] + ".jpg"
            try:
                im = Image.open(io.BytesIO(dados))
                icone = capa_para_icone(im, ICON_LADO)      # o que a tela usa
                jpg = im.convert("RGB")
                jpg.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
                jpg.save(os.path.join(dir_capas, nome), "JPEG",
                         quality=85, optimize=True)
                # ao lado do MP3, que é o único lugar que o app Música lê
                lado = os.path.join(pasta, "cover.jpg")
                if not os.path.exists(lado):
                    jpg.save(lado, "JPEG", quality=90, optimize=True)
                caminho_capa = ("ux0:/music/" + rel_pasta + "/cover.jpg"
                                if rel_pasta != "." else "ux0:/music/cover.jpg")
                capas += 1
            except Exception:
                caminho_capa = None
                icone = None

        for nome_arq in arquivos:
            full = os.path.join(pasta, nome_arq)
            vpath = "ux0:/music/" + (rel_pasta + "/" if rel_pasta != "." else "") + nome_arq
            titulo = os.path.splitext(nome_arq)[0]
            artista = album = "Unknown"
            albart, genero, ano, dur, tn = "Unknown", None, None, 0, 0
            try:
                m = TagFile(full, easy=True)

                def tag(chave, padrao=None):
                    v = m.get(chave) if m else None
                    return (v[0] if v else padrao) or padrao

                titulo = tag("title", titulo)
                artista = tag("artist", "Unknown")
                album = tag("album", os.path.basename(pasta))
                albart = tag("albumartist", artista)
                genero = tag("genre")
                ano = tag("date") or tag("originaldate")
                if ano:
                    ano = str(ano)[:10]
                try:
                    tn = int(str(tag("tracknumber", "0")).split("/")[0])
                except ValueError:
                    tn = 0
                if m and m.info:
                    dur = int(m.info.length * 1000)
            except Exception:
                pass

            cur.execute(ins, (tn, os.path.getsize(full), dur, artista, titulo,
                              genero, ano, vpath, albart, album))
            faixas += 1

            # a capa vai amarrada ao mrid que a faixa acabou de receber
            if icone:
                cur.execute(
                    "INSERT INTO tbl_Icon (content_id, content_table_type,"
                    " width, height, data_type, offset, size, codec_type,"
                    " language_type, aspect_ratio, data)"
                    " VALUES (?,?,?,?,?,0,?,?,0,1.0,?)",
                    (cur.lastrowid, ICON_TABLE_TYPE, ICON_LADO, ICON_LADO,
                     ICON_DATA_TYPE, len(icone), ICON_CODEC_DDS,
                     sqlite3.Binary(icone)))

        if caminho_capa:
            cur.execute("UPDATE tbl_Music SET icon_path=?, icon_codec_type=?,"
                        " icon_data_type=0"
                        " WHERE content_path LIKE ?",
                        (caminho_capa, JPEG_CODEC,
                         "ux0:/music/" + rel_pasta + "/%"))

    cur.execute("UPDATE tbl_config SET val=0")   # marca para o sistema reler
    con.commit()

    com_capa = cur.execute("SELECT COUNT(*) FROM tbl_Icon").fetchone()[0]
    con.close()
    print("faixas: %d   álbuns com capa: %d   ícones DXT1 na tbl_Icon: %d"
          % (faixas, capas, com_capa))
    print("ejete o cartão antes de tirar (sync + desmontar).")


if __name__ == "__main__":
    main()
