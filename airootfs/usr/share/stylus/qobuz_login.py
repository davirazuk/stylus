#!/usr/bin/env python3
"""Entra na conta do Qobuz e grava o config.ini do qobuz-dl.

POR QUE ISTO EXISTE
-------------------
Para usar o Qubuz aqui, a máquina precisava que a pessoa abrisse um navegador
numa interface web, entrasse lá, e voltasse — e o único motivo de aquele
navegador existir era guardar um token num arquivo. Num sistema feito para
ser usado do sofá, com um controle, "abra o navegador" é o mesmo que "não dá
para fazer daqui".

Isto faz o que aquela página fazia: e-mail e senha entram, o token e o app_id
saem gravados em ~/.config/qobuz-dl/config.ini, no mesmo formato que o
qobuz-dl escreve — para que tudo que já lê aquele arquivo continue lendo.

    echo -e "eu@exemplo.com\\nminhasenha" | qobuz_login.py

TRÊS COISAS QUE ISTO TEM QUE RESPEITAR
--------------------------------------
1. A senha entra pelo STDIN, nunca por argumento. Argumento de processo
   aparece no `ps` para qualquer usuário da máquina, e fica no histórico do
   shell. Pelo stdin não passa por lugar nenhum que alguém possa ler depois.
2. O que fica gravado NÃO é a senha, é o md5 dela e o token — que é o mesmo
   que o qobuz-dl grava, e é o que a API do Qobuz espera receber de volta.
3. O arquivo nasce com modo 0600. Ele contém um token que dá acesso à conta
   de streaming de alguém; um config.ini legível por todo mundo é um
   descuido que não se percebe até tarde demais.
"""
import configparser
import hashlib
import json
import os
import stat
import sys
import threading

CONF = os.path.expanduser("~/.config/qobuz-dl/config.ini")


def responde(**campos):
    """Uma linha de JSON no stdout. Quem lê é a tela cheia e o shell."""
    print(json.dumps(campos, ensure_ascii=False))
    raise SystemExit(0 if campos.get("ok") else 1)


