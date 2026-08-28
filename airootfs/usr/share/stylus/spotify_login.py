#!/usr/bin/env python3
"""Guarda as credenciais do Spotify, depois de conferir que elas servem.

POR QUE ISTO EXISTE
-------------------
A seção do Spotify pedia um client_id e um client_secret escritos à mão num
arquivo que ninguém sabia onde ficava, e não dizia nada quando eles estavam
errados: a busca simplesmente não achava disco nenhum, e o erro que aparecia
era o do servidor, não "essas credenciais não servem".

Isto recebe os dois pelo STDIN, PERGUNTA AO SPOTIFY se eles valem, e só grava
quando valem. Errado é dito na hora, uma vez, em vez de virar uma seção que
não funciona pelo resto da vida da máquina.

    echo -e "ID\\nSEGREDO" | spotify_login.py

O que se guarda aqui não é a conta de ninguém: é a credencial de um "app" que
a pessoa cria de graça em developer.spotify.com. Ainda assim o arquivo nasce
0600 — um segredo de app é um segredo.
"""
import base64
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request

CONF = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "stylus", "spotify.conf")


def responde(**campos):
    print(json.dumps(campos, ensure_ascii=False))
    raise SystemExit(0 if campos.get("ok") else 1)


def vale(cid, seg):
    """As credenciais servem? Pergunta ao Spotify, com prazo.

    É o fluxo "client credentials", o mesmo que a busca usa. Se ele
    responde com um token, os dois valores estão certos — e é a única forma
    de saber sem esperar a primeira busca falhar.
    """
    dados = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    autor = base64.b64encode(f"{cid}:{seg}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token", data=dados,
        headers={"Authorization": "Basic " + autor,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return bool(json.loads(r.read()).get("access_token")), ""
    except urllib.error.HTTPError as e:
        # 400/401 aqui é sempre credencial: o Spotify não distingue "id não
        # existe" de "segredo errado", e dizer qual dos dois seria inventar.
        if e.code in (400, 401):
            return False, "o Spotify recusou: confira o ID e o segredo"
        return False, "o Spotify respondeu %s" % e.code
    except Exception as e:                               # noqa: BLE001
        return False, "não deu para falar com o Spotify: %s" % e


def main():
    linhas = sys.stdin.read().split("\n")
    cid = (linhas[0] if linhas else "").strip()
    seg = (linhas[1] if len(linhas) > 1 else "").strip()
    if not cid or not seg:
        responde(ok=False, erro="faltou o ID ou o segredo")

    bom, erro = vale(cid, seg)
    if not bom:
        responde(ok=False, erro=erro)

    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    # Modo certo ANTES de ter conteúdo: entre criar o arquivo e apertar as
    # permissões existe uma janela, curta mas real, em que o segredo está
    # legível por qualquer um.
    tmp = CONF + ".novo"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                 stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("[spotify]\nclient_id = %s\nclient_secret = %s\n" % (cid, seg))
    os.replace(tmp, CONF)
    responde(ok=True)


if __name__ == "__main__":
    main()
