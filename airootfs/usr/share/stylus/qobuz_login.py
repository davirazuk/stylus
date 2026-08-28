#!/usr/bin/env python3
"""Entra na conta do Qobuz e grava o config.ini do qobuz-dl.

POR QUE ISTO EXISTE
-------------------
Para usar o Qobuz aqui, a máquina precisava que a pessoa abrisse um navegador
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
import hashlib
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qobuz_conta import guardar, ler_credenciais            # noqa: E402


def responde(**campos):
    """Uma linha de JSON no stdout. Quem lê é a tela cheia e o shell."""
    print(json.dumps(campos, ensure_ascii=False))
    raise SystemExit(0 if campos.get("ok") else 1)


def raspar_bundle(Bundle, prazo=45):
    """O app_id e os segredos, do player web do Qobuz.

    Eles não são fixáveis no código: o Qobuz os troca, e um app_id velho
    responde "Invalid app id" — que, sem esta explicação, se lê como senha
    errada. Quem os tem é o player web, e a única forma de obtê-los é raspar
    o bundle.js dele.

    Só que esse bundle.js é o ponto mais frágil de todo o caminho. Medido
    aqui em dois dias diferentes: 7,6 s num, e no outro NÃO TERMINOU DE
    BAIXAR em dois minutos — nem pelo requests nem pelo curl. E o `timeout`
    do requests é por leitura, não total: um fluxo lento pinga um byte de vez
    em quando e a chamada nunca volta. Por isso o prazo é de uma THREAD, que
    é a única coisa que segura isso de verdade; ela fica para trás e o
    processo sai sem ela.
    """
    colhido = {}

    def _raspar():
        try:
            b = Bundle()
            colhido["app_id"] = b.get_app_id()
            colhido["segredos"] = [x for x in b.get_secrets().values() if x]
            try:
                colhido["chave"] = b.get_private_key() or ""
            except Exception:                            # noqa: BLE001
                colhido["chave"] = ""
        except Exception as e:                           # noqa: BLE001
            colhido["erro"] = str(e)

    t = threading.Thread(target=_raspar, daemon=True)
    t.start()
    t.join(prazo)
    if "app_id" not in colhido:
        return None
    return colhido["app_id"], colhido["segredos"], colhido.get("chave", "")


def tentar(Client, app_id, segredos, email, md5):
    """UMA tentativa de entrar com este app_id. Devolve (token, id, selo).

    O user_id sai da MESMA chamada que autenticou. Antes ele vinha de um
    segundo `user/login` embrulhado num `except: user_id = ""` — e quando
    esse segundo pedido falhava, o login dizia "entrou" e gravava um user_id
    vazio, com o qual nada mais funciona: o `qobuz_busca` olha o arquivo,
    não vê user_id, e responde "o Qobuz ainda não tem conta aqui". Entrar e
    continuar sem conta é a pior resposta possível.
    """
    cl = Client(None, None, app_id, segredos, skip_auth=True)
    info = cl.api_call("user/login", email=email, pwd=md5)
    usuario = info.get("user") or {}
    cred = usuario.get("credential") or {}
    if not cred.get("parameters"):
        from qobuz_dl.exceptions import IneligibleError
        raise IneligibleError("sem assinatura")
    token = info.get("user_auth_token") or ""
    uid = str(usuario.get("id") or "")
    if not token or not uid:
        raise RuntimeError("o Qobuz não devolveu token nem conta")
    # Confere os SEGREDOS antes de gravar: o auth_with_token chama o
    # cfg_setup, que experimenta um por um contra a API. Sem isto o login
    # grava um segredo que só vai falhar mais tarde, na primeira busca, longe
    # daqui — e aí parece defeito da busca.
    cl.auth_with_token(uid, token)
    return token, uid, (cred.get("parameters") or {}).get("short_label", "?")


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
        from qobuz_dl.exceptions import (AuthenticationError, IneligibleError,
                                         InvalidAppIdError,
                                         InvalidAppSecretError)
        from qobuz_dl.qopy import Client
    except ImportError:
        responde(ok=False,
                 erro="o qobuz-dl não está instalado. Rode: stylus qobuz instalar")

    # Primeiro o que a máquina JÁ TEM guardado: é instantâneo, e a raspagem é
    # o pedaço lento e frágil do caminho.
    app_id, segredos, chave = ler_credenciais()
    md5 = hashlib.md5(senha.encode("utf-8")).hexdigest()

    resultado = erro_guardado = None
    if app_id and segredos:
        try:
            resultado = tentar(Client, app_id, segredos, email, md5)
        except (InvalidAppIdError, InvalidAppSecretError) as e:
            # O caso que o comentário lá em cima previa e o código nunca
            # tratava: o Qobuz TROCOU o app_id, o que estava guardado azedou,
            # e a mensagem em inglês ("Invalid app id") se lê como senha
            # errada. Não é. O conserto é jogar fora e raspar de novo — e
            # como isso nunca acontecia, uma máquina com app_id velho não
            # tinha caminho nenhum de volta.
            erro_guardado = e
            app_id = None
        except AuthenticationError:
            resultado = "senha"
        except IneligibleError:
            resultado = "sem-assinatura"
        except Exception as e:                           # noqa: BLE001
            responde(ok=False, erro=str(e) or type(e).__name__)

    if resultado is None:
        novo = raspar_bundle(Bundle)
        if novo is None:
            responde(ok=False, erro=(
                "o Qobuz não respondeu a tempo (é a página do player deles que "
                "está lenta, não a sua conexão). Tente de novo em alguns "
                "minutos — ou entre uma vez pela interface web, que guarda o "
                "mesmo dado:  stylus qobuz abrir"))
        app_id, segredos, chave_nova = novo
        chave = chave_nova or chave
        try:
            resultado = tentar(Client, app_id, segredos, email, md5)
        except AuthenticationError:
            resultado = "senha"
        except IneligibleError:
            resultado = "sem-assinatura"
        except (InvalidAppIdError, InvalidAppSecretError) as e:
            # Raspado agora e ainda recusado: aí não é credencial velha, é o
            # Qobuz que mudou o formato do bundle. Diz isso, em vez de repetir
            # "senha errada" para quem digitou a senha certa.
            responde(ok=False, erro=(
                "o Qobuz aceitou a conta mas recusou a chave do aplicativo "
                "(%s). Costuma ser o player web deles ter mudado; o "
                "`stylus qobuz instalar` traz a versão nova do qobuz-dl."
                % (erro_guardado or e).__class__.__name__))
        except Exception as e:                           # noqa: BLE001
            responde(ok=False, erro=str(e) or type(e).__name__)

    if resultado == "senha":
        # 401 da API com app_id válido: Qobuz recusou O QUE FOI DIGITADO, e
        # quase nunca é a digitação. Conta criada pelo Google/Apple ou pela
        # loja de aplicativo NÃO TEM senha de site — não existe senha que
        # "confira". O caminho que funciona para ESSAS contas é o navegador,
        # que aceita o Google/Apple do jeito que a conta pede.
        responde(ok=False, erro=(
            "e-mail ou senha não conferem. Se esta conta foi criada pelo "
            "Google, pela Apple ou pela loja de aplicativo, ela não tem "
            "senha de site e este login nunca vai aceitar — rode "
            "`stylus qobuz abrir` e entre pelo navegador uma vez: é o "
            "mesmo resultado e guarda o token."))
    if resultado == "sem-assinatura":
        responde(ok=False,
                 erro="esta conta do Qobuz não tem assinatura de streaming")

    token, user_id, selo = resultado
    guardar(email=email, password=md5, app_id=str(app_id),
            secrets=",".join(segredos), private_key=chave,
            user_auth_token=token, user_id=user_id)
    responde(ok=True, assinatura=selo or "?", email=email)


if __name__ == "__main__":
    main()