def main():
    dados = sys.stdin.read().split("\n")
    email = (dados[0] if dados else "").strip()
    senha = dados[1] if len(dados) > 1 else ""
    # Só o \n final é enfeite; espaço numa senha é senha.
    senha = senha.rstrip("\r\n")
    if not email or not senha:
        responde(ok=False, erro="faltou o e-mail ou a senha")

    # O logging do qobuz_dl escreve "Logging..." em inglês no stderr toda vez
    # que autentica. Aqui quem lê a saída é uma tela, e a resposta é uma linha
    # de JSON: barulho no meio só atrapalha.
    import logging
    logging.getLogger("qobuz_dl").setLevel(logging.WARNING)
    logging.getLogger("qopy").setLevel(logging.WARNING)
    try:
        from qobuz_dl.bundle import Bundle
        from qobuz_dl.qopy import Client
    except ImportError:
        responde(ok=False,
                 erro="o qobuz-dl não está instalado. Rode: stylus qobuz instalar")

    # ── o app_id e os segredos ────────────────────────────────────────────
    # Eles não são fixáveis no código: o Qobuz os troca, e um app_id velho
    # responde "Invalid app id" — que, sem esta explicação, se lê como senha
    # errada. Quem os tem é o player web do Qobuz, e a única forma de obtê-los
    # é raspar o bundle.js dele.
    #
    # Só que esse bundle.js é o ponto mais frágil de todo o caminho. Medido
    # aqui: a página de login responde em 1,2 s, e o bundle.js NÃO TERMINA DE
    # BAIXAR em dois minutos — nem pelo requests nem pelo curl. E o `timeout`
    # do requests é por leitura, não total: um fluxo lento pinga um byte de vez
    # em quando e a chamada nunca volta. Um login que depende disso é um login
    # que pendura a tela para sempre, sem nada explicando.
    #
    # Então: primeiro o que a máquina JÁ TEM guardado, que funciona e é
    # instantâneo; a raspagem só quando não há nada, e com prazo.
    velho = configparser.ConfigParser()
    if os.path.isfile(CONF):
        try:
            velho.read(CONF, encoding="utf-8")
        except Exception:                                # noqa: BLE001
            pass
    app_id = velho.get("DEFAULT", "app_id", fallback="").strip()
    segredos = [x.strip() for x in
                velho.get("DEFAULT", "secrets", fallback="").split(",") if x.strip()]
    chave = velho.get("DEFAULT", "private_key", fallback="").strip()

    if not (app_id and segredos):
        colhido = {}

        def _raspar():
            try:
                b = Bundle()
                colhido["app_id"] = b.get_app_id()
                colhido["segredos"] = [x for x in b.get_secrets().values() if x]
                try:
                    colhido["chave"] = b.get_private_key() or ""
                except Exception:                        # noqa: BLE001
                    colhido["chave"] = ""
            except Exception as e:                       # noqa: BLE001
                colhido["erro"] = str(e)

        # Em thread com prazo, e não com o timeout do requests: o do requests
        # é por leitura e não segura um fluxo lento. A thread fica para trás;
        # o processo sai e o sistema a leva junto.
        t = threading.Thread(target=_raspar, daemon=True)
        t.start()
        t.join(45)
        if "app_id" not in colhido:
            responde(ok=False, erro=(
                "o Qobuz não respondeu a tempo (é a página do player deles que "
                "está lenta, não a sua conexão). Tente de novo em alguns "
                "minutos — ou entre uma vez pela interface web, que guarda o "
                "mesmo dado:  stylus qobuz abrir"))
        app_id = colhido["app_id"]
        segredos = colhido["segredos"]
        chave = colhido.get("chave", "")

    md5 = hashlib.md5(senha.encode("utf-8")).hexdigest()
    try:
        cl = Client(email, md5, app_id, segredos)
    except Exception as e:                               # noqa: BLE001
        nome = type(e).__name__
        if "Auth" in nome or "Credential" in nome:
            responde(ok=False, erro="e-mail ou senha não conferem")
        if "Ineligible" in nome:
            responde(ok=False,
                     erro="esta conta do Qobuz não tem assinatura de streaming")
        responde(ok=False, erro=str(e) or nome)

    token = getattr(cl, "uat", "") or ""
    if not token:
        responde(ok=False, erro="o Qobuz não devolveu token nenhum")

    # O user_id não vem do Client; sai da mesma chamada de login.
    try:
        info = cl.api_call("user/login", email=email, pwd=md5)
        user_id = str((info.get("user") or {}).get("id") or "")
    except Exception:                                    # noqa: BLE001
        user_id = ""

    cfg = configparser.ConfigParser()
    # Lê o que já existe e só TROCA o que é de conta: quem já tinha ajustado
    # o formato das pastas, a qualidade ou as etiquetas não perde nada por
    # ter entrado de novo.
    if os.path.isfile(CONF):
        try:
            cfg.read(CONF, encoding="utf-8")
        except Exception:                                # noqa: BLE001
            cfg = configparser.ConfigParser()
    d = cfg["DEFAULT"]
    d["email"] = email
    d["password"] = md5
    d["app_id"] = str(app_id)
    d["secrets"] = ",".join(segredos)
    d["private_key"] = chave
    d["user_auth_token"] = token
    d["user_id"] = user_id
    # Só quando o arquivo é novo: um valor destes já escolhido é escolha da
    # pessoa, e sobrescrever seria desfazê-la.
    for chave_p, valor in (("folder_format", "{artist}/{album}"),
                           ("track_format", "{tracknumber} - {tracktitle}"),
                           ("default_limit", "20"),
                           ("no_m3u", "false"),
                           ("albums_only", "false"),
                           ("no_fallback", "false"),
                           ("og_cover", "false"),
                           ("embed_art", "true"),
                           ("no_cover", "false"),
                           ("no_database", "false")):
        d.setdefault(chave_p, valor)

    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    # Pelo temporário, e com o modo certo ANTES de ter conteúdo dentro: entre
    # criar o arquivo e apertar as permissões existe uma janela, curta mas
    # real, em que o token está legível por qualquer um.
    tmp = CONF + ".novo"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                 stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        cfg.write(fh)
    os.replace(tmp, CONF)

    responde(ok=True, assinatura=getattr(cl, "label", "") or "?",
             email=email)


if __name__ == "__main__":
    main()
