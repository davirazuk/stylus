#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
#  livearea.py — a cara do app na tela inicial do Vita
# ═══════════════════════════════════════════════════════════════════════════
#      ./tools/livearea.py             escreve os três PNGs em sce_sys/
#      ./tools/livearea.py --em DIR    escreve noutra pasta, para só olhar
#
#  ── O QUE É A LIVEAREA ───────────────────────────────────────────────────
#  A tela que o Vita abre ao tocar a bolha do app: um fundo de 840x500, um
#  "portão" de 280x158 (o botão que inicia) e o ícone da bolha, 128x128. Para
#  quem usa o aparelho todo dia é a primeira coisa que aparece — e a única
#  parte do app que se vê sem abri-lo.
#
#  ── POR QUE A ARTE ANTERIOR SAIU ─────────────────────────────────────────
#  Ela era um TOCA-DISCOS: prato, braço de metal, cabeçote e cápsula
#  desenhados na ponta. Bonito, e contra a lei deste projeto — a que o lado
#  desktop escreveu depois de reprovar exatamente isso três vezes:
#
#      o vinil existe para dar a SENSAÇÃO analógica, e o desenho é FÓSFORO,
#      não foto. Disco de luz flutuando no quase-preto; o braço é o FACHO.
#      Proibido: madeira, plinto, parafuso, contrapeso, cabeçote — qualquer
#      coisa que exista numa foto de toca-discos.
#
#  Estes continuam em paleta de 8 bits, porque o instalador do Vita EXIGE
#  isso (recusa com 0x9010113D em qualquer outro modo — ver o check.sh). O
#  que muda é que agora eles saem PONTILHADOS: o gradiente do fundo antes
#  bandava em faixas visíveis, e o Floyd-Steinberg troca a faixa por ruído
#  fino.
#
#  A paleta é a MESMA do app (os VINYL_* do src/ui.c). A LiveArea e a
#  primeira tela do programa têm de ser a mesma coisa — duas paletas
#  parecidas leem como duas versões do app.
# ═══════════════════════════════════════════════════════════════════════════

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# do src/ui.c — não invente vizinhos
FUNDO = (10, 14, 21)
AMBER = (255, 170, 40)
AMBER_BRIGHT = (255, 197, 107)
TEXT = (184, 192, 208)
TEXT_DIM = (121, 131, 150)
COLD = (32, 48, 74)

FONTES = ("/usr/share/fonts/noto/NotoSans-Bold.ttf",
          "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf")


def fonte(px):
    for f in FONTES:
        if os.path.exists(f):
            return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def soma(base, luz):
    """Luz SOMA sobre o fundo.

    Sombra preta não desenha nada sobre (10,14,21) — está medido no
    repositório do desktop: a sombra que existia lá mudava no máximo sete
    unidades somando os três canais. Num fundo escuro, peso vem de LUZ.
    """
    return Image.merge("RGB", [
        Image.eval(Image.merge("L", [b]), lambda _: 0) if False else
        ImageMathAdd(b, l) for b, l in zip(base.split(), luz.split())])


def ImageMathAdd(a, b):
    from PIL import ImageChops
    return ImageChops.add(a, b)


def fundo(w, h):
    """Quase-preto com um respiro frio vindo de FORA do quadro.

    Não é um gradiente de cima para baixo: é uma luz fora de quadro, que é o
    que o `draw_bg` do app faz. Gradiente linear lê como papel de parede; um
    foco lê como um lugar.
    """
    im = Image.new("RGB", (w, h), FUNDO)
    px = im.load()
    fx, fy = w * 0.16, h * -0.12
    maxd = math.hypot(w, h)
    for y in range(h):
        for x in range(w):
            k = max(0.0, 1.0 - math.hypot(x - fx, y - fy) / maxd * 1.35) ** 2.4
            px[x, y] = (int(FUNDO[0] + (COLD[0] - FUNDO[0]) * k * 0.42),
                        int(FUNDO[1] + (COLD[1] - FUNDO[1]) * k * 0.42),
                        int(FUNDO[2] + (COLD[2] - FUNDO[2]) * k * 0.42))
    return im


