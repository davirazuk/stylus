"""STYLUS — a paleta e o desenho básico da interface.

POR QUE ELA É ASSIM
-------------------
Preto esmagado, âmbar como a ÚNICA cor viva. Tudo o mais recua — o disco
é quem tem cor, a interface é quem dá palco. Quando não tem disco tocando,
o âmbar é o fio que mantém a tela viva. Quando tem, o âmbar desaparece
e deixa a capa falar.

A filosofia: âmbar é fogo, é luz, é calor. Azul é informação. Lavanda é
especial. Verde é ok. Vermelho é alerta. Mas âmbar é a alma — ele aparece
onde a pessoa olha primeiro, onde o sistema está dizendo "estou aqui".
"""
import glob
import math
import os
import random
import time

import pygame

# ── cores ──────────────────────────────────────────────────────────────────
INK        = (7, 8, 11)          # o fundo. quase preto, levemente azul
INK_SOFT   = (16, 18, 25)        # painéis — mais separação do fundo
INK_LIFT   = (26, 30, 40)        # sob cursor — mais claro
LINE       = (52, 58, 72)        # divisórias visíveis a 3m (antes 1.22:1)
TEXT       = (232, 236, 245)     # principal — branco limpo
TEXT_DIM   = (138, 149, 170)     # secundário — legível
TEXT_FAINT = (118, 128, 148)     # terciário — WCAG 4.5:1, não invisível

# âmbar: a alma do sistema. ÚNICA cor viva.
AMBER      = (240, 160, 48)      # quente, vivo, o fio que prende o olhar
AMBER_DIM  = (192, 128, 32)      # âmbar abafado para segundos planos
AMBER_GLOW = (255, 200, 80)      # âmbar brilhante para brilhos e glows

# cores de informação — secundárias, nunca competem com o âmbar
BLUE       = (91, 206, 250)      # informação, links, dados
LAV        = (183, 160, 255)     # especial, destaque suave
GREEN      = (126, 217, 158)     # ok, sucesso, conectado
RED        = (238, 122, 130)     # erro, alerta, desconectado
PINK       = (245, 169, 184)     # rare — used sparingly

# aliases para compatibilidade com código existente
BLUE_LEGACY = BLUE

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
    key = (ch, size)
    if key in _tem:
        return _tem[key]
    try:
        m = font(size).metrics(ch)
        ok = bool(m) and m[0] is not None
    except Exception:                     # noqa: BLE001 — fonte estranha não derruba a tela
        ok = False
    _tem[key] = ok
    return ok


def icon(ch, alt="•"):
    """O ícone quando a fonte o tem; senão um ponto. Coluna vazia = escolha;
    coluna de caixinhas = sistema quebrado. Ponto nunca quebra."""
    # tenta Nerd, depois fallback para ponto simples — nunca caixinha
    if has_glyph(ch):
        return ch
    # fallback: tenta Material ponto, senão • genérico
    return alt if alt and has_glyph(alt) else "•"


# ── desenho ────────────────────────────────────────────────────────────────
def text(surf, s, pos, size=20, colour=TEXT, bold=False, anchor="topleft",
         maxw=None):
    """Escreve, cortando com reticências em vez de vazar do painel."""
    f = font(size, bold)
    if maxw and f.size(s)[0] > maxw:
        # binário, não O(n²) — coleção de 400 discos com nome japonês longo não janka
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi + 1)//2
            if f.size(s[:mid] + "…")[0] <= maxw:
                lo = mid
            else:
                hi = mid - 1
        s = s[:lo] + "…"
    img = f.render(s, True, colour)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def panel(surf, rect, colour=INK_SOFT, radius=14, border=None, border_width=None):
    pygame.draw.rect(surf, colour, rect, border_radius=radius)
    if border:
        # 1px em 4K é 0.2mm, some — escala com a largura da tela
        bw = border_width if border_width is not None else max(1, round(surf.get_width() / 1600))
        pygame.draw.rect(surf, border, rect, width=bw, border_radius=radius)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def shadow_card(surf, rect, radius=12):
    """Sombra sob a capa — POUSADA, não colada. Blur escalado para não ser escada."""
    # 4 camadas escalonadas com alpha mais forte — visível sobre INK mesmo
    for i, alpha in ((10, 22), (6, 36), (3, 52), (1, 70)):
        s = pygame.Surface((rect.w + i * 2, rect.h + i * 2), pygame.SRCALPHA)
        pygame.draw.rect(s, (0, 0, 0, alpha), s.get_rect(),
                         border_radius=radius + i)
        surf.blit(s, (rect.x - i, rect.y - i + 3))


