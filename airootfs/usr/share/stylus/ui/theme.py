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
INK_DEEP   = (4, 6, 10)          # um degrau ABAIXO do fundo, para o rofi
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
BLUE_BRIGHT= (127, 215, 255)     # o azul do FOCO — a borda de "o teclado
                                 # está aqui". Mesmo papel que o
                                 # AMBER_GLOW faz para o âmbar.
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



def largura(s, size=20, bold=False):
    """Quanto este texto vai ocupar, em pixels.

    Existe para que dois textos na mesma linha — um à esquerda, outro
    encostado à direita — possam ser separados por uma conta em vez de por um
    número chutado. **Sintoma:** na tela SINAL o nome do conversor ("Meteor
    Lake-P HD Audio Controller Speaker") entrava por cima do "pode trocar de
    taxa": a folga reservada era um `- 300` fixo, e o valor mais largo mede
    ~320 px. Chute contra chute, e o nome do aparelho é o único dos dois que
    varia de máquina para máquina — ou seja, quebrava só na máquina do outro.
    """
    return font(size, bold).size(s)[0]


def paragrafo(surf, s, pos, size=20, colour=TEXT, maxw=600, anchor="topleft",
              bold=False, entrelinha=1.35, limite=6):
    """Escreve em várias linhas, quebrando nos espaços. Devolve a altura.

    O `text()` corta com reticências, que é o certo para um nome de disco
    numa prateleira e o errado para uma frase que explica o que fazer: uma
    mensagem de erro cortada no meio não diz o que estava tentando dizer.
    """
    f = font(size, bold)
    linhas, atual = [], ""
    for palavra in s.split():
        tenta = (atual + " " + palavra).strip()
        if atual and f.size(tenta)[0] > maxw:
            linhas.append(atual)
            atual = palavra
            if len(linhas) >= limite:
                break
        else:
            atual = tenta
    if atual and len(linhas) < limite:
        linhas.append(atual)

    passo = int(size * entrelinha)
    x, y = pos
    if anchor.endswith("center") or anchor == "center":
        # centralizado na horizontal; o `pos` é o topo do bloco
        for i, ln in enumerate(linhas):
            text(surf, ln, (x, y + i * passo), size, colour, bold=bold,
                 anchor="midtop")
    else:
        for i, ln in enumerate(linhas):
            text(surf, ln, (x, y + i * passo), size, colour, bold=bold)
    return len(linhas) * passo

def panel(surf, rect, colour=INK_SOFT, radius=14, border=None, border_width=None):
    pygame.draw.rect(surf, colour, rect, border_radius=radius)
    if border:
        # 1px em 4K é 0.2mm, some — escala com a largura da tela
        bw = border_width if border_width is not None else max(1, round(surf.get_width() / 1600))
        pygame.draw.rect(surf, border, rect, width=bw, border_radius=radius)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def linha_escolhida(surf, rect, radius=9):
    """A linha selecionada de uma lista: painel + a barra âmbar do trilho.

    O trilho da esquerda marca a seção atual com uma barra âmbar, e as listas
    de dentro das telas marcavam a linha escolhida só com um painel cinza um
    pouco mais claro. Duas gramáticas para a mesma ideia — e a cinza é a que
    some numa TV do outro lado do quarto, que é onde este sistema costuma
    estar. §5.5: o âmbar é a única cor viva, e "onde eu estou" é a informação
    mais viva que existe numa tela que se navega com controle.
    """
    panel(surf, rect, INK_LIFT, radius=radius)
    pygame.draw.rect(surf, AMBER, (rect.x, rect.y + 3, 3, rect.h - 6),
                     border_radius=2)


