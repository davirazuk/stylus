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
import subprocess
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
    return _abrir(_arquivo_principal(), size, bold)


def _arquivo_principal():
    global _FONT_FILE
    if _FONT_FILE is None:
        _FONT_FILE = _find_font() or ""
    return _FONT_FILE


def _abrir(arquivo, size, bold):
    key = (arquivo, size, bold)
    if key in _cache:
        return _cache[key]
    if arquivo:
        try:
            f = pygame.font.Font(arquivo, size)
        except OSError:
            f = pygame.font.SysFont("dejavusansmono,monospace", size)
        f.set_bold(bold)
    else:
        f = pygame.font.SysFont("dejavusansmono,monospace", size, bold=bold)
    _cache[key] = f
    return f


# ── outros alfabetos ───────────────────────────────────────────────────────
# A JetBrains Mono cobre o latino, o cirílico e o grego, e MAIS NADA. Um disco
# japonês, coreano ou chinês na estante virava uma fileira de caixinhas — e o
# nome do disco é a única coisa que a grade tem para dizer qual disco é. Fica
# ilegível, não "meio feio".
#
# O pygame não faz cadeia de reserva sozinho, e não dá para perguntar a ele se
# a fonte tem o caractere: `metrics()` devolve métrica para tudo, inclusive
# para um codepoint que não existe em fonte nenhuma. Medido: 日, 한 e um plano
# 1 inventado saem TODOS com a mesma tinta, que é a do retângulo vazio.
#
# Então a pergunta certa é essa mesma: este caractere desenha igual ao
# retângulo vazio? Se sim, esta fonte não o tem, e vai para a próxima.
_RESERVAS = ("NotoSansCJK-Regular.ttc", "NotoSansCJK*-Regular.*",
             "NotoSans-Regular.ttf", "NotoSansSymbols2-Regular.ttf",
             "DejaVuSans.ttf")