# ── partículas atmosféricas ────────────────────────────────────────────────
# Poeira virtual que flutua no fundo — dá profundidade sem chamar atenção.
# Cada partícula é um ponto âmbar que nasce, flutua, e morre.
class Particles:
    """Poeira atmosférica — pontos âmbar que flutuam no fundo."""

    def __init__(self, w, h, n=24):
        self.w, self.h = w, h
        self.particles = []
        for _ in range(n):
            self.particles.append({
                "x": random.uniform(0, w),
                "y": random.uniform(0, h),
                "vx": random.uniform(-0.15, 0.15),
                "vy": random.uniform(-0.08, -0.02),
                "r": random.uniform(1, 3),
                "alpha": random.uniform(8, 25),
                "life": random.uniform(0, 1),
            })
        # Pré-renderiza os 3 tamanhos possíveis (raio 1, 2, 3) — evita
        # criar Surface por partícula por frame.
        self._cache = {}
        for r_int in (1, 2, 3):
            sz = r_int * 4
            s = pygame.Surface((sz, sz), pygame.SRCALPHA)
            pygame.draw.circle(s, (*AMBER_GLOW, 255), (r_int * 2, r_int * 2), r_int)
            self._cache[r_int] = s

    def update(self, dt):
        """Move as partículas. dt em segundos."""
        for p in self.particles:
            p["x"] += p["vx"] * dt * 60
            p["y"] += p["vy"] * dt * 60
            p["life"] += dt * 0.15
            if p["life"] > 1.0:
                p["life"] = 0.0
                p["x"] = random.uniform(0, self.w)
                p["y"] = self.h + 10
            if p["x"] < -10:
                p["x"] = self.w + 10
            elif p["x"] > self.w + 10:
                p["x"] = -10

    def draw(self, surf):
        """Desenha as partículas. Alpha varia com o ciclo de vida."""
        for p in self.particles:
            life = p["life"]
            if life < 0.1:
                a = int(p["alpha"] * (life / 0.1))
            elif life > 0.8:
                a = int(p["alpha"] * ((1.0 - life) / 0.2))
            else:
                a = int(p["alpha"])
            if a <= 0:
                continue
            r_int = max(1, min(3, int(p["r"])))
            cached = self._cache[r_int]
            cached.set_alpha(a)
            surf.blit(cached, (int(p["x"] - p["r"]), int(p["y"] - p["r"])))


# ── vinheta ────────────────────────────────────────────────────────────────
# Escurecimento suave nas bordas — dá profundidade sem chamá-la.
_vignette_cache = {}

def vignette(surf):
    """Aplica vinheta suave na superfície. Cacheada por tamanho.
    Usa BLEND_RGBA_MULT: o centro é branco (inalterado), bordas pretas (escurecidas)."""
    w, h = surf.get_size()
    key = (w, h)
    if key not in _vignette_cache:
        s = pygame.Surface((w, h))
        s.fill((255, 255, 255))
        cx, cy = w // 2, h // 2
        max_r = (cx * cx + cy * cy) ** 0.5
        for i in range(16):
            r = max_r * (0.55 + i * 0.03)
            val = 255 - int(8 + i * 4)
            pygame.draw.circle(s, (val, val, val), (cx, cy), int(r))
        _vignette_cache[key] = s
    surf.blit(_vignette_cache[key], (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
