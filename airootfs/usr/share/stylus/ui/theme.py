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


_shadow_cache = {}

def shadow_card(surf, rect, radius=12):
    """Sombra sob a capa — POUSADA, não colada. Cacheada por tamanho."""
    key = (rect.w, rect.h, radius)
    layers = _shadow_cache.get(key)
    if layers is None:
        layers = []
        for i, alpha in ((10, 22), (6, 36), (3, 52), (1, 70)):
            s = pygame.Surface((rect.w + i * 2, rect.h + i * 2), pygame.SRCALPHA)
            pygame.draw.rect(s, (0, 0, 0, alpha), s.get_rect(),
                             border_radius=radius + i)
            layers.append((i, s))
        # cap cache at 32 entries to avoid unbounded growth
        if len(_shadow_cache) > 32:
            _shadow_cache.clear()
        _shadow_cache[key] = layers
    for i, s in layers:
        surf.blit(s, (rect.x - i, rect.y - i + 3))


# ── partículas atmosféricas ────────────────────────────────────────────────
# Poeira virtual que flutua no fundo — dá profundidade sem chamar atenção.
# Cada partícula é um ponto âmbar que nasce, flutua, e morre.
class Particles:
    """Poeira atmosférica — pontos âmbar que flutuam no fundo."""

    def __init__(self, w, h, n=0):
        # scale particle count to screen area (baseline: 24 at 1280x720)
        if n <= 0:
            n = max(8, min(40, int(w * h / 38400)))
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

# ═══════════════════════════════════════════════════════════════════════════
#  O DISCO
# ═══════════════════════════════════════════════════════════════════════════
# A tela AGORA parada mostrava oito circunferências finas e uma linha girando
# em volta do centro. Lia como um radar, não como um disco — e a linha era
# errada de um jeito que quem tem toca-discos vê na hora: um braço não gira
# em torno do eixo, ele pivota de um ponto FORA do disco.
#
# Isto aqui é um disco de verdade em fósforo, não em madeira (§5.5): corpo,
# sulcos, os intervalos entre as faixas que dá para contar de longe, bolacha
# no meio e furo do eixo. Nada de textura imitando vinil.
#
# As proporções são as mesmas que o deck usa em deck/vinyl.py, para os dois
# desenhos não descreverem discos diferentes.
LABEL_R   = 0.34      # bolacha do meio
GROOVE_I  = 0.42      # onde os sulcos começam
GROOVE_O  = 0.96      # e onde acabam
SPINDLE_R = 0.035     # o furo

# Onde ficam os intervalos entre faixas, na fração do raio. São eles que
# fazem um disco parecer um disco a três metros: dá para CONTAR as músicas.
_INTERVALOS = (0.52, 0.63, 0.71, 0.80, 0.885)

_disco_cache = {}


def disco(raio):
    """O disco parado, pronto para desenhar. Superfície com alfa, em cache.

    Desenhado no dobro do tamanho e reduzido: o pygame não suaviza
    circunferência, e sulco serrilhado a 60 quadros por segundo cintila.
    Como o resultado é sempre igual, o custo é pago uma vez só.
    """
    raio = int(raio)
    if raio < 8:
        raio = 8
    pronto = _disco_cache.get(raio)
    if pronto is not None:
        return pronto

    e = 2                                   # fator de superamostragem
    lado = raio * 2 * e
    d = pygame.Surface((lado, lado), pygame.SRCALPHA)
    c = lado // 2
    R = raio * e

    # corpo: quase o fundo, só o suficiente para virar objeto
    pygame.draw.circle(d, (*INK_SOFT, 255), (c, c), R)
    # a borda do disco
    pygame.draw.circle(d, (*lerp(INK_LIFT, AMBER_DIM, 0.30), 255), (c, c), R, e)

    # os sulcos — grafite, não âmbar
    dentro, fora = int(R * GROOVE_I), int(R * GROOVE_O)
    passo = max(2 * e, (fora - dentro) // 60)
    for rr in range(dentro, fora, passo):
        f = (rr - dentro) / max(1, fora - dentro)
        # um pouco mais claros na borda, onde a luz pegaria primeiro
        cor = lerp(INK_LIFT, LINE, 0.15 + 0.40 * f)
        pygame.draw.circle(d, (*cor, 150), (c, c), rr, e)

    # os intervalos entre as faixas. É AQUI que o âmbar entra, e só aqui:
    # é a única informação que o disco parado carrega — quantas faixas tem.
    for frac in _INTERVALOS:
        rr = int(R * frac)
        if dentro < rr < fora:
            pygame.draw.circle(d, (*AMBER_DIM, 150), (c, c), rr, e)

    # a bolacha do meio — escura, com o aro âmbar
    lr = int(R * LABEL_R)
    pygame.draw.circle(d, (*lerp(INK, AMBER_DIM, 0.07), 255), (c, c), lr)
    pygame.draw.circle(d, (*AMBER_DIM, 190), (c, c), lr, e)
    # a faixa lisa entre o último sulco e a bolacha (o fim do lado)
    pygame.draw.circle(d, (*lerp(INK_LIFT, AMBER_DIM, 0.18), 160),
                       (c, c), int(R * (GROOVE_I - 0.03)), e)

    # o furo do eixo
    pygame.draw.circle(d, (*INK, 255), (c, c), max(e, int(R * SPINDLE_R)))

    d = pygame.transform.smoothscale(d, (raio * 2, raio * 2))
    if len(_disco_cache) > 6:
        _disco_cache.clear()
    _disco_cache[raio] = d
    return d