# ── a tecla como objeto ────────────────────────────────────────────────────
def tecla(surf, letra, pos, size=18, anchor="topleft", cor=None):
    """Uma tecla desenhada como TECLA, não como uma letra solta na frase.

    **Sintoma:** a tela da pilha dizia "na estante, s empilha um disco". Isso
    se lê como erro de digitação — falta uma palavra. O `s` era o nome da
    tecla, mas nada na página dizia isso, e o leitor não tem como adivinhar
    que aquela letra é um objeto e não uma palavra mal escrita.

    Desenhar a tecla resolve sem gastar uma palavra a mais, e resolve em
    todo lugar de uma vez: a mesma frase vira "na estante, [S] empilha um
    disco" e não dá para ler errado.

    Devolve o retângulo ocupado, para quem precisa continuar a frase depois.
    """
    cor = cor or AMBER
    f = font(size, bold=True)
    txt = f.render(letra.upper(), True, cor)
    pad_x, pad_y = max(7, size // 2), max(4, size // 5)
    w, h = txt.get_width() + pad_x * 2, txt.get_height() + pad_y * 2
    r = pygame.Rect(0, 0, w, h)
    setattr(r, anchor, pos)
    # A tecla é um objeto com relevo: fundo mais claro que o painel, um fio
    # de luz em cima (a luz da sala bate na quina de cima) e uma borda. É o
    # mesmo raciocínio da capa — num fundo escuro, peso vem de luz.
    pygame.draw.rect(surf, INK_LIFT, r, border_radius=5)
    pygame.draw.rect(surf, lerp(LINE, cor, 0.35), r, width=1, border_radius=5)
    luz = pygame.Surface((r.w - 6, 1), pygame.SRCALPHA)
    luz.fill((255, 255, 255, 30))
    surf.blit(luz, (r.x + 3, r.y + 1))
    surf.blit(txt, txt.get_rect(center=r.center))
    return r


def frase_com_teclas(surf, texto, pos, size=18, colour=TEXT_DIM,
                     anchor="topleft", cor_tecla=None):
    """Escreve uma frase em que `[X]` vira uma tecla desenhada.

        frase_com_teclas(s, "na estante, [S] empilha um disco", ...)

    Existe para que a frase seja escrita uma vez, em português corrido, e o
    desenho da tecla saia de graça — em vez de cada tela ter que medir texto
    à mão para saber onde encaixar o quadradinho.
    """
    import re as _re
    pedacos = [p for p in _re.split(r"(\[[^\]]{1,6}\])", texto) if p]
    f = font(size)
    larg = 0
    for p in pedacos:
        larg += (tecla_largura(p[1:-1], size) if p.startswith("[") and
                 p.endswith("]") else f.size(p)[0])
    alt = f.get_height()
    x, y = pos
    if anchor in ("midtop", "center"):
        x -= larg // 2
    if anchor == "center":
        y -= alt // 2
    for p in pedacos:
        if p.startswith("[") and p.endswith("]"):
            r = tecla(surf, p[1:-1], (x, y + alt // 2), size - 2,
                      anchor="midleft", cor=cor_tecla)
            x = r.right
        else:
            r = text(surf, p, (x, y), size, colour)
            x = r.right
    return pygame.Rect(pos[0] - (larg // 2 if anchor in ("midtop", "center")
                                 else 0), y, larg, alt)


def tecla_largura(letra, size=18):
    f = font(size - 2, bold=True)
    return f.size(letra.upper())[0] + max(7, (size - 2) // 2) * 2


# ── a capa como objeto ─────────────────────────────────────────────────────
_sleeve_cache = {}


def sleeve(surf, rect, art, selected=False):
    """Uma capa de disco desenhada como OBJETO, não como quadrado colorido.

    Vale de 46 px (a miniatura do trilho) a meia tela (a AGORA): é o único
    jeito de desenhar capa no sistema, para a mesma capa não ter duas
    aparências dependendo da tela em que aparece.

    **Sintoma:** a estante parecia uma grade de retângulos chapados. Havia
    um `shadow_card` que desenhava preto com alfa sob a capa e não aparecia —
    e não podia aparecer: o INK é (7,8,11), não há para onde escurecer.
    Medido: sobre o INK a maior mudança que ele fazia em qualquer pixel era
    de 7 unidades somando os três canais, ~2 por canal. Quatro blits com alfa
    por capa para produzir zero pixel de diferença. Foi removido.

    Num fundo escuro, peso não vem de sombra: vem de LUZ. Três coisas, todas
    baratas, e juntas a capa passa a ter espessura:

      a lombada    uma faixa escura na borda esquerda com um fio claro do
                   lado de dentro. É o que o olho lê como "isto é uma capa de
                   papelão vista quase de frente", e é o detalhe que mais
                   rende pelo que custa.
      a luz        um fio claro em cima e à esquerda: a luz da sala bate ali.
      o contato    uma linha escura logo abaixo, curta e fechada, que é onde
                   a capa encosta na prateleira.

    Isto é o §5.5 (fósforo, não realismo) e não o contradiz: não há madeira,
    nem textura falsa, nem brilho plástico. É a MESMA paleta, com uma aresta
    iluminada — do jeito que um osciloscópio mostra volume sem desenhar um
    alto-falante.
    """
    # ── contato: onde a capa encosta ──────────────────────────────────────
    # Curto e fechado de propósito. Sombra grande e difusa não é lida como
    # peso num fundo escuro; é lida como borrão.
    base = _sleeve_cache.get(("sombra", rect.w))
    if base is None:
        base = pygame.Surface((rect.w, 10), pygame.SRCALPHA)
        for k in range(10):
            a = int(58 * (1.0 - k / 10.0) ** 2)
            pygame.draw.line(base, (0, 0, 0, a), (k // 2, k), (rect.w - k // 2, k))
        if len(_sleeve_cache) > 48:
            _sleeve_cache.clear()
        _sleeve_cache[("sombra", rect.w)] = base
    surf.blit(base, (rect.x, rect.bottom - 1))

    # ── a arte ────────────────────────────────────────────────────────────
    if art is not None:
        surf.blit(pygame.transform.smoothscale(art, rect.size), rect)
    else:
        panel(surf, rect, INK_LIFT, radius=3)

    # ── a lombada ─────────────────────────────────────────────────────────
    lom = max(2, round(rect.w / 32))
    faixa = pygame.Surface((lom, rect.h), pygame.SRCALPHA)
    faixa.fill((0, 0, 0, 92))
    surf.blit(faixa, rect.topleft)
    pygame.draw.line(surf, lerp(INK, TEXT, 0.22),
                     (rect.x + lom, rect.y + 1), (rect.x + lom, rect.bottom - 2))

    # ── a luz ─────────────────────────────────────────────────────────────
    luz = pygame.Surface((rect.w, 1), pygame.SRCALPHA)
    luz.fill((255, 255, 255, 26))
    surf.blit(luz, rect.topleft)
    lado = pygame.Surface((1, rect.h), pygame.SRCALPHA)
    lado.fill((255, 255, 255, 14))
    surf.blit(lado, rect.topleft)

    # ── selecionado: o disco puxado meio palmo para fora ──────────────────
    if selected:
        pygame.draw.rect(surf, AMBER, rect.inflate(4, 4), width=2, border_radius=2)


_fade_cache = {}


def borda_rolagem(surf, rect, acima=False, abaixo=False, alt=44):
    """Desvanece o topo e/ou o pé de uma área que rola.

    Uma grade cortada no meio de uma fileira já é o aviso de que tem mais
    coisa — mas só para quem sabe que aquilo é uma grade que rola. Sem
    nenhuma outra pista, a leitura mais natural é que a fileira de baixo
    está com defeito, não que ela continua.

    Um degradê até o fundo resolve sem gastar espaço nem cor: o conteúdo
    "entra" e "sai" da área em vez de ser decepado. É a mesma ideia da
    lombada da capa — a informação vem de luz, não de moldura.
    """
    for lado, liga in (("cima", acima), ("baixo", abaixo)):
        if not liga:
            continue
        chave = (lado, rect.w, alt)
        faixa = _fade_cache.get(chave)
        if faixa is None:
            faixa = pygame.Surface((rect.w, alt), pygame.SRCALPHA)
            for y in range(alt):
                # quadrático: quase opaco na borda e sumindo rápido, para
                # não apagar a fileira inteira só para sugerir que ela segue
                t = (y / alt) if lado == "baixo" else (1.0 - y / alt)
                faixa.fill((*INK, int(255 * t * t)), (0, y, rect.w, 1))
            if len(_fade_cache) > 12:
                _fade_cache.clear()
            _fade_cache[chave] = faixa
        surf.blit(faixa, (rect.x, rect.bottom - alt if lado == "baixo"
                          else rect.y))


# ── o vazio como cena ──────────────────────────────────────────────────────
def vazio(surf, rect, desenhar, titulo, linhas, alt=210):
    """O estado vazio desenhado como CENA, não como um buraco com legenda.

    **Sintoma:** numa instalação nova, quase toda seção está vazia — a pilha,
    o diário, as buscas. E o vazio era sempre o mesmo: duas linhas de texto
    cinza no meio de uma tela preta. A primeira impressão do sistema inteiro,
    para quem acabou de instalar, era uma sequência de telas pretas.

    Isso é exatamente o defeito que este sistema existe para não ter. Uma
    prateleira vazia no mundo físico ainda é uma PRATELEIRA: você vê o móvel,
    entende o que vai ali, e a falta vira convite. O equivalente digital de
    uma tela preta é o balde de lixo, não a prateleira.

    Então: um desenho fantasma do que está faltando, o nome do que é, e o que
    apertar — com as teclas desenhadas como teclas (ver `tecla`).

        desenhar(surf, caixa)   pinta o fantasma dentro de `caixa`
        linhas                  frases; `[X]` vira tecla
    """
    caixa = pygame.Rect(0, 0, min(rect.w - 120, 420), alt)
    bloco_h = alt + 34 + len(linhas) * 32
    caixa.midtop = (rect.centerx, rect.centery - bloco_h // 2)
    desenhar(surf, caixa)
    y = caixa.bottom + 34
    text(surf, titulo, (rect.centerx, y), 28, TEXT_DIM, anchor="midtop")
    y += 44
    for ln in linhas:
        frase_com_teclas(surf, ln, (rect.centerx, y), 19, TEXT_FAINT,
                         anchor="midtop")
        y += 32


def fantasma_pilha(surf, caixa):
    """Uma pilha de três capas, vista de frente: a da frente inteira, as de
    trás só espiando pela quina.

    É o desenho mais direto do que a pilha É. Quem olha entende antes de ler.

    Duas tentativas antes desta não funcionaram, e por um motivo que vale
    anotar: contornos vazados que se cruzam pela metade não se leem como
    "capas empilhadas", se leem como um emaranhado de riscos verticais — o
    olho segue as linhas, não as caixas. Pilha só fica legível quando UMA
    delas está inteira e as outras aparecem apenas pela borda, que é o que
    de fato se vê num monte de disco em cima da mesa.
    """
    lado = int(min(caixa.h * 0.78, caixa.w * 0.42))
    espia = max(8, lado // 11)
    base = caixa.bottom - 14
    cx = caixa.centerx - espia
    # A mesa em que a pilha está: sem ela as capas flutuam no vazio.
    pygame.draw.line(surf, lerp(INK, LINE, 0.42),
                     (cx - lado // 2 - 22, base + 3),
                     (cx + lado // 2 + espia * 2 + 22, base + 3), 2)
    # De trás para a frente, para a da frente cobrir as outras.
    for i in (2, 1, 0):
        r = pygame.Rect(0, 0, lado, lado)
        r.midbottom = (cx + i * espia, base - i * espia)
        tom = lerp(INK, LINE, 0.30 + (2 - i) * 0.20)
        # Preenchida com o próprio fundo: é isto que faz a da frente TAPAR as
        # de trás em vez de deixar as linhas se cruzarem.
        pygame.draw.rect(surf, INK, r, border_radius=3)
        pygame.draw.rect(surf, tom, r, width=2, border_radius=3)
        if i == 0:
            # A lombada só na da frente: nas outras não caberia e viraria
            # mais um risco solto.
            lom = r.x + max(3, round(r.w / 20))
            pygame.draw.line(surf, tom, (lom, r.y + 6), (lom, r.bottom - 6), 2)


def fantasma_diario(surf, caixa):
    """Um livro de registro em branco: coluna de data à esquerda, o disco à
    direita, e nada escrito ainda.

    Pautas soltas se leem como "texto", genérico. O que o diário é de fato é
    um LIVRO-CAIXA — uma data e um disco por linha —, e desenhar as duas
    colunas faz o fantasma dizer isso sem legenda.
    """
    larg = int(caixa.w * 0.72)
    x = caixa.centerx - larg // 2
    col = int(larg * 0.19)                 # a coluna da data
    y = caixa.y + 18
    passo = (caixa.h - 40) // 6
    # A régua da margem, em âmbar apagado: o único fio vivo do desenho, e é
    # o que separa a data do disco.
    pygame.draw.line(surf, lerp(INK, AMBER, 0.34),
                     (x + col + 10, caixa.y + 6),
                     (x + col + 10, caixa.bottom - 10), 2)
    for i in range(6):
        yy = y + i * passo
        tom = lerp(INK, LINE, 0.60 - i * 0.08)
        # a data: sempre do mesmo tamanho, porque data tem tamanho fixo
        pygame.draw.line(surf, tom, (x, yy), (x + col - 6, yy), 2)
        # o disco: comprimento variado, porque nome de disco varia
        resto = larg - col - 22
        w = int(resto * (0.95, 0.72, 0.88, 0.61, 0.80, 0.45)[i])
        pygame.draw.line(surf, tom, (x + col + 22, yy), (x + col + 22 + w, yy), 2)


def fantasma_busca(surf, caixa):
    """Uma lupa sobre uma grade de capas — o gesto de procurar num acervo
    que não é o seu.

    É o que separa as seções de loja da estante: na estante os discos são
    seus e estão todos ali; na loja eles só existem depois que você procura.
    """
    lado = int(min(caixa.h * 0.34, caixa.w * 0.20))
    gap = max(6, lado // 8)
    larg = lado * 3 + gap * 2
    x0 = caixa.centerx - larg // 2
    y0 = caixa.y + 14
    for i in range(6):
        r = pygame.Rect(x0 + (i % 3) * (lado + gap),
                        y0 + (i // 3) * (lado + gap), lado, lado)
        pygame.draw.rect(surf, lerp(INK, LINE, 0.52 - (i // 3) * 0.16), r,
                         width=2, border_radius=3)
    # A lupa, em âmbar: é o único gesto vivo do desenho, e é o que se faz aqui.
    raio = int(lado * 0.62)
    cen = (x0 + larg - int(lado * 0.55), y0 + lado + gap + int(lado * 0.6))
    pygame.draw.circle(surf, INK, cen, raio)
    pygame.draw.circle(surf, lerp(INK, AMBER, 0.62), cen, raio, 3)
    d = int(raio * 0.72)
    pygame.draw.line(surf, lerp(INK, AMBER, 0.62),
                     (cen[0] + d, cen[1] + d),
                     (cen[0] + d + raio, cen[1] + d + raio), 4)


# Alturas do cartão de passos. Ficam aqui, uma vez, porque a caixa precisa
# ser medida ANTES de ser desenhada — e a primeira versão media com uma conta
# e desenhava com outra, o que punha o rodapé em cima do último comando.
_P_TOPO, _P_TIT, _P_POR = 26, 36, 42
_P_PASSO, _P_CMD, _P_ROD, _P_BASE = 32, 36, 44, 14


def passos(surf, rect, titulo, porque, lista, rodape=None):
    """A tela de um recurso que ainda não foi ligado, com o que falta fazer.

    **Sintoma:** a seção do Spotify, numa máquina sem nada configurado,
    mostrava "spotifyd não encontrado" em cinza miúdo no canto superior
    direito — o lugar de menos atenção da tela inteira — e no meio, sozinha,
    uma linha de atalhos para funções que não funcionavam. A pessoa via uma
    tela vazia, apertava as teclas que a própria tela sugeria, nada
    acontecia, e nada em lugar nenhum dizia o que fazer.

    Um recurso desligado não é um erro: é um passo que falta. Então mostra-se
    a lista dos passos, quais já estão feitos, e o comando exato do primeiro
    que não está — com o ✓ e o ○ dizendo de longe quanto falta.

        lista   [(feito: bool, o que é, o comando ou None), ...]
    """
    larg = min(rect.w - 120, 720)
    corpo = larg - 60
    f_rod = font(16)
    n_rod = 0
    if rodape:
        # Quantas linhas o rodapé vai ocupar de fato: ele é uma frase inteira
        # e cortá-la com reticências apaga justamente o endereço que ela dá.
        n_rod = max(1, -(-f_rod.size(rodape)[0] // corpo))
    alt = (_P_TOPO + _P_TIT + _P_POR
           + sum(_P_PASSO + (_P_CMD if d else 0) for _f, _t, d in lista)
           + (_P_ROD + (n_rod - 1) * 22 if rodape else 0) + _P_BASE)
    caixa = pygame.Rect(0, 0, larg, alt)
    caixa.center = rect.center
    panel(surf, caixa, INK_SOFT, radius=14, border=LINE)

    x = caixa.x + 30
    y = caixa.y + _P_TOPO
    text(surf, titulo, (x, y), 26, TEXT, bold=True, maxw=corpo)
    y += _P_TIT
    text(surf, porque, (x, y), 18, TEXT_FAINT, maxw=corpo)
    y += _P_POR

    for feito, oque, fazer in lista:
        # ✓ verde para o que já está de pé, ○ âmbar para o que falta: o âmbar
        # é a cor viva (§5.5), e "o que falta" é a coisa viva desta tela.
        text(surf, "✓" if feito else "○", (x, y), 20,
             GREEN if feito else AMBER, bold=True)
        text(surf, oque, (x + 30, y), 19, TEXT_DIM if feito else TEXT,
             maxw=corpo - 30)
        y += _P_PASSO
        if fazer:
            # O comando em painel próprio: é para ser lido por alguém que vai
            # digitá-lo num terminal do outro lado do quarto.
            cr = pygame.Rect(x + 30, y - 6, font(17).size(fazer)[0] + 24, 30)
            panel(surf, cr, INK, radius=6, border=lerp(LINE, AMBER, 0.3))
            text(surf, fazer, (cr.x + 12, cr.y + 6), 17, AMBER)
            y += _P_CMD

    if rodape:
        paragrafo(surf, rodape, (x, y + 6), 16, TEXT_FAINT, maxw=corpo,
                  entrelinha=1.35, limite=3)
    return caixa


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
