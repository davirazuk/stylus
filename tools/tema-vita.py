#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
#  tema-vita.py — um tema de SISTEMA do Vita na paleta do Stylus
# ═══════════════════════════════════════════════════════════════════════════
#      ./tools/tema-vita.py                   escreve em ux0:customtheme/stylus
#      ./tools/tema-vita.py --em PASTA        escreve noutro lugar, para olhar
#
#  ── POR QUE ISTO EXISTE ──────────────────────────────────────────────────
#  O Custom Themes Manager do aparelho dá "network error" ao procurar temas,
#  e a causa não é o Vita: o catálogo dele mora em `psv.altervista.org`, e
#  esse servidor responde 403 para TODO cliente — inclusive com user-agent de
#  Vita. Medido; o domínio pai responde 302, então é a conta de hospedagem
#  que morreu, não a rede do aparelho. Nenhum conserto de TLS ajuda: aquilo é
#  HTTP puro.
#
#  A metade OFFLINE do CTM continua boa: ele lê os temas de
#  `ux0:customtheme/<nome>/`. Então o caminho é pôr um tema lá direto.
#
#  ── O QUE ELE GERA ───────────────────────────────────────────────────────
#  Dez fundos de 960x512, as dez miniaturas de 360x192, a tela de bloqueio,
#  as três prévias, os pontos de página e os dois avisos da barra — tudo em
#  paleta de 8 bits, que é o que o sistema aceita, com pontilhado para o
#  gradiente não bandar.
#
#  NÃO gera os dezoito ícones dos apps do sistema. É de propósito: dezoito
#  ícones desenhados às pressas ficam piores que os da Sony, e o `theme.xml`
#  aceita ser omisso — as entradas `m_browser`, `m_calendar` e companhia
#  simplesmente não entram, e o sistema usa os dele. O mesmo vale para o
#  `m_bgmFilePath`, que no tema de referência já aparece vazio uma vez.
#
#  A paleta e o desenho saem do `livearea.py` — a tela inicial do aparelho e
#  a do app têm de ser a mesma coisa.
# ═══════════════════════════════════════════════════════════════════════════

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from livearea import (AMBER, AMBER_BRIGHT, COLD, FUNDO, TEXT_DIM, SUPER,
                      disco, facho, fonte, fundo, halo, paleta)

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOME = "Stylus"
AUTOR = "vitastylus"

BG = (960, 512)          # o fundo da tela inicial
BGT = (360, 192)         # a miniatura dele, no seletor
PREV = (480, 272)        # as prévias de página e de bloqueio
PREV_MINI = (226, 128)   # a prévia do pacote
PONTO = (22, 22)         # o ponto de página
AVISO = (120, 110)       # o sino da barra


def hexa(c, a=0xFF):
    return "%02x%02x%02x%02x" % (a, c[0], c[1], c[2])


def cena(w, h, qual):
    """As dez páginas. Todas da MESMA família — é um tema, não dez temas —
    e o que muda é onde o disco está e quanto dele aparece.

    A tela inicial do Vita põe as bolhas dos apps por cima disto, e elas
    ocupam o meio. Então o disco vive nas BORDAS: entrando por um canto,
    saindo por outro. Um disco centrado ficaria escondido atrás das bolhas —
    que é o defeito de metade dos temas que existem por aí.
    """
    S = SUPER
    W, H = w * S, h * S
    im = fundo(W, H)

    # onde o disco entra em cada página, em fração da tela, e o raio
    poses = [(1.02, 0.50, 0.62), (-0.02, 0.52, 0.58), (0.50, 1.10, 0.70),
             (1.06, 0.08, 0.46), (-0.06, 0.94, 0.52), (0.94, 0.96, 0.54),
             (0.06, 0.06, 0.44), (1.10, 0.55, 0.78), (0.50, -0.12, 0.66),
             (-0.10, 0.45, 0.72)]
    fx, fy, fr = poses[qual % len(poses)]
    cx, cy, r = W * fx, H * fy, H * fr

    im = halo(im, cx, cy, r * 1.10, 0.22)
    im = disco(im, cx, cy, r, 5, S)
    # o facho só nas páginas em que ele CABE inteiro: um facho cortado pela
    # borda lê como risco na tela, não como luz
    if 0.10 < fx < 0.90 or 0.10 < fy < 0.90:
        im = facho(im, cx, cy, r, math.radians(-130))
    return im.resize((w, h), Image.LANCZOS)