def _quem_tem(ch):
    """Quem, nesta máquina, desenha ESTE caractere? Pergunta ao fontconfig.

    A lista fixa acima não escala: são dezenas de alfabetos e o Noto é um
    arquivo por alfabeto. Medido aqui, a NotoSans-Regular respondia à
    máscara como se tivesse hebraico, tailandês E árabe — os três com a
    MESMA quantidade de tinta, porque os três caíam no mesmo glifo de
    reserva dela. Pixel não distingue isso; o fontconfig sabe.

    `scalable=true` porque sem ele o hebraico casava com uma fonte de
    terminal em bitmap (ter-u12n.otb), que o pygame não sabe redimensionar —
    e o conserto sairia num tamanho só.
    """
    try:
        r = subprocess.run(
            ["fc-match", "--format=%{file}",
             ":charset=%04X:scalable=true" % ord(ch)],
            capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return ""
    caminho = (r.stdout or "").strip()
    return caminho if caminho and os.path.isfile(caminho) else ""
_CADEIA = None
_TOFU = {}
_COBRE = {}
# Um codepoint do plano 1 que nenhuma fonte de texto tem: serve de padrão do
# "retângulo vazio" desta fonte neste tamanho.
_NADA = "\U000107a2"


def _cadeia():
    """Os arquivos de fonte, na ordem: a nossa primeiro, as reservas depois."""
    global _CADEIA
    if _CADEIA is not None:
        return _CADEIA
    achados = [_arquivo_principal()]
    for pat in _RESERVAS:
        for d in _FONT_DIRS:
            hits = sorted(glob.glob(os.path.join(d, "**", pat), recursive=True))
            if hits and hits[0] not in achados:
                achados.append(hits[0])
                break
    _CADEIA = [a for a in achados if a]
    return _CADEIA


def _cobre(arquivo, ch, size=24):
    """Esta fonte desenha ESTE caractere, ou desenha a caixinha?"""
    chave = (arquivo, ch)
    if chave in _COBRE:
        return _COBRE[chave]
    f = _abrir(arquivo, size, False)
    if arquivo not in _TOFU:
        _TOFU[arquivo] = _assinatura(f, _NADA)
    resp = _assinatura(f, ch) != _TOFU[arquivo]
    _COBRE[chave] = resp
    return resp


def _assinatura(f, ch):
    """Largura, altura e a média da TINTA. Um número por glifo.

    Conta PIXEL, e não média de cor. A média de um glifo branco num quadro de
    14x32 arredonda para preto — para TODOS eles — e a comparação passava a
    dizer que a fonte principal não tinha nem o cirílico, que ela tem. A
    máscara conta os pixels que têm tinta, e dois glifos diferentes não
    acertam o mesmo número por acaso.
    """
    try:
        sup = f.render(ch, True, (255, 255, 255))
    except pygame.error:
        return None
    return (sup.get_width(), sup.get_height(),
            pygame.mask.from_surface(sup, 40).count())


def fonte_para(texto, size=20, bold=False):
    """A primeira fonte da cadeia que desenha ESTE texto de verdade.

    Decidida por texto inteiro, e não por caractere: um nome de disco é de um
    alfabeto só, e trocar de fonte no meio de uma palavra desalinha a linha de
    base — fica pior do que a caixinha que se veio consertar.
    """
    principal = _arquivo_principal()
    # O caminho comum, e é a maioria esmagadora das chamadas num quadro: nome
    # de disco em ASCII. `isascii()` é uma comparação em C sobre a string
    # inteira; o laço abaixo é um `if` por caractere em Python.
    if texto.isascii():
        return _abrir(principal, size, bold)
    faltando = None
    for ch in texto:
        # ASCII e a área de ícones do Nerd Font são da nossa fonte por
        # definição; perguntar por elas seria o caso comum pagando o caro.
        #
        # **E "a área de ícones" são TRÊS.** Isto conferia só a do BMP
        # (E000–F8FF), e não há um único ícone nossa ali: os 27 que o app.py
        # usa — 󰝰 󰊴 󰲸 — são Material Design, que o Nerd Font v3 pôs no plano
        # 15 (F0000–FFFFD). Ou seja, o atalho descrito no comentário nunca
        # valia, e todo rótulo com ícone caía no caminho caro.
        #
        # Pior que lento: numa máquina sem o Nerd Font, o ícone "faltando"
        # escolhia a fonte do RÓTULO INTEIRO — e quem cobre um caractere de
        # uso privado é uma fonte de símbolos, que não tem letra latina. O
        # resultado era "Clone Hero" desenhado como uma fileira de caixinhas.
        # Ícone que falta tem que ser um glifo faltando, não um rótulo
        # ilegível.
        if (ch < "\u0080" or "\ue000" <= ch <= "\uf8ff"
                or "\U000f0000" <= ch <= "\U000ffffd"
                or "\U00100000" <= ch <= "\U0010fffd"):
            continue
        if not _cobre(principal, ch):
            faltando = ch
            break
    if faltando is None:
        return _abrir(principal, size, bold)
    # A escolha é guardada pelo BLOCO do caractere, não pelo texto: são
    # dezenas de discos japoneses e um punhado de blocos, e guardar por texto
    # faria o cache crescer com a coleção.
    chave = (ord(faltando) >> 8, size, bold)
    if chave in _ESCOLHA:
        return _ESCOLHA[chave]
    escolhida = None
    # O fontconfig primeiro: ele responde por alfabeto, não por lista escrita
    # à mão, e é o mesmo que todo programa gráfico desta máquina usa.
    achado = _quem_tem(faltando)
    if achado and _cobre(achado, faltando):
        escolhida = _abrir(achado, size, bold)
    if escolhida is None:
        for arquivo in _cadeia()[1:]:
            if _cobre(arquivo, faltando):
                escolhida = _abrir(arquivo, size, bold)
                break
    if escolhida is None:
        escolhida = _abrir(principal, size, bold)
    _ESCOLHA[chave] = escolhida
    return escolhida


_ESCOLHA = {}


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
    f = fonte_para(s, size, bold)
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
    return fonte_para(s, size, bold).size(s)[0]


def paragrafo(surf, s, pos, size=20, colour=TEXT, maxw=600, anchor="topleft",
              bold=False, entrelinha=1.35, limite=6):
    """Escreve em várias linhas, quebrando nos espaços. Devolve a altura.

    O `text()` corta com reticências, que é o certo para um nome de disco
    numa prateleira e o errado para uma frase que explica o que fazer: uma
    mensagem de erro cortada no meio não diz o que estava tentando dizer.
    """
    f = fonte_para(s, size, bold)
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


def frase_largura(texto, size=18):
    """Quanto uma frase com `[X]` vai ocupar — contando o quadradinho.

    A conta que o `frase_com_teclas` faz para desenhar, disponível para quem
    precisa saber ANTES se a frase cabe. Havia um `largura(sem colchetes) +
    18 por tecla` escrito à mão no rodapé da interface; 18 é um chute (o
    quadradinho mede a letra em negrito de dois pontos a menos, mais 14 de
    folga), e chute que erra para menos numa linha de rodapé é texto
    desenhado fora da tela.
    """
    import re as _re
    total = 0
    for p in (q for q in _re.split(r"(\[[^\]]{1,6}\])", texto) if q):
        if p.startswith("[") and p.endswith("]"):
            total += tecla_largura(p[1:-1], size)
        else:
            total += largura(p, size)
    return total


# ── a capa como objeto ─────────────────────────────────────────────────────
_sleeve_cache = {}


def sleeve(surf, rect, art, selected=False, lombada="esq"):
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
    alt_s = max(6, min(22, rect.w // 40))
    base = _sleeve_cache.get(("sombra", rect.w))
    if base is None:
        base = pygame.Surface((rect.w, alt_s), pygame.SRCALPHA)
        for k in range(alt_s):
            a = int(58 * (1.0 - k / alt_s) ** 2)
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
    # De que LADO ela fica importa desde que a AGORA passou a puxar o disco
    # para fora da capa: a lombada é a borda FECHADA, e o disco estava saindo
    # exatamente por ela. Na grade tanto faz (vê-se a frente); ali não.
    lom = max(2, round(rect.w / 32))
    faixa = pygame.Surface((lom, rect.h), pygame.SRCALPHA)
    faixa.fill((0, 0, 0, 92))
    if lombada == "dir":
        surf.blit(faixa, (rect.right - lom, rect.y))
        pygame.draw.line(surf, lerp(INK, TEXT, 0.22),
                         (rect.right - lom - 1, rect.y + 1),
                         (rect.right - lom - 1, rect.bottom - 2))
    else:
        surf.blit(faixa, rect.topleft)
        pygame.draw.line(surf, lerp(INK, TEXT, 0.22),
                         (rect.x + lom, rect.y + 1),
                         (rect.x + lom, rect.bottom - 2))

    # ── a luz ─────────────────────────────────────────────────────────────
    # A espessura ACOMPANHA o tamanho. Um fio de 1 px é o certo numa capa de
    # 200 px na grade e some numa de 560 na AGORA — que é justamente onde a
    # aresta iluminada teria mais trabalho a fazer, porque ali a capa é meia
    # tela e um retângulo chapado de meia tela não é um objeto.
    fio = max(1, rect.w // 260)
    luz = pygame.Surface((rect.w, fio), pygame.SRCALPHA)
    luz.fill((255, 255, 255, 26))
    surf.blit(luz, rect.topleft)
    # A borda por onde o disco sai (a oposta à lombada) ganha um fio mais
    # claro: é a boca da capa, e é o que faz o disco atrás dela ler como
    # estando DENTRO dela e não simplesmente atrás.
    boca = max(1, rect.w // 200)
    lado = pygame.Surface((boca, rect.h), pygame.SRCALPHA)
    lado.fill((255, 255, 255, 14 if lombada == "esq" else 30))
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
    # O "porquê" é uma frase inteira e cabia numa linha só. Numa caixa de
    # 720 px ela saía cortada — "depois o disco cai direto na esta…" — e a
    # metade que sumia é justamente a que responde por que vale a pena fazer
    # os passos. Quebra em linhas, como o rodapé já fazia.
    f_por = font(18)
    n_por = max(1, -(-f_por.size(porque)[0] // corpo)) if porque else 0
    f_rod = font(16)
    n_rod = 0
    if rodape:
        # Quantas linhas o rodapé vai ocupar de fato: ele é uma frase inteira
        # e cortá-la com reticências apaga justamente o endereço que ela dá.
        # O teto tem que ser o MESMO aqui e no `limite` do paragrafo lá
        # embaixo. Eram 3 no desenho e nenhum aqui: uma frase de quatro
        # linhas reservava espaço para quatro e desenhava três, e a quarta
        # — que era a que dizia o que fazer — sumia sem nada indicando.
        n_rod = max(1, min(4, -(-f_rod.size(rodape)[0] // corpo)))
    alt = (_P_TOPO + _P_TIT + _P_POR + (n_por - 1) * 24
           + sum(_P_PASSO + (_P_CMD if d else 0) for _f, _t, d in lista)
           + (_P_ROD + (n_rod - 1) * 22 if rodape else 0) + _P_BASE)
    caixa = pygame.Rect(0, 0, larg, alt)
    caixa.center = rect.center
    panel(surf, caixa, INK_SOFT, radius=14, border=LINE)

    x = caixa.x + 30
    y = caixa.y + _P_TOPO
    text(surf, titulo, (x, y), 26, TEXT, bold=True, maxw=corpo)
    y += _P_TIT
    if porque:
        paragrafo(surf, porque, (x, y), 18, TEXT_FAINT, maxw=corpo,
                  entrelinha=1.33, limite=3)
    y += _P_POR + (n_por - 1) * 24

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
            #
            # E nem todo passo é um comando: a loja do Qobuz manda "[c] entra
            # aqui mesmo", que é uma TECLA. Ela vinha desenhada com os
            # colchetes literais, do lado de uma interface inteira em que
            # `[X]` vira quadradinho — a única tecla do sistema escrita como
            # texto, e justamente numa tela cujo trabalho é dizer o que fazer
            # agora. Quem tem marcação vira tecla; quem não tem continua
            # sendo o comando que se digita.
            import re as _re
            e_tecla = bool(_re.search(r"\[[^\]]{1,6}\]", fazer))
            larg_f = (frase_largura(fazer, 17) if e_tecla
                      else font(17).size(fazer)[0])
            cr = pygame.Rect(x + 30, y - 6, larg_f + 24, 30)
            panel(surf, cr, INK, radius=6, border=lerp(LINE, AMBER, 0.3))
            if e_tecla:
                frase_com_teclas(surf, fazer, (cr.x + 12, cr.y + 6), 17, AMBER)
            else:
                text(surf, fazer, (cr.x + 12, cr.y + 6), 17, AMBER)
            y += _P_CMD

    if rodape:
        paragrafo(surf, rodape, (x, y + 6), 16, TEXT_FAINT, maxw=corpo,
                  entrelinha=1.35, limite=n_rod)
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
# As proporções vêm do `vinyl.py`, que as tem em medida de LP de verdade (o
# rótulo com um terço do raio, que é bem mais do que se desenha de memória).
#
# **Sintoma:** o comentário aqui dizia "as mesmas que o deck usa" e os quatro
# números eram OUTROS — 0.34 contra 0.329, 0.42 contra 0.395, 0.96 contra
# 0.945, 0.035 contra 0.024. Duas cópias à mão da mesma medida, uma delas
# afirmando por escrito que era cópia. É a família das seis listas de
# extensão: a divergência não dá erro, só faz os dois desenhos descreverem
# discos diferentes. Agora há um número só.
try:                                                        # pragma: no cover
    from vinyl import R_LABEL as _R_LABEL, R_PROG_IN as _R_IN, \
        R_PROG_OUT as _R_OUT, R_SPINDLE as _R_SP
except Exception:                                           # pragma: no cover
    _R_LABEL, _R_IN, _R_OUT, _R_SP = 0.329, 0.395, 0.945, 0.024
LABEL_R   = _R_LABEL   # bolacha do meio
GROOVE_I  = _R_IN      # onde os sulcos começam
GROOVE_O  = _R_OUT     # e onde acabam
SPINDLE_R = _R_SP      # o furo

# Onde ficam os intervalos entre faixas, na fração do raio. São eles que
# fazem um disco parecer um disco a três metros: dá para CONTAR as músicas.
_INTERVALOS = (0.52, 0.63, 0.71, 0.80, 0.885)

_disco_cache = {}
_halo_cache = {}


def halo(raio, folga=None, forca=255):
    """A luz que o disco espalha no escuro atrás de si. Em cache.

    `raio` é o do DISCO; `folga` é o quanto a luz vaza para fora dele
    (padrão: 30% do raio). A superfície devolvida tem raio+folga.

    A lei do desenho do vinil (CLAUDE.md §5.5) diz onde vem o peso num fundo
    quase preto: de LUZ, nunca de sombra — não há para onde escurecer a
    partir de (7,8,11). O disco parado, desenhado sozinho, boiava recortado
    no nada. Um halo por trás é o que o assenta sem inventar mesa, plinto ou
    sombra de contato.

    O brilho é FORTE NA BORDA DO DISCO e cai para fora. A primeira versão
    disto era um degradê radial comum, mais claro no centro — e o centro
    fica inteiro debaixo do disco, então noventa por cento da luz era gasta
    onde ninguém a via e o que sobrava na borda não dava para notar.

    A força do brilho vem ASSADA na superfície, e não por `set_alpha` na hora
    de desenhar, que era como isto começou. **Medido, num halo de 1040 px:**

        set_alpha + blit          4,44 ms
        blit, sem set_alpha       0,27 ms

    Dezesseis vezes. Alfa por superfície SOMADO a alfa por pixel joga o SDL
    no caminho de composição mais lento que ele tem, e a tela AGORA blita
    isto uma vez por quadro — sozinho, um quarto do orçamento de 60 fps para
    desenhar uma luz.

    Por isso a força é quantizada em passos de 64: o brilho ainda respira com
    a música, em quatro degraus que a 60 quadros por segundo ninguém separa,
    e cada degrau é desenhado uma vez e reusado para sempre. Quatro e não
    dezesseis porque cada um destes é uma superfície de cinco megabytes.

    ── E NÃO, o `set_alpha(None)` no fim não era de graça ────────────────────
    Havia aqui um `h.set_alpha(None)` com "1,09 ms viram 0,30 ms" ao lado. O
    número era verdade e o que ele mediu não era um blit mais rápido: era o
    blit DEIXANDO DE ACONTECER. No pygame 2, `set_alpha(None)` numa superfície
    SRCALPHA **apaga o próprio SRCALPHA** e põe o modo de mistura em NONE —
    o blit vira cópia crua, alfa por pixel e tudo. Medido aqui:

        superfície SRCALPHA recém-criada    flags SRCALPHA=True
        depois de set_alpha(None)           flags SRCALPHA=False

    E na tela: o canto transparente do halo, que é (0,0,0,0), passava a
    pintar PRETO (0,0,0) por cima do fundo desfocado da capa, e o âmbar do
    brilho passava a ser desenhado opaco. Ou seja, a AGORA desenhava um
    QUADRADO PRETO de meia tela com um disco de mostarda chapado dentro —
    exatamente o "app de um dólar" que a §5.5 do CLAUDE.md proíbe pelo nome.
    Rápido porque não desenhava luz nenhuma: pintava por cima.

    A economia de verdade continua sendo a de cima (força assada, cache); o
    alfa por pixel é o trabalho que esta superfície EXISTE para fazer. E ele
    cabe: medido de novo, já sem o `set_alpha(None)`, o blit CORRETO custa

        halo de 938 px (a tela parada)      0,85 ms
        halo de 694 px (tocando)            0,45 ms

    contra os 4,2 ms do `set_alpha` por quadro que a tela parada fazia. Ou
    seja: o desenho certo é cinco vezes mais barato do que o errado que
    estava lá, e a "otimização" que faltava era não desenhar nada.
    """
    raio = max(8, int(raio))
    folga = max(4, int(raio * 0.3 if folga is None else folga))
    # A força vem QUANTIZADA e é assada na superfície. Ver a docstring: um
    # `set_alpha` neste tamanho custa 4,4 ms por quadro.
    forca = max(0, min(255, int(forca)))
    forca -= forca % 64
    chave = (raio, folga, forca)
    pronto = _halo_cache.get(chave)
    if pronto is not None:
        return pronto
    total = raio + folga
    h = pygame.Surface((total * 2, total * 2), pygame.SRCALPHA)
    c = total
    # De fora para dentro, senão cada anel apaga o anterior: o pygame desenha
    # círculo CHEIO, e um círculo menor por cima substitui os pixels em vez
    # de somar.
    # `u`: 0 na borda de FORA do halo, 1 encostado no disco. O brilho cresce
    # com u — máximo colado no disco. A primeira versão tinha o expoente do
    # lado errado (`(1-u)²`) e desenhava uma auréola brilhante na borda
    # externa com o miolo apagado: uma nuvem de mostarda em volta do disco,
    # em vez de luz saindo dele.
    passos = max(10, folga)
    for i in range(passos):
        u = i / (passos - 1)
        rr = int(total - u * folga)
        a = int(34 * u ** 2 * forca / 255.0)
        if a <= 0:
            continue
        pygame.draw.circle(h, (*AMBER_GLOW, a), (c, c), rr)
    # O teto tem que caber os DEGRAUS de força, senão o cache se limpa a cada
    # respiração e cada quadro redesenha um halo do zero — que é mais caro do
    # que o set_alpha que se veio tirar. Quatro degraus por raio, e a AGORA
    # usa um raio por vez.
    if len(_halo_cache) > 10:
        _halo_cache.clear()
    _halo_cache[chave] = h
    return h


_bolacha_cache = {}


def bolacha(art, raio, chave):
    """A capa recortada em CÍRCULO, do tamanho da bolacha do disco.

    Num disco de verdade o meio é impresso, e com o disco no prato é a única
    parte da arte que se vê. Quadrada no meio de um disco redondo seria um
    adesivo colado; o recorte é o que a faz PERTENCER ao objeto.

    Em cache pela `chave` (o caminho da capa) e pelo raio — recortar é um
    smoothscale mais um blit de máscara, e isto é desenhado em todo quadro
    da tela cheia.
    """
    raio = max(8, int(raio))
    k = (chave, raio)
    pronto = _bolacha_cache.get(k)
    if pronto is not None:
        return pronto
    lado = raio * 2
    sup = pygame.transform.smoothscale(art, (lado, lado)).convert_alpha()
    # A máscara: branco dentro do círculo, transparente fora. O BLEND_RGBA_MIN
    # leva o alfa para zero onde a máscara é zero — é o recorte sem precisar
    # de per-pixel à mão.
    mascara = pygame.Surface((lado, lado), pygame.SRCALPHA)
    pygame.draw.circle(mascara, (255, 255, 255, 255), (raio, raio), raio)
    sup.blit(mascara, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    # O aro âmbar e o furo do eixo: sem eles a arte redonda ainda lê como
    # adesivo. São as duas coisas que toda bolacha de disco tem.
    pygame.draw.circle(sup, AMBER_DIM, (raio, raio), raio, max(1, raio // 40))
    pygame.draw.circle(sup, INK, (raio, raio), max(2, int(raio * 0.075)))
    if len(_bolacha_cache) > 8:
        _bolacha_cache.clear()
    _bolacha_cache[k] = sup
    return sup


_RASCUNHOS = {}


def rascunho(w, h, tag=""):
    """Uma superfície transparente para desenhar e jogar fora — REAPROVEITADA.

    A tela AGORA criava uma `pygame.Surface` nova por quadro só para poder
    desenhar com alfa por cima do fundo: no reflexo do disco isso é uma
    superfície de 1000x1000 — quatro megabytes — alocada e descartada
    sessenta vezes por segundo, para desenhar quarenta e seis linhas finas
    dentro dela.

    **Medido, e o resultado NÃO foi o esperado:** alocar 1000x1000 custa 0,17
    ms e reaproveitar+limpar custa os mesmos 0,17 ms. O SDL aloca tão rápido
    quanto varre. Isto não é, portanto, uma otimização de tempo, e escrever
    aqui que era seria mentira que alguém acreditaria depois.

    O que se ganha é não produzir quatro megabytes de lixo por quadro, que o
    coletor do Python leva na conta dele. Fica porque não custa nada e porque
    o número acima já está pago; se um dia atrapalhar, o comentário diz que
    não há tempo nenhum a perder desfazendo.

    O `tag` separa quem desenha o quê: dois usos do mesmo tamanho no mesmo
    quadro apagariam um ao outro, e o defeito apareceria como "às vezes o
    brilho some".
    """
    chave = (int(w), int(h), tag)
    sup = _RASCUNHOS.get(chave)
    if sup is None:
        sup = pygame.Surface((max(1, int(w)), max(1, int(h))), pygame.SRCALPHA)
        _RASCUNHOS[chave] = sup
    else:
        sup.fill((0, 0, 0, 0))
    return sup


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
    # Quantos sulcos: sessenta era um número FIXO, e um número fixo é
    # densidade que muda com o tamanho. No disco pequeno da AGORA lê como
    # sulco; na tela cheia, com o raio em 430 px, os mesmos sessenta viram
    # anéis largos e o disco lê como alvo de tiro. Cresce com o raio, com
    # teto — passar de ~1 px real de espaçamento só produz cintilação.
    n_sulcos = max(60, min(190, raio // 3))
    passo = max(2 * e, (fora - dentro) // n_sulcos)
    for rr in range(dentro, fora, passo):
        f = (rr - dentro) / max(1, fora - dentro)
        # um pouco mais claros na borda, onde a luz pegaria primeiro
        cor = lerp(INK_LIFT, LINE, 0.15 + 0.40 * f)
        pygame.draw.circle(d, (*cor, 150), (c, c), rr, e)

    # os intervalos entre as faixas. É AQUI que o âmbar entra, e só aqui:
    # é a única informação que o disco parado carrega — quantas faixas tem.
    # 105 e não 150: a espessura é sempre 1 px real, então o que muda com o
    # tamanho é só QUANTO do quadro eles ocupam. Na tela cheia os cinco a 150
    # desenhavam curvas de nível de mapa por cima do disco inteiro, mais
    # fortes que o próprio aro. Contar as faixas é para quem olha; não é o
    # assunto do quadro.
    for frac in _INTERVALOS:
        rr = int(R * frac)
        if dentro < rr < fora:
            pygame.draw.circle(d, (*AMBER_DIM, 105), (c, c), rr, e)

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
    # NÃO ponha `d.set_alpha(None)` aqui — havia um, copiado do halo com a
    # mesma promessa de 3,6x. Ele apaga o SRCALPHA da superfície (ver a
    # docstring do `halo`): o disco passava a ser blitado como CÓPIA, e o
    # quadrado transparente em volta dele pintava preto por cima do fundo.
    # O disco é redondo; o que existe fora dele tem que continuar existindo.
    _disco_cache[raio] = d
    return d