def halo(im, cx, cy, r, forca=0.30):
    """O halo que respira atrás do disco: um ARO de luz, não um disco cheio.

    ERA um disco cheio de âmbar, borrado e somado. Somar âmbar puro num fundo
    azul-quase-preto não dá "brilho": dá BARRO. A conta é direta —
    (255,170,40) a 26% somado a (10,14,21) chega em (76,58,31), um marrom
    fosco, e ele cobria o quarto inferior direito inteiro do fundo. O que se
    via não era uma luz atrás do disco, era uma mancha suja do lado dele.

    Luz atrás de um objeto opaco não vaza pelo meio dele: ela escapa pela
    BORDA. Então o halo é um aro na altura do aro do disco, borrado — mais
    forte onde encosta e sumindo depressa. O centro, que o disco tapa de
    qualquer forma, deixa de ser pintado de marrom.
    """
    luz = Image.new("RGB", im.size, (0, 0, 0))
    d = ImageDraw.Draw(luz)
    largura = max(2, int(r * 0.16))
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              outline=tuple(int(c * forca) for c in AMBER), width=largura)
    return soma(im, luz.filter(ImageFilter.GaussianBlur(r * 0.22)))


# As FAIXAS deste disco, em fração do raio. Não é enfeite e não é aleatório:
# são durações plausíveis de um LP, e é o que o app desenha no prato — os
# anéis âmbar dizem quantas músicas o disco tem, e dá para CONTÁ-LAS de longe.
FAIXAS = (0.00, 0.13, 0.29, 0.41, 0.58, 0.71, 0.86, 1.00)


def disco(im, cx, cy, r, aceso=None, S=1):
    """O DISCO DE LUZ.

    O corpo fica MAIS ESCURO que o fundo — é o que o faz flutuar — e quem o
    desenha são os anéis por cima.

    A primeira versão disto tinha trinta sulcos igualmente espaçados e virou
    ALVO DE TIRO: é o mesmo defeito que o desenho do desktop já cometeu e
    corrigiu. O que se vê num disco de três metros não são os sulcos (são
    finos demais) — é o INTERVALO entre as faixas, que reflete a luz. Então:
    poucos sulcos, fracos, e os intervalos em âmbar de verdade.
    """
    # A ESPESSURA ACOMPANHA A SUPERAMOSTRAGEM.
    #
    # Uma linha de 1 px desenhada em 4x vira um QUARTO de pixel ao reduzir, e
    # some: os anéis do disco saíam fantasmas. Quem quer um traço de 1 px no
    # fim tem de desenhá-lo com S px aqui. Vale para todo contorno desta
    # função — e é o tipo de erro que passa despercebido porque a imagem
    # continua "quase certa".
    cam = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(cam)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(4, 6, 10, 242))

    r0, r1 = r * 0.34, r * 0.96          # do selo até o aro

    # QUANTOS ANÉIS DEPENDE DO TAMANHO FINAL, não do desenhado.
    #
    # Oito intervalos e catorze sulcos num disco de 230 px são um disco; num
    # ícone de 47 px são uma MANCHA LARANJA — os anéis encostam uns nos
    # outros e o que sobra é um donut. A bolha é vista a esse tamanho entre
    # outras vinte, e o que ela precisa dizer é "disco", não "quantas faixas".
    rf = r / max(1, S)                   # o raio como ele vai ser visto
    nsulcos = 14 if rf > 120 else (7 if rf > 60 else 0)
    faixas = FAIXAS if rf > 120 else (FAIXAS[::2] if rf > 60 else (0.0, 0.5, 1.0))
    a_sul = 26 if rf > 120 else 20
    a_int = 90 if rf > 120 else 70

    for i in range(nsulcos):
        t = (i + 0.5) / nsulcos
        rr = r0 + (r1 - r0) * (t ** 1.25)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=AMBER + (a_sul,), width=S)

    # os INTERVALOS entre as faixas: é o que se conta de longe
    for f in faixas:
        rr = r0 + (r1 - r0) * f
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=AMBER + (a_int,), width=S)

    # A FAIXA QUE TOCA: uma banda acesa entre dois intervalos, e o arco forte
    # onde a agulha passou. Diz onde ela está sem desenhar agulha nenhuma.
    if aceso is not None:
        i = max(1, min(len(faixas) - 1, aceso if rf > 120 else 1))
        ra = r0 + (r1 - r0) * faixas[i - 1]
        rb = r0 + (r1 - r0) * faixas[i]
        d.ellipse([cx - ra, cy - ra, cx + ra, cy + ra], outline=AMBER + (150,), width=S)
        d.ellipse([cx - rb, cy - rb, cx + rb, cy + rb], outline=AMBER + (150,), width=S)
        rm = (ra + rb) * 0.5
        for k, alfa in ((0, 220), (S * 2, 90), (S * 4, 30)):
            d.arc([cx - rm - k, cy - rm - k, cx + rm + k, cy + rm + k],
                  -172, -104, fill=AMBER_BRIGHT + (alfa,), width=S * 2)

    # o selo, pequeno: grande demais ele vira o assunto, e o assunto é o disco.
    # FRIO, e não marrom: o (24,16,7) que estava aqui era âmbar escurecido, e
    # âmbar escuro sobre azul-quase-preto não lê como papel — lê como sujeira.
    # No app o selo é a CAPA sobre um corpo frio; a LiveArea tem de ser o
    # mesmo objeto, não uma segunda versão dele.
    rs = r * 0.30
    d.ellipse([cx - rs, cy - rs, cx + rs, cy + rs],
              fill=(16, 20, 28, 255), outline=AMBER + (150,), width=S)
    d.ellipse([cx - rs * 0.62, cy - rs * 0.62, cx + rs * 0.62, cy + rs * 0.62],
              outline=AMBER + (70,), width=S)
    rh = max(1.5, r * 0.030)
    d.ellipse([cx - rh, cy - rh, cx + rh, cy + rh], fill=FUNDO + (255,))

    # o ARO em duas passadas: a de fora, larga e fraca, é o bloom
    d.ellipse([cx - r - S * 2, cy - r - S * 2, cx + r + S * 2, cy + r + S * 2],
              outline=AMBER + (40,), width=S * 3)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=AMBER + (170,), width=S * 2)

    return Image.alpha_composite(im.convert("RGBA"), cam).convert("RGB")


