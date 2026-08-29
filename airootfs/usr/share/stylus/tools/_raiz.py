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


# Sem o vinyl, a mesma lista escrita à mão — e SÓ aqui.
_EXT_PADRAO = (".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".aac",
               ".wma", ".shn", ".ape")


def audio_ext():
    """O que conta como arquivo de música — a MESMA resposta para todas.

    Mesmo motivo do `raiz()` acima, e o mesmo estrago. Havia QUATRO listas
    diferentes aqui dentro: o `check_library` e o `discover` traziam oito
    extensões (com .shn e sem .wma), o `extract_covers` e o `embed_metadata`
    paravam em .flac e .mp3, e o `make_new_playlist` e o `suggest_playlists`
    idem. Numa coleção em ALAC, Opus ou Vorbis — que é o que sai de um
    celular e de metade das lojas — essas quatro ferramentas não achavam
    faixa nenhuma e não davam erro: diziam que estava tudo bem.

    A resposta é a do `vinyl.AUDIO_EXT`, que é quem monta a estante.
    """
    _com_o_deck_no_caminho()
    try:
        import vinyl
        ext = tuple(getattr(vinyl, "AUDIO_EXT", ()) or ())
        if ext:
            return ext
    except Exception:                      # noqa: BLE001
        pass
    return _EXT_PADRAO


# Sem o vinyl, a mesma lista de novo — e SÓ aqui.
_CAPA_PADRAO = ("cover", "folder", "front", "capa", "albumart", "album")
_CAPA_EXT = (".jpg", ".jpeg", ".png")


def find_cover(pasta, entries=None):
    """A capa desta pasta — a MESMA escolha que a estante e o deck fazem.

    Havia QUATRO listas de nome de capa no sistema, e elas discordavam: duas
    conheciam `folder.png`, as outras duas `cover.jpeg`. E as duas que
    desenham — o deck e a estante — comparavam o nome EXATO: numa coleção
    passada por um Windows, que guarda `Folder.jpg` e `Cover.jpg` com
    maiúscula, o deck ficava sem capa nenhuma.
    """
    _com_o_deck_no_caminho()
    try:
        import vinyl
        return vinyl.find_cover(pasta, entries)
    except Exception:                      # noqa: BLE001
        pass
    if entries is None:
        try:
            entries = os.listdir(pasta)
        except OSError:
            return None
    porordem = {}
    for e in entries:
        if e.lower().endswith(_CAPA_EXT):
            porordem.setdefault(e.lower(), e)
    for nome in _CAPA_PADRAO:
        for ext in _CAPA_EXT:
            if nome + ext in porordem:
                return os.path.join(pasta, porordem[nome + ext])
    return None
