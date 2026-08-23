"""Onde fica a coleção — a MESMA resposta para todas as ferramentas.

POR QUE ISTO EXISTE
-------------------
Nove ferramentas deste diretório traziam o caminho da coleção escrito à mão,
e escrito com a casa de uma pessoa específica dentro:

    ROOT = "/home/davirazuk/Músicas"
    LIB  = "/home/davirazuk/Músicas/Fortnite Balls"

Em qualquer outro computador esse caminho não existe — no medium ao vivo o
usuário é `stylus`, então `/home/davirazuk` nunca existe — e as ferramentas
que o README promete (`stylus covers`, `stylus gaps`, `stylus tags`,
`stylus check`, `stylus suggest`) não achavam disco nenhum. Não davam erro
claro: varriam uma pasta inexistente e diziam que estava tudo bem.

O sistema já sabe a resposta: `stylus library` a define, o first-run.sh a
descobre sozinho, e o vinyl.library_root() a lê. Esta função é só a ponte,
para que nenhuma ferramenta precise repetir — e errar — essa decisão.
"""
import os
import sys


def _com_o_deck_no_caminho():
    """O vinyl mora em /usr/share/stylus/deck, não aqui.

    Quem chama pelo `stylus` já recebe o PYTHONPATH pronto; quem roda o .py
    direto, não. As duas formas têm que funcionar, então o caminho é
    acrescentado aqui — o de instalação e o relativo a este arquivo, que é o
    que serve para rodar do repositório sem instalar nada.
    """
    aqui = os.path.dirname(os.path.abspath(__file__))
    for p in ("/usr/share/stylus/deck",
              os.path.join(os.path.dirname(aqui), "deck")):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def raiz():
    """A pasta da coleção, ou o padrão sensato quando nada foi definido."""
    _com_o_deck_no_caminho()
    try:
        import vinyl
        r = vinyl.library_root()
        if r:
            return r
    except Exception:                      # noqa: BLE001
        pass
    # Sem o vinyl (dependência faltando, ferramenta rodando fora do sistema),
    # ainda assim NÃO se inventa a casa de alguém: respeita a variável, senão
    # o lugar padrão do XDG.
    return os.path.expanduser(
        os.environ.get("STYLUS_LIBRARY")
        or os.environ.get("XDG_MUSIC_DIR")
        or "~/Music")
