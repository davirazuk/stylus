#!/usr/bin/env python3
"""O arquivo de conta do Qobuz — um só lugar que sabe ler e gravar.

O `~/.config/qobuz-dl/config.ini` é lido pelo login, pela busca, pela
transmissão e pelo próprio qobuz-dl. Cada um tinha o seu jeito de abrir, e
duas coisas se perdiam no caminho:

* **O modo.** O arquivo guarda um `user_auth_token`, que é acesso à conta de
  streaming de alguém. Quem o criou primeiro foi a interface web do qobuz-dl,
  com o 0644 padrão — e nesta máquina ele estava assim, legível por qualquer
  usuário, sem nada nunca ter apertado. Gravar 0600 no login novo não conserta
  arquivo que já existe; por isso `ler_credenciais` também APERTA o que
  encontra frouxo.
* **A janela.** Entre criar o arquivo e apertar a permissão existe um
  instante, curto mas real, em que o token está legível. Por isso se escreve
  num temporário que JÁ NASCE 0600, e só então se renomeia por cima.
"""
import configparser
import os
import stat

CONF = os.path.expanduser("~/.config/qobuz-dl/config.ini")


def _apertar(caminho):
    """0600, se ainda não estiver. Silencioso: não é para atrapalhar ninguém."""
    try:
        modo = stat.S_IMODE(os.stat(caminho).st_mode)
        if modo & (stat.S_IRWXG | stat.S_IRWXO):
            os.chmod(caminho, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def ler(caminho=None):
    """O config.ini como ConfigParser. Vazio quando não existe."""
    caminho = caminho or CONF
    cfg = configparser.ConfigParser()
    if os.path.isfile(caminho):
        _apertar(caminho)
        try:
            cfg.read(caminho, encoding="utf-8")
        except Exception:                                # noqa: BLE001
            return configparser.ConfigParser()
    return cfg


def campo(cfg, chave):
    return cfg.get("DEFAULT", chave, fallback="").strip()


def ler_credenciais(caminho=None):
    """(app_id, [segredos], private_key) do que está guardado."""
    cfg = ler(caminho)
    segredos = [x.strip() for x in campo(cfg, "secrets").split(",") if x.strip()]
    return campo(cfg, "app_id"), segredos, campo(cfg, "private_key")


# Havia aqui um `tem_conta()` — "dá para falar com o Qobuz com o que está
# gravado?" — e ele NUNCA foi chamado. Saiu, e o motivo vale escrever: ele
# era a TERCEIRA resposta para essa pergunta e discordava das outras duas.
#
# Exigia app_id, segredos, user_id e token, o que reprova quem entrou pela
# interface web com e-mail e senha — que é como quase todo mundo entra, e é
# justamente o caso que a tela cheia teve que consertar (ela dizia "a loja
# ainda não está ligada" numa máquina perfeitamente logada). E, do outro
# lado, ficava muito aquém do `qobuz_estado.py`, que é onde essa pergunta
# mora de verdade: lá se PERGUNTA ao Qobuz, em seis etapas, porque "existe um
# token gravado" nunca foi a mesma coisa que "isto funciona".
#
# Função escrita e nunca chamada costuma ser um recurso inteiro faltando.
# Quando não é, é uma opinião a mais sobre algo que já tem dono.


# Só quando o arquivo é novo: um valor destes já escolhido é escolha da
# pessoa, e sobrescrever seria desfazê-la.
PADROES = (("folder_format", "{artist}/{album}"),
           ("track_format", "{tracknumber} - {tracktitle}"),
           ("default_limit", "20"),
           ("no_m3u", "false"),
           ("albums_only", "false"),
           ("no_fallback", "false"),
           ("og_cover", "false"),
           ("embed_art", "true"),
           ("no_cover", "false"),
           ("no_database", "false"))


def guardar(caminho=None, **campos):
    """Troca só o que é de conta e regrava, 0600, sem janela aberta."""
    caminho = caminho or CONF
    cfg = ler(caminho)
    d = cfg["DEFAULT"]
    for k, v in campos.items():
        d[k] = str(v)
    for k, v in PADROES:
        d.setdefault(k, v)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".novo"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                 stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        cfg.write(fh)
    os.replace(tmp, caminho)
    return caminho