def bloqueio(w, h):
    """A TELA DE BLOQUEIO. O relógio do sistema fica no alto à esquerda, e a
    frase "deslize para cima" embaixo — então o disco vai para a direita e o
    canto inferior esquerdo fica limpo."""
    S = SUPER
    W, H = w * S, h * S
    im = fundo(W, H)
    cx, cy, r = W * 0.72, H * 0.54, H * 0.60
    im = halo(im, cx, cy, r * 1.12, 0.24)
    im = disco(im, cx, cy, r, 5, S)
    im = facho(im, cx, cy, r, math.radians(-132))
    im = im.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = fonte(max(11, h // 26))
    d.text((int(w * 0.055), int(h * 0.80)), "STYLUS", font=fonte(max(14, h // 18)),
           fill=AMBER)
    d.text((int(w * 0.055), int(h * 0.87)), "the record goes on the platter",
           font=f, fill=TEXT_DIM)
    return im


def ponto(n, cheio):
    """Os pontos de página: 22x22. Cheio é a página em que se está."""
    im = Image.new("RGB", (n, n), FUNDO)
    S = 4
    g = Image.new("RGB", (n * S, n * S), FUNDO)
    d = ImageDraw.Draw(g)
    c = n * S / 2.0
    r = n * S * 0.30
    if cheio:
        d.ellipse([c - r, c - r, c + r, c + r], fill=AMBER)
    else:
        d.ellipse([c - r, c - r, c + r, c + r], outline=AMBER, width=S)
    return g.resize((n, n), Image.LANCZOS)


def aviso(w, h, novo):
    """O sino da barra: 120x110. Com aviso novo ele acende."""
    S = 4
    im = Image.new("RGB", (w * S, h * S), FUNDO)
    d = ImageDraw.Draw(im)
    cor = AMBER_BRIGHT if novo else COLD
    cx, cy = w * S / 2.0, h * S / 2.0
    r = min(w, h) * S * 0.26
    # um disquinho: o mesmo vocabulário do resto, e não um sino desenhado
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=cor, width=S * 2)
    d.ellipse([cx - r * 0.22, cy - r * 0.22, cx + r * 0.22, cy + r * 0.22], fill=cor)
    if novo:
        d.arc([cx - r * 1.6, cy - r * 1.6, cx + r * 1.6, cy + r * 1.6],
              -150, -30, fill=cor, width=S * 2)
    return im.resize((w, h), Image.LANCZOS)


def theme_xml():
    """O XML, sem os dezoito ícones e sem bgm — ver a nota do cabeçalho.

    A ordem e a grafia dos campos são as do tema de referência que já
    funciona neste aparelho, inclusive o "Infomation" sem o "r" (é assim no
    formato da Sony; corrigir para "Information" quebra o tema).
    """
    bgs = "\n".join(
        "      <BackgroundParam>\n"
        "        <m_thumbnailFilePath>bgt%d.png</m_thumbnailFilePath>\n"
        "        <m_imageFilePath>bg%d.png</m_imageFilePath>\n"
        "        <m_waveType>%d</m_waveType>\n"
        "        <m_fontColor>%s</m_fontColor>\n"
        "        <m_fontShadow>1</m_fontShadow>\n"
        "      </BackgroundParam>" % (i, i, (i * 3) % 30, hexa((235, 240, 250)))
        for i in range(1, 11))
    return (
        '<?xml version="1.0" encoding="UTF-8"?><theme format-ver="01.00" package="0">\n'
        '  <InfomationBarProperty>\n'
        '    <m_barColor>%s</m_barColor>\n'
        '    <m_indicatorColor>%s</m_indicatorColor>\n'
        '    <m_noticeFontColor>%s</m_noticeFontColor>\n'
        '    <m_noticeGlowColor>%s</m_noticeGlowColor>\n'
        '    <m_noNoticeFilePath>notices.png</m_noNoticeFilePath>\n'
        '    <m_newNoticeFilePath>notice.png</m_newNoticeFilePath>\n'
        '  </InfomationBarProperty>\n'
        '  <HomeProperty>\n'
        '    <m_bgParam>\n%s\n    </m_bgParam>\n'
        '    <m_basePageFilePath>basePage.png</m_basePageFilePath>\n'
        '    <m_curPageFilePath>curPage.png</m_curPageFilePath>\n'
        '    <m_bgmFilePath></m_bgmFilePath>\n'
        '  </HomeProperty>\n'
        '  <InfomationProperty>\n'
        '    <m_contentVer>01.00</m_contentVer>\n'
        '    <m_homePreviewFilePath>preview_page.png</m_homePreviewFilePath>\n'
        '    <m_packageImageFilePath>preview_thumbnail.png</m_packageImageFilePath>\n'
        '    <m_provider><m_default>%s</m_default><m_param></m_param></m_provider>\n'
        '    <m_startPreviewFilePath>preview_lockscreen.png</m_startPreviewFilePath>\n'
        '    <m_title><m_default>%s</m_default><m_param></m_param></m_title>\n'
        '  </InfomationProperty>\n'
        '  <StartScreenProperty>\n'
        '    <m_dateColor>%s</m_dateColor>\n'
        '    <m_dateLayout>1</m_dateLayout>\n'
        '    <m_filePath>lockpaper.png</m_filePath>\n'
        '    <m_notifyBgColor>%s</m_notifyBgColor>\n'
        '    <m_notifyBorderColor>%s</m_notifyBorderColor>\n'
        '    <m_notifyFontColor>%s</m_notifyFontColor>\n'
        '  </StartScreenProperty>\n'
        '</theme>\n' % (
            "%02x%02x%02x" % FUNDO,          # a barra: o fundo do app
            hexa(AMBER),
            hexa((235, 240, 250)),
            hexa(AMBER, 0x7D),
            bgs,
            AUTOR, NOME,
            hexa((235, 240, 250)),
            hexa(FUNDO, 0xCC),
            hexa(AMBER, 0x99),
            hexa((235, 240, 250)),
        ))


def main():
    dest = "/run/media/davirazuk/VITASD/customtheme/stylus"
    if "--em" in sys.argv:
        dest = sys.argv[sys.argv.index("--em") + 1]
    os.makedirs(dest, exist_ok=True)

    def grava(nome, im):
        p = os.path.join(dest, nome)
        paleta(im).save(p, "PNG", optimize=True)
        return os.path.getsize(p)

    total = 0
    paginas = []
    for i in range(1, 11):
        im = cena(BG[0], BG[1], i - 1)
        paginas.append(im)
        total += grava("bg%d.png" % i, im)
        total += grava("bgt%d.png" % i, im.resize(BGT, Image.LANCZOS))
        print("  bg%-2d + miniatura" % i)

    lp = bloqueio(BG[0], BG[1])
    total += grava("lockpaper.png", lp)
    total += grava("preview_lockscreen.png", lp.resize(PREV, Image.LANCZOS))
    total += grava("preview_page.png", paginas[0].resize(PREV, Image.LANCZOS))
    total += grava("preview_thumbnail.png", paginas[0].resize(PREV_MINI, Image.LANCZOS))
    total += grava("basePage.png", ponto(PONTO[0], False))
    total += grava("curPage.png", ponto(PONTO[0], True))
    total += grava("notices.png", aviso(AVISO[0], AVISO[1], False))
    total += grava("notice.png", aviso(AVISO[0], AVISO[1], True))

    with open(os.path.join(dest, "theme.xml"), "w", encoding="utf-8") as f:
        f.write(theme_xml())

    print("\n  %d arquivos, %.1f MB em %s"
          % (len(os.listdir(dest)), total / 1048576.0, dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
