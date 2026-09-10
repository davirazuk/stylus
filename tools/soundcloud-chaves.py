#!/usr/bin/env python3
"""O client_id do SoundCloud -> cartão do Vita.

Mesmo papel do `qobuz-chaves.py`, e pelo mesmo motivo: o aparelho não pode ser
o lugar onde se descobre uma credencial.

O client_id do SoundCloud não se registra em lugar nenhum — ele está publicado
nos bundles JavaScript do próprio site, e pegá-lo é baixar ~1,2 MB e varrer.
Fazer isso em C, dentro do app, seria escrever uma varredura de expressão
regular sobre um megabyte às cegas, num aparelho sem depurador, para uma coisa
que este PC faz em dois segundos. E é a MESMA conta que fez as chaves do Qobuz
virarem `qobuz.config` em vez de uma tela pedindo 32 dígitos no teclado.

Roda a cada `pro-cartao.sh`, então o cartão é reabastecido toda vez que o dono
instala uma versão nova — que é mais frequente do que o SoundCloud troca o
client_id.

NÃO É SEGREDO DE CONTA: é a credencial do APLICATIVO, a mesma que o site
entrega a qualquer navegador que abra soundcloud.com. Não há login, não há
token de usuário, não há nada aqui que identifique o dono — por isso este
arquivo pode ser gravado sem as cautelas do `qobuz.config`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    cartao = sys.argv[1] if len(sys.argv) > 1 else "/run/media/davirazuk/VITASD"
    if not os.path.isdir(cartao):
        sys.exit(f"não achei o cartão em {cartao}")

    try:
        import soundcloud_api
        cid = soundcloud_api.client_id()
    except Exception as e:
        # SEM REDE NÃO É MOTIVO PARA APAGAR O QUE JÁ ESTÁ LÁ. O client_id
        # antigo provavelmente ainda vale; um arquivo vazio no lugar dele
        # transformaria "sem internet agora" em "SoundCloud quebrado".
        print(f"  (não deu para obter o client_id: {e})")
        print("  o que já estiver no cartão continua valendo.")
        return 0

    destino_dir = os.path.join(cartao, "data", "vitastylus")
    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, "soundcloud.config")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(f"client_id={cid}\n")

    print(f"  {destino}")
    print(f"  client_id {len(cid)} chars — a loja do SoundCloud sobe conectada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
