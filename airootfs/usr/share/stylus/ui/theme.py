"""STYLUS — a paleta e o desenho básico da interface.

POR QUE ELA É ASSIM
-------------------
Preto esmagado, azul frio, e os acentos em rosa/azul/lavanda saturados por
cima. Não é uma escolha de estilo genérica: é a mesma direção do resto do
sistema — a capa do disco é a única coisa colorida na tela, e todo o resto
recua para trás dela. Uma interface de música que compete com a arte da capa
está fazendo a coisa errada.

Os acentos ficam em saturação cheia de propósito, para lerem como néon sobre
preto e não como pastel sobre pastel.
"""
import glob
import os

import pygame

# ── cores ──────────────────────────────────────────────────────────────────
INK        = (7, 8, 11)          # o fundo. quase preto, levemente azul
INK_SOFT   = (13, 15, 20)        # painéis
INK_LIFT   = (20, 23, 30)        # o que está sob o cursor
LINE       = (32, 36, 46)        # divisórias
TEXT       = (226, 231, 240)
TEXT_DIM   = (126, 137, 156)
TEXT_FAINT = (74, 82, 96)

BLUE       = (91, 206, 250)      # o acento principal
PINK       = (245, 169, 184)
LAV        = (183, 160, 255)
GREEN      = (126, 217, 158)
AMBER      = (240, 189, 118)
RED        = (238, 122, 130)

# ── tipos ──────────────────────────────────────────────────────────────────
_FONT_DIRS = ("/usr/share/fonts/TTF", "/usr/share/fonts/truetype",
              "/usr/share/fonts", os.path.expanduser("~/.local/share/fonts"))
_PREFER = ("JetBrainsMono*NerdFont-Regular.ttf", "JetBrainsMono*NerdFont-*.ttf",
           "JetBrainsMono*.ttf", "NotoSans-Regular.ttf", "DejaVuSans.ttf")
_cache = {}


def _find_font():
    for pat in _PREFER:
        for d in _FONT_DIRS:
            hits = sorted(glob.glob(os.path.join(d, "**", pat), recursive=True))
            if hits:
                return hits[0]
    return None


_FONT_FILE = None


def font(size, bold=False):
    """Uma fonte, em cache. Chamar isto num laço de desenho é normal."""
    global _FONT_FILE
    key = (size, bold)
    if key in _cache:
        return _cache[key]
    if _FONT_FILE is None:
        _FONT_FILE = _find_font() or ""
    if _FONT_FILE:
        f = pygame.font.Font(_FONT_FILE, size)
        f.set_bold(bold)
    else:
        f = pygame.font.SysFont("dejavusansmono,monospace", size, bold=bold)
    _cache[key] = f
    return f


_tem = {}


def has_glyph(ch, size=22):
    """A fonte escolhida tem ESTE caractere?

    Os ícones do trilho são pontos da área de uso privado do Nerd Font. Numa
    máquina onde a fonte não entrou — ou entrou numa versão que moveu a faixa,
    como o Nerd Fonts fez com os Material Design entre a v2 e a v3 — o pygame
    não avisa nada: ele desenha o retângulo vazio da fonte, e a tela fica com
    uma coluna de caixinhas onde deveria haver ícones.

    `metrics()` devolve None na posição de um caractere sem glifo, e é a única
    forma honesta de perguntar isso antes de desenhar.
    """
    if ch in _tem:
        return _tem[ch]
    try:
        m = font(size).metrics(ch)
        ok = bool(m) and m[0] is not None
    except Exception:                     # noqa: BLE001 — fonte estranha não derruba a tela
        ok = False
    _tem[ch] = ok
    return ok


def icon(ch, alt=""):
    """O ícone quando a fonte o tem; senão o que se pôs no lugar (em geral
    nada). Uma coluna vazia lê como escolha; uma coluna de caixinhas lê como
    sistema quebrado."""
    return ch if has_glyph(ch) else alt


# ── desenho ────────────────────────────────────────────────────────────────
def text(surf, s, pos, size=20, colour=TEXT, bold=False, anchor="topleft",
         maxw=None):
    """Escreve, cortando com reticências em vez de vazar do painel.

    Cortar é responsabilidade de quem desenha, não de quem chama: metade dos
    nomes de disco de uma coleção de verdade são longos demais para qualquer
    largura que se escolha, e um nome vazando por cima do vizinho é o defeito
    mais fácil de produzir numa grade.
    """
    f = font(size, bold)
    if maxw and f.size(s)[0] > maxw:
        while s and f.size(s + "…")[0] > maxw:
            s = s[:-1]
        s += "…"
    img = f.render(s, True, colour)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def panel(surf, rect, colour=INK_SOFT, radius=14, border=None):
    pygame.draw.rect(surf, colour, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surf, border, rect, width=1, border_radius=radius)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def shadow_card(surf, rect, radius=12):
    """Uma sombra barata sob uma capa, para ela parecer estar POUSADA.

    Sem isto a grade lê como um mosaico de imagens; com isto lê como objetos
    numa prateleira, que é a diferença que interessa aqui.
    """
    for i, alpha in ((6, 26), (4, 34), (2, 44)):
        s = pygame.Surface((rect.w + i * 2, rect.h + i * 2), pygame.SRCALPHA)
        pygame.draw.rect(s, (0, 0, 0, alpha), s.get_rect(),
                         border_radius=radius + i)
        surf.blit(s, (rect.x - i, rect.y - i + 2))