def facho(im, cx, cy, r, ang, comp=1.55):
    """O BRAÇO É O FACHO.

    Transliteração do `draw_needle` do app: o corpo começa depois de uma boa
    parte do caminho e quase toda a luz mora na PONTA. Nenhum tubo, nenhum
    contrapeso, nenhuma cápsula — a §5.5 recusa os três pelo nome.
    """
    luz = Image.new("RGB", im.size, (0, 0, 0))
    d = ImageDraw.Draw(luz)
    px = cx + math.cos(ang) * r * comp
    py = cy + math.sin(ang) * r * comp        # o pivô, fora do disco
    # a agulha pousa na banda acesa do disco — as duas coisas têm de
    # concordar, senão a luz aponta para um sulco e a banda acende noutro
    fr = 0.34 + (0.96 - 0.34) * ((FAIXAS[4] + FAIXAS[5]) * 0.5)
    tx = cx + math.cos(ang) * r * fr
    ty = cy + math.sin(ang) * r * fr
    esc = r / 100.0                            # o traço acompanha o disco
    for i in range(90):
        t = i / 89.0
        if t < 0.38:                           # o corpo só começa em 38%
            continue
        x = px + (tx - px) * t
        y = py + (ty - py) * t
        k = ((t - 0.38) / 0.62) ** 2.2         # a luz mora na ponta
        w = esc * (1.1 + 2.2 * k)
        c = tuple(int(v * (0.12 + 0.88 * k)) for v in AMBER_BRIGHT)
        d.ellipse([x - w, y - w, x + w, y + w], fill=c)
    # a agulha: uma cruz curta e quente, no sulco
    b = esc * 5.0
    d.line([tx - b, ty, tx + b, ty], fill=AMBER_BRIGHT, width=int(esc * 2) + 1)
    d.line([tx, ty - b, tx, ty + b], fill=AMBER_BRIGHT, width=int(esc * 2) + 1)
    return soma(im, luz.filter(ImageFilter.GaussianBlur(esc * 1.6)))


