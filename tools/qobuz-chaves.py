#!/usr/bin/env python3
"""Leva as chaves do Qobuz do PC para o cartão, sem ninguém digitar nada.

    ./tools/qobuz-chaves.py [/caminho/do/cartao]

POR QUE ISTO EXISTE: a tela de Qobuz do app pede app_id, segredo e e-mail, e
pedir isso NO VITA significa digitar um app_id e um segredo de 32 dígitos
hexadecimais no teclado da tela — com o analógico, uma letra por vez. Ninguém
faz isso duas vezes, e a prova é que o cartão nunca teve um qobuz.config: a
tela estava lá, montada, e o Qobuz simplesmente nunca foi usado.

As chaves já existem neste PC, em ~/.config/qobuz-dl/config.ini, e são as
mesmas. Copiá-las é o passo que faltava.

Isto NÃO fere o "no pc things": o PC já está envolvido no dia em que se copia
o VPK para o cartão, e é só nesse dia. Depois disso o aparelho busca, baixa e
toca sozinho — que é o pedido de verdade.

NUNCA imprime o valor de uma chave, e NUNCA escreve chave dentro do
repositório: o destino é o cartão, que não é versionado.
"""

import configparser
import os
import sys

ORIGEM = os.path.expanduser("~/.config/qobuz-dl/config.ini")
MP3 = 5  # QB_MP3; ele prefere MP3 — 1 GB de cartão rende bem mais


def lista_de_segredos(bruto):
    """O qobuz-dl guarda `secrets` como repr de lista Python
    (["abc","def"]); o app quer uma lista separada por vírgula.

    São VÁRIOS de propósito: o Qobuz publica mais de um segredo por app_id e
    só um assina, e qual muda com o tempo. Guardar um só é guardar "funcionou
    no dia em que eu configurei" — o qobuz.c tenta todos, então mande todos.
    """
    s = (bruto or "").strip()
    for c in "[]()":
        s = s.replace(c, "")
    partes = []
    for p in s.split(","):
        p = p.strip().strip("'\"").strip()
        if p:
            partes.append(p)
    return ",".join(partes)


def main():
    cartao = sys.argv[1] if len(sys.argv) > 1 else "/run/media/davirazuk/VITASD"

    if not os.path.isdir(cartao):
        sys.exit(f"não achei o cartão em {cartao}\n  (plugue o SD2VITA e confira o caminho)")
    app_id = segredos = token = email = ""
    if os.path.isfile(ORIGEM):
        cp = configparser.ConfigParser()
        cp.read(ORIGEM)
        d = cp["DEFAULT"]
        app_id = (d.get("app_id") or "").strip()
        segredos = lista_de_segredos(d.get("secrets"))
        token = (d.get("user_auth_token") or "").strip()
        email = (d.get("email") or "").strip().strip("'\"")

    # SEM CONFIG DO QOBUZ-DL, O APP_ID E O SEGREDO AINDA SAEM DE ALGUM LUGAR.
    #
    # Eles são do APLICATIVO, não da pessoa: o próprio tocador web do Qobuz os
    # serve dentro do main.js, e é de lá que o SpotiFLAC os tira. Só o TOKEN é
    # da conta, e esse ninguém raspa.
    #
    # Antes isto morria com "configure o qobuz-dl uma vez" mesmo quando faltava
    # só a metade que dá para ir buscar — e o cartão ficava sem qobuz.config,
    # que é a tela pedindo um segredo de 32 dígitos DIGITADO no teclado do
    # Vita. Ver o pedido nº 2 do dono.
    if not app_id or not segredos:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import qobuz_api
        a, sgr, de_onde = qobuz_api.chaves(preferir_config=False)
        if not a or not sgr:
            sys.exit(f"faltam app_id/segredo e não deu para buscá-los: {de_onde}")
        app_id = app_id or a
        # `chaves()` devolve LISTA (só um dos segredos assina — ver a nota
        # lá); o cartão quer a mesma string separada por vírgula que o
        # `lista_de_segredos` produz, porque o qobuz.c tenta um por um.
        segredos = segredos or ",".join(sgr)
        print(f"  (app_id/segredo vieram de: {de_onde})")

    if not token:
        sys.exit("falta o token da CONTA — é o único pedaço que não dá para\n"
                 "  buscar sozinho. Entre uma vez no Qobuz e deixe-o em\n"
                 f"  {ORIGEM}")

    destino_dir = os.path.join(cartao, "data", "vitastylus")
    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, "qobuz.config")

    # 0600: o cartão é exFAT e não guarda modo, mas se um dia o destino for
    # outra coisa, o arquivo não nasce legível para todo mundo.
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"app_id={app_id}\n")
        f.write(f"app_secret={segredos}\n")
        f.write(f"email={email}\n")
        f.write(f"token={token}\n")
        f.write(f"formato={MP3}\n")

    # o que se imprime é o TAMANHO, nunca o valor
    print(f"  {destino}")
    print(f"  app_id {len(app_id)} chars · {segredos.count(',') + 1} segredo(s) · "
          f"token {len(token)} chars · formato MP3")
    print("  o app já sobe conectado: nada a digitar no aparelho.")


if __name__ == "__main__":
    main()
