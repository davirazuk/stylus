#!/usr/bin/env python3
"""Por que o Qobuz não funciona NESTA máquina — uma resposta por etapa.

POR QUE ISTO EXISTE
-------------------
O `stylus qobuz` dizia "conta: entrada por token" olhando o config.ini com um
grep. Isso responde "existe um token gravado", que não é a pergunta: numa
segunda máquina o token estava lá, gravado, e nenhuma busca funcionava. A
única resposta útil é a que PERGUNTA ao Qobuz, e é a que faltava.

São seis etapas, na ordem em que uma depende da outra, e cada uma diz o que
fazer quando falha. Sai texto para o terminal, ou JSON com --json para quem
desenha.
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qobuz_conta import CONF, campo, ler                       # noqa: E402

PRAZO = 25


def com_prazo(fn, prazo=PRAZO):
    """Roda `fn` numa thread com prazo. Devolve (valor, erro, estourou).

    Thread e não `timeout=` do requests: o do requests é POR LEITURA, e um
    servidor que pinga um byte de vez em quando o segura para sempre. Foi
    exatamente assim que o login do Qobuz pendurou por dois minutos.
    """
    caixa = {}

    def _correr():
        try:
            caixa["v"] = fn()
        except Exception as e:                           # noqa: BLE001
            caixa["e"] = e

    t = threading.Thread(target=_correr, daemon=True)
    t.start()
    t.join(prazo)
    if t.is_alive():
        return None, None, True
    return caixa.get("v"), caixa.get("e"), False


def etapas():
    passos = []

    def diz(nome, bem, texto, conserto=""):
        passos.append({"etapa": nome, "ok": bool(bem), "texto": texto,
                       "conserto": conserto})
        return bem

    # 1 ─ o pacote
    try:
        import qobuz_dl
        versao = getattr(qobuz_dl, "__version__", "")
        diz("qobuz-dl", True, "instalado" + (" %s" % versao if versao else ""))
    except ImportError:
        diz("qobuz-dl", False, "não está instalado",
            "stylus qobuz instalar")
        return passos

    # 2 ─ o arquivo
    if not os.path.isfile(CONF):
        diz("config.ini", False, "não existe", "stylus qobuz entrar")
        return passos
    modo = oct(os.stat(CONF).st_mode & 0o777)[2:]
    diz("config.ini", True, "%s (modo %s)" % (CONF, modo))

    cfg = ler()
    app_id = campo(cfg, "app_id")
    segredos = [x for x in campo(cfg, "secrets").split(",") if x.strip()]
    uid = campo(cfg, "user_id")
    token = campo(cfg, "user_auth_token")

    # 3 ─ a chave do aplicativo (não é sua: é a do player web do Qobuz)
    if not (app_id and segredos):
        diz("chave do aplicativo", False,
            "faltando — sem ela nem o login começa", "stylus qobuz entrar")
        return passos
    diz("chave do aplicativo", True,
        "app_id %s, %d segredo(s)" % (app_id, len(segredos)))

    # 4 ─ a conta gravada
    if not (uid and token):
        diz("conta", False,
            "o arquivo existe mas não tem conta dentro", "stylus qobuz entrar")
        return passos
    diz("conta", True, "id %s, token guardado" % uid)

    # 5 ─ o Qobuz ACEITA esta conta? (a pergunta que faltava)
    from qobuz_dl.qopy import Client
    import logging
    logging.getLogger("qobuz_dl").setLevel(logging.ERROR)
    logging.getLogger("qopy").setLevel(logging.ERROR)

    def _entrar():
        cl = Client(None, None, app_id, segredos, skip_auth=True)
        cl.auth_with_token(uid, token)
        return cl

    cl, erro, estourou = com_prazo(_entrar)
    if estourou:
        diz("o Qobuz responde?", False,
            "não respondeu em %ds (rede, ou o Qobuz fora do ar)" % PRAZO,
            "tente de novo daqui a pouco")
        return passos
    if erro is not None:
        nome = type(erro).__name__
        if "AppId" in nome or "AppSecret" in nome:
            # O caso da segunda máquina: token gravado, e mesmo assim nada
            # funciona, porque a chave do APLICATIVO envelheceu. Entrar de
            # novo raspa uma nova.
            diz("o Qobuz responde?", False,
                "a chave do aplicativo azedou (%s)" % nome,
                "stylus qobuz entrar — ele raspa uma nova")
        elif "Auth" in nome:
            diz("o Qobuz responde?", False, "o token não vale mais",
                "stylus qobuz entrar")
        elif "Ineligible" in nome:
            diz("o Qobuz responde?", False,
                "a conta não tem assinatura de streaming",
                "assine em qobuz.com — daqui não dá")
        else:
            diz("o Qobuz responde?", False, "%s: %s" % (nome, erro),
                "stylus qobuz entrar")
        return passos
    diz("o Qobuz responde?", True,
        "sim — assinatura %s" % (getattr(cl, "label", "") or "?"))

    # 6 ─ e ENTREGA música? Autenticar e conseguir o endereço de uma faixa são
    #     coisas diferentes: a segunda precisa do segredo certo, e é aí que
    #     uma chave velha aparece. Sem esta etapa o estado dizia "tudo bem" e
    #     tocar não funcionava.
    def _favoritos():
        return cl.api_call("favorite/getUserFavorites", type="albums",
                           offset=0, limit=1, sec=cl.sec)

    dados, erro, estourou = com_prazo(_favoritos, 15)
    if estourou or erro is not None:
        diz("entrega música?", False,
            "não" if estourou else "%s" % erro,
            "stylus qobuz entrar")
        return passos
    total = ((dados or {}).get("albums") or {}).get("total", "?")
    diz("entrega música?", True, "sim — %s discos favoritados" % total)
    return passos


def main():
    passos = etapas()
    if "--json" in sys.argv:
        print(json.dumps({"passos": passos}, ensure_ascii=False))
        raise SystemExit(0 if all(p["ok"] for p in passos) else 1)
    largura = max((len(p["etapa"]) for p in passos), default=10)
    for p in passos:
        marca = "\033[1;32m✓\033[0m" if p["ok"] else "\033[1;31m✗\033[0m"
        print("  %s %-*s  %s" % (marca, largura, p["etapa"], p["texto"]))
        if not p["ok"] and p["conserto"]:
            print("    %*s  → %s" % (largura, "", p["conserto"]))
    raise SystemExit(0 if all(p["ok"] for p in passos) else 1)


if __name__ == "__main__":
    main()