def paleta(im):
    """PALETA DE 8 BITS, COM PONTILHADO — e não é escolha de estilo.

    O instalador do Vita RECUSA o VPK com 0x9010113D se os PNG do `sce_sys`
    não forem paleta de 256 cores. Já custou uma tarde a este projeto, e o
    "conserto" que se acha por aí (`ffmpeg -pix_fmt ya8`) produz CINZA: o app
    instala e o ícone fica sem cor. O `check.sh` confere as duas coisas.

    Duzentas e cinquenta e seis cores num fundo de gradiente BANDAM — saem
    faixas visíveis, e no LCD do Vita 2000 elas aparecem mais ainda. O
    pontilhado de Floyd-Steinberg troca a faixa por ruído fino, que é o mesmo
    efeito que o grão manual dava e sai de graça na conversão.
    """
    return im.convert("P", palette=Image.ADAPTIVE, colors=256,
                      dither=Image.FLOYDSTEINBERG)


# QUATRO VEZES, e depois reduz.
#
# O `ellipse` do PIL com `width=1` num raio de duzentos pixels sai SERRILHADO
# a ponto de parecer tracejado: os anéis do disco viravam pontinhos. Desenhar
# grande e reduzir com LANCZOS é o antisserrilhado que o PIL não tem — e
# arruma junto o aro, o arco aceso e a curva do facho.
#
# O grão entra DEPOIS de reduzir: reduzido, ele viraria borrão.
SUPER = 4


def bg(w=840, h=500):
    S = SUPER
    im = fundo(w * S, h * S)
    cx, cy, r = w * S * 0.70, h * S * 0.52, h * S * 0.46
    im = halo(im, cx, cy, r * 1.12, 0.26)
    im = disco(im, cx, cy, r, 5, S)
    im = facho(im, cx, cy, r, math.radians(-130))
    im = im.resize((w, h), Image.LANCZOS)

    d = ImageDraw.Draw(im)
    f1, f2 = fonte(58), fonte(19)
    d.text((54, 176), "STYLUS", font=f1, fill=AMBER)
    # a régua entre o nome e a frase: a mesma que separa as abas no app
    d.rectangle([56, 240, 56 + 228, 241], fill=tuple(int(c * 0.5) for c in AMBER))
    d.text((56, 252), "the record goes on the platter", font=f2, fill=TEXT_DIM)
    return paleta(im)


def startup(w=280, h=158):
    """O PORTÃO. É um BOTÃO: tem borda, e a palavra é o assunto."""
    S = SUPER
    im = fundo(w * S, h * S)
    im = halo(im, w * S * 0.5, h * S * 0.42, h * S * 0.55, 0.22)
    im = disco(im, w * S * 0.5, h * S * 0.42, h * S * 0.30, 5, S)
    im = im.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = fonte(18)
    t = "PLAY"
    tw = d.textbbox((0, 0), t, font=f)[2]
    d.text(((w - tw) / 2, h - 36), t, font=f, fill=AMBER)
    d.rectangle([0, 0, w - 1, h - 1], outline=tuple(int(c * 0.55) for c in AMBER))
    return paleta(im)


def icone(n=128):
    """A BOLHA. Vista a uns 60 px entre outras vinte: só o disco, grande e
    sem texto. Um nome escrito aqui vira três pixels de manchinha."""
    S = SUPER
    im = fundo(n * S, n * S)
    im = halo(im, n * S * 0.5, n * S * 0.5, n * S * 0.52, 0.32)
    im = disco(im, n * S * 0.5, n * S * 0.5, n * S * 0.40, 5, S)
    return paleta(im.resize((n, n), Image.LANCZOS))


def main():
    dest = os.path.join(RAIZ, "sce_sys")
    if "--em" in sys.argv:
        dest = sys.argv[sys.argv.index("--em") + 1]
    la = os.path.join(dest, "livearea", "contents")
    os.makedirs(la, exist_ok=True)
    os.makedirs(dest, exist_ok=True)

    for nome, im in (("livearea/contents/bg.png", bg()),
                     ("livearea/contents/startup.png", startup()),
                     ("icon0.png", icone())):
        p = os.path.join(dest, nome)
        im.save(p, "PNG", optimize=True)
        print("  %-34s %dx%d  %d KB" % (nome, im.size[0], im.size[1],
                                        os.path.getsize(p) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
