#include "ui.h"
#include "ime.h"
#include "lastfm.h"
#include "qobuz.h"
#include "soundcloud.h"
#include "fsutil.h"
#include "paths.h"
#include "ui_layout.h"
#include "sides.h"
#include "lyrics.h"

#include <vita2d.h>
#include <psp2/ctrl.h>
#include <psp2/touch.h>
#include <psp2/kernel/processmgr.h>
#ifdef __vita__
#include <psp2/kernel/threadmgr.h>
#endif
#ifdef __vita__
/* Só no aparelho: a lista de módulos do processo (quem mais está aqui
   dentro) não tem equivalente no PC, e o shim do preview não a finge. */
#include <psp2/kernel/modulemgr.h>
#endif
#include <psp2/power.h>
#ifdef __vita__
#include <psp2/rtc.h>
#endif

#include <math.h>
#include <stdio.h>
#include <ctype.h>
#include <string.h>
#include <time.h>
#include <stdlib.h>

/* O RGBA8 DO SDK DESLOCA EM `int`, E ISSO É COMPORTAMENTO INDEFINIDO.

   O vita2d.h define
       #define RGBA8(r,g,b,a) ((((a)&0xFF)<<24) | ...)
   e `(a)&0xFF` é `int`. Com alfa 255 — que é o alfa de QUASE TODA cor deste
   arquivo — a conta é `255 << 24`, que não cabe num int de 32 bits com sinal:
   estouro de sinal, undefined behavior pela norma.

   Achado rodando o preview sob o UBSan: ~100 ocorrências, uma por cor
   desenhada, em todo quadro de toda tela. Hoje "funciona" porque o gcc do
   ARM faz a coisa esperada — mas isto compila com -O2, e estouro de sinal é
   exatamente a licença que o otimizador tem para assumir que não acontece.
   Não é falha que se vê: é falha que aparece um dia, numa versão nova do
   compilador, como uma cor errada ou pior.

   O conserto é local de propósito: o vita2d.h é SDK de terceiro, e corrigir
   lá seria um remendo que o próximo `vdpm` apaga sem avisar. Aqui a mesma
   grafia continua valendo — o check.sh exige que toda cor passe pelo RGBA8,
   e continua passando —, só que agora em `unsigned`, onde o deslocamento é
   definido e o resultado é bit a bit o mesmo. */
#undef RGBA8
#define RGBA8(r, g, b, a) ((unsigned int)( \
      (((unsigned int)(a) & 0xFFu) << 24) \
    | (((unsigned int)(b) & 0xFFu) << 16) \
    | (((unsigned int)(g) & 0xFFu) <<  8) \
    |  ((unsigned int)(r) & 0xFFu)))

#define SCRW 960
#define SCRH 544

/* ═══ A PORTEIRA DA GPU ═══════════════════════════════════════════════════

   TUDO que este arquivo manda desenhar passa por aqui antes de virar
   sceGxmDraw. São 148 chamadas de desenho no ui.c e ESTE É O ÚNICO LUGAR
   onde elas se encontram.

   POR QUE UMA PORTEIRA, E NÃO MAIS UM `if` NO LUGAR CERTO.

   Uma coordenada NaN ou absurda entregue ao sceGxm não devolve erro: a GPU
   do Vita TRAVA, e a trava derruba o sistema inteiro — é o que enche o
   `ux0:data` de `psp2core-*-GPUCRASH.psp2dmp`. Já se consertou a conta que
   produzia o NaN duas vezes (o clamp do Goertzel que não pegava NaN; o raio
   do `ring_segmentos`), e as duas vezes o cartão voltou a encher: o conserto
   fechava UMA torneira num arquivo de 6.700 linhas, e a seguinte não estava
   escrita ainda.

   O `coord_ok` já existia e era chamado em DOIS dos 148 desenhos. O
   `vita2d_draw_rectangle` — 127 dos 148, o desenho que este app mais faz —
   não era conferido em lugar nenhum, nem aqui nem no shim do PC.

   Então a conferência sai da conta e vem para a saída. Quem quiser trocar
   `vita2d_draw_rectangle` por outra coisa continua escrevendo
   `vita2d_draw_rectangle`: os `#define` no fim deste bloco desviam as 148
   chamadas sem tocar em nenhuma delas.

   O QUE ELA FAZ COM O QUE RECUSA: nada. Não desenha. Um NaN não tem posição
   "quase certa" para onde possa ser empurrado, e um valor fora de
   ±100000 já está fora da tela de qualquer jeito — recusar não muda um pixel
   do que se vê e é a diferença entre um buraco no desenho e o aparelho
   reiniciando.

   E ELA CONTA. `ui_gpu_recusas`/`ui_gpu_primeira` levam o número e a primeira
   recusa por extenso para o `gpu.txt` do cartão: da próxima vez a resposta
   vem escrita, em vez de sair de mais uma sessão de leitura. */

/* Escrito como `!(x > lo && x < hi)` de propósito: TODA comparação com NaN é
   falsa, então NaN cai sozinho no ramo da recusa. `if (x < lo) ...` não
   pega NaN — foi exatamente esse o defeito do clamp do espectro. */
static int gg_num(float v) { return v > -100000.0f && v < 100000.0f; }

/* ONDE O DESENHO ESTAVA QUANDO A GPU MORREU.
 *
 * Vai sendo escrito ao longo do quadro e lido no COMEÇO do quadro seguinte —
 * que é o que o torna útil: uma trava de GPU não para a CPU na hora (o vita2d
 * é triplo-bufferizado e ela corre até dois quadros à frente), então o último
 * marco do quadro que travou já está gravado quando o `gpu.txt` seguinte
 * sai. */
static const char *g_fase = "(nenhuma)";
static void fase(const char *f) { g_fase = f; }

static unsigned long g_gg_recusas;
static char          g_gg_primeira[128];
static long          g_gg_desenhos;      /* neste quadro */
static long          g_gg_pior;          /* o pior quadro desde o arranque */
static int           g_gg_estourou;      /* o teto de desenho por quadro pegou */

/* O QUE, EXATAMENTE, ESTÁ SENDO DESENHADO DEMAIS.
 *
 * A primeira caixa-preta disse "pior quadro 10.731" e nada mais — e o PC mede
 * 1.177 nas mesmas telas. Nove vezes, e nenhuma pista de ONDE. Pior: o "pior
 * quadro" é um máximo corrido desde o arranque, então nem a tela que o
 * produziu era certa: o `gpu.txt` dizia PLAYING porque era a tela do momento
 * em que ele foi escrito, não a do recorde.
 *
 * Um contador que diz só o total manda ler 6.700 linhas de novo. Estes dizem
 * a primitiva, e o `g_gg_pior_tela` diz a tela — que é o que transforma a
 * próxima queda numa resposta em vez de mais uma teoria. */
enum { GG_RECT = 0, GG_LINHA, GG_CIRC, GG_LOTE, GG_TEX, GG_GLIFO, GG_N };
static const char *GG_NOME[GG_N] =
    { "rect", "line", "circle", "array", "texture", "glyph" };
static long g_gg_cat[GG_N];        /* neste quadro */
static long g_gg_pior_cat[GG_N];   /* no pior quadro */

/* ═══ O QUE O CONTADOR DE CHAMADAS NÃO VÊ: O PREENCHIMENTO ════════════════
 *
 * Todo o orçamento de GPU deste arquivo conta CHAMADAS. Isso pegou a estante
 * que emitia 21.272 num quadro, e desde então o número anda perto de 1.100 —
 * "cap hit no", "rejected 0", tudo limpo — enquanto o cartão continuava
 * enchendo de GPUCRASH.
 *
 * Porque chamada não é custo. O `deck_backdrop` desenhava a capa AMPLIADA
 * 2,15x em SEIS passes tingidos, mais o véu por cima: SETE chamadas, e sete
 * TELAS INTEIRAS de pixel misturado com leitura de textura, todo quadro, na
 * tela mais pesada do app. Sete de um teto de quatro mil — o guarda olhava
 * para o lado errado do problema e dizia que estava tudo bem.
 *
 * Então mede-se também o pixel. Não é exato (não há como saber o que o tiler
 * descartou), mas é a ÁREA QUE A PRIMITIVA COBRE DENTRO DA TELA, que é a
 * conta que o SGX paga: ele sombreia por tile, e o que cobre a tela inteira
 * seis vezes custa seis vezes, mesmo sendo uma chamada cada.
 *
 * Em telas de tela cheia (960x544 = 0,52 Mpx) isto vira uma unidade legível:
 * "quantas telas este quadro pintou". Um quadro são deste app pinta 2 a 3.
 * O backdrop antigo sozinho pintava 7. */
static double g_gg_px;             /* pixels cobertos neste quadro */
static double g_gg_pior_px;        /* no pior quadro (pelo mesmo critério) */
static double g_gg_px_ultimo;      /* o quadro anterior, para o governador */

/* Área da caixa (x,y,w,h) que cai DENTRO da tela. Fora dela o tiler não
   sombreia nada, e somar o que não é pintado inventaria custo. */
static void gg_px_caixa(float x, float y, float w, float h)
{
    if (w < 0.0f) { x += w; w = -w; }
    if (h < 0.0f) { y += h; h = -h; }
    float x0 = x > 0.0f ? x : 0.0f;
    float y0 = y > 0.0f ? y : 0.0f;
    float x1 = x + w, y1 = y + h;
    if (x1 > (float)SCRW) x1 = (float)SCRW;
    if (y1 > (float)SCRH) y1 = (float)SCRH;
    if (!(x1 > x0) || !(y1 > y0)) return;      /* !(>) para NaN cair aqui */
    g_gg_px += (double)(x1 - x0) * (double)(y1 - y0);
}
static int  g_gg_pior_tela = -1;
static long g_gg_ultimo;           /* o quadro anterior, para o governador */
static unsigned long g_gg_aparadas;   /* janelas de textura que passavam do fim */
static char g_gg_apara1[128];
static unsigned long g_gg_longe;      /* geometria finita, mas muito fora da tela */
static char g_gg_longe1[128];

/* MUITO FORA DA TELA AINDA É TRABALHO PARA A GPU.
 *
 * A porteira aceitava qualquer coisa entre ±100000 porque o que ela caçava
 * era NaN. Mas a tela tem 960x544, e o tiler do SGX percorre a área que a
 * primitiva cobre: um triângulo que vai de (0,0) a (90000,90000) faz ele
 * caminhar por um campo de tiles absurdo — e uma GPU que demora demais neste
 * aparelho é uma GPU que o watchdog mata. O número é FINITO, então
 * `rejected` continua zero e nada acusa.
 *
 * ±4000 é sete vezes a diagonal da tela: nenhum desenho legítimo deste app
 * chega perto, e o que passar disso é conta errada, não estilo. */
static int gg_perto(float v) { return v > -4000.0f && v < 4000.0f; }
static void gg_conta_longe(const char *quem, float a, float b, float c, float d)
{
    g_gg_longe++;
    if (g_gg_longe1[0]) return;
    snprintf(g_gg_longe1, sizeof(g_gg_longe1), "%s(%g, %g, %g, %g)",
             quem, (double)a, (double)b, (double)c, (double)d);
}

/* O TETO DE DESENHO POR QUADRO.

   A outra forma de travar esta GPU não é o número errado, é o número DE
   chamadas: cada primitiva do vita2d é um sceGxmDraw próprio (conferido
   desmontando o libvita2d.a) e a lista de display tem fim. A estante já
   emitiu 21.272 num quadro só, e era isso que travava quando o compositor do
   sistema tentava encaixar o overlay de volume por cima.

   Hoje a tela mais cara mede 1.177 (tools/varredura.sh), e o aparelho
   concorda desde que a varredura pare de somar centenas de quadros num só
   (ver o `gg_quadro` no `ui_draw_scanning`). 4.000 é três vezes e meia o
   pior caso medido — longe de qualquer quadro são, e perto o bastante para
   servir de guarda. Era 12.000, que só protegia contra um laço infinito. */
#define GG_TETO_QUADRO 4000

/* ONDE O MODO ENXUTO ENTRA. Ver a nota no `ui_frame`. */
#define GG_ENXUTO 2000

/* QUANTOS QUADROS o deck desenha enxuto ao entrar. São QUATRO, em DOIS
   andares: 2 lite (~40 chamadas: fundo, corpo, rótulo) + 2 médios (fundo
   esborratado, disco cheio, agulha — sem lista, sem lustro fino, sem
   espectro). Só aí o quadro cheio.

   Dois bastavam no papel: o quadro da troca + o primeiro sem a tela
   anterior. Mas os dumps de 08/09 caíram TODOS no primeiro quadro CHEIO
   (frame 107 vindo da ARTISTS com fill 3.6, frame 195 vindo da SEARCH com
   fill 4.0 — nos dois o anterior saiu "whole frame OK"): a CPU entrega a
   lista e a GPU, com triplo buffer, ainda mastiga as listas velhas. O
   degrau 40 -> 1050 chamadas de uma vez é o que mata; 40 -> ~600 -> 1050
   em 66 ms não se vê e dá à GPU o tempo de esvaziar. */
#define DECK_ENXUTO_QUADROS 4

static void gg_recusa(const char *quem, float a, float b, float c, float d)
{
    g_gg_recusas++;
    if (g_gg_primeira[0]) return;
    snprintf(g_gg_primeira, sizeof(g_gg_primeira), "%s(%g, %g, %g, %g)",
             quem, (double)a, (double)b, (double)c, (double)d);
}

/* Devolve 0 quando o desenho NÃO deve sair. Conta o desenho que sai. */
static int gg_passa_cat(int cat)
{
    if (g_gg_desenhos >= GG_TETO_QUADRO) { g_gg_estourou = 1; return 0; }
    g_gg_desenhos++;
    if (cat >= 0 && cat < GG_N) g_gg_cat[cat]++;
    return 1;
}

static void gg_rect(float x, float y, float w, float h, unsigned int c)
{
    if (!gg_num(x) || !gg_num(y) || !gg_num(w) || !gg_num(h))
        { gg_recusa("rect", x, y, w, h); return; }
    if (!gg_perto(x) || !gg_perto(y) || !gg_perto(x + w) || !gg_perto(y + h))
        { gg_conta_longe("rect", x, y, w, h); return; }
    if (gg_passa_cat(GG_RECT)) { gg_px_caixa(x, y, w, h); vita2d_draw_rectangle(x, y, w, h, c); }
}

static void gg_line(float x0, float y0, float x1, float y1, unsigned int c)
{
    if (!gg_num(x0) || !gg_num(y0) || !gg_num(x1) || !gg_num(y1))
        { gg_recusa("line", x0, y0, x1, y1); return; }
    if (!gg_perto(x0) || !gg_perto(y0) || !gg_perto(x1) || !gg_perto(y1))
        { gg_conta_longe("line", x0, y0, x1, y1); return; }
    if (gg_passa_cat(GG_LINHA)) {
        /* a linha é fina: a caixa que ela cobre é o que interessa, e uma
           diagonal cobre menos que a caixa — meia caixa é a aproximação
           honesta e barata */
        gg_px_caixa(x0 < x1 ? x0 : x1, y0 < y1 ? y0 : y1,
                    (x1 > x0 ? x1 - x0 : x0 - x1) + 1.0f, 1.0f);
        vita2d_draw_line(x0, y0, x1, y1, c);
    }
}

static void gg_circle(float cx, float cy, float r, unsigned int c)
{
    if (!gg_num(cx) || !gg_num(cy) || !gg_num(r))
        { gg_recusa("circle", cx, cy, r, 0.0f); return; }
    if (!gg_perto(cx) || !gg_perto(cy) || !gg_perto(r))
        { gg_conta_longe("circle", cx, cy, r, 0.0f); return; }
    if (gg_passa_cat(GG_CIRC)) {
        gg_px_caixa(cx - r, cy - r, 2.0f * r, 2.0f * r);   /* ~78% é o disco */
        vita2d_draw_fill_circle(cx, cy, r, c);
    }
}

/* O LOTE é o caminho mais curto até a GPU que este app tem: os vértices vão
   crus, sem nenhuma conta do vita2d no meio. Um vértice sujo condena o
   desenho INTEIRO — meio anel não é desenho, e o que interessa aqui é não
   entregar lixo. */
#ifdef __vita__
typedef SceGxmPrimitiveType GgPrim;
#else
typedef int GgPrim;            /* o shim do PC declara o modo como int */
#endif

static void gg_array(GgPrim modo, const vita2d_color_vertex *v, size_t n)
{
    if (!v || n == 0) return;
    for (size_t i = 0; i < n; i++) {
        if (!gg_num(v[i].x) || !gg_num(v[i].y) || !gg_num(v[i].z))
            { gg_recusa("array", v[i].x, v[i].y, v[i].z, (float)i); return; }
        if (!gg_perto(v[i].x) || !gg_perto(v[i].y))
            { gg_conta_longe("array", v[i].x, v[i].y, 0.0f, (float)i); return; }
    }
    if (gg_passa_cat(GG_LOTE)) {
        /* o lote é sempre LINHAS aqui (anéis e arcos): cada par de vértices
           é um segmento de 1 px de espessura */
        for (size_t i = 0; i + 1 < n; i += 2)
            gg_px_caixa(v[i].x < v[i+1].x ? v[i].x : v[i+1].x,
                        v[i].y < v[i+1].y ? v[i].y : v[i+1].y,
                        (v[i+1].x > v[i].x ? v[i+1].x - v[i].x
                                           : v[i].x - v[i+1].x) + 1.0f, 1.0f);
        vita2d_draw_array(modo, v, n);
    }
}

static void gg_tex_scale(const vita2d_texture *t, float x, float y,
                         float sx, float sy)
{
    if (!t) return;
    if (!gg_num(x) || !gg_num(y) || !gg_num(sx) || !gg_num(sy))
        { gg_recusa("tex_scale", x, y, sx, sy); return; }
    if (gg_passa_cat(GG_TEX)) {
        gg_px_caixa(x, y, (float)vita2d_texture_get_width(t) * sx,
                          (float)vita2d_texture_get_height(t) * sy);
        vita2d_draw_texture_scale(t, x, y, sx, sy);
    }
}

static void gg_tex_tint(const vita2d_texture *t, float x, float y,
                        float sx, float sy, unsigned int c)
{
    if (!t) return;
    if (!gg_num(x) || !gg_num(y) || !gg_num(sx) || !gg_num(sy))
        { gg_recusa("tex_tint", x, y, sx, sy); return; }
    if (gg_passa_cat(GG_TEX)) {
        gg_px_caixa(x, y, (float)vita2d_texture_get_width(t) * sx,
                          (float)vita2d_texture_get_height(t) * sy);
        vita2d_draw_texture_tint_scale(t, x, y, sx, sy, c);
    }
}

static void gg_tex_part(const vita2d_texture *t, float x, float y,
                        float tx, float ty, float tw, float th,
                        float sx, float sy)
{
    if (!t) return;
    if (!gg_num(x) || !gg_num(y) || !gg_num(sx) || !gg_num(sy))
        { gg_recusa("tex_part", x, y, sx, sy); return; }
    if (!gg_num(tx) || !gg_num(ty) || !gg_num(tw) || !gg_num(th))
        { gg_recusa("tex_part/janela", tx, ty, tw, th); return; }

    /* ═══ A JANELA TEM DE CABER NA TEXTURA — E ESTE ERA O DEFEITO ═══════
     *
     * A janela é ENDEREÇO dentro da memória da textura, não posição na tela.
     * Passar do fim dela é mandar o sceGxm ler fora do bloco que mapeou, e a
     * GPU do Vita não devolve erro para isso: ela TRAVA, e a trava derruba o
     * sistema.
     *
     * A versão anterior desta função conferia `tx < 0 || tw <= 0` e o
     * comentário dizia "negativa OU MAIOR QUE A TEXTURA" — metade da frase
     * virou código. A metade que faltou é a que acontecia.
     *
     * ONDE: o `draw_cover_round` desenha o rótulo do vinil e os retratos da
     * ARTISTS como uma pilha de tiras. A capa é escalada para PREENCHER o
     * círculo (`s = 2r / menor lado`), e a tira de baixo pede
     * `(y1 + 1 - dy0)/s`, que para uma capa quadrada dá `th + th/(2r)` — uma
     * capa de 500 px num raio de 60 lê **quatro pixels depois do fim**. A
     * borda direita cai exatamente em `tw`, e daí qualquer arredondamento
     * passa. Não é um caso raro: é TODO rótulo redondo, em TODO quadro.
     *
     * Bate com o que o `gpu.txt` mostrou: `rejected 0` (os números são
     * finitos, só estão fora de alcance), memória sobrando, 1.009 desenhos —
     * e `texture=528`, a categoria dominante. E bate com os dois gatilhos que
     * o dono descreveu: o deck (o rótulo) e a ARTISTS (dezoito retratos).
     *
     * APARA em vez de recusar: recusar deixaria buracos no rótulo. O excesso
     * é de um pixel de origem, e o destino continua o mesmo — o que se perde
     * é invisível, e o que se evita é o aparelho reiniciando. */
    float TW = (float)vita2d_texture_get_width(t);
    float TH = (float)vita2d_texture_get_height(t);
    if (!(TW >= 1.0f) || !(TH >= 1.0f)) return;
    if (tx < 0.0f || ty < 0.0f || tx + tw > TW || ty + th > TH) {
        g_gg_aparadas++;
        if (!g_gg_apara1[0])
            snprintf(g_gg_apara1, sizeof(g_gg_apara1),
                     "src(%.1f,%.1f %.1fx%.1f) in %gx%g", (double)tx, (double)ty,
                     (double)tw, (double)th, (double)TW, (double)TH);
    }
    if (tx < 0.0f) { tw += tx; tx = 0.0f; }
    if (ty < 0.0f) { th += ty; ty = 0.0f; }
    if (tx + tw > TW) tw = TW - tx;
    if (ty + th > TH) th = TH - ty;
    if (!(tw > 0.0f) || !(th > 0.0f) || tx >= TW || ty >= TH) return;

    if (gg_passa_cat(GG_TEX)) {
        gg_px_caixa(x, y, tw * sx, th * sy);
        vita2d_draw_texture_part_scale(t, x, y, tx, ty, tw, th, sx, sy);
    }
}

/* O TEXTO desenha um sceGxmDraw POR GLIFO — a `escala` multiplica cada
   vértice de cada um deles. Uma escala NaN não faz um texto torto: faz
   centenas de quadriláteros sujos de uma vez. */
static int gg_text(vita2d_pvf *f, int x, int y, unsigned int c,
                   float escala, const char *s)
{
    if (!f || !s) return 0;
    if (!gg_num((float)x) || !gg_num((float)y) || !gg_num(escala) ||
        !(escala > 0.0f))
        { gg_recusa("texto", (float)x, (float)y, escala, 0.0f); return 0; }
    if (!gg_passa_cat(GG_GLIFO)) return 0;
    /* cada glifo é um desenho; o contador do quadro tem de saber disso ou o
       teto mede metade do custo — foi assim que o contador antigo aprovou
       telas que estouravam */
    for (const char *p = s; *p; p++) {
        g_gg_desenhos++; g_gg_cat[GG_GLIFO]++;
        /* a PVF do vita2d tem 18 px de corpo (ver a nota do PX() adiante);
           o quadrilátero de um glifo não passa disso vezes a escala */
        gg_px_caixa((float)x, (float)y - 18.0f * escala,
                    18.0f * escala, 18.0f * escala);
    }
    return vita2d_pvf_draw_text(f, x, y, c, escala, s);
}

/* O QUADRO NOVO. Chamado do `ui_frame`, DEPOIS do start_drawing: o teto é
   por quadro, e o pior quadro fica guardado para o `gpu.txt` do cartão. */
static void gg_quadro(int tela)
{
    g_gg_ultimo = g_gg_desenhos;
    g_gg_px_ultimo = g_gg_px;
    if (g_gg_desenhos > g_gg_pior) {
        g_gg_pior = g_gg_desenhos;
        g_gg_pior_tela = tela;
        for (int i = 0; i < GG_N; i++) g_gg_pior_cat[i] = g_gg_cat[i];
    }
    /* o pior PREENCHIMENTO é guardado à parte do pior número de chamadas:
       foram exatamente essas duas coisas que andaram em direções opostas */
    if (g_gg_px > g_gg_pior_px) g_gg_pior_px = g_gg_px;
    g_gg_desenhos = 0;
    g_gg_px = 0.0;
    for (int i = 0; i < GG_N; i++) g_gg_cat[i] = 0;
}

/* Em "telas cheias": 960x544 é a unidade em que este número se lê. */
/* O quadro QUE ACABOU DE SER DESENHADO — vale entre o fim de um ui_frame e o
   gg_quadro do seguinte, que é onde a varredura mede. */
double ui_gpu_telas_agora(void)  { return g_gg_px / ((double)SCRW * SCRH); }
double ui_gpu_telas_ultimo(void) { return g_gg_px_ultimo / ((double)SCRW * SCRH); }
double ui_gpu_telas_pior(void)   { return g_gg_pior_px  / ((double)SCRW * SCRH); }

long ui_gpu_ultimo(void) { return g_gg_ultimo; }
int  ui_gpu_pior_tela(void) { return g_gg_pior_tela; }
void ui_gpu_pior_por_tipo(char *out, int cap)
{
    int n = 0;
    if (cap > 0) out[0] = '\0';
    for (int i = 0; i < GG_N && n < cap - 1; i++)
        n += snprintf(out + n, (size_t)(cap - n), "%s%s=%ld",
                      i ? " " : "", GG_NOME[i], g_gg_pior_cat[i]);
}

unsigned long ui_gpu_longe(void) { return g_gg_longe; }
const char   *ui_gpu_longe1(void)
{ return g_gg_longe1[0] ? g_gg_longe1 : "(nenhuma)"; }

unsigned long ui_gpu_aparadas(void) { return g_gg_aparadas; }
const char   *ui_gpu_apara1(void)
{ return g_gg_apara1[0] ? g_gg_apara1 : "(nenhuma)"; }

unsigned long ui_gpu_recusas(void)  { return g_gg_recusas; }
const char   *ui_gpu_primeira(void)
{ return g_gg_primeira[0] ? g_gg_primeira : "(nenhuma)"; }
long          ui_gpu_pior(void)     { return g_gg_pior; }
int           ui_gpu_estourou(void) { return g_gg_estourou; }

#define vita2d_draw_rectangle          gg_rect
#define vita2d_draw_line               gg_line
#define vita2d_draw_fill_circle        gg_circle
#define vita2d_draw_array              gg_array
#define vita2d_draw_texture_scale      gg_tex_scale
#define vita2d_draw_texture_tint_scale gg_tex_tint
#define vita2d_draw_texture_part_scale gg_tex_part
#define vita2d_pvf_draw_text           gg_text

/* SÓ O TESTE CHAMA. Empurra um NaN por cada porta da porteira.

   ELA MORA DEPOIS DOS `#define` DE PROPÓSITO, e isso não é detalhe: escrita
   ACIMA deles, ela chamava o `vita2d_draw_rectangle` CRU e o NaN passava
   direto — a porteira nem era consultada. O teste pegou na primeira rodada
   ("0 recusas, 4 desenhos emitidos"), que é exatamente o serviço dele: aqui
   a diferença entre estar protegido e não estar é a ORDEM de duas linhas, e
   ela não aparece lendo.

   Sem isto a porteira é uma promessa: ela some do relatório justamente
   quando funciona (nada a atravessa, o contador fica em zero) e ficaria
   indistinguível de uma que foi desligada por engano — um `#define` a menos,
   uma função nova chamando o `vita2d_` cru, e ninguém saberia. Aqui ela é
   VISTA recusando, e o teste confere que o desenho não saiu. */
void ui_gpu_forca_nan(void)
{
    const float nan_ = 0.0f / 0.0f;
    vita2d_draw_rectangle(nan_, 0.0f, 10.0f, 10.0f, 0xFFFFFFFFu);
    vita2d_draw_line(0.0f, nan_, 10.0f, 10.0f, 0xFFFFFFFFu);
    vita2d_draw_fill_circle(10.0f, 10.0f, nan_, 0xFFFFFFFFu);
    vita2d_draw_rectangle(1e30f, 0.0f, 10.0f, 10.0f, 0xFFFFFFFFu);   /* absurdo finito */

    /* A PORTA DA TEXTURA TINGIDA precisa de uma textura de verdade: ela
       devolve cedo quando o ponteiro é nulo, e uma porta que o teste só sabe
       atravessar com NULL não foi testada. Duas por dois pixels bastam.

       Soltar aqui é seguro porque o desenho FOI RECUSADO — a textura nunca
       chegou à GPU, e o `ultimo_uso` do shim continua zero. Se algum dia esta
       recusa deixar de acontecer, o detector de "solta cedo" do shim acusa,
       que é exatamente o que se quer. */
    vita2d_texture *t = vita2d_create_empty_texture_format(
        2, 2, SCE_GXM_TEXTURE_FORMAT_U8U8U8_BGR);
    if (t) {
        vita2d_draw_texture_tint_scale(t, 0.0f, 0.0f, nan_, 1.0f, 0xFFFFFFFFu);
        vita2d_free_texture(t);
    }
}



#ifdef STYLUS_CYCLE
/* DIAGNÓSTICO do GPUCRASH: o ciclo estende o deck em variantes para isolar
   se a GPU trava por causa da ROTAÇÃO do disco ou por causa do CONTEÚDO
   estático (sulcos/lustro). Nunca ligados fora de um build de diagnóstico. */
static int g_congela_disco;   /* a cena 6: disco parado, mesmo conteúdo */
static int g_disco_plano;     /* a cena 7: disco liso, sem sulcos nem lustro */
#endif

/* paleta: quase-preto frio + âmbar como ÚNICA cor viva. A lei do desenho é a
   do resto do STYLUS — fósforo, não foto: luz no escuro, nada de madeira,
   plinto, parafuso ou sombra "física".

   AS CORES SÃO ESCRITAS PELO RGBA8, NUNCA EM HEXADECIMAL À MÃO. O vita2d
   empacota ABGR (`RGBA8` põe o vermelho no byte BAIXO), e a paleta anterior
   estava escrita como se fosse ARGB: `0xFFFFAA28`, o âmbar do projeto
   inteiro, saía no aparelho como (40,170,255) — AZUL-CELESTE. E o
   `0xFF20304A`, o azul frio do halo, saía marrom. Isto é a §5.5 ao contrário
   em todas as telas, e não dá para ver lendo o código: os números "parecem"
   âmbar. */
/* ---------- OS TEMAS ----------

   A paleta deixou de ser uma constante e virou uma ESCOLHA. O âmbar sobre
   quase-preto é a identidade do app e continua sendo o padrão; o "vita" é
   para quem quer o aparelho inteiro falando a mesma língua — é o azul da
   interface do sistema, que é onde o tocador de música da Sony vive.

   Cada tema declara o PRÓPRIO fundo, e o `tools/contraste.py` confere TODOS
   eles contra o fundo de cada um. Um tema bonito que apaga o nome do artista
   no LCD do Vita 2000 não é um tema, é um defeito — e a conta que pega isso
   não é o olho de quem revisa num monitor bom.

   Os nomes com prefixo existem para essa conferência conseguir ler daqui. */
#define VINYL_FUNDO            RGBA8( 10,  14,  21, 255)
#define VINYL_COL_AMBER        RGBA8(255, 170,  40, 255)
#define VINYL_COL_AMBER_BRIGHT RGBA8(255, 197, 107, 255)
#define VINYL_COL_TEXT         RGBA8(184, 192, 208, 255)
#define VINYL_COL_TEXT_DIM     RGBA8(121, 131, 150, 255)
#define VINYL_COL_TEXT_FAINT   RGBA8( 93, 106, 128, 255)
#define VINYL_COL_COLD         RGBA8( 32,  48,  74, 255)
#define VINYL_COL_ALARM        RGBA8(255, 102,  85, 255)
#define VINYL_COL_BAR_BED      RGBA8( 24,  32,  44, 255)

/* O AZUL DO SISTEMA. Não é o azul do Vita copiado a olho: é a família de
   tons que a interface dele usa — fundo azul-noite, texto quase branco e um
   acento celeste. Os cinzas de texto subiram junto, porque um fundo mais
   claro come contraste do texto secundário exatamente como o LCD faz. */
#define VITA_FUNDO             RGBA8( 12,  20,  34, 255)
#define VITA_COL_AMBER         RGBA8( 96, 176, 255, 255)
#define VITA_COL_AMBER_BRIGHT  RGBA8(166, 212, 255, 255)
#define VITA_COL_TEXT          RGBA8(226, 234, 246, 255)
#define VITA_COL_TEXT_DIM      RGBA8(148, 167, 196, 255)
#define VITA_COL_TEXT_FAINT    RGBA8(116, 136, 168, 255)
#define VITA_COL_COLD          RGBA8( 34,  58,  92, 255)
#define VITA_COL_ALARM         RGBA8(255, 122, 106, 255)
#define VITA_COL_BAR_BED       RGBA8( 28,  42,  64, 255)

typedef struct {
    const char  *nome;
    unsigned int fundo, amber, amber_bright, text, text_dim, text_faint,
                 cold, alarm, bar_bed;
} Tema;

static const Tema TEMAS[] = {
    { "amber", VINYL_FUNDO, VINYL_COL_AMBER, VINYL_COL_AMBER_BRIGHT,
      VINYL_COL_TEXT, VINYL_COL_TEXT_DIM, VINYL_COL_TEXT_FAINT,
      VINYL_COL_COLD, VINYL_COL_ALARM, VINYL_COL_BAR_BED },
    { "vita",  VITA_FUNDO,  VITA_COL_AMBER,  VITA_COL_AMBER_BRIGHT,
      VITA_COL_TEXT,  VITA_COL_TEXT_DIM,  VITA_COL_TEXT_FAINT,
      VITA_COL_COLD,  VITA_COL_ALARM,  VITA_COL_BAR_BED },
};
#define N_TEMAS ((int)(sizeof(TEMAS) / sizeof(TEMAS[0])))

static int g_tema;                     /* índice em TEMAS */
#define TEMA (TEMAS[g_tema])

/* Os nomes de sempre continuam valendo em todo o desenho — o que mudou é que
   agora eles são uma LEITURA, não uma constante. Nenhuma das 251 chamadas
   precisou mudar. */
#define COL_AMBER        (TEMA.amber)
#define COL_AMBER_BRIGHT (TEMA.amber_bright)
#define COL_TEXT         (TEMA.text)
/* ESTES DOIS SUBIRAM, e o motivo é o APARELHO.

   O Vita 2000 é o modelo de LCD, não o de OLED: o preto dele não é preto, é
   um cinza aceso por trás. Uma paleta de fósforo — âmbar sobre quase-preto —
   é feita para o OLED, onde o fundo some de verdade; no LCD o fundo sobe e a
   diferença entre ele e um cinza escuro encolhe.

   Medido contra o fundo (10,14,21), com a fórmula de contraste da WCAG:
     COL_TEXT_DIM    3,14:1   abaixo do mínimo de 4,5 para texto
     COL_TEXT_FAINT  1,91:1   ilegível — e isso num preto IDEAL
   E não é pouco texto: o DIM leva o nome do artista em cada card, as
   contagens e a fila de dicas do rodapé; o FAINT leva as linhas de ajuda.
   Numa tela de 5 polegadas ao sol isso simplesmente não está lá.

   Os valores novos mantêm a matiz cinza-fria (é a mesma cor, mais acesa) e
   passam de 5,0:1 e 3,5:1 — folga de propósito, porque o preto levantado do
   LCD come contraste que a conta não vê. O tools/contraste.py confere. */
#define COL_TEXT_DIM     (TEMA.text_dim)
#define COL_TEXT_FAINT   (TEMA.text_faint)
#define COL_COLD         (TEMA.cold)
#define COL_ALARM        (TEMA.alarm)

/* tintas (o alfa entra por fora, então o RGB vai com alfa 0) */
#define TINT_SEL         ((TEMA.amber & 0x00FFFFFFu) | (0x1Du << 24))
#define TINT_SEL_ROW     ((TEMA.amber & 0x00FFFFFFu) | (0x14u << 24))
#define TINT_ARMED       ((TEMA.alarm & 0x00FFFFFFu) | (0x33u << 24))
/* o card é o próprio fundo, com alfa — assim ele acompanha o tema */
#define COL_CARD         ((TEMA.fundo & 0x00FFFFFFu) | (200u << 24))
#define COL_BAR_BED      (TEMA.bar_bed)
#define COL_FUNDO        (TEMA.fundo)
/* A MESMA COR DO TEMA, com o alfa que o desenho pedir.

   Havia ~30 lugares escrevendo `AMBER_A(40)` na mão — filetes,
   halos, molduras. Cada um deles é um pedaço do tema que NÃO trocava junto:
   no tema azul a régua embaixo das abas continuava âmbar, e não há como ver
   isso lendo o código, só olhando a tela. */
#define AMBER_A(a)       ((TEMA.amber & 0x00FFFFFFu) | ((unsigned)(a) << 24))
#define AMBERB_A(a)      ((TEMA.amber_bright & 0x00FFFFFFu) | ((unsigned)(a) << 24))
#define ALARM_A(a)       ((TEMA.alarm & 0x00FFFFFFu) | ((unsigned)(a) << 24))
#define COLD_A(a)        ((TEMA.cold & 0x00FFFFFFu) | ((unsigned)(a) << 24))

/* TIPOGRAFIA, escrita em PIXEL DE APARELHO e não em "escala".

   A PVF padrão do vita2d tem em = 18 px exatos quando scale = 1,0: ela é
   montada com scePvfSetResolution(128,128) e scePvfSetCharSize(10,125), e
   px = pt * dpi / 72 = 10,125 * 128 / 72 = 18. O 10,125 foi escolhido para
   dar 18 redondo. Daí o PX(): quem lê o desenho vê "17 px" e sabe julgar,
   enquanto "0,56f" não diz nada a ninguém.

   SINTOMA: a tela inteira estava desenhada entre 0,45 e 0,60 — de 8,1 a
   10,8 px numa tela de 5 polegadas. Das 109 chamadas de texto, 88 saíam
   abaixo de 11 px e a MAIOR coisa do app inteiro tinha 19,8. O usuário leu
   a tela de verdade e disse "text is kind of illegible"; estava.

   E não foi descuido: o preview do PC supunha 25 px por em em vez de 18 (o
   número está em tests/hostgfx/vita2d_host.c), então cada PNG saía com a
   tipografia 39% maior que o aparelho. A UI foi julgada nesses PNGs e
   passou. Um preview que erra para o lado generoso APROVA o ilegível.

   Os sete degraus abaixo substituem vinte escalas soltas que iam de 0,45 a
   1,10 — a maioria separada por menos de um pixel, o que não é escala
   tipográfica, é deriva. 13 px é o piso: abaixo disso a PVF perde o desenho
   da letra nesta tela e o rótulo vira mancha cinza. */
#define PVF_EM_PX  18.0f
#define PX(n)      ((float)(n) / PVF_EM_PX)

#define T_MIUDO    PX(13)   /* rodapé, dicas, carimbos — o piso */
#define T_META     PX(15)   /* segunda linha: artista, tempo, contagem */
#define T_CORPO    PX(17)   /* lista, rótulo de card, campo de formulário */
#define T_DESTAQUE PX(20)   /* a linha que importa dentro de um item */
#define T_SECAO    PX(22)   /* "nada no prato", vazios, cerimônia */
#define T_CABECA   PX(24)   /* o título da tela */
#define T_TITULO   PX(30)   /* o nome da faixa tocando: a maior coisa da tela */

/* As margens e as faixas da tela vêm do ui_layout.c, que é puro e por isso
   MEDÍVEL: o teste de host varre resoluções e exige que todo retângulo caiba.
   Número solto no meio do desenho é sempre a tela de quem escreveu. */
/* Os mesmos números do ui_layout.h — que é onde eles moram. Ver a nota lá:
   escritos duas vezes, eles JÁ divergiram uma vez, e o sintoma foi uma linha
   cortada no pé da lista com os dois lados se achando certos. */
#define PAD_X    UI_PAD_X
#define HEAD_Y   UI_HEAD_Y
#define BODY_Y   UI_BODY_Y
#define FOOT_Y   (SCRH - UI_FOOT_DY)

typedef enum { VIEW_SHELF = 0, VIEW_DECK, VIEW_RECS, VIEW_PLAYLISTS,
               VIEW_HANDOFF, VIEW_CONTA, VIEW_QOBUZ, VIEW_AJUSTES,
               VIEW_CONTROLES, VIEW_ARTISTAS, VIEW_HOME } View;

/* A MÍDIA NO PRATO. O vinil é o visual de origem do app; o CD é a outra
   metade da mesma ideia, e quem gosta de um raramente gosta dos dois ao
   mesmo tempo. É escolha da pessoa, e por isso mora nos ajustes — não num
   combo de botão que ninguém descobre. */
typedef enum { MIDIA_VINIL = 0, MIDIA_CD, MIDIA_N } Midia;

/* A FILA DE ABAS — e por que ela existe.

   SINTOMA, nas palavras do dono: "qobuz simply doesn't exist". E do lado
   dele isso era LITERAL. Para chegar ao Qobuz era preciso, a partir da
   estante, apertar R1 três vezes: estante → listas → conta → Qobuz. Nenhuma
   dessas telas dizia a palavra "Qobuz" antes da última; a dica da estante
   dizia "R1 playlists", a das listas dizia "R1 account", e só a da conta
   dizia "R1 qobuz". Ou seja: o caminho existia, e a única forma de descobri-
   lo era percorrê-lo às cegas até o fim. Uma tela que ninguém acha é uma
   tela que não existe.

   O anel sempre esteve lá — o que faltava era ele ser VISÍVEL. Agora L1 e R1
   andam nesta fila em TODA tela, a fila inteira fica desenhada no topo com a
   atual acesa, e o dedo pode tocar direto na que quiser. Nada mais se
   descobre por tentativa.

   VIEW_HANDOFF não entra: ela é um detalhe do deck (R1+△), não um destino. */
#define UI_NABAS 9
static const View ABAS[UI_NABAS] = {
    VIEW_HOME, VIEW_SHELF, VIEW_ARTISTAS, VIEW_DECK, VIEW_QOBUZ,
    VIEW_PLAYLISTS, VIEW_RECS, VIEW_CONTA, VIEW_AJUSTES
};
/* A aba da loja chamava-se QOBUZ, e passou a mentir no dia em que o
   SoundCloud virou a segunda fonte: a pessoa escolhia SoundCloud nos ajustes,
   entrava na aba e lia "QOBUZ" no alto da tela que ia buscar no outro
   serviço. Trocar o rótulo pelo nome do serviço ativo não cabe — a fila já
   ocupa quase toda a largura e "SOUNDCLOUD" empurraria o relógio e a bateria
   para fora. Então a aba passa a dizer o que ela FAZ, que vale para as duas,
   e o serviço é dito na própria tela, ao lado do campo de busca. */
static const char *ABA_NOME[UI_NABAS] = {
    "HOME", "SHELF", "ARTISTS", "PLAYING", "SEARCH", "LISTS", "RECS",
    "ACCOUNT", "SETTINGS"
};

/* AS LINHAS DOS AJUSTES.

   Existem porque a alternativa era mais um atalho escondido. Um app que
   ensina "R1+quadrado cicla a soneca" está pedindo para a pessoa decorar o
   que ele devia mostrar; e no Vita, que tem tela sensível ao toque, uma
   opção que só existe como combinação de botão é uma opção que não existe.
   Cada linha aqui se lê, se navega com o d-pad E se toca com o dedo. */
enum { AJ_TEMA = 0, AJ_MIDIA, AJ_TRASEIRA, AJ_SONECA, AJ_FUNDO,
       AJ_FONTE, AJ_CONTROLES, AJ_N };

/* DE ONDE A BUSCA PROCURA.

   O SoundCloud entrou como segunda fonte de rede e ficou meses sem torneira:
   o app sabia TOCAR uma faixa `sc:` — resolver a URL, escolher a
   progressiva, recusar a prévia — e não havia como uma chegar até ele. Este
   ajuste é a torneira, e ele é um AJUSTE e não um atalho porque foi
   exatamente isso que ele pediu: "make a better ui thingy instead of making
   100 shortcuts". */
enum { FONTE_QOBUZ = 0, FONTE_SC, FONTE_N };


/* -1 quando a tela atual não é uma aba (o handoff) */
static int aba_de(View v)
{
    for (int i = 0; i < UI_NABAS; i++) if (ABAS[i] == v) return i;
    return -1;
}

/* ---------- quantas capas cada tela desenha ----------

   MORA AQUI, JUNTO DO CACHE, e não junto de cada tela. O motivo custou uma
   semana e seis `psp2core-*-GPUCRASH` no cartão do dono.

   O cache tinha DEZ lugares. A tela de ARTISTS desenha DOZE círculos e a HOME
   desenha ONZE capas. Um cache menor que a tela não é "um pouco apertado": ele
   DEBULHA — a cada quadro, para caber a última, ele despeja uma que acabou de
   ser desenhada. E despejar quer dizer soltar a textura, num aparelho em que a
   GPU pode estar lendo aquela memória por mais dois quadros (o vita2d é
   triplo-bufferizado; ver TEX_ESPERA). Ler memória solta na GPU do Vita não dá
   erro: trava a GPU e derruba o sistema.

   Por que ninguém viu: no PC a coleção de teste não tem UM arquivo de capa, e
   sem capa nenhuma o cache nunca enche — a varredura passava verde exatamente
   por cima do defeito que ela existe para achar, enquanto o cartão do aparelho
   (339 capas guardadas) travava todo dia. É a lição de sempre deste projeto,
   na sua forma mais cara: TELA MEDIDA VAZIA NÃO É TELA MEDIDA.

   Daí a forma: os números moram um ao lado do outro, o cache SAI deles, e uma
   tela nova que desenhe mais tem de passar por aqui. */
/* CAPAS POR FAIXA DA HOME — E POR QUE DEIXOU DE SER CINCO.

   Cinco capas de 96 px ocupam 528 dos 900 px úteis: quatrocentos pixels de
   preto à direita, em TODAS as três faixas, com a contagem da coleção
   boiando sozinha lá no canto. A estante já é 6 por fileira e a ARTISTS
   também — a HOME era a única tela que parava no meio e parecia recortada.

   Oito é o que cabe com a capa no tamanho MÁXIMO (8×96 + 7×12 = 852 de 900).
   O `home_fila` ainda corta pelo que a largura aceitar naquele quadro, porque
   `lado` também depende da ALTURA que sobrou, e a altura é quem manda quando
   há três seções cheias.

   Este número entra na conta do COVER_CACHE logo abaixo: mudar aqui muda
   quanta textura o app segura na memória de vídeo, e é por isso que ele mora
   junto dos outros. */
#define HOME_FILA 8                          /* capas por faixa da HOME */
#define ART_COLS  6
/* TRÊS fileiras, não duas.

   Com duas, a célula tinha 215 px de altura para um círculo de 100 e um
   rótulo de 20: uma faixa morta de oitenta e cinco pixels entre as fileiras e
   outra no rodapé. A tela lia como um formulário pela metade — e com 109
   artistas nesta coleção, doze por página são nove viradas de página para
   chegar ao fim do alfabeto.

   Três cabem: 410 px de corpo divididos por 3 dão 136, e o círculo mais o
   rótulo mais o vão pedem 135. Dezoito por página, e o espaço vazio some
   porque o desenho passou a ocupá-lo. */
#define ART_ROWS  3
#define ART_PAG   (ART_COLS * ART_ROWS)      /* 18 círculos na ARTISTS */
#define HOME_CAPAS (1 + 3 * HOME_FILA)       /* continuar + três faixas = 25 */

/* A ESTANTE entrou nesta conta. Ela desenhava OITO capas e agora desenha
   dezoito — e o `COVER_CACHE` menor que a tela é exatamente o defeito que
   encheu o cartão de GPUCRASH. Um macro que esquece uma das telas é o mesmo
   erro com outra roupa: as três que desenham capa estão todas aqui. */
#define MAIOR2(a, b) ((a) > (b) ? (a) : (b))
#define COVER_NA_TELA MAIOR2(UI_SHELF_PAGE, MAIOR2(ART_PAG, HOME_CAPAS))

/* ---------- cache de capas ----------
   O desenho antigo chamava vita2d_load_JPEG_buffer e vita2d_free_texture DENTRO
   do laço de cada quadro: nove JPEGs decodificados e jogados fora sessenta
   vezes por segundo na estante, onze nas recomendações. Não é lentidão de
   margem — é o quadro inteiro gasto decodificando a mesma imagem de novo.

   O TAMANHO tem de passar da tela mais cheia, com folga: encostado, trocar de
   aba (ARTISTS -> HOME) despeja tudo de uma vez e paga a decodificação
   inteira de novo. +4 é essa folga. */
#define COVER_CACHE (COVER_NA_TELA + 4)

/* Quantas linhas da lista do deck o toque pode alcançar. O `list_rows` do
   ui_layout tem teto de 6; a folga é para ele poder crescer sem que este
   vetor precise ser lembrado. */
#define DECK_LIN_MAX 12

typedef struct {
    const Album *owner;
    vita2d_texture *tex;
    vita2d_texture *blur;   /* a MESMA capa, 64x64 — ver deck_backdrop */
    bool  blur_tentado;     /* já se tentou: NULL aqui quer dizer "não dá" */
    unsigned age;
} CoverSlot;

/* A CERIMÔNIA. É o que o deck do desktop tinha de próprio e a §5.5 chama de
   sagrado: o prato sai do zero e acelera, o braço vem de fora e desce, a
   agulha encosta. Sem ela um disco "começa a tocar" como um arquivo abre.

   Ela NÃO é encenada ao abrir o app com música já tocando: ali o disco não
   foi posto agora, foi encontrado no meio, e encenar a descida da agulha
   seria mentira sobre o que aconteceu. É a diferença entre um ritual e uma
   animação de abertura. */
typedef enum { RIT_OFF = 0, RIT_SPINUP, RIT_CUE, RIT_DROP } RitualPhase;

#define RIT_SPINUP_S 1.10f
#define RIT_CUE_S    0.65f
#define RIT_DROP_S   0.38f

/* Uma tela inteira de arrasto na almofada de trás vale isto em segundos.
   Fino o bastante para achar o começo de um verso — que é o que a barra da
   frente, com o lado inteiro em 400 px, não dá. */
#define CUE_SEGUNDOS 90.0f

/* Quanto o dedo tem de andar na almofada, em pixels de TELA, para virar uma
   página ou andar uma fileira. Em pixels de tela e não de painel: a área
   ativa de trás tem outra escala, e um limiar escrito na grade do painel
   pediria 40% mais dedo na vertical do que na horizontal — o gesto ficaria
   "meio morto" sem nada acusando. Ver painel_medir. */
#define TRAS_PAGINA  60
#define TRAS_FILEIRA 50

#define SPECT_BANDS 16
#define SPARKS 14

typedef struct { float x, y, vx, vy, life; } Spark;

/* O estado de UM painel de toque, já em coordenadas de TELA. Existe em dois
   exemplares porque o aparelho tem dois painéis e eles se leem igual — o que
   muda é o que cada um comanda, não como se lê um arrasto. */
typedef struct {
    int   x, y;
    bool  down, was_down;
    int   start_x, start_y;
    int   frames;
    bool  moved;
} Toque;

struct Ui {
    /* onde cada aba foi desenhada neste quadro, para o dedo poder acertá-la.
       Preenchido pelo draw_abas, lido pelo ui_handle_input. */
    float aba_x[UI_NABAS], aba_w[UI_NABAS];
    /* tem som saindo AGORA? A fila de abas desenha um ponto ao lado de
       PLAYING quando sim — ver header(). */
    bool tocando;
    /* a estante tem ALGUM disco visível? O desenho sabe (tem a Library); a
       entrada não recebe uma. Ver o uso no ui_handle_input. */
    bool tem_disco;
    /* a PRIMEIRA FILEIRA visível da estante. Rolar por fileira, e não por
       página, é o que tira o salto de oito discos — ver draw_shelf. */
    int shelf_top;

    bool bgm_port_ok;    /* o main conseguiu a porta BGM no arranque */
    vita2d_pvf *font;
    View view;
    int sel;
    int pl_sel;
    int rec_sel;
    float halo_phase;
    float disc_angle;      /* acumula: o disco PÁRA quando a música pára */
    float spin;            /* velocidade do prato, 0..1 — a cerimônia a sobe */
    /* QUANTOS QUADROS DO DECK AINDA VÊM ENXUTOS — ver `draw_deck`. Armado
       quando a tela NÃO é o deck (toda entrada é a "primeira aparição"), e
       consumido só pelo deck, que desenha o mínimo até zerar. É a tela mais
       pesada do app entrando num momento de troca de tela — o instante em
       que todo GPUCRASH deste aparelho caiu. */
    int deck_enxuto;

    /* O retrato do ÚLTIMO quadro do deck, para a caixa-preta: em que degrau
       da rampa ele saiu (lite/medio/full/empty), se o fundo texturizado foi
       desenhado e quantas linhas a lista teve. A caixa-preta escreve ANTES
       de desenhar, então o que ela conta é o quadro anterior — que é
       exatamente o que interessa quando o aparelho cai no quadro atual. */
    const char *deck_stage;
    int deck_tex;
    int deck_linhas;

    RitualPhase rit;
    float rit_t;

    float spect[SPECT_BANDS];
    Spark sparks[SPARKS];

    /* toque: DOIS painéis. O Vita tem a tela sensível na frente e uma
       almofada atrás, onde os dedos já estão segurando o aparelho — e o app
       ignorava a de trás por inteiro. Os dois estados têm a mesma forma, e
       por isso a mesma estrutura. */
    float scrub_to;
    float scrub_pend;    /* para onde o dedo apontou, no quadro em que soltou */
    Toque frente, tras;
    bool  scrubbing;
    bool  cue_tras;      /* o dedo de trás está girando o disco */
    int   midia;         /* Midia: vinil ou CD, escolha da pessoa */
    bool  toque_tras;    /* a almofada de trás responde? (padrão: não) */
    int   aj_sel;        /* linha marcada na tela de ajustes */
    int   art_sel;       /* artista marcado na tela de artistas */
    int   pl_botao;      /* pílula marcada no painel de lista, -1 nenhuma */
    const Rec *rec;      /* o histórico, só para leitura (ver ui_set_rec) */
    int   home_sel;      /* item marcado na home */
    int   home_alvo;     /* índice do álbum sob a marca, -1 se nenhum */
    bool  bg_trava;      /* segurar o botão PS para não ser suspenso */
    int   fonte;         /* FONTE_QOBUZ / FONTE_SC — de onde a busca procura */
    int   sc_sel;        /* linha escolhida na lista do SoundCloud */
    /* A conta do SoundCloud, lida do cartão na primeira vez que a tela dela
       aparece — mesma preguiça do `qb_cfg`. O main tem a sua para RESOLVER a
       URL na hora de tocar; esta é para BUSCAR. Duas cópias de um arquivo só
       de leitura não divergem. */
    ScConfig sc_cfg;
    bool  sc_lida;
    float cue_base;      /* de que ponto do lado ele partiu */
    /* o que o ÚLTIMO quadro do deck desenhou. A entrada é lida antes de
       saber a duração da faixa — ela mora no Player, e o ui_handle_input não
       o recebe —, e o cue relativo precisa de um ponto de partida. */
    float prog;
    int   dur;
    /* qual botão de transporte acabou de ser tocado, e por quantos quadros
       ele fica aceso. Sem esse retorno, o dedo não sabe se o toque pegou —
       e a diferença entre "não pegou" e "pegou e a faixa demorou" é o que
       faz alguém tocar duas vezes. */
    int   tr_aceso, tr_pisca;

    Lyrics lrc;
    bool  show_lyrics;

    /* busca por letra inicial: uma estante de quatrocentos discos não se
       navega item por item, e o d-pad é tudo que existe */
    bool  jump_open;
    int   jump_letter;   /* 0..25 = A..Z, 26 = # */

    /* O FILTRO DA ESTANTE.

       São 388 discos em 49 páginas no cartão do dono deste app. A régua de
       letras corta isso para uma letra; digitar um pedaço do nome corta para
       o que ele quer ver. `vis` guarda os índices dos álbuns que passam, e
       `u->sel` passa a ser a posição DENTRO dessa lista — o ui_selected
       traduz de volta, para que o main continue recebendo o índice real da
       biblioteca e nada lá fora precise saber que existe filtro. */
    char  busca[48];
    int  *vis;
    int   nvis, vis_cap;
    int   vis_para;      /* nalbums para o qual `vis` foi montado */
    bool  busca_suja;
    bool  busca_pedida;  /* o teclado foi aberto para o filtro da estante */

    /* repouso: a tela apaga e a música segue */
    bool  resting;
    int   rest_idle;
    int   rest_skip;

    CoverSlot cache[COVER_CACHE];
    unsigned clock;

    /* orçamento de carga: no máximo um álbum por quadro ganha tags e capa,
       senão rolar a estante trava a cada disco novo */

    /* a tela da conta: ver draw_conta */
    int  conta_sel;
    int  conta_campo;         /* que campo o teclado está editando, -1 nenhum */
    /* A FILA DO LAST.FM, contada de vez em quando e não a cada quadro.
       O lastfm_queue_size abre o arquivo e conta as linhas; a tela de conta
       chamava isso 60 vezes por segundo enquanto estivesse aberta. Uma vez
       por segundo é mais do que suficiente para um número que só muda quando
       uma faixa termina. */
    int  fila_lastfm;
    int  fila_quando;         /* u->clock da última contagem */
    char conta_msg[96];
    unsigned conta_msg_ate;   /* o recado some sozinho; erro que fica é ruído */
    LastfmConfig conta_cfg;
    bool conta_lida;
    char conta_senha[64];     /* só até o login; nunca vai para o cartão */

    /* a loja: ver draw_qobuz */
    QobuzConfig qb_cfg;
    bool qb_lida;
    /* qual pílula de busca recente está marcada, e quantas couberam na tela
       neste quadro — o dedo e o d-pad leem as duas coisas daqui */
    int  qb_rec_sel;
    int  qb_nrec_vis;
    /* A ESTANTE COMO SUGESTÃO DE BUSCA. -1 = o dedo/d-pad está nas pílulas
       de busca recente; >= 0 = está na grade de artistas que a pessoa já
       tem. Ver `qb_art_pilula`. */
    int  qb_art_sel;
    int  qb_nart_vis;
    int  qb_sel;
    int  qb_campo;            /* campo que o teclado edita, -1 nenhum */
    char qb_termo[96];
    char qb_senha[64];
    QobuzAlbum qb_res[12];
    int  qb_nres;
    char qb_msg[96];
    unsigned qb_msg_ate;
    /* streaming: abrir um disco para tocar pela rede */
    bool qb_abrindo;          /* qobuz_abre_async em curso */
    QobuzAlbum qb_ab_alb;     /* o álbum que está sendo aberto */

    /* A TROCA POR LOSSLESS: "toque a versão em FLAC desta música daqui".
       `casando` é a busca em curso; `casa_msg` é o que a tela diz depois —
       inclusive quando NÃO deu, porque "achei, mas a duração não bate" manda
       a pessoa a algum lugar e um silêncio não manda. */
    /* A CAPA PEDIDA pelo desenho deste quadro, servida no PRÓXIMO — e fora da
       cena da GPU. Ver a nota grande no cover_tex: criar textura com uma cena
       aberta é mapear memória de GPU no meio da lista de display, e foi isso
       que voltou a encher o cartão de GPUCRASH. */
    Album *pede_capa;
    /* o álbum cujo fundo esborratado falta construir — ver o blur_serve */
    const Album *pede_blur;
    char   pede_qb[32];

    /* onde o interruptor do 2º plano ficou na tela do handoff, para o dedo */
    float hoff_x, hoff_y, hoff_w, hoff_h;

    /* ONDE CADA LINHA DA LISTA DO DECK CAIU, e a que faixa ela pertence.
       Preenchido pelo desenho, lido pelo toque — ver a nota no draw_deck. */
    float deck_lin_y[DECK_LIN_MAX];
    int   deck_lin_i[DECK_LIN_MAX];
    int   deck_nlin;
    int   deck_alvo;       /* a faixa que o dedo escolheu na lista do deck */

    bool casando;
    char casa_msg[128];
    unsigned casa_msg_ate;
    float casa_x, casa_y, casa_w, casa_h;   /* onde a pílula ficou, para o dedo */

    Playlist *plists;
    int nplists;
    const Track **recs;
    int nrecs;
    bool pl_armed;

    /* ORÇAMENTO DE GPU: frames lentos reduzem desenho para dar folga à
       composição do sistema (sobretudo o overlay de volume). O toggle é
       POR QUADRO — se o quadro anterior gastou mais que o teto, este
       entra em modo enxuto. A volta ao normal é gradual (uns 5 quadros
       lentos bastam para estabilizar). */
    bool  gpu_safe;        /* modo enxuto: menos sulcos, sem espectro */
    int   gpu_slow_frames; /* quantos quadros seguidos passaram do teto */
#ifdef __vita__
    SceRtcTick gpu_t0;     /* tick de ANTES do start_drawing deste quadro */
    unsigned long gpu_ms;  /* quanto o quadro anterior gastou MONTANDO a lista */
#endif

    bool  input_locked;    /* R1+L1 trava todos os inputs até destravar */
    bool  ritual_just_done;/* cerimônia acabou neste quadro (consumido por ui_ritual_done) */
};

/* ═══ O TEXTO REDUZIDO SAÍA QUEBRADO ═════════════════════════════════════

   SINTOMA, nas palavras do dono: "the text shows fine but its like, low res
   and you cant read properly". E o preview do PC nunca mostrou isso, porque
   ali quem desenha é o FreeType, que rasteriza no tamanho final e sai nítido
   em qualquer escala.

   No aparelho é outra coisa. O `vita2d_load_system_pvf` chama
   `scePvfSetCharSize` UMA vez — 10,125 pt a 128 dpi = 18 px exatos — e
   guarda os glifos rasterizados nesse tamanho num atlas. O
   `vita2d_pvf_draw_text` não rasteriza nada: ele ESCALA a textura do atlas.

   E o filtro dessa textura, no `texture_atlas_create` deste libvita2d.a:

       vita2d_texture_set_filters(tex, 0, 1)   -> min=POINT, mag=LINEAR

   Ampliar é suave; REDUZIR é vizinho-mais-próximo. Os três tamanhos mais
   usados do app são reduções — 13, 15 e 17 px a partir de 18 —, e a 13 px
   isso descarta 28% das linhas e colunas do glifo. O traço horizontal de um
   "e" some. Não é "um pouco borrado": é a letra perdendo pedaço.

   ── POR QUE MEXER NA ENTRANHA, E COMO ISSO É SEGURO ────────────────────

   O `vita2d_pvf` é opaco e não há função para trocar o filtro depois. Os
   dois deslocamentos abaixo NÃO foram adivinhados de um código-fonte de
   memória — saíram do desmonte DESTE arquivo:

       generic_pvf_draw_text:  ldr r3, [r6, #8]   -> vita2d_pvf + 8 = atlas
       texture_atlas_create:   str r0, [r4, #0]   -> atlas + 0 = textura

   E mesmo assim a leitura é CONFERIDA antes de valer: só se a largura da
   textura for um tamanho de atlas plausível é que o filtro é trocado. Num
   vita2d com outro layout, a conferência falha e nada acontece — o texto
   continua como está hoje, que é o pior caso aceitável.

   O conserto de verdade seria rasterizar em cada tamanho, com um atlas por
   corpo. Isto aqui é o que cabe sem escrever um renderizador de fonte
   inteiro às cegas num aparelho que não dá para depurar. */
static void pvf_filtro_linear(vita2d_pvf *f)
{
#ifdef __vita__
    if (!f) return;
    void **como_vetor = (void **)f;
    void **atlas = (void **)como_vetor[2];          /* +8 bytes = índice 2 */
    if (!atlas) return;
    vita2d_texture *tex = (vita2d_texture *)atlas[0];
    if (!tex) return;
    unsigned int w = vita2d_texture_get_width(tex);
    unsigned int h = vita2d_texture_get_height(tex);
    /* A CONFERÊNCIA. Um atlas de fonte tem centenas de pixels de lado; um
       ponteiro lido do lugar errado devolve qualquer coisa. Se não for
       plausível, desiste — e o app fica exatamente como estava. */
    if (w < 64 || w > 4096 || h < 64 || h > 4096) return;
    vita2d_texture_set_filters(tex, SCE_GXM_TEXTURE_FILTER_LINEAR,
                                    SCE_GXM_TEXTURE_FILTER_LINEAR);
#else
    (void)f;
#endif
}

/* ---------- primitivas ---------- */

/* Um disco cheio é UMA chamada de desenho, não uma por linha de tela.

   O vita2d TEM primitiva de círculo (vita2d_draw_fill_circle), e cada
   vita2d_draw_rectangle vira um sceGxmDraw próprio — não há agrupamento,
   conferido desmontando o libvita2d.a. Desenhar um disco de raio 166 linha
   a linha eram ~330 chamadas de GPU para uma forma que a biblioteca faz em
   uma. */
static void fill_circle(float cx, float cy, float r, unsigned int color)
{
    if (r <= 0) return;
    vita2d_draw_fill_circle(cx, cy, r, color);
}

/* Um anel FINO é uma circunferência, e uma circunferência desenha com
   segmentos de reta.

   O laço linha a linha emite DOIS retângulos por linha de tela que o anel
   cruza — num anel de raio 36 são ~144 chamadas de desenho, e cada
   vita2d_draw_rectangle é um sceGxmDraw próprio (não há agrupamento;
   conferido no libvita2d.a). Com 14 sulcos por card e 8 cards, a estante
   passava de vinte mil chamadas por quadro.

   Em segmentos, o mesmo anel custa uma chamada por segmento. O número sai
   do raio: o erro de corda de um polígono de n lados é r*(1-cos(pi/n)), e
   manter isso abaixo de meio pixel é o que decide — abaixo disso o olho não
   separa do círculo. */
/* Um número que a GPU pode receber sem travar.

   Uma coordenada NaN ou infinita vira lixo dentro do sceGxm, e a GPU do Vita
   não devolve erro: ela TRAVA, e a trava derruba o sistema inteiro. Escrito
   como `!(x > lo && x < hi)` de propósito — com NaN toda comparação é falsa,
   então NaN cai no ramo do "não desenhe", que é o que se quer. */
static bool coord_ok(float x)
{
    return (x > -100000.0f && x < 100000.0f);
}

static void ring_segmentos(float cx, float cy, float r, unsigned int color)
{
    /* r NaN faria `(int)(6*sqrtf(NaN))` ser indefinido — e um n negativo ou
       gigante é uma trava de GPU, não um desenho feio. */
    if (!(r > 0.0f) || !(r < 100000.0f)) return;
    if (!coord_ok(cx) || !coord_ok(cy)) return;   /* o centro também vai cru */
    int n = (int)(6.0f * sqrtf(r));        /* erro de corda < 0,5 px */
    if (n < 12) n = 12;
    if (n > 96) n = 96;

    /* O ANEL INTEIRO NUM SCE_GXM_DRAW SÓ, e é esta a pendência grande que a
       varredura anunciava desde o dia em que nasceu.

       Antes, cada segmento era um `vita2d_draw_line` = um sceGxmDraw; um anel
       de raio 230 custava 96 chamadas e o deck desenha ~20 anéis — ~2000
       chamadas só de circunferências, e era essa lista de display que
       estourava no momento em que o overlay de volume do sistema compunha por
       cima (sintoma: psp2core-*-GPUCRASH ao apertar volume durante música).

       O `vita2d_draw_array` desenha um vetor inteiro de vértices em UMA
       chamada (conferido no libvita2d.a deste SDK: dá um único sceGxmDraw no
       fim) com cor POR VÉRTICE — que é o que os arcos do lustro precisam. Ele
       NÃO copia: os vértices têm de vir do `vita2d_pool_memalign`, que é de
       onde o próprio draw_line desenha, alinhados a 16. */    vita2d_color_vertex *v =
        (vita2d_color_vertex *)vita2d_pool_memalign(
        (unsigned int)(2 * n * sizeof(vita2d_color_vertex)), 16);
    if (!v) return;
    /* ═══ A COSTURA HORIZONTAL NO MEIO DO DISCO ══════════════════════════
     *
     * `SCE_GXM_PRIMITIVE_LINES` desenha PARES independentes, e segmentos
     * vizinhos compartilham um vértice — que então é pintado DUAS VEZES.
     * Com alfa isso compõe duas vezes: no corpo do disco (32,37,47), um
     * sulco escuro a 0,42 dá (20,23,31) numa passada e (13,15,22) em duas.
     * Foi assim que se achou: os pixels da linha batiam com a segunda conta.
     *
     * Sozinho seria um pontilhado invisível. O problema é que TODO anel
     * começava no ângulo zero, então os vértices dobrados de todos eles se
     * empilhavam em 3 e 9 horas — e o disco ganhava uma cicatriz horizontal
     * atravessando o meio, nos dois lados do rótulo.
     *
     * A fase por raio espalha esses vértices: eles continuam existindo (é o
     * preço de um anel num sceGxmDraw só), mas viram ruído de um pixel em
     * vez de uma linha reta. Um círculo não tem lado certo para começar. */
    float passo = 6.2831853f / (float)n;
    float fase = r * 0.7f;
    for (int i = 0; i < n; i++) {
        float a0 = fase + passo * (float)i, a1 = fase + passo * (float)(i + 1);
        v[2 * i + 0].x = cx + cosf(a0) * r;
        v[2 * i + 0].y = cy + sinf(a0) * r;
        v[2 * i + 0].z = 0.0f;
        v[2 * i + 0].color = color;
        v[2 * i + 1].x = cx + cosf(a1) * r;
        v[2 * i + 1].y = cy + sinf(a1) * r;
        v[2 * i + 1].z = 0.0f;
        v[2 * i + 1].color = color;
    }
    vita2d_draw_array(SCE_GXM_PRIMITIVE_LINES, v, (size_t)(2 * n));
}

static void ring_circle(float cx, float cy, float r, float th, unsigned int color)
{
    if (!coord_ok(cx) || !coord_ok(cy) || !coord_ok(r) || !coord_ok(th)) return;
    if (r <= 0 || th <= 0) return;
    /* ═══ NÃO HÁ MAIS CAMINHO DE ESCADINHA ════════════════════════════════
     *
     * Um anel grosso era desenhado varrendo a tela linha a linha e emitindo
     * um ou dois `vita2d_draw_rectangle` por bloco — o gerador de geometria
     * mais complicado deste arquivo, com dois laços aninhados, uma condição
     * de "furo" que abre e fecha, e aritmética de inteiro para as bordas.
     *
     * Um anel de espessura N é N circunferências encostadas, e a
     * circunferência já é UMA chamada (`ring_segmentos` manda o vetor inteiro
     * num `vita2d_draw_array`). Um anel de 2 px passa de ~130 retângulos para
     * DOIS lotes. É mais barato, e some o único gerador que ainda tinha
     * caminhos que nenhum teste percorria.
     *
     * O desenho é o mesmo: as bordas já eram serrilhadas (não há filtragem),
     * e a espessura destes anéis vai de 1 a ~2,2 px no app inteiro. */
    if (th > 1.6f) {
        int camadas = (int)(th + 0.5f);
        if (camadas < 2) camadas = 2;
        if (camadas > 8) camadas = 8;          /* nada neste app passa disso */
        for (int i = 0; i < camadas; i++) {
            float rr = r - th * 0.5f + (float)i + 0.5f;
            if (rr > 0.5f) ring_segmentos(cx, cy, rr, color);
        }
        return;
    }
    ring_segmentos(cx, cy, r, color);
    return;
#if 0   /* o caminho antigo, guardado só para leitura */
    if (th <= 1.6f) { ring_segmentos(cx, cy, r, color); return; }
    int ymin = (int)(cy - r - th), ymax = (int)(cy + r + th);
    /* O LAÇO TEM DE CABER NA TELA.

       Cada volta emite um vita2d_draw_rectangle, e cada um desses é um
       sceGxmDraw próprio. Sem este corte, um raio grande demais (ou vindo de
       uma animação que escapou) enfileira milhares de chamadas por quadro —
       a maioria FORA da tela, todas custando — e é assim que a lista de
       display estoura. Cortar em 0..SCRH não muda um pixel do que se vê. */
    if (ymin < 0) ymin = 0;
    if (ymax > SCRH - 1) ymax = SCRH - 1;
    /* UMA LINHA POR VEZ ERA O PIOR CASO PAGO NA ALTURA TODA.

       Cada volta emite um ou dois `vita2d_draw_rectangle`, e cada um é um
       `sceGxmDraw` no aparelho. O disco do deck tem raio ~145: um anel grosso
       dele saía com trezentas chamadas, e a tela desenha vários.

       Mas as duas bordas do anel quase não andam perto do EQUADOR — de uma
       linha para a seguinte elas mudam uma fração de pixel — e só correm
       perto dos polos. Junta as linhas vizinhas enquanto NENHUMA das duas
       bordas passar de um pixel de diferença, e desenha o bloco de uma vez.

       O que se vê não muda: a borda já é serrilhada (não há filtragem), e
       perto dos polos, onde a curva corre, cada linha continua sendo sua. */
    int y = ymin;
    while (y <= ymax) {
        float dy = (float)y - cy;
        if (fabsf(dy) > r + th) { y++; continue; }
        float ho = (r + th) * (r + th) - dy * dy;
        ho = ho < 0 ? 0 : sqrtf(ho);
        float di = (r - th) * (r - th) - dy * dy;
        bool furo = (di >= 0 && r > th);
        float hi = furo ? sqrtf(di) : 0.0f;

        int fim = y;
        while (fim + 1 <= ymax) {
            float dy2 = (float)(fim + 1) - cy;
            if (fabsf(dy2) > r + th) break;
            float ho2 = (r + th) * (r + th) - dy2 * dy2;
            ho2 = ho2 < 0 ? 0 : sqrtf(ho2);
            float di2 = (r - th) * (r - th) - dy2 * dy2;
            bool furo2 = (di2 >= 0 && r > th);
            if (furo2 != furo) break;              /* o furo abriu ou fechou */
            if (fabsf(ho2 - ho) > 1.0f) break;
            float hi2 = furo2 ? sqrtf(di2) : 0.0f;
            if (furo && fabsf(hi2 - hi) > 1.0f) break;
            /* o bloco fica com a MENOR borda externa e a MAIOR interna:
               transbordar para fora do anel se vê, faltar por dentro não */
            if (ho2 < ho) ho = ho2;
            if (furo && hi2 > hi) hi = hi2;
            fim++;
        }
        float alt = (float)(fim - y + 1);
        int xo0 = (int)(cx - ho), xo1 = (int)(cx + ho);
        if (furo) {
            int xi0 = (int)(cx - hi), xi1 = (int)(cx + hi);
            if (xi0 - 1 >= xo0)
                vita2d_draw_rectangle(xo0, y, (float)(xi0 - 1 - xo0 + 1), alt, color);
            if (xo1 - (xi1 + 1) + 1 > 0)
                vita2d_draw_rectangle(xi1 + 1, y, (float)(xo1 - (xi1 + 1) + 1), alt, color);
        } else {
            if (xo1 >= xo0)
                vita2d_draw_rectangle(xo0, y, (float)(xo1 - xo0 + 1), alt, color);
        }
        y = fim + 1;
    }
#endif
}

/* Um ARCO, e não um anel: `a0`..`a1` em radianos, com o alfa esmaecendo nas
   duas pontas. É o que permite desenhar luz que pega num PEDAÇO do disco —
   um anel inteiro seria outro sulco, não um brilho. */
static void arco(float cx, float cy, float r, float a0, float a1,
                 int segs, float alfa, unsigned int rgb)
{
    /* `r <= 0` NÃO RECUSA NaN — toda comparação com NaN é falsa, e um raio
       NaN atravessava esta linha inteira para virar 2*segs vértices NaN num
       `vita2d_draw_array`, que é o caminho mais curto que este app tem até a
       GPU. O mesmo vale para o centro e para os dois ângulos, que nunca
       foram conferidos aqui. Escrito ao contrário, o NaN cai na recusa. */
    if (!(r > 0.0f) || segs < 2 || !(alfa > 0.0f)) return;
    if (!coord_ok(cx) || !coord_ok(cy) || !coord_ok(r) ||
        !coord_ok(a0) || !coord_ok(a1)) return;
    /* O mesmo lote do ring_segmentos: um sceGxmDraw por arco, não por
       segmento. A cor POR VÉRTICE guarda o esmaecimento nas pontas — que é o
       que o loop abaixo fazia linha a linha. */
    vita2d_color_vertex *v =
        (vita2d_color_vertex *)vita2d_pool_memalign(
        (unsigned int)(2 * segs * sizeof(vita2d_color_vertex)), 16);
    if (!v) return;
    float passo = (a1 - a0) / (float)segs;
    for (int i = 0; i < segs; i++) {
        float t0 = (float)i / (float)segs;
        float t1 = (float)(i + 1) / (float)segs;
        /* seno de 0..pi: apaga nas pontas e cheio no meio, para o brilho não
           terminar num corte reto — que é o que denuncia o desenho */
        float m = sinf(((t0 + t1) * 0.5f) * 3.14159265f);
        unsigned int c = (rgb & 0x00FFFFFF) |
                         ((unsigned int)(alfa * m * 255.0f) << 24);
        float b0 = a0 + passo * (float)i, b1 = a0 + passo * (float)(i + 1);
        v[2 * i + 0].x = cx + cosf(b0) * r;
        v[2 * i + 0].y = cy + sinf(b0) * r;
        v[2 * i + 0].z = 0.0f;
        v[2 * i + 0].color = c;
        v[2 * i + 1].x = cx + cosf(b1) * r;
        v[2 * i + 1].y = cy + sinf(b1) * r;
        v[2 * i + 1].z = 0.0f;
        v[2 * i + 1].color = c;
    }
    vita2d_draw_array(SCE_GXM_PRIMITIVE_LINES, v, (size_t)(2 * segs));
}

static void alpha_fill(float cx, float cy, float r, float a, unsigned int rgb)
{
    if (!(a > 0)) return;
    if (a > 1) a = 1;
    unsigned int c = (rgb & 0x00FFFFFF) | ((unsigned int)(a * 255.0f) << 24);
    fill_circle(cx, cy, r, c);
}

static void alpha_ring(float cx, float cy, float r, float th, float a, unsigned int rgb)
{
    if (!(a > 0)) return;
    if (a > 1) a = 1;
    unsigned int c = (rgb & 0x00FFFFFF) | ((unsigned int)(a * 255.0f) << 24);
    ring_circle(cx, cy, r, th, c);
}

/* ---------- texto ---------- */

/* linha grossa (o vita2d só tem linha de 1px) */
static void thick_line(float x0, float y0, float x1, float y1, float w,
                       unsigned int color)
{
    float dx = x1 - x0, dy = y1 - y0;
    float len = sqrtf(dx * dx + dy * dy);
    if (len < 0.001f) return;
    float nx = -dy / len, ny = dx / len;
    for (float o = -w / 2; o <= w / 2; o += 0.5f)
        vita2d_draw_line(x0 + nx * o, y0 + ny * o, x1 + nx * o, y1 + ny * o, color);
}

/* ---------- o texto que a fonte do aparelho consegue desenhar ----------

   O que passa por aqui não é só literal do programa: é NOME DE ARQUIVO, tag
   de MP3, título vindo do Qobuz — texto que outra pessoa escreveu, em outro
   computador, com outro teclado. E um caractere que a PVF do sistema não tem
   NÃO some: vira um quadradinho. Nesta coleção, na tela de recomendados, um
   título com aspas curvas aparecia literalmente assim:

       []All I need[] but its finally shoegazed

   Duas coisas diferentes acontecem aqui, e as duas vêm de fora:

   1. ASPAS E TRAÇOS TIPOGRÁFICOS. A aspa curva é U+201C e falta na maioria
      das fontes de interface; a reta existe em todas. Trocar é perda zero —
      ninguém lê aspa reta como defeito, e todo mundo lê quadradinho como
      defeito.

   2. NOME DE ARQUIVO QUE NÃO É UTF-8. Cartão FAT32 gravado por Windows traz
      nome em CP1252, e ali a aspa curva é UM byte: 0x93. Lido como UTF-8
      aquilo é sequência inválida e o que sai na tela é lixo — inclusive nos
      acentos, que é como um "coração" vira "coraÃ§Ã£o". Aqui um byte solto é
      promovido pela tabela do CP1252, que é de onde ele veio.

   O que NÃO se faz: trocar por "?" o que não se reconhece. Um título em
   japonês, num aparelho da Sony, tem chance real de ter fonte; três
   interrogações não têm chance nenhuma de virar o título de volta. Só se
   troca o que tem equivalente ASCII de verdade.

   O tools/glifos.py é o outro lado desta regra: ele confere os literais que
   NÓS escrevemos; isto trata o texto que chega de fora, que nenhuma
   conferência de código alcança. */

/* O CP1252 nos 32 lugares em que ele difere do Latin-1 — e é justamente essa
   faixa que carrega as aspas curvas e os travessões do Word. */
static const unsigned short CP1252_ALTO[32] = {
    0x20AC, 0x0081, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021,
    0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0x008D, 0x017D, 0x008F,
    0x0090, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014,
    0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0x009D, 0x017E, 0x0178
};

/* Um caractere UTF-8; byte inválido volta como CP1252 em vez de virar lixo. */
static unsigned int utf8_prox(const unsigned char **pp)
{
    const unsigned char *p = *pp;
    unsigned int c = *p;
    int extra = 0;
    unsigned int cp = 0;

    if (c < 0x80)                    { *pp = p + 1; return c; }
    else if ((c & 0xE0) == 0xC0)     { cp = c & 0x1F; extra = 1; }
    else if ((c & 0xF0) == 0xE0)     { cp = c & 0x0F; extra = 2; }
    else if ((c & 0xF8) == 0xF0)     { cp = c & 0x07; extra = 3; }
    else                             { *pp = p + 1;
                                       return c < 0xA0 ? CP1252_ALTO[c - 0x80] : c; }

    for (int i = 1; i <= extra; i++)
        if ((p[i] & 0xC0) != 0x80) {   /* não era UTF-8: era um byte de 8 bits */
            *pp = p + 1;
            return c < 0xA0 ? CP1252_ALTO[c - 0x80] : c;
        }
    for (int i = 1; i <= extra; i++) cp = (cp << 6) | (p[i] & 0x3F);
    *pp = p + extra + 1;
    return cp;
}

/* O equivalente ASCII, quando existe DE VERDADE. NULL = deixa como está. */
static const char *troca_ascii(unsigned int cp)
{
    switch (cp) {
    case 0x00A0: return " ";                                  /* espaço fixo */
    case 0x00AD: case 0xFEFF: return "";        /* invisíveis, e só atrapalham */
    case 0x2018: case 0x2019: case 0x201A: case 0x201B:
    case 0x2032: return "\'";
    case 0x201C: case 0x201D: case 0x201E: case 0x201F:
    case 0x2033: return "\"";
    case 0x2010: case 0x2011: case 0x2012: case 0x2015:
    case 0x2212: return "-";
    case 0x2022: return "·";                       /* marcador vira ponto médio */
    case 0x2044: return "/";
    case 0x2039: return "<";
    case 0x203A: return ">";
    case 0x02C6: return "^";
    case 0x02DC: return "~";
    case 0x2030: return "%";
    case 0x0192: return "f";
    }
    return NULL;
}

static void utf8_poe(char **d, char *fim, unsigned int cp)
{
    if (cp < 0x80) {
        if (*d + 1 < fim) *(*d)++ = (char)cp;
    } else if (cp < 0x800) {
        if (*d + 2 < fim) {
            *(*d)++ = (char)(0xC0 | (cp >> 6));
            *(*d)++ = (char)(0x80 | (cp & 0x3F));
        }
    } else if (cp < 0x10000) {
        if (*d + 3 < fim) {
            *(*d)++ = (char)(0xE0 | (cp >> 12));
            *(*d)++ = (char)(0x80 | ((cp >> 6) & 0x3F));
            *(*d)++ = (char)(0x80 | (cp & 0x3F));
        }
    } else {
        if (*d + 4 < fim) {
            *(*d)++ = (char)(0xF0 | (cp >> 18));
            *(*d)++ = (char)(0x80 | ((cp >> 12) & 0x3F));
            *(*d)++ = (char)(0x80 | ((cp >> 6) & 0x3F));
            *(*d)++ = (char)(0x80 | (cp & 0x3F));
        }
    }
}

/* Devolve `dst`, sempre — é feito para entrar direto na chamada de desenho. */
static const char *tela_texto(char *dst, size_t cap, const char *src)
{
    char *d = dst, *fim = dst + cap;
    if (!src) { dst[0] = 0; return dst; }
    const unsigned char *p = (const unsigned char *)src;
    while (*p && d + 4 < fim) {
        unsigned int cp = utf8_prox(&p);
        if (cp < 0x20) { if (cp) *d++ = ' '; continue; }  /* controle vira espaço */
        /* AS FORMAS DE LARGURA INTEIRA. Quem baixa vídeo da internet troca os
           caracteres que o sistema de arquivos proíbe pelo gêmeo de largura
           inteira: a aspa vira U+FF02, a interrogação U+FF1F, a barra U+FF0F.
           O nome fica válido no cartão e ilegível na tela — foi exatamente
           assim que apareceu, nas recomendações desta coleção,
           "[]All I need[] but its finally shoegazed". O bloco inteiro é o
           ASCII deslocado de 0xFEE0, então desfazer é uma subtração. */
        if (cp >= 0xFF01 && cp <= 0xFF5E) cp -= 0xFEE0;
        else if (cp == 0x3000) cp = ' ';          /* o espaço ideográfico */
        const char *t = troca_ascii(cp);
        if (t) { while (*t && d + 1 < fim) *d++ = *t++; }
        else   utf8_poe(&d, fim, cp);
    }
    *d = 0;
    return dst;
}

#define TELA_TXT 640

static float text_w(Ui *u, float scale, const char *s)
{
    return (float)vita2d_pvf_text_width(u->font, scale, s);
}

/* Corta no SEPARADOR quando dá, senão no caractere — terminar em "· p…" lê
   como defeito; terminar numa palavra inteira lê como resumo. */
static void elide(Ui *u, char *dst, size_t cap, float scale, float maxw, const char *src)
{
    /* SANEIA ANTES DE MEDIR: o corte é decidido pela largura, e a largura é
       a do texto que vai mesmo ser desenhado. */
    tela_texto(dst, cap, src);
    if (text_w(u, scale, dst) <= maxw) return;
    size_t n = strlen(dst);
    while (n > 1) {
        n--;
        /* não corta no meio de um caractere UTF-8 */
        while (n > 1 && ((unsigned char)dst[n] & 0xC0) == 0x80) n--;
        dst[n] = '\0';
        char probe[512];
        snprintf(probe, sizeof(probe), "%s…", dst);
        if (text_w(u, scale, probe) <= maxw) {
            /* recua até um espaço se ele estiver perto do fim */
            for (size_t k = n; k > 0 && n - k < 12; k--)
                if (dst[k - 1] == ' ' || dst[k - 1] == '-') { dst[k - 1] = '\0'; break; }
            snprintf(dst + strlen(dst), cap - strlen(dst), "…");
            return;
        }
    }
}

static void text(Ui *u, int x, int y, unsigned int col, float scale, const char *s);

/* ---------- glifos dos botões ----------
   O rodapé dizia "[tri] estante  [L1] recs  [R1+quad] soneca  [toque] no
   disco pausa" — uma parede de colchetes que obriga a pessoa a traduzir o
   NOME do botão de volta para o desenho que está na mão dela. Aqui os botões
   são DESENHADOS: ✕ ○ △ □ como forma dentro de um anel, ombros e sistema
   como pastilha com a sigla, e as combinações com um "+" entre as duas. */
typedef enum {
    BTN_CROSS = 0, BTN_CIRCLE, BTN_TRIANGLE, BTN_SQUARE,
    /* Não há BTN_L2R2: o Vita não tem L2 nem R2. Ele existiu aqui,
       desenhava uma pílula "L2/R2" e nenhuma dica jamais o usou —
       um botão que a tela sabia desenhar e o aparelho não tem. */
    BTN_L1, BTN_R1, BTN_SEL, BTN_START,
    BTN_DPAD, BTN_UPDOWN, BTN_LEFTRIGHT, BTN_TOUCH, BTN_TRAS
} Btn;

#define GLIFO_R 8.5f

static float pill(Ui *u, float x, float cy, const char *txt)
{
    float tw2 = text_w(u, T_MIUDO, txt);
    float w = tw2 + 10.0f, h = 15.0f, y = cy - h / 2.0f;
    vita2d_draw_rectangle(x, y, w, 1, COL_AMBER);
    vita2d_draw_rectangle(x, y + h - 1, w, 1, COL_AMBER);
    vita2d_draw_rectangle(x, y, 1, h, COL_AMBER);
    vita2d_draw_rectangle(x + w - 1, y, 1, h, COL_AMBER);
    text(u, (int)(x + 5), (int)(cy + 4), COL_AMBER, T_MIUDO, txt);
    return w;
}

static float glyph(Ui *u, float x, float cy, Btn b)
{
    float r = GLIFO_R, cx = x + r, d = r * 0.44f;
    switch (b) {
    case BTN_CROSS:
        alpha_ring(cx, cy, r, 1.0f, 0.45f, COL_AMBER);
        thick_line(cx - d, cy - d, cx + d, cy + d, 1.8f, COL_AMBER);
        thick_line(cx - d, cy + d, cx + d, cy - d, 1.8f, COL_AMBER);
        return 2 * r;
    case BTN_CIRCLE:
        alpha_ring(cx, cy, r, 1.0f, 0.45f, COL_AMBER);
        alpha_ring(cx, cy, d * 1.15f, 1.4f, 0.95f, COL_AMBER);
        return 2 * r;
    case BTN_TRIANGLE:
        alpha_ring(cx, cy, r, 1.0f, 0.45f, COL_AMBER);
        thick_line(cx, cy - d * 1.2f, cx + d, cy + d * 0.8f, 1.6f, COL_AMBER);
        thick_line(cx + d, cy + d * 0.8f, cx - d, cy + d * 0.8f, 1.6f, COL_AMBER);
        thick_line(cx - d, cy + d * 0.8f, cx, cy - d * 1.2f, 1.6f, COL_AMBER);
        return 2 * r;
    case BTN_SQUARE:
        alpha_ring(cx, cy, r, 1.0f, 0.45f, COL_AMBER);
        vita2d_draw_rectangle(cx - d, cy - d, 2 * d, 1.6f, COL_AMBER);
        vita2d_draw_rectangle(cx - d, cy + d, 2 * d, 1.6f, COL_AMBER);
        vita2d_draw_rectangle(cx - d, cy - d, 1.6f, 2 * d, COL_AMBER);
        vita2d_draw_rectangle(cx + d, cy - d, 1.6f, 2 * d + 1.6f, COL_AMBER);
        return 2 * r;
    case BTN_DPAD:
        vita2d_draw_rectangle(cx - 2, cy - r * 0.8f, 4, r * 1.6f, COL_AMBER);
        vita2d_draw_rectangle(cx - r * 0.8f, cy - 2, r * 1.6f, 4, COL_AMBER);
        return 2 * r;
    case BTN_UPDOWN:
        vita2d_draw_rectangle(cx - 2, cy - r * 0.8f, 4, r * 1.6f, COL_AMBER);
        thick_line(cx - 4, cy - r * 0.4f, cx, cy - r * 0.85f, 1.6f, COL_AMBER);
        thick_line(cx + 4, cy - r * 0.4f, cx, cy - r * 0.85f, 1.6f, COL_AMBER);
        thick_line(cx - 4, cy + r * 0.4f, cx, cy + r * 0.85f, 1.6f, COL_AMBER);
        thick_line(cx + 4, cy + r * 0.4f, cx, cy + r * 0.85f, 1.6f, COL_AMBER);
        return 2 * r;
    case BTN_LEFTRIGHT:   /* o mesmo do UPDOWN, deitado */
        vita2d_draw_rectangle(cx - r * 0.8f, cy - 2, r * 1.6f, 4, COL_AMBER);
        thick_line(cx - r * 0.4f, cy - 4, cx - r * 0.85f, cy, 1.6f, COL_AMBER);
        thick_line(cx - r * 0.4f, cy + 4, cx - r * 0.85f, cy, 1.6f, COL_AMBER);
        thick_line(cx + r * 0.4f, cy - 4, cx + r * 0.85f, cy, 1.6f, COL_AMBER);
        thick_line(cx + r * 0.4f, cy + 4, cx + r * 0.85f, cy, 1.6f, COL_AMBER);
        return 2 * r;
    case BTN_TOUCH:   /* um dedo tocando: o arco é a ponta, os traços o toque */
        alpha_ring(cx, cy + 2, r * 0.62f, 1.3f, 0.85f, COL_AMBER);
        thick_line(cx - r * 0.75f, cy - r * 0.75f, cx - r * 0.35f, cy - r * 0.3f, 1.4f, COL_AMBER);
        thick_line(cx + r * 0.75f, cy - r * 0.75f, cx + r * 0.35f, cy - r * 0.3f, 1.4f, COL_AMBER);
        return 2 * r;
    case BTN_TRAS:  /* o aparelho de perfil e o dedo POR BAIXO dele */
        vita2d_draw_rectangle(cx - r * 0.85f, cy - r * 0.55f, r * 1.7f, 1.3f, COL_AMBER);
        vita2d_draw_rectangle(cx - r * 0.85f, cy + r * 0.30f, r * 1.7f, 1.3f, COL_AMBER);
        vita2d_draw_rectangle(cx - r * 0.85f, cy - r * 0.55f, 1.3f, r * 0.85f, COL_AMBER);
        vita2d_draw_rectangle(cx + r * 0.85f, cy - r * 0.55f, 1.3f, r * 0.85f, COL_AMBER);
        alpha_fill(cx, cy + r * 0.80f, r * 0.30f, 0.95f, COL_AMBER);
        return 2 * r;
    case BTN_L1:    return pill(u, x, cy, "L1");
    case BTN_R1:    return pill(u, x, cy, "R1");
    case BTN_SEL:   return pill(u, x, cy, "SELECT");
    case BTN_START: return pill(u, x, cy, "START");
    }
    return 0;
}

/* uma dica: glifo (ou dois com "+") e o rótulo. Devolve onde a próxima começa. */
static float hint2(Ui *u, float x, float cy, Btn a, Btn b, const char *txt)
{
    x += glyph(u, x, cy, a) + 3.0f;
    if (b != (Btn)-1) {
        text(u, (int)x, (int)(cy + 4), COL_AMBER, T_MIUDO, "+");
        x += text_w(u, T_MIUDO, "+") + 3.0f;
        x += glyph(u, x, cy, b) + 3.0f;
    }
    x += 2.0f;
    text(u, (int)x, (int)(cy + 5), COL_TEXT_DIM, T_MIUDO, txt);
    return x + text_w(u, T_MIUDO, txt) + 14.0f;
}

/* ---------- TODO ATALHO, NUM LUGAR SÓ ----------

   Antes cada tela carregava a própria fila de atalhos no rodapé, em cinza de
   13 px. Alguém já a tinha cortado de nove para cinco no deck, e ainda era
   uma parede: a tecla que se usa a cada faixa e a que se usa uma vez por mês
   dividiam a mesma linha, com o mesmo peso, embaixo da música.

   O problema não era a QUANTIDADE, era o LUGAR. Um atalho é uma coisa que se
   aprende UMA vez; o rodapé é uma coisa que se vê SEMPRE. Então a lista
   inteira — nenhum atalho foi perdido, nem os que o rodapé escondia — mudou
   para cá, e as telas ficaram com a música. */
typedef struct { const char *tela; Btn b, b2; const char *txt; } Controle;

static const Controle CONTROLES[] = {
    { "Shelf",    BTN_CROSS,    (Btn)-1,      "play the record" },
    { NULL,       BTN_SQUARE,   (Btn)-1,      "jump to a letter / search" },
    { NULL,       BTN_TRIANGLE, (Btn)-1,      "go to what is playing" },
    { NULL,       BTN_SEL,      (Btn)-1,      "shuffle" },

    { "Playing",  BTN_TOUCH,    (Btn)-1,      "tap the disc to pause" },
    { NULL,       BTN_SQUARE,   (Btn)-1,      "lyrics" },
    { NULL,       BTN_UPDOWN,   (Btn)-1,      "seek 10 seconds" },
    { NULL,       BTN_SEL,      (Btn)-1,      "repeat mode" },
    { NULL,       BTN_R1,       BTN_TRIANGLE, "listen while gaming" },
    { NULL,       BTN_R1,       BTN_L1,       "screen off, keep playing" },
    { NULL,       BTN_L1,       BTN_R1,       "lock all buttons (again to unlock)" },
    { NULL,       BTN_TOUCH,    (Btn)-1,      "touch a track in the list to play it" },
    { NULL,       BTN_R1,       BTN_CIRCLE,   "swap for the Qobuz lossless" },

    { "Gaming",   BTN_R1,       BTN_TRIANGLE, "open listen-while-gaming" },
    { NULL,       BTN_SQUARE,   (Btn)-1,      "keep playing when I leave" },

    { "Lists",    BTN_CIRCLE,   (Btn)-1,      "play from here" },
    { NULL,       BTN_SQUARE,   (Btn)-1,      "save what is playing" },
    { NULL,       BTN_SEL,      (Btn)-1,      "delete (press twice)" },

    { "Qobuz",    BTN_SQUARE,   (Btn)-1,      "search" },
    { NULL,       BTN_LEFTRIGHT, (Btn)-1,     "pick a recent search" },
    { NULL,       BTN_CROSS,    (Btn)-1,      "download the record" },
    { NULL,       BTN_CIRCLE,   (Btn)-1,      "play it over the network" },
    { NULL,       BTN_SEL,      (Btn)-1,      "MP3 / FLAC / hi-res" },

    { "Anywhere", BTN_TRIANGLE, (Btn)-1,      "back to the shelf" },
    { NULL,       BTN_L1,       BTN_R1,       "move between tabs" },
    { NULL,       BTN_UPDOWN,   (Btn)-1,      "navigate a list" },
    { NULL, 0, 0, NULL }
};

static void text(Ui *u, int x, int y, unsigned int col, float scale, const char *s)
{
    /* TODO texto passa por aqui, inclusive o que veio do cartão e da rede.
       É o único ponto por onde a UI escreve, e por isso é onde o saneamento
       cabe: sanear na varredura deixaria de fora o Qobuz e as playlists. */
    char b[TELA_TXT];
    vita2d_pvf_draw_text(u->font, x, y, col, scale, tela_texto(b, sizeof(b), s));
}

static void text_elided(Ui *u, int x, int y, unsigned int col, float scale,
                        float maxw, const char *s)
{
    char b[512];
    elide(u, b, sizeof(b), scale, maxw, s);
    vita2d_pvf_draw_text(u->font, x, y, col, scale, b);
}

/* Escreve `s` em ATÉ duas linhas que caibam em `maxw`; a segunda vai elidida.
   Quebra no último espaço que ainda cabe — uma palavra só, mais larga que a
   coluna, continua elidida numa linha (não há onde quebrar sem mentir).

   Existe porque a elisão de UMA linha corta pela direita, e num card de
   estante o que fica à direita é justamente o que distingue um disco do
   outro. Ver album_display no library.c: lá tira-se o que se repete, aqui
   dá-se espaço ao que sobrou. */
static void text_2linhas(Ui *u, int x, int y1, int y2, unsigned int col,
                         float scale, float maxw, const char *s)
{
    char l1[MAX_NAME_LEN];
    if (text_w(u, scale, s) <= maxw) { text(u, x, y1, col, scale, s); return; }

    int corte = 0;
    for (int i = 0; s[i]; i++) {
        if (s[i] != ' ') continue;
        snprintf(l1, sizeof(l1), "%.*s", i, s);
        if (text_w(u, scale, l1) > maxw) break;
        corte = i;
    }
    if (corte == 0) { text_elided(u, x, y1, col, scale, maxw, s); return; }

    snprintf(l1, sizeof(l1), "%.*s", corte, s);
    text(u, x, y1, col, scale, l1);
    text_elided(u, x, y2, col, scale, maxw, s + corte + 1);
}

/* ---------- capa ---------- */

/* ---------- O CEMITÉRIO DE TEXTURAS ----------

   `vita2d_free_texture` devolve a memória de vídeo NA HORA. Só que a troca
   de capa acontece DENTRO do desenho: o `cover_tex` despeja a mais velha
   para caber a nova, e o que já foi mandado desenhar neste quadro ainda não
   passou pela GPU. Liberar ali é puxar o chão de um sceGxmDraw que ainda vai
   ler aqueles pixels — a GPU TRAVA, e no Vita a trava derruba o sistema
   inteiro. É o que vinha enchendo o cartão de `psp2core-*-GPUCRASH.psp2dmp`,
   um a cada hora de uso, desde antes de haver capa do Qobuz.

   O que NÃO era: volume de desenho. Medido no preview, a tela mais cara do
   app custa 1.825 chamadas por quadro — longe das ~20.000 que já estouraram
   a lista de display uma vez. Foi essa medição que apontou para cá.

   Aqui a textura morta só entra na FILA. Ela é liberada dois quadros depois,
   no COMEÇO do quadro, quando o quadro que a usava já foi apresentado.
   Dois, e não um, porque o vita2d tem buffer duplo: o quadro anterior ainda
   pode estar na tela enquanto o próximo é montado. */
/* O TAMANHO DA FILA, E POR QUE ELE CRESCEU DE 32 PARA 128.

   A conta do pior caso não fecha em 32 por pouco: os dois caches somam 22
   texturas e o `qb_capas_esquece` mata as 12 do Qobuz de uma vez — de DENTRO
   do desenho da tela da loja —, enquanto a fila ainda segura o que morreu nos
   quatro quadros anteriores. 22 + 8 = 30, com 32 de fila. Dois de folga para
   uma conta que ninguém mediu no aparelho não é folga: é sorte.

   E o preço de errar era grande demais para ser pago por dois ponteiros. */
#define TEX_MORTAS 128
static vita2d_texture *g_mortas[TEX_MORTAS];
static unsigned g_mortas_qd[TEX_MORTAS];
static unsigned g_quadro_tex;
static unsigned long g_tex_vazadas;   /* fila cheia: preferimos vazar a travar */

static void tex_matar(vita2d_texture *t)
{
    if (!t) return;
    for (int i = 0; i < TEX_MORTAS; i++) {
        if (g_mortas[i]) continue;
        g_mortas[i] = t;
        g_mortas_qd[i] = g_quadro_tex;
        return;
    }
    /* FILA CHEIA: VAZA, NÃO LIBERA.

       O que estava escrito aqui era `vita2d_free_texture(t)`, com o
       comentário de que vazar era pior do que "arriscar um quadro". A conta
       está errada nos dois lados.

       `vita2d_free_texture` é `sceGxmUnmapMemory`, e quem chama este caminho
       é o `qb_capas_esquece`, que roda DENTRO da cena. Desmapear memória de
       GPU com a lista de display aberta não arrisca um quadro: trava a GPU, e
       a trava do Vita derruba o SISTEMA — é a linha que este arquivo inteiro
       existe para não voltar a ter (ver o cemitério, acima).

       Vazar 768 KB de CDRAM custa 1% do que sobra (medido num
       `psp2core-*-GPUCRASH.psp2dmp` do cartão: 74 MB livres de 112), não se
       repete sozinho — a fila é esvaziada todo quadro — e fica CONTADO, para
       o `gpu.txt` poder dizer que aconteceu em vez de deixar isto silencioso.
       Entre perder memória e derrubar o aparelho de quem está ouvindo música,
       perde-se memória. */
    g_tex_vazadas++;
}

/* QUANTOS QUADROS ESPERAR ANTES DE SOLTAR UMA TEXTURA.

   Este número estava em 2, e 2 É POUCO. SINTOMA: o cartão continuou enchendo
   de `psp2core-*-GPUCRASH` DEPOIS de o cemitério existir — cinco no dia 5 de
   setembro e mais um no dia 6, este último num build que já o tinha.

   O motivo é um só e dá para medir: o vita2d é TRIPLO-bufferizado. No
   `libvita2d.a` deste SDK, o `displayBufferData` tem 12 bytes — três
   ponteiros. Com três buffers a CPU corre até DOIS quadros à frente do que a
   tela está mostrando, então uma textura entregue no quadro N ainda pode
   estar sendo LIDA pela GPU enquanto a CPU desenha N+1 e N+2. Soltar em N+2
   é soltar exatamente na borda — e a borda é onde isto quebra.

   4 = os três buffers mais um de folga. O preço é ridículo (um punhado de
   ponteiros segurados por 1/15 de segundo a mais) e o preço de errar para o
   lado curto é a GPU travar, que derruba o sistema inteiro. Quando um número
   destes for duvidoso, erre para o lado que só custa memória. */
#define TEX_ESPERA 4

static void tex_coletar(void)
{
    g_quadro_tex++;
    for (int i = 0; i < TEX_MORTAS; i++) {
        if (!g_mortas[i]) continue;
        if (g_quadro_tex - g_mortas_qd[i] < TEX_ESPERA) continue;
        vita2d_free_texture(g_mortas[i]);
        g_mortas[i] = NULL;
    }
}

/* No fim da vida do app não há próximo quadro para coletar: espera a GPU
   terminar e esvazia na mão. */
static void tex_cemiterio_esvazia(void)
{
    vita2d_wait_rendering_done();
    for (int i = 0; i < TEX_MORTAS; i++) {
        if (g_mortas[i]) vita2d_free_texture(g_mortas[i]);
        g_mortas[i] = NULL;
    }
}

/* AS CAPAS DA LOJA.

   Uma lista de discos sem capa é uma lista de textos, e numa loja é pela
   capa que se reconhece o disco. O arquivo já está (ou vai estar) no cartão,
   posto lá pelo baixador do qobuz.c; aqui só se decodifica e se guarda a
   textura.

   O cache guarda TAMBÉM o fracasso (textura NULL): sem isso, um JPEG que o
   decodificador não aceita seria retentado a cada quadro, para sempre. */
static char g_capas_de[32];   /* de que leva de resultados são as capas */

#define QB_CAPA_CACHE 12
typedef struct { char id[32]; vita2d_texture *tex; bool cheio; } QbCapa;
static QbCapa g_qbcapa[QB_CAPA_CACHE];
static int    g_qbcapa_prox;
/* O pedido que está na fila do `u->pede_qb` traz também a URL dela — sem isso
   o `qb_capa_serve` não tem como RE-baixar quando o arquivo ainda não chegou
   (a leva da loja baixa tudo de uma vez; um GET FLAC pede um arquivo só). */
static char    g_qb_pede_url[200];
static char    g_qb_pede_id[32];
static int     g_qb_pede_tent;
static unsigned g_qb_pede_clock;

/* Mesma regra da capa local: o desenho CONSULTA, quem carrega é o quadro
   seguinte, fora da cena. Ver a nota grande no cover_tex. */
static vita2d_texture *qb_capa_tex_por(Ui *u, const char *id, const char *url)
{
    if (!id || !id[0]) return NULL;
    for (int i = 0; i < QB_CAPA_CACHE; i++)
        if (g_qbcapa[i].cheio && !strcmp(g_qbcapa[i].id, id))
            return g_qbcapa[i].tex;
    if (!u->pede_qb[0]) {
        snprintf(u->pede_qb, sizeof(u->pede_qb), "%.31s", id);
        snprintf(g_qb_pede_url, sizeof(g_qb_pede_url), "%s", url ? url : "");
    }
    return NULL;
}

static vita2d_texture *qb_capa_tex(Ui *u, const QobuzAlbum *a)
{
    if (!a) return NULL;
    return qb_capa_tex_por(u, a->id, a->capa);
}

static void qb_capa_serve(Ui *u)
{
    char id[32];
    snprintf(id, sizeof(id), "%s", u->pede_qb);
    u->pede_qb[0] = '\0';
    if (!id[0]) return;
    for (int i = 0; i < QB_CAPA_CACHE; i++)
        if (g_qbcapa[i].cheio && !strcmp(g_qbcapa[i].id, id)) return;

    char caminho[512];
    qobuz_capa_arquivo(STYLUS_DATA_DIR, id, caminho, (int)sizeof(caminho));
    FILE *f = fopen(caminho, "rb");
    if (!f) {
        /* O ARQUIVO AINDA NÃO EXISTE. Na loja quem o cria é a leva inteira
           de downloads; num GET FLAC (capa pedida por id+url) não há leva, e
           se o download único falhou ou foi recusado por já existir outro
           em curso, ninguém vai trazê-lo de novo — a não ser que este lugar
           RE-PEÇA. Uma vez por segundo, no máximo cinco vezes por id. */
        if (strcmp(id, g_qb_pede_id) != 0) {
            snprintf(g_qb_pede_id, sizeof(g_qb_pede_id), "%s", id);
            g_qb_pede_tent = 0;
        }
        if (g_qb_pede_tent < 5 && g_qb_pede_url[0] &&
            (int)(u->clock - g_qb_pede_clock) >= 60) {
            g_qb_pede_clock = u->clock;
            QobuzAlbum a;
            memset(&a, 0, sizeof(a));
            snprintf(a.id, sizeof(a.id), "%s", id);
            snprintf(a.capa, sizeof(a.capa), "%s", g_qb_pede_url);
#ifdef __vita__
            if (qobuz_capas_async(&a, 1, STYLUS_DATA_DIR) == 0)
                g_qb_pede_tent++;
#else
            g_qb_pede_tent++;   /* no PC o download é do chamador, não daqui */
#endif
        }
        return;                 /* ainda baixando: tenta no próximo quadro */
    }
    fclose(f);

    vita2d_texture *t = vita2d_load_JPEG_file(caminho);

    QbCapa *slot = &g_qbcapa[g_qbcapa_prox++ % QB_CAPA_CACHE];
    if (slot->cheio && slot->tex) tex_matar(slot->tex);
    snprintf(slot->id, sizeof(slot->id), "%s", id);
    slot->tex = t;
    slot->cheio = true;
}

static void qb_capas_esquece(void)
{
    for (int i = 0; i < QB_CAPA_CACHE; i++) {
        if (g_qbcapa[i].cheio && g_qbcapa[i].tex) tex_matar(g_qbcapa[i].tex);
        g_qbcapa[i].tex = NULL;
        g_qbcapa[i].cheio = false;
        g_qbcapa[i].id[0] = '\0';
    }
    g_qbcapa_prox = 0;
}

static vita2d_texture *decode_cover(const Album *a)
{
    if (!a->cover || a->cover_len < 4) return NULL;
    const unsigned char *m = a->cover;
    if (m[0] == 0xFF && m[1] == 0xD8) /* JPEG */
        return vita2d_load_JPEG_buffer(a->cover, (unsigned long)a->cover_len);
    if (m[0] == 0x89 && m[1] == 'P' && m[2] == 'N' && m[3] == 'G')
        return vita2d_load_PNG_buffer(a->cover);
    return NULL;
}

/* Devolve a textura da capa, decodificando no máximo UMA por quadro.
   NULL tem dois sentidos e eles não podem virar o mesmo desenho: "ainda não
   carreguei" e "este disco não tem capa". Quem quiser distinguir olha
   alb->cover_loaded. */
/* ═══ POR QUE CARREGAR CAPA SAIU DE DENTRO DO DESENHO ═════════════════

   O `cover_tex` decodificava o JPEG e criava a textura ALI, no meio do
   desenho — isto é, entre o `vita2d_start_drawing()` e o `end_drawing()`, com
   uma cena da GPU aberta. Criar textura no vita2d é `sceGxmMapMemory`: mapear
   memória de GPU enquanto a lista de display está sendo gravada.

   SINTOMA: `psp2core-*-GPUCRASH` no cartão, de novo, minutos depois de o app
   passar a ler os 324 `cover.jpg` que ele ignorava. Até então ele quase nunca
   decodificava uma capa — a coleção não tem arte embutida —, então esse
   caminho quase nunca rodava e o defeito ficou escondido por meses. Foi ao
   CONSERTAR as capas que ele apareceu, o que é o pior jeito de descobrir uma
   coisa dessas.

   Agora o desenho só CONSULTA o cache. Faltou? ele anota o pedido e desenha o
   marcador; quem carrega é o quadro seguinte, ANTES da cena abrir. A capa
   aparece um quadro depois — dezesseis milissegundos que ninguém vê — e
   nenhuma memória de GPU é mapeada com uma cena em andamento.

   A REGRA, para não voltar: nada entre `start_drawing` e `end_drawing` pode
   criar ou destruir textura. Quem precisa de uma, pede. */
static vita2d_texture *cover_tex(Ui *u, Album *a)
{
    if (!a) return NULL;
    for (int i = 0; i < COVER_CACHE; i++)
        if (u->cache[i].owner == a) { u->cache[i].age = u->clock; return u->cache[i].tex; }
    if (!u->pede_capa) u->pede_capa = a;    /* o primeiro que faltar, no próximo quadro */
    return NULL;
}

/* A CAPA DO DISCO QUE ESTÁ TOCANDO. O deck chama ela, não o `cover_tex`
   direto: um disco da LOJA ou do GET FLAC não tem arquivo de capa — tem um
   id e uma URL do Qobuz, pendurados em `qb_kapa`/`qb_kapa_url` — e sem este
   passo o prato tocando pela rede ficaria para sempre com o marcador âmbar
   no rótulo, que é exatamente a queixa: "qobuz isnt getting the cover". */
static vita2d_texture *deck_capa_tex(Ui *u, Album *a)
{
    vita2d_texture *tex = cover_tex(u, a);
    if (tex) return tex;
    if (a && a->qb_kapa[0])
        return qb_capa_tex_por(u, a->qb_kapa, a->qb_kapa_url);
    return NULL;
}

/* ═══ A CAPA MINÚSCULA QUE VIRA O FUNDO DO DECK ═══════════════════════════
 *
 * O `deck_backdrop` desenhava a capa AMPLIADA 2,15x (500 px esticados para
 * cobrir 960x544 com folga) SEIS vezes, com deslocamentos de poucos pixels,
 * para fingir um borrão. Sete chamadas de desenho — nada, para um teto de
 * quatro mil — e SETE TELAS CHEIAS de pixel misturado com leitura de uma
 * textura de 1 MB, sessenta vezes por segundo, na tela que trava.
 *
 * Seis cópias deslocadas também não são um borrão: são seis fantasmas. De
 * perto se veem as bordas repetidas.
 *
 * Um borrão de verdade é média de vizinhança, e média de vizinhança é o que
 * a AMPLIAÇÃO BILINEAR faz de graça, no hardware. Então a conta vai ao
 * contrário: encolhe-se a capa para 64x64 UMA VEZ, quando ela é carregada
 * (aqui, fora da cena, onde criar textura é seguro — a regra do cover_tex),
 * e o desenho amplia essa miniatura para a tela inteira em UMA chamada.
 *
 * O que muda no aparelho:
 *   - preenchimento do fundo: ~7 telas por quadro -> 2 (a capa e o véu);
 *   - a textura lida por pixel deixa de ter 1 MB e passa a ter 16 KB, que
 *     cabe inteira no cache de textura do SGX — num amplificador de 17x, cada
 *     tile lê os mesmos poucos texels;
 *   - e o borrão fica MELHOR, porque é média e não sobreposição.
 *
 * O custo é 16 KB de memória de vídeo por capa em cache (29 x 16 KB = 464 KB)
 * e uma passada de média por capa carregada, que já custa a decodificação de
 * um JPEG de 500x500 no mesmo quadro. */
#define BLUR_LADO 64

/* O VÉU VAI ASSADO NO BORRÃO, não desenhado por cima.
 *
 * O fundo do deck era DUAS telas cheias por quadro: a miniatura ampliada +
 * um retângulo de véu por cima. Assar o véu nos 4.096 texels UMA vez (aqui,
 * fora da cena) tira o retângulo do quadro para sempre: o fundo cai para
 * UMA tela, e o pixel que sai é o mesmo — escurecer e ampliar comutam, as
 * duas são lineares (a menos de ±1 nível de arredondamento).
 *
 * Preço: o borrão carrega a cor do TEMA da hora em que foi feito. Trocar de
 * tema invalida os borrões (ver o AJ_TEMA), e eles se refazem sozinhos, um
 * por quadro, como qualquer capa nova. */
#define DECK_FUNDO_VEU 214

/* ═══ QUANTOS BYTES TEM UM PIXEL — MEDIDO, NÃO SUPOSTO ════════════════════
 *
 * A primeira versão disto comparava com `SCE_GXM_TEXTURE_FORMAT_A8B8G8R8`
 * porque o `vita2d_image_jpeg.o` passa 0x98000000 e o nome "A8B8G8R8" parecia
 * o candidato óbvio. **Não é**: A8B8G8R8 vale 0x0C000000, e 0x98000000 é
 * `U8U8U8_BGR` — TRÊS bytes por pixel, não quatro.
 *
 * A comparação errada não daria erro nenhum: `blur_bpp` devolveria 0, o
 * `blur_faz` desistiria calado e o deck ficaria SEM FUNDO no aparelho —
 * enquanto o preview do PC, que passa por outro ramo, continuaria mostrando
 * o fundo bonito. Mais uma imagem do PC aprovando o que o Vita não faz.
 *
 * Conferido compilando contra o `psp2/gxm.h` do SDK:
 *   JPEG colorido -> U8U8U8_BGR  0x98000000  3 bytes, em memória R,G,B
 *   JPEG cinza    ->             0x00007000  1 byte  (não vira fundo)
 *   PNG           -> A8B8G8R8    0x0C000000  4 bytes, R,G,B,A
 *     (o carregador de PNG chama `vita2d_create_empty_texture`, sem formato,
 *      e o padrão do vita2d é A8B8G8R8)
 *
 * Nos dois que interessam o byte 0 é R, o 1 é G e o 2 é B — só o passo muda.
 * O shim do PC guarda exatamente o layout do primeiro e diz isso pelo
 * get_format, então não há caminho separado para o preview. */
static int blur_bpp(const vita2d_texture *t)
{
    unsigned int f = (unsigned int)vita2d_texture_get_format(t);
    if (f == (unsigned int)SCE_GXM_TEXTURE_FORMAT_U8U8U8_BGR) return 3;
    if (f == (unsigned int)SCE_GXM_TEXTURE_FORMAT_A8B8G8R8)   return 4;
    return 0;   /* formato que não se adivinha: sem fundo, e sem chutar */
}

static void blur_le(const unsigned char *p, int bpp, int *r, int *g, int *b)
{
    (void)bpp;   /* 3 e 4 bytes começam igual: R, G, B */
    *r = p[0]; *g = p[1]; *b = p[2];
}

static void blur_grava(unsigned char *p, int bpp, int r, int g, int b)
{
    p[0] = (unsigned char)r; p[1] = (unsigned char)g; p[2] = (unsigned char)b;
    if (bpp == 4) p[3] = 255;
}

/* Encolhe `src` para BLUR_LADO x BLUR_LADO por MÉDIA DE CAIXA (não por
   amostragem: amostrar uma capa de 500 px em 64 pontos devolve ruído, e o
   ruído amplificado 17x vira sujeira piscando a cada troca de faixa).
   Devolve NULL sem barulho quando não dá — o fundo simplesmente não aparece. */
static vita2d_texture *blur_faz(const vita2d_texture *src)
{
    if (!src) return NULL;
    int bpp = blur_bpp(src);
    if (!bpp) return NULL;
    int sw = (int)vita2d_texture_get_width(src);
    int sh = (int)vita2d_texture_get_height(src);
    if (sw < BLUR_LADO || sh < BLUR_LADO) return NULL;
    const unsigned char *sp = (const unsigned char *)vita2d_texture_get_datap(src);
    unsigned int ss = vita2d_texture_get_stride(src);
    if (!sp || !ss) return NULL;

    /* o MESMO formato do carregador de JPEG: três bytes, comprovadamente
       desenhável (é o que toda capa do cartão já é) e 25% menor que RGBA */
    vita2d_texture *dst = vita2d_create_empty_texture_format(
        BLUR_LADO, BLUR_LADO, SCE_GXM_TEXTURE_FORMAT_U8U8U8_BGR);
    if (!dst) return NULL;
    /* SEM ISTO O FUNDO É UM MOSAICO. Ampliar 64 px para 1075 com filtro de
       ponto desenha quadrados de 17 px; o borrão inteiro depende de o
       hardware interpolar. O vita2d cria textura em POINT por padrão. */
    vita2d_texture_set_filters(dst, SCE_GXM_TEXTURE_FILTER_LINEAR,
                                    SCE_GXM_TEXTURE_FILTER_LINEAR);
    unsigned char *dp = (unsigned char *)vita2d_texture_get_datap(dst);
    unsigned int ds = vita2d_texture_get_stride(dst);
    if (!dp || !ds) { vita2d_free_texture(dst); return NULL; }
    int dbpp = blur_bpp(dst);
    if (!dbpp) { vita2d_free_texture(dst); return NULL; }

    /* NÃO É PRECISO LER OS 250.000 PIXELS DA CAPA. A média de uma caixa de
       8x8 e a de quatro pontos dela dão a mesma cor a menos de ruído, e o
       3x3 logo abaixo apaga o ruído. Amostrar no máximo 4 por eixo por
       texel corta a leitura de 250 mil para ~65 mil — e isto roda no mesmo
       quadro que já decodifica um JPEG. */
    int passo_x = (sw / BLUR_LADO) / 4; if (passo_x < 1) passo_x = 1;
    int passo_y = (sh / BLUR_LADO) / 4; if (passo_y < 1) passo_y = 1;

    for (int y = 0; y < BLUR_LADO; y++) {
        int y0 = y * sh / BLUR_LADO, y1 = (y + 1) * sh / BLUR_LADO;
        if (y1 <= y0) y1 = y0 + 1;
        for (int x = 0; x < BLUR_LADO; x++) {
            int x0 = x * sw / BLUR_LADO, x1 = (x + 1) * sw / BLUR_LADO;
            if (x1 <= x0) x1 = x0 + 1;
            long r = 0, g = 0, b = 0, n = 0;
            for (int j = y0; j < y1; j += passo_y) {
                const unsigned char *lin = sp + (size_t)j * ss;
                for (int i = x0; i < x1; i += passo_x) {
                    int pr, pg, pb;
                    blur_le(lin + (size_t)i * bpp, bpp, &pr, &pg, &pb);
                    r += pr; g += pg; b += pb; n++;
                }
            }
            if (!n) n = 1;
            blur_grava(dp + (size_t)y * ds + (size_t)x * dbpp, dbpp,
                       (int)(r / n), (int)(g / n), (int)(b / n));
        }
    }

    /* UMA PASSADA DE 3x3 POR CIMA. A ampliação bilinear de uma imagem de 64
       px ainda deixa a "tenda" do filtro visível — losangos suaves onde os
       texels se encontram. Custa 4.096 pixels UMA vez e tira isso. */
    {
        static unsigned char tmp[BLUR_LADO * BLUR_LADO * 3];
        for (int y = 0; y < BLUR_LADO; y++)
            for (int x = 0; x < BLUR_LADO; x++) {
                int r = 0, g = 0, b = 0, n = 0;
                for (int j = -1; j <= 1; j++)
                    for (int i = -1; i <= 1; i++) {
                        int yy = y + j, xx = x + i;
                        if (yy < 0 || yy >= BLUR_LADO || xx < 0 || xx >= BLUR_LADO)
                            continue;
                        int pr, pg, pb;
                        blur_le(dp + (size_t)yy * ds + (size_t)xx * dbpp,
                                dbpp, &pr, &pg, &pb);
                        r += pr; g += pg; b += pb; n++;
                    }
                unsigned char *o = &tmp[((size_t)y * BLUR_LADO + x) * 3];
                o[0] = (unsigned char)(r / n);
                o[1] = (unsigned char)(g / n);
                o[2] = (unsigned char)(b / n);
            }
        for (int y = 0; y < BLUR_LADO; y++)
            for (int x = 0; x < BLUR_LADO; x++) {
                const unsigned char *s = &tmp[((size_t)y * BLUR_LADO + x) * 3];
                blur_grava(dp + (size_t)y * ds + (size_t)x * dbpp, dbpp,
                           s[0], s[1], s[2]);
            }
    }

    /* ASSA O VÉU: cada texel vira texel*(1-V) + FUNDO*V, que é exatamente o
       que o retângulo de véu fazia por cima do fundo — ver a nota no
       DECK_FUNDO_VEU. Daqui para frente o desenho amplia e pronto. */
    {
        unsigned int fc = (unsigned int)TEMA.fundo;
        int fr = (int)(fc & 0xFFu);
        int fg = (int)((fc >> 8) & 0xFFu);
        int fb = (int)((fc >> 16) & 0xFFu);
        int inv = 255 - DECK_FUNDO_VEU;
        for (int y = 0; y < BLUR_LADO; y++)
            for (int x = 0; x < BLUR_LADO; x++) {
                int pr, pg, pb;
                blur_le(dp + (size_t)y * ds + (size_t)x * dbpp,
                        dbpp, &pr, &pg, &pb);
                blur_grava(dp + (size_t)y * ds + (size_t)x * dbpp, dbpp,
                           (pr * inv + fr * DECK_FUNDO_VEU + 127) / 255,
                           (pg * inv + fg * DECK_FUNDO_VEU + 127) / 255,
                           (pb * inv + fb * DECK_FUNDO_VEU + 127) / 255);
            }
    }
    return dst;
}

/* O TRABALHO DE VERDADE, fora da cena. Uma capa por quadro: decodificar um
   JPEG de 500x500 custa alguns milissegundos, e duas num quadro já se vê. */
static void capa_serve(Ui *u)
{
    Album *a = u->pede_capa;
    u->pede_capa = NULL;
    if (!a) return;
    for (int i = 0; i < COVER_CACHE; i++)
        if (u->cache[i].owner == a) return;    /* chegou por outro caminho */

    if (!a->cover_loaded) album_load_cover(a);
    if (!a->cover) {
        /* SEM CAPA, e isso precisa ser LEMBRADO: sem marcar o slot, este
           álbum seria pedido de novo a cada quadro para sempre — uma leitura
           de diretório por quadro, no cartão. */
        int v = -1;
        for (int i = 0; i < COVER_CACHE; i++)
            if (!u->cache[i].tex && !u->cache[i].owner) { v = i; break; }
        if (v < 0) {
            for (int i = 0; i < COVER_CACHE; i++) {
                if (u->cache[i].age == u->clock) continue;
                if (v < 0 || u->cache[i].age < u->cache[v].age) v = i;
            }
        }
        if (v >= 0) {
            if (u->cache[v].tex)  tex_matar(u->cache[v].tex);
            if (u->cache[v].blur) tex_matar(u->cache[v].blur);
            u->cache[v].tex = NULL;
            u->cache[v].blur = NULL;
            u->cache[v].blur_tentado = false;
            u->cache[v].owner = a;
            u->cache[v].age = u->clock;
        }
        return;
    }

    vita2d_texture *tex = decode_cover(a);
    /* Os BYTES CRUS já cumpriram o papel — quem fica é a textura, e o cache
       dela tem teto. Sem soltá-los, cada capa vista ficava na memória para
       sempre: 17,6 MB nesta coleção, e num acervo com capas de 500 KB seriam
       200 MB, que é o mesmo estouro de heap que deixa a estante vazia.
       O album_free_cover também zera o `cover_loaded`, então voltar ao disco
       depois de ele sair do cache relê do arquivo — que é justamente o que
       carregar sob demanda quer dizer. */
    if (a->cover) album_free_cover(a);
    if (!tex) return;

    /* DESPEJA O MAIS VELHO — e nunca um que esta tela já desenhou.

       O laço de antes era `age < age[victim]` a partir do zero. Quando TODAS
       as capas do cache foram desenhadas no mesmo quadro — o que acontece
       sempre que a tela pede tantas quanto o cache guarda — as idades ficam
       IGUAIS, nenhuma comparação é verdadeira, e a vítima continua sendo o
       slot 0. Isto é: o cache despeja justamente a que acabou de ir para a
       GPU, todo quadro, para sempre.

       O tamanho do cache agora passa da tela mais cheia (ver COVER_NA_TELA),
       então o empate não deveria acontecer — mas "não deveria" é como este
       defeito nasceu. Um slot cuja idade é o relógio DESTE quadro está em uso
       agora, e sair dele é o que trava a GPU. Preferir um livre, depois o mais
       velho, e só cair no empate se não houver outro jeito. */
    int victim = -1;
    for (int i = 0; i < COVER_CACHE; i++)
        if (!u->cache[i].tex && !u->cache[i].owner) { victim = i; break; }
    if (victim < 0) {
        for (int i = 0; i < COVER_CACHE; i++) {
            if (u->cache[i].age == u->clock) continue;   /* está na tela AGORA */
            if (victim < 0 || u->cache[i].age < u->cache[victim].age) victim = i;
        }
    }
    /* Todas em uso neste quadro: a tela pede mais capas que o cache tem, o
       que o COVER_NA_TELA existe para impedir. Não dá para despejar sem
       arriscar a GPU, então NÃO se guarda esta — desenha e solta no
       cemitério, que é lento e seguro. Um quadro mais caro é melhor que um
       sistema derrubado. */
    if (victim < 0) { tex_matar(tex); return; }
    if (u->cache[victim].tex)  tex_matar(u->cache[victim].tex);
    if (u->cache[victim].blur) tex_matar(u->cache[victim].blur);
    u->cache[victim].blur = NULL;
    u->cache[victim].tex = tex;
    /* A MINIATURA NÃO NASCE AQUI. Ela só serve ao fundo do deck, isto é, a UM
       álbum — o que está tocando. Construí-la junto com a capa faria as 29 do
       cache, e cada uma custa uma passada pela capa inteira no mesmo quadro
       que já decodifica um JPEG: rolar a estante ficaria aos solavancos, para
       jogar fora 28 delas. Quem pede é o `deck_backdrop`; ver o `blur_serve`. */
    u->cache[victim].blur = NULL;
    u->cache[victim].blur_tentado = false;
    u->cache[victim].owner = a;
    u->cache[victim].age = u->clock;
}

/* A MINIATURA PEDIDA NO QUADRO PASSADO, construída aqui: fora da cena, onde
   mapear memória de GPU é seguro — a mesma regra do `capa_serve`. Uma por
   quadro, e na prática uma por disco posto no prato. */
static void blur_serve(Ui *u)
{
    const Album *a = u->pede_blur;
    u->pede_blur = NULL;
    if (!a) return;
    for (int i = 0; i < COVER_CACHE; i++) {
        if (u->cache[i].owner != a) continue;
        if (u->cache[i].blur || u->cache[i].blur_tentado) return;
        if (!u->cache[i].tex) return;
        u->cache[i].blur_tentado = true;    /* uma tentativa, não uma por quadro */
        u->cache[i].blur = blur_faz(u->cache[i].tex);
        return;
    }
}

static void cache_clear(Ui *u)
{
    for (int i = 0; i < COVER_CACHE; i++) {
        if (u->cache[i].tex)  tex_matar(u->cache[i].tex);
        if (u->cache[i].blur) tex_matar(u->cache[i].blur);
        u->cache[i].tex = NULL;
        u->cache[i].blur = NULL;
        u->cache[i].blur_tentado = false;
        u->cache[i].owner = NULL;
    }
}

/* desenha a capa "cobrindo" o quadrado: escala pelo lado que precisa de mais e
   deixa o resto sair — esticar deforma uma capa quadrada num quadro que não é */
static void draw_cover_fit(vita2d_texture *tex, float x, float y, float side)
{
    float tw = (float)vita2d_texture_get_width(tex);
    float th = (float)vita2d_texture_get_height(tex);
    if (tw <= 0 || th <= 0) return;
    float s = side / (tw < th ? tw : th);
    float dw = tw * s, dh = th * s;
    vita2d_draw_texture_scale(tex, x + (side - dw) / 2, y + (side - dh) / 2, s, s);
}

/* A capa como RÓTULO REDONDO. Um quadrado no meio de um disco redondo lê como
   adesivo colado; rótulo de vinil é redondo, e é essa forma que faz o desenho
   inteiro ler como disco.

   O vita2d não tem recorte nem máscara. Mas tem draw_texture_part_scale, e um
   círculo é uma pilha de cordas: uma tira de 1px por linha da tela, cada uma
   com a largura da corda naquela altura — a mesma ideia do fill_circle. A
   capa é escalada para PREENCHER (pelo lado menor), senão uma capa não
   quadrada deixaria buraco dentro do círculo. */
static void draw_cover_round(vita2d_texture *tex, float cx, float cy, float r)
{
    float tw = (float)vita2d_texture_get_width(tex);
    float th = (float)vita2d_texture_get_height(tex);
    if (tw < 1 || th < 1 || r < 2) return;
    float s = (2.0f * r) / (tw < th ? tw : th);
    float dx0 = cx - tw * s * 0.5f, dy0 = cy - th * s * 0.5f;
    /* UMA TIRA POR LINHA DE PIXEL ERA CEM CHAMADAS DE GPU POR CÍRCULO.

       Cada `vita2d_draw_texture_part_scale` é um `sceGxmDraw` no aparelho
       (conferido desmontando o libvita2d.a). Um círculo de raio 50 saía com
       101 deles, e a tela de ARTISTS desenha dezoito círculos: mil e
       oitocentas chamadas só para os retratos.

       Só que a largura da tira quase não muda perto do EQUADOR do círculo —
       de uma linha para a seguinte ela anda uma fração de pixel — e muda
       rápido só perto dos polos. Uma tira por linha paga o preço do pior caso
       em toda a altura.

       Então: junta as linhas vizinhas enquanto a meia-largura não andar mais
       que um pixel, e desenha o bloco de uma vez. A silhueta é a mesma (a
       borda já é serrilhada de qualquer jeito, sem filtragem) e a conta cai
       para menos da metade. Perto dos polos, onde a curva anda depressa,
       cada linha continua sendo sua própria tira — que é onde a precisão
       importa. */
    int y0 = (int)(cy - r), y1 = (int)(cy + r);
    int y = y0;
    while (y <= y1) {
        float dy = (float)y - cy;
        float d2 = r * r - dy * dy;
        if (d2 <= 0) { y++; continue; }
        float half = sqrtf(d2);

        /* ═══ O BLOCO SE MEDE PELO COMEÇO, NÃO PELO PRÓPRIO MÍNIMO ════════
         *
         * SINTOMA: uma MORDIDA retangular escura nos dois lados do rótulo do
         * disco, na altura do equador, e a mesma mordida nos dezoito
         * retratos da ARTISTS. Some no topo do círculo e só aparece do
         * equador para baixo.
         *
         * A causa é uma linha: o teste de parada comparava `h2` com `half`
         * DEPOIS de `half` já ter sido puxado para baixo pela linha anterior.
         * Descendo do equador, cada linha é um tiquinho mais estreita que a
         * de cima, `half` acompanhava, e a diferença testada passava a ser a
         * de UM PASSO — que só chega a um pixel perto do polo. Ou seja: o
         * bloco começava no equador e não terminava mais, e era desenhado
         * inteiro com a largura da ÚLTIMA linha. Num rótulo de raio 62 isso
         * corta dezoito pixels de cada lado.
         *
         * Subindo, o mesmo laço se comportava: `half` não CRESCE, então
         * `h2 > half + 1` disparava logo. É por isso que só a metade de
         * baixo ficava mordida — e por que a metade de cima parecia certa e
         * o defeito passou despercebido.
         *
         * Agora o limite é a largura do INÍCIO do bloco (`h0`), que não se
         * move: nenhuma linha do bloco pode estar a mais de um pixel dela, e
         * o pior erro volta a ser o um pixel que o comentário sempre
         * prometeu. */
        float h0 = half;
        int fim = y;
        while (fim + 1 <= y1) {
            float dy2 = (float)(fim + 1) - cy;
            float d22 = r * r - dy2 * dy2;
            if (d22 <= 0) break;
            float h2 = sqrtf(d22);
            if (h2 > h0 + 1.0f || h2 < h0 - 1.0f) break;
            /* a tira usa a MENOR das larguras do bloco: transbordar para fora
               do círculo se vê; faltar um pixel para dentro, não. */
            if (h2 < half) half = h2;
            fim++;
        }

        float sx = cx - half;
        float alt = (float)(fim - y + 1);

        /* ═══ A TIRA TEM DE CABER DENTRO DA CAPA ═══════════════════════════
         *
         * ESTE ERA O DEFEITO QUE TRAVAVA A GPU.
         *
         * A capa é escalada para PREENCHER o círculo (`s = 2r / menor lado`),
         * e as bordas do círculo caem exatamente nas bordas da imagem — na
         * conta ideal. Na conta de verdade não: `y1` é `(int)(cy + r)`, a
         * tira tem altura inteira, e a última pede
         * `(y1 + 1 - dy0)/s`, que para uma capa quadrada dá `th + th/(2r)`.
         * Numa capa de 500 px com raio 60 são QUATRO PIXELS depois do fim da
         * textura. A borda direita cai bem em cima de `tw`, e daí qualquer
         * arredondamento passa.
         *
         * Ler fora do bloco que o `sceGxmMapMemory` mapeou não devolve erro
         * no Vita: a GPU TRAVA e leva o sistema junto. E não era caso raro —
         * a varredura conta **6.830 tiras fora dos limites** numa passada,
         * ou seja, em todo quadro que desenha um rótulo redondo: o deck e os
         * dezoito retratos da ARTISTS. São exatamente as duas telas em que o
         * dono reproduziu a queda.
         *
         * Apara-se aqui, na origem, e a porteira apara de novo lá embaixo —
         * porque `draw_texture_part_scale` é chamado de mais de um lugar e o
         * próximo a errar não vai reler este comentário. */
        float ux = (sx - dx0) / s;
        float uy = ((float)y - dy0) / s;
        float uw = (2.0f * half) / s;
        float uh = alt / s;
        if (ux < 0.0f) { uw += ux; ux = 0.0f; }
        if (uy < 0.0f) { uh += uy; uy = 0.0f; }
        if (ux + uw > tw) uw = tw - ux;
        if (uy + uh > th) uh = th - uy;
        if (uw > 0.0f && uh > 0.0f)
            vita2d_draw_texture_part_scale(tex, sx, (float)y, ux, uy, uw, uh, s, s);
        y = fim + 1;
    }
}

/* ---------- o fundo do deck: a capa, esborratada ---------- */

/* Quanto da capa sobra atrás de tudo. É o complemento do véu: 214 deixa
   passar 16%.

   Um fundo que se pode DESCREVER não é fundo — com 176 (31%) dava para ler a
   foto, uma arquibancada de estádio disputando atenção com o disco e com a
   lista de faixas. O que se quer é a COR do disco e a mancha dela.

    O borrão de antes eram seis cópias deslocadas a alfa 20, o que sobrava em
    7% de capa: quase nada, e ainda assim caro. Com um borrão de verdade dá
    para deixar passar o dobro e continuar ilegível — que é o ponto. O valor
    mora no DECK_FUNDO_VEU, junto ao BLUR_LADO: o véu vai assado no borrão,
    e este desenho só amplia. */

/* Devolve se a textura do fundo saiu: a caixa-preta quer saber se o quadro
   que matou a GPU tinha a tela texturizada ligada. */
static int deck_backdrop(Ui *u, Album *a)
{
    /* pede a capa (o rótulo do disco vai precisar dela de qualquer forma) e
       usa a MINIATURA para o fundo — ver a nota grande no blur_faz */
    vita2d_texture *tex = cover_tex(u, a);
    vita2d_texture *bl = NULL;
    if (tex)
        for (int i = 0; i < COVER_CACHE; i++)
            if (u->cache[i].owner == a) {
                bl = u->cache[i].blur;
                /* falta? anota o pedido e desenha sem fundo neste quadro. É a
                   mesma dança do cover_tex: o desenho CONSULTA, quem constrói
                   é o quadro seguinte, fora da cena. */
                if (!bl && !u->cache[i].blur_tentado && !u->pede_blur)
                    u->pede_blur = a;
                break;
            }
    if (!bl) return 0;

    float tw = (float)vita2d_texture_get_width(bl);
    float th = (float)vita2d_texture_get_height(bl);
    if (tw <= 0 || th <= 0) return 0;

    /* COBRE a tela: escala pelo lado que precisa de mais e deixa o resto
       sair. A miniatura é quadrada, então isto corta em cima e embaixo —
       que é o mesmo enquadramento que a capa grande tinha. O véu já vem
       assado nos texels (ver DECK_FUNDO_VEU): sem retângulo por cima, o
       fundo inteiro é UMA chamada e UMA tela de fill. */
    float s = (float)SCRW / tw;
    if (th * s < (float)SCRH) s = (float)SCRH / th;
    float dw = tw * s, dh = th * s;
    vita2d_draw_texture_scale(bl, (SCRW - dw) / 2, (SCRH - dh) / 2, s, s);
    return 1;
}

/* ---------- o disco ---------- */

/* Os sulcos são as faixas DESTE disco, e o anel aceso é onde a agulha está.
   Cinco anéis fixos desenhariam o mesmo objeto para um single e para um LP.

   No aro vai o ESPECTRO: raio = energia, grave no alto, espelhado nos dois
   lados. Parado, é uma circunferência — e é isso que ele tem que ser quando
   não há som, porque o anel é a única fonte e ausência de dado não vira
   afirmação de nível. */

/* O FURO DO CD, desenhável duas vezes.

   A capa é pintada DEPOIS do disco, no lugar do selo — e num CD ela tapava
   exatamente o furo, que é a única coisa que faz a forma ser um CD e não um
   prato cinza. Então o furo virou função: o disco desenha, a capa cobre, e o
   furo volta por cima. */
static void cd_furo(float cx, float cy, float r)
{
    alpha_fill(cx, cy, r * 0.115f, 1.0f, COL_FUNDO);
    alpha_ring(cx, cy, r * 0.115f, 1.0f, 0.55f, RGBA8(120, 132, 152, 255));
}

/* Quantas durações o desenho copia para a pilha. Passa disso, os vãos voltam
   a ser iguais — que é o que eles eram antes de existirem durações. */
#define DISC_FAIXAS_MAX 64

/* `segundos` é a duração de cada faixa (NULL, ou -1 numa faixa, quando não se
   sabe — aí os vãos voltam a ser iguais). Ver a nota dos vãos, adiante. */
static void draw_disc(float cx, float cy, float r, float progress,
                      int ntracks, const int *segundos,
                      int track_idx, float angle,
                      const float *spect, float spin, int midia,
                      bool gpu_safe)
{
    if (r < 6) { alpha_fill(cx, cy, r, 0.5f, COL_AMBER); return; }
    const bool cd = (midia == MIDIA_CD);

    if (!cd) {
        /* ═══ VINIL — PRETO TOTAL + SULCOS GROSSOS DE LUZ ═════════════════
         *
         * Terceira escrita do zero, e a lição das duas anteriores: o LCD do
         * Vita 2000 não mostra o que o monitor mostra. Campo denso de anel
         * fino vira cinza médio no olho (a média ótica come o contraste), e
         * foi assim que 96 anéis "ricos" chegaram como "a mesma coisa
         * cinza". Corpo chapado + 16 riscos idem.
         *
         * Então é o contrário: o corpo é o preto mais fundo do painel, e
         * por cima POUCOS sulcos (10), ESPAÇADOS (~9px de preto respirando
         * entre eles) e CLAROS de verdade (120+ níveis acima do corpo, que
         * é o que o LCD separa). Nenhum tom intermediário para virar lama:
         * ou é preto ou é luz. Continua um cheio só + linhas. */
        alpha_fill(cx, cy, r, 1.0f, RGBA8(  5,   7,  10, 255));
        /* SULCO TRIPLO: o vita2d só tem linha de 1px, e 1px some no LCD —
           então cada sulco são TRÊS anéis concêntricos (±1px), uma faixa
           de 3px por UMA chamada cada. 10 sulcos = 30 chamadas. */
        {
            const float R_INT = 0.36f, R_EXT = 0.94f;
            float span = R_EXT - R_INT;
            int n_rings = gpu_safe ? 6 : 10;
            for (int i = 0; i < n_rings; i++) {
                float t = (float)(i + 1) / (float)(n_rings + 1);
                float rr = r * (R_EXT - t * span);
                unsigned int c = (i & 1) ? RGBA8(110, 128, 165, 255)
                                         : RGBA8(170, 188, 220, 255);
                alpha_ring(cx, cy, rr - 1.0f, 1.5f, 1.0f, c);
                alpha_ring(cx, cy, rr,        1.5f, 1.0f, c);
                alpha_ring(cx, cy, rr + 1.0f, 1.5f, 1.0f, c);
            }
        }
        /* aro: reflexo FORTE da borda — o que separa o disco do fundo */
        alpha_ring(cx, cy, r,       3.5f, 1.0f, RGBA8(220, 235, 252, 255));
        alpha_ring(cx, cy, r*0.975f, 1.5f, 0.85f, RGBA8(130, 148, 180, 255));
    } else {
        /* ═══ CD — PRATA CLARA + SULCOS ESCUROS GROSSOS ═══════════════════
         *
         * O espelho do vinil: no prata o que o LCD separa é a SOMBRA. Corpo
         * no branco (215+) e 10 sulcos escuros de verdade (70+, 140 níveis
         * abaixo), espaçados. O sulco claro sutil morreu aqui: sobre prata
         * ele era o "círculo branco" da queixa. A luz do CD vem do aro, do
         * glint e do arco-íris — não do sulco. */
        alpha_fill(cx, cy, r, 1.0f, RGBA8(215, 222, 238, 255));
        /* sulco triplo, como no vinil: 1px some no LCD. */
        {
            const float R_INT = 0.36f, R_EXT = 0.94f;
            float span = R_EXT - R_INT;
            int n_rings = gpu_safe ? 6 : 10;
            for (int i = 0; i < n_rings; i++) {
                float t = (float)(i + 1) / (float)(n_rings + 1);
                float rr = r * (R_EXT - t * span);
                unsigned int c = (i & 1) ? RGBA8(150, 162, 190, 255)
                                         : RGBA8( 70,  84, 115, 255);
                alpha_ring(cx, cy, rr - 1.0f, 1.5f, 1.0f, c);
                alpha_ring(cx, cy, rr,        1.5f, 1.0f, c);
                alpha_ring(cx, cy, rr + 1.0f, 1.5f, 1.0f, c);
            }
        }
        /* aro externo: reflexo metálico */
        alpha_ring(cx, cy, r,       3.5f, 1.0f, RGBA8(240, 245, 255, 255));
        alpha_ring(cx, cy, r*0.972f, 1.5f, 0.80f, RGBA8(110, 122, 152, 255));
        /* borda da área gravada */
        alpha_ring(cx, cy, r*0.34f, 1.8f, 0.85f, RGBA8( 80,  92, 120, 255));
        /* CURVATURA: faixa escura perto do aro */
        alpha_ring(cx, cy, r*0.945f, 4.0f, 0.70f, RGBA8(110, 122, 152, 255));
        /* GLINT especular */
        {
            const float GLINT = -2.15f;
            arco(cx, cy, r*0.55f, GLINT-0.30f, GLINT+0.30f,
                 gpu_safe ? 4 : 8, 0.80f, RGBA8(250, 252, 255, 255));
            arco(cx, cy, r*0.72f, GLINT-0.18f, GLINT+0.18f,
                 gpu_safe ? 4 : 8, 0.55f, RGBA8(235, 242, 255, 255));
        }
        /* IRIDESCÊNCIA: 5 bandas circulares de difração, um anel fino
           por chamada. Paradas no raio como no disco de verdade. Anel
           CHEIO (não arco: o arco esmaece as pontas e o círculo ficaria
           com uma costura apagada no ângulo zero). */
        {
            static const struct { float rf; unsigned int c; } IRIS[5] = {
                { 0.46f, RGBA8(235,  90,  90, 255) },
                { 0.55f, RGBA8(235, 180,  80, 255) },
                { 0.63f, RGBA8(110, 210, 130, 255) },
                { 0.71f, RGBA8(110, 200, 230, 255) },
                { 0.79f, RGBA8(170, 130, 230, 255) },
            };
            int n_iris = gpu_safe ? 3 : 5;
            for (int i = 0; i < n_iris; i++)
                alpha_ring(cx, cy, r * IRIS[i].rf, 1.5f, 0.30f, IRIS[i].c);
        }
    }
    /* A SILHUETA DO PRATO — o que faz o olho LER "objeto" em vez de
       "círculo chapado". O queixo do cartão: na tela do aparelho estes
       dois anéis eram o que faltava para o disco não ser um cheio preto
       (vinil) ou um cheio branco (CD). Uma sombra fina por dentro do aro
       + um lábio claro na borda viram o disco num cilindro baixo. */
    alpha_ring(cx, cy, r - 0.8f, 1.2f, cd ? 0.40f : 0.30f,
               RGBA8(50, 60, 82, 255));
    alpha_ring(cx, cy, r - 0.15f, 1.2f, cd ? 0.35f : 0.25f,
               cd ? RGBA8(210, 222, 242, 255) : RGBA8(110, 125, 160, 255));
#ifdef STYLUS_CYCLE
    if (g_disco_plano) return;   /* cena 7: corpo e aro, e nada mais */
#endif
    int cabem = (int)(r / 5.0f);
    if (cabem < 3) cabem = 3;
    if (gpu_safe) {
        if (cabem > 12) cabem = 12;
    } else {
        if (cabem > 24) cabem = 24;
    }

    /* ═══ OS VÃOS DE FAIXA SEGUEM A DURAÇÃO, E NÃO A CONTAGEM ═════════════
     *
     * Eram `t = (i+1)/(n+2)`: vinte e quatro anéis IGUALMENTE espaçados,
     * cobrindo o disco todo até debaixo do rótulo. Espaçamento igual é
     * exatamente o que faz um disco virar ALVO DE RADAR — a queixa que o
     * comentário da superfície, logo acima, cita com as palavras do dono.
     * Nenhuma quantidade de sulco fino conserta isso enquanto os anéis que
     * mais aparecem estiverem numa grade regular.
     *
     * Num disco de verdade o vão está onde a FAIXA acaba, e uma faixa de
     * seis minutos ocupa três vezes mais sulco que uma de dois. É isso que
     * dá ao vinil a assinatura irregular que se reconhece de longe — e, de
     * quebra, é informação: dá para VER que a terceira faixa é a longa.
     *
     * Duas coisas mudam junto:
     *  - o tempo é mapeado no ANEL GRAVADO (do rótulo ao aro) e não em
     *    `0..r`. Antes, `rr = r*(1-t)` punha os últimos vãos em 0,08r —
     *    debaixo do rótulo, invisíveis, gastos à toa;
     *  - sem duração conhecida cai-se na divisão igual de antes, que é o
     *    melhor palpite que existe quando não há dado. */
    int n = ntracks > 0 ? ntracks : 1;
    if (n > cabem) n = cabem;
    {
        /* o anel gravado: do rótulo ao aro. O vinil corre de fora para
           dentro (a agulha entra pela borda); o CD, de dentro para fora. */
        const float R_INT = 0.365f, R_EXT = 0.955f;
        long total = 0;
        if (segundos && ntracks > 0)
            for (int i = 0; i < ntracks; i++)
                if (segundos[i] > 0) total += segundos[i];

        long corrido = 0;
        for (int i = 0; i < n; i++) {
            /* a fração do LADO em que esta faixa termina */
            float t;
            if (total > 0 && segundos && n == ntracks) {
                corrido += segundos[i] > 0 ? segundos[i] : 0;
                t = (float)corrido / (float)total;
            } else {
                t = (float)(i + 1) / (float)n;
            }
            if (t > 1.0f) t = 1.0f;
            float rr = cd ? r * (R_INT + t * (R_EXT - R_INT))
                          : r * (R_EXT - t * (R_EXT - R_INT));
            bool here = (track_idx >= 0 && ntracks > 0 &&
                         i == (track_idx * n) / ntracks);
            /* Sobre a superfície nova, o vão de faixa não precisa mais
               gritar: ele só tem de se distinguir do sulco comum. A faixa
               TOCANDO continua acesa — é a única que responde "onde estou". */
            /* ═══ VINTE E QUATRO ANÉIS ÂMBAR SÃO UM ALVO, NÃO UM DISCO ═════
             *
             * O vão de faixa era âmbar como a faixa que toca, só que mais
             * fraco. Com vinte e quatro deles a tela vira um bullseye — e
             * âmbar é a cor que este app usa para dizer "aqui", então dizê-la
             * vinte e quatro vezes é não dizer nada.
             *
             * O vão é um acidente da SUPERFÍCIE: num disco de verdade ele é
             * um anel um pouco mais claro, da cor do próprio disco. Então é
             * isso que ele é agora — um sulco mais forte que os outros — e o
             * âmbar fica para a ÚNICA coisa que ele sempre quis dizer: a
             * faixa que está tocando. Que é o que o comentário abaixo já
             * prometia e a cor desmentia. */
            unsigned int c = cd ? RGBA8(145, 155, 180, 255)
                                : RGBA8( 50,  60,  85, 255);
            alpha_ring(cx, cy, rr, here ? 2.5f : 1.0f,
                       here ? 1.0f : 0.45f,
                       here ? COL_AMBER : c);
        }
    }

    /* ═══ LUSTRO SUTIL — facho fino, NÃO mancha grande ═════════════════════
     *
     * As elipses enormes (r*0.78) criavam "white shit" — manchas brancas
     * gigantes no disco. Um disco real tem um facho FINO e ALONGADO, não
     * uma nuvem. Três arcos concêntricos em direção à lâmpada (10h30) dão
     * a ideia de reflexo sem criar mancha. */
    {
        /* 0.32 no vinil: acima disso o facho vira mancha azul sobre o preto
           e o disco chega cinza no LCD — o vão apagado acima conta a mesma
           história. Luz que se nota sem pintar por cima. */
        float ea_base = cd ? 0.55f : 0.32f;
        float ea_spin = cd ? 0.10f : 0.06f;
        float ea = ea_base + ea_spin * spin;
        unsigned int ec = cd ? RGBA8(240, 245, 255, 255)
                             : RGBA8(180, 200, 235, 255);
        /* arco principal — mais largo e opaco para o LCD */
        arco(cx, cy, r * 0.65f, -2.8f, -1.7f,
             gpu_safe ? 5 : 10, ea, ec);
        /* segundo arco — mais perto do centro */
        arco(cx, cy, r * 0.48f, -2.7f, -1.8f,
             gpu_safe ? 4 : 8, ea * 0.75f, ec);
    }

    /* raio é tempo: da borda para o centro */
    /* O RAIO É TEMPO — mas em sentidos opostos. A agulha do vinil entra pela
       BORDA e caminha para o centro; o laser do CD começa no MIOLO e vai
       para fora. Inverter isto é o tipo de detalhe que ninguém sabe explicar
       e todo mundo sente. */
    float read_r = cd ? r * (0.36f + progress * 0.60f)
                      : r * (1.0f - progress * 0.86f);
    /* DOIS anéis finos, e não um de 2,5 px: acima de 1,6 o ring_circle cai no
       caminho de scanline, que desenha um retângulo POR LINHA — uns 600
       retângulos por quadro só para esta linha. Dois finos custam ~190
       segmentos e leem igual. Ver a nota do orçamento no desenho_test. */
    alpha_ring(cx, cy, read_r,        1.0f, 0.34f, COL_AMBER_BRIGHT);
    alpha_ring(cx, cy, read_r - 1.5f, 1.0f, 0.22f, COL_AMBER_BRIGHT);

    /* Em modo seguro, o espectro é o primeiro a sair: são 32 draw_lines
       que o olho mal vê num disco girando, mas que custam GPU. */
    if (spect && !gpu_safe) {
        for (int i = 0; i < SPECT_BANDS; i++) {
            /* O CLAMP QUE FALTAVA — e é ele que travava a GPU.

               Este valor vem do Goertzel, que vem do ÁUDIO. Um NaN ou um
               número enorme aqui vira `len`, vira coordenada, e uma
               coordenada NaN dentro do sceGxm não dá erro: a GPU TRAVA, e a
               trava derruba o sistema. Está escrito no `coord_ok` deste
               mesmo arquivo — e o `vita2d_draw_line` lá embaixo era chamado
               CRU, sem passar por ele.

               Escrito como `!(v > 0)` de propósito: com NaN toda comparação
               é falsa, então NaN cai no zero. Um `if (v < 0)` deixaria o NaN
               passar inteiro, que é como este defeito sobreviveu aos clamps
               que já existem no player.c.

               SINTOMA: `psp2core-*-GPUCRASH` DEPOIS DE PÔR MÚSICA. Sem som o
               espectro nem é desenhado (o `live` é falso), e é por isso que
               a varredura do PC — que usa um tocador de mentira — passava
               verde: ela nunca chegou a desenhar uma barra sequer. */
            float v = spect[i];
            if (!(v > 0.0f)) v = 0.0f;
            else if (!(v < 1.0f)) v = 1.0f;
            /* grave no alto, espelhado: a fatia i vai para os dois lados */
            float a0 = -1.5707963f + (float)i * 3.14159265f / (float)SPECT_BANDS;
            float step = 3.14159265f / (float)SPECT_BANDS;
            for (int side = 0; side < 2; side++) {
                float a = side ? -1.5707963f - (float)i * step - step * 0.5f
                               : a0 + step * 0.5f;
                /* PARA DENTRO, não para fora. Espetados para fora do aro,
                   estes traços viravam raios de sol de desenho animado: o
                   disco deixava de ter silhueta de disco, que é a única
                   forma que a tela inteira depende de que se leia. Por
                   dentro, o mesmo dado vira uma coroa no sulco externo —
                   que é, aliás, onde o som de verdade está. */
                float len = 3.0f + v * r * 0.16f;
                float x0 = cx + cosf(a) * (r - 3.0f);
                float y0 = cy + sinf(a) * (r - 3.0f);
                float x1 = cx + cosf(a) * (r - 3.0f - len);
                float y1 = cy + sinf(a) * (r - 3.0f - len);
                unsigned int c = (COL_AMBER & 0x00FFFFFF) |
                                 ((unsigned int)(50.0f + v * 165.0f) << 24);
                /* CINTO E SUSPENSÓRIO. O clamp acima já garante o `len`, mas
                   `cx`, `cy` e `r` vêm de fora desta função — e uma delas
                   suja envenena os quatro números do mesmo jeito. Custa
                   quatro comparações; o preço de errar é o sistema. */
                if (coord_ok(x0) && coord_ok(y0) && coord_ok(x1) && coord_ok(y1))
                    vita2d_draw_line(x0, y0, x1, y1, c);
            }
        }
    }

    if (!cd) {
        /* o selo, com uma marca que gira — é o que diz que ele ESTÁ girando */
        alpha_fill(cx, cy, r * 0.16f, 0.25f, COL_AMBER);
        float mx = cx + cosf(angle) * r * 0.12f;
        float my = cy + sinf(angle) * r * 0.12f;
        alpha_fill(mx, my, 2.5f, 0.55f + 0.4f * spin, COL_AMBER_BRIGHT);
        alpha_fill(cx, cy, 3.0f, 0.85f, COL_AMBER);
    } else {
        /* O CUBO E O FURO. É o furo que faz um círculo virar um CD: sem ele
           a forma é só um prato claro. O anel transparente em volta é a
           parte não gravada do policarbonato, e o furo é pintado com o FUNDO
           do app (10,14,21) — é assim que se fura sem ter recorte. */
        alpha_fill(cx, cy, r * 0.20f, 0.55f, RGBA8(150, 162, 180, 255));
        alpha_ring(cx, cy, r * 0.20f, 1.0f, 0.40f, RGBA8(226, 234, 248, 255));
        /* a marca que gira vive no cubo, onde ainda há material */
        float mx = cx + cosf(angle) * r * 0.165f;
        float my = cy + sinf(angle) * r * 0.165f;
        alpha_fill(mx, my, 2.5f, 0.50f + 0.4f * spin, RGBA8(245, 250, 255, 255));
        cd_furo(cx, cy, r);
    }
}

/* O braço.

   O QUE ESTAVA ERRADO: era um "facho" — um gradiente radial curtinho e um
   ponto de luz, nascendo de um ponto que se movia junto com a agulha. No
   aparelho isso lê como uma fagulha solta sobre o disco. Não havia braço.
   Num app cuja tela inteira é um toca-discos, a peça que dá nome ao
   programa não aparecia.

   O que muda: o PIVÔ agora é FIXO, fora do prato, em cima e à direita — como
   num toca-discos de verdade. O braço é uma reta do pivô até a agulha, e a
   agulha anda para dentro conforme o lado avança. Isso dá duas coisas de
   graça: a peça vira reconhecível, e a posição dela passa a INFORMAR — dá
   para ver de longe quanto falta do lado, sem ler número nenhum.

   `cue` é 0 no descanso (fora do disco) e 1 no sulco; `down` é 0 suspenso e
   1 encostado. A cerimônia move os dois; fora dela valem 1 e 1. Suspenso, o
   braço clareia menos e a agulha paira alguns pixels acima do sulco — é o
   que distingue "pousado" de "esperando". */
/* O ângulo em que a agulha lê, no sulco. UM dono, porque a faísca do
   toque precisa nascer exatamente na ponta — e nasce de outro lugar do
   arquivo. Duas cópias da mesma expressão já se separaram uma vez.

   SINTOMA: o braço dava uma volta INTEIRA em torno do pivô a cada ~12 s.
   A conta era `phase * 0.18f` com o `phase` sendo um contador que só cresce
   (0,05 por quadro): 0,009 rad por quadro, 0,54 rad/s, 2π em 11,6 s. Era
   para ser um bamboleio — um braço de toca-discos fica praticamente PARADO
   no ângulo e anda é para dentro, que é o que o raio já faz. Daí o seno. */
static float agulha_angulo(float phase)
{
    return -1.5707963f + sinf(phase * 0.25f) * 0.05f;
}

static void draw_needle(float cx, float cy, float r, float phase, float progress,
                        bool live, float cue, float down)
{
    float park = -1.5707963f + 0.95f;         /* o descanso, fora do prato */
    float play = agulha_angulo(phase);
    float ang = park + (play - park) * cue;

    float rest_r = r * 1.30f;                 /* suspenso, fora do sulco */
    float groove_r = r * (1.0f - progress * 0.86f);
    float read_r = rest_r + (groove_r - rest_r) * cue;

    float px = cx + cosf(ang) * read_r;
    float py = cy + sinf(ang) * read_r;
    py -= (1.0f - down) * 9.0f;               /* suspenso, paira */

    /* O pivô é FIXO: é o que separa um braço de um raio.

       Ele fica DENTRO da metade esquerda da tela de propósito. A 1,16 r ele
       caía em cima do nome do álbum, na coluna de texto à direita — um braço
       de toca-discos atravessando o título não é composição, é acidente. */
    float pvx = cx + r * 0.97f;
    float pvy = cy - r * 1.03f;

    float a = (live || cue > 0.01f) ? (0.42f + 0.58f * down) : 0.30f;
    unsigned int esc = RGBA8(4, 6, 10, (unsigned)(210 * a));
    unsigned int tubo = (COL_AMBER & 0x00FFFFFF) | ((unsigned)(150 * a) << 24);
    unsigned int luz  = (COL_AMBER_BRIGHT & 0x00FFFFFF) | ((unsigned)(210 * a) << 24);

    /* O S DO BRAÇO, curvo de verdade.

       Aqui havia DOIS segmentos retos com um vinco a 80% do caminho. De
       longe passa; de perto é um cotovelo, e um braço de toca-discos não tem
       cotovelo — tem uma curva contínua, que existe para a agulha chegar ao
       sulco tangente e não de esguelha. O vinco era a única coisa que
       impedia o braço de ler como vareta, e trocava um defeito por outro.

       Uma Bézier quadrática resolve: pivô, um ponto de controle deslocado na
       PERPENDICULAR à reta, e a concha. O deslocamento é proporcional ao
       comprimento, então a curva continua a mesma quando a agulha anda para
       dentro do disco. Doze segmentos bastam nesta escala; acima disso já não
       se distingue da curva, e cada segmento custa uma linha grossa. */
    #define ARM_SEGS 12
    float axs[ARM_SEGS + 1], ays[ARM_SEGS + 1];
    {
        float dx = px - pvx, dy = py - pvy;
        float l = sqrtf(dx * dx + dy * dy);
        if (l < 1.0f) l = 1.0f;
        /* a perpendicular, normalizada; o sinal escolhe para que lado o S cai */
        float nx = -dy / l, ny = dx / l;
        float k = l * 0.13f;                  /* a barriga da curva */
        float qx = pvx + dx * 0.55f + nx * k;
        float qy = pvy + dy * 0.55f + ny * k;
        for (int i = 0; i <= ARM_SEGS; i++) {
            float t = (float)i / (float)ARM_SEGS, it = 1.0f - t;
            axs[i] = it * it * pvx + 2.0f * it * t * qx + t * t * px;
            ays[i] = it * it * pvy + 2.0f * it * t * qy + t * t * py;
        }
    }
    /* o contorno escuro primeiro, o tubo por cima: é o contorno que separa o
       braço do disco quando os dois estão sobre o mesmo preto */
    for (int i = 0; i < ARM_SEGS; i++)
        thick_line(axs[i], ays[i], axs[i + 1], ays[i + 1],
                   7.0f - 1.0f * ((float)i / (float)ARM_SEGS), esc);
    for (int i = 0; i < ARM_SEGS; i++) {
        float t = (float)i / (float)ARM_SEGS;
        /* clareia na direção da ponta: o olho segue a luz até a agulha */
        thick_line(axs[i], ays[i], axs[i + 1], ays[i + 1],
                   3.0f + t * 1.0f, t > 0.72f ? luz : tubo);
    }

    /* a concha, no fim do braço */
    alpha_fill(px, py, 5.0f, 0.9f * a, RGBA8(10, 13, 20, 255));
    alpha_ring(px, py, 5.0f, 1.4f, 0.85f * a, COL_AMBER);

    /* o pivô e o contrapeso */
    alpha_fill(pvx, pvy, 8.0f, 0.95f, RGBA8(10, 13, 20, 255));
    alpha_ring(pvx, pvy, 8.0f, 2.2f, 0.70f, COL_AMBER);
    alpha_fill(pvx, pvy, 2.2f, 0.8f, COL_AMBER_BRIGHT);
    {
        /* a direção do contrapeso sai do PRIMEIRO segmento da curva, e não da
           reta pivô-agulha: com a curva, as duas já não são a mesma, e usar a
           reta punha o peso ligeiramente torto em relação ao tubo */
        float dx = pvx - axs[1], dy = pvy - ays[1];
        float l = sqrtf(dx * dx + dy * dy);
        if (l > 1.0f) {
            float wx = pvx + dx / l * 15.0f, wy = pvy + dy / l * 15.0f;
            thick_line(pvx, pvy, wx, wy, 5.0f, esc);
            alpha_fill(wx, wy, 5.0f, 0.85f, RGBA8(10, 13, 20, 255));
            alpha_ring(wx, wy, 5.0f, 1.6f, 0.55f, COL_AMBER);
        }
    }

    /* a agulha em si: o ponto quente, e só quando está tocando */
    if (down > 0.5f && live) {
        alpha_fill(px, py, 2.4f, 0.95f, COL_AMBER_BRIGHT);
        alpha_fill(px, py, 9.0f, 0.25f, COL_AMBER);
    }
}

/* O halo: o brilho frio que respira em volta do prato.

   Ele custava ~1400 chamadas de GPU por quadro — quase um QUARTO do teto de
   6000 do deck (tests/desenho_test.c) — para dois anéis que mal se veem. A
   culpa era da espessura: 16 e 7 px caem no caminho de scanline do
   ring_circle, um retângulo por linha de tela, duas vezes por linha.

   Quatro anéis FINOS custam ~380 segmentos e desenham o mesmo esfumado. Com
   alfa de 0,03 a 0,09 não há banda visível para separar um do outro — e o
   orçamento que sobra é o que paga o brilho do disco e o resto da tela. */
static void draw_halo(float cx, float cy, float base_r, float phase)
{
    float r = base_r * (1.0f + 0.03f * sinf(phase * 1.7f));
    alpha_ring(cx, cy, r * 1.03f, 1.0f, 0.09f, COL_COLD);
    alpha_ring(cx, cy, r * 1.07f, 1.0f, 0.07f, COL_COLD);
    alpha_ring(cx, cy, r * 1.11f, 1.0f, 0.05f, COL_COLD);
    alpha_ring(cx, cy, r * 1.15f, 1.0f, 0.03f, COL_COLD);
}

/* ---------- a cerimônia ---------- */

void ui_begin_ritual(Ui *u)
{
    if (!u) return;
    u->rit = RIT_SPINUP;
    u->rit_t = 0.0f;
    u->spin = 0.0f;
    for (int i = 0; i < SPARKS; i++) u->sparks[i].life = 0.0f;
}


/* Sem cerimônia (o app abriu com música já tocando), o prato já está a plena
   rotação — não há nada a encenar. */
void ui_skip_ritual(Ui *u)
{
    if (!u) return;
    u->rit = RIT_OFF;
    u->rit_t = 0.0f;
    u->spin = 1.0f;
}

bool ui_ritual_done(Ui *u)
{
    if (!u) return false;
    if (u->ritual_just_done) {
        u->ritual_just_done = false;
        return true;
    }
    return false;
}

static void ritual_step(Ui *u, bool live)
{
    const float dt = 1.0f / 60.0f;
    if (u->rit == RIT_OFF) {
        /* o prato acompanha o som: parar a música PARA o disco */
        float target = live ? 1.0f : 0.0f;
        u->spin += (target - u->spin) * 0.06f;
        return;
    }
    u->rit_t += dt;
    switch (u->rit) {
    case RIT_SPINUP:
        /* acelera com folga no fim: um prato de verdade não chega na rotação
           de repente, e é essa folga que faz o olho ler "pesado" */
        u->spin = 1.0f - (1.0f - u->rit_t / RIT_SPINUP_S) * (1.0f - u->rit_t / RIT_SPINUP_S);
        if (u->spin < 0) u->spin = 0;
        if (u->rit_t >= RIT_SPINUP_S) { u->spin = 1.0f; u->rit = RIT_CUE; u->rit_t = 0; }
        break;
    case RIT_CUE:
        u->spin = 1.0f;
        if (u->rit_t >= RIT_CUE_S) { u->rit = RIT_DROP; u->rit_t = 0; }
        break;
    case RIT_DROP:
        u->spin = 1.0f;
        if (u->rit_t >= RIT_DROP_S) { u->rit = RIT_OFF; u->rit_t = 0;
            u->ritual_just_done = true; }
        break;
    default:
        break;
    }
}

/* As faíscas da gota da agulha. O crackle existia no deck do desktop e nunca
   foi desenhado — e quando foi, cada faísca era um segmento de comprimento
   ZERO, que desenha exatamente nada. Aqui elas são círculos com raio mínimo
   garantido, pelo mesmo motivo. */
static void sparks_spawn(Ui *u, float x, float y)
{
    for (int i = 0; i < SPARKS; i++) {
        if (u->sparks[i].life > 0.0f) continue;
        float a = (float)(rand() % 628) / 100.0f;
        float sp = 0.6f + (float)(rand() % 100) / 60.0f;
        u->sparks[i].x = x;
        u->sparks[i].y = y;
        u->sparks[i].vx = cosf(a) * sp;
        u->sparks[i].vy = sinf(a) * sp - 0.5f;
        u->sparks[i].life = 0.5f + (float)(rand() % 50) / 100.0f;
    }
}

static void sparks_draw(Ui *u)
{
    for (int i = 0; i < SPARKS; i++) {
        Spark *s = &u->sparks[i];
        if (s->life <= 0.0f) continue;
        s->life -= 1.0f / 60.0f;
        s->x += s->vx;
        s->y += s->vy;
        s->vy += 0.06f;
        if (s->life <= 0.0f) continue;
        float a = s->life;
        if (a > 1.0f) a = 1.0f;
        /* raio mínimo 1: abaixo disso o fill_circle não põe um pixel e a
           faísca "existe" sem aparecer, que é o defeito que já aconteceu */
        alpha_fill(s->x, s->y, 1.0f + a * 1.6f, a * 0.9f, COL_AMBER_BRIGHT);
    }
}

/* ---------- fundo ---------- */

/* O FUNDO SEGUE O TEMA.

   Era um degradê com seis números escritos à mão — (6,8,13) em cima,
   (13,18,28) embaixo. Com dois temas isso vira a única parte da tela que
   continua falando a língua antiga: o azul do sistema com um fundo âmbar por
   baixo fica sujo, e não há como ver isso lendo o código.

   Agora as duas pontas SAEM da cor de fundo do tema — 70% dela em cima,
   130% embaixo. O degradê continua sendo o mesmo desenho; o que mudou é de
   onde ele tira a cor. */
static unsigned int mistura(unsigned int cor, float f)
{
    int r = (int)((cor        & 0xFF) * f);
    int g = (int)(((cor >> 8) & 0xFF) * f);
    int b = (int)(((cor >> 16) & 0xFF) * f);
    if (r > 255) r = 255;
    if (g > 255) g = 255;
    if (b > 255) b = 255;
    return 0xFF000000u | ((unsigned int)b << 16) |
           ((unsigned int)g << 8) | (unsigned int)r;
}

static void draw_bg(void)
{
    unsigned int topo  = mistura(COL_FUNDO, 0.70f);
    unsigned int baixo = mistura(COL_FUNDO, 1.30f);
    for (int y = 0; y < SCRH; y += 8) {
        float t = (float)y / (float)SCRH;
        int r = (int)(( topo        & 0xFF) + (int)((baixo        & 0xFF) - (int)( topo        & 0xFF)) * t);
        int g = (int)(((topo >> 8)  & 0xFF) + (int)(((baixo >> 8) & 0xFF) - (int)((topo >> 8)  & 0xFF)) * t);
        int b = (int)(((topo >> 16) & 0xFF) + (int)(((baixo >> 16)& 0xFF) - (int)((topo >> 16) & 0xFF)) * t);
        unsigned int c = 0xFF000000 | ((unsigned int)b << 16) |
                         ((unsigned int)g << 8) | (unsigned int)r;
        vita2d_draw_rectangle(0, (float)y, SCRW, 8, c);
    }
    /* vinheta sutil no topo: escurece a barra de abas sem competir com o
       conteúdo — a cabeça é mapa, não assunto */
    vita2d_draw_rectangle(0, 0, SCRW, 50, RGBA8(0, 0, 0, 40));
}

/* Só o título e o fio embaixo dele.

   Ele tinha um terceiro parâmetro, `hint`, que imprimia a fila de atalhos em
   TEXTO — "[tri] estante   [L1] recs". O header_hints veio substituir isso
   DESENHANDO os botões, e a migração ficou pela metade: cinco dos seis
   chamadores já passavam NULL e chamavam o header_hints logo em seguida.

   O sexto, que ainda usava, era o que carregava o "□" — um caractere que a
   fonte do aparelho não tem e que virava quadradinho na tela. Um parâmetro
   que só um chamador usa é onde esse tipo de coisa se esconde. */
/* O CABEÇALHO É O MAPA.

   Antes era um título solto — "SHELF", "QOBUZ" — que dizia onde você está e
   nada sobre onde mais dá para ir. Agora é a fila inteira, com a atual acesa
   e apoiada no filete: a metáfora de aba, que todo mundo já sabe ler. O
   `estado` é o que aquela tela quer acrescentar ("PLAYING", o filtro da
   busca) e vai à DIREITA, longe da fila, para não se confundir com um
   destino.

   Guarda a posição de cada aba no `u` porque o dedo também escolhe: ver o
   trecho do toque no ui_handle_input. */
/* A BATERIA, no canto do cabeçalho.

   O app não mostrava carga em lugar nenhum. Num tocador de mesa isso não
   faz falta; num aparelho que sai de casa no bolso, é a diferença entre
   saber e não saber se a volta tem música. Quem usa isto o dia inteiro
   precisa desse número sem sair da tela em que está.

   Desenhado, e não escrito: uma pilha de 22x11 lê-se de relance, o número
   ao lado só confirma. Abaixo de 15% o conjunto vai para a cor de alarme —
   é a única hora em que ele deve chamar atenção. Carregando, um traço
   atravessa: o estado muda a FORMA, não só a cor, porque no LCD ao sol a
   cor é a primeira coisa que se perde.

   Devolve a largura que ocupou, para quem escreve à direita saber onde
   parar. */
static float desenha_bateria(Ui *u, float dir_x, float cy)
{
    int pct = scePowerGetBatteryLifePercent();
    bool carregando = scePowerIsBatteryCharging() != 0;
    if (pct < 0) return 0.0f;          /* sem leitura: não inventa um número */
    if (pct > 100) pct = 100;

    char txt[8];
    snprintf(txt, sizeof(txt), "%d%%", pct);
    int tw = text_w(u, T_MIUDO, txt);

    const float cw = 22.0f, chh = 11.0f;
    float x = dir_x - tw - 6.0f - cw - 3.0f;   /* 3 = o bico da pilha */
    float y = cy - chh / 2.0f;

    unsigned int cor = (pct <= 15 && !carregando) ? COL_ALARM : COL_TEXT_DIM;
    if (carregando) cor = COL_AMBER;

    /* o corpo e o bico */
    vita2d_draw_rectangle(x, y, cw, 1, cor);
    vita2d_draw_rectangle(x, y + chh - 1, cw, 1, cor);
    vita2d_draw_rectangle(x, y, 1, chh, cor);
    vita2d_draw_rectangle(x + cw - 1, y, 1, chh, cor);
    vita2d_draw_rectangle(x + cw, y + 3.0f, 3.0f, chh - 6.0f, cor);

    /* o quanto resta, por dentro */
    float dentro = (cw - 4.0f) * ((float)pct / 100.0f);
    if (dentro > 0.0f)
        vita2d_draw_rectangle(x + 2.0f, y + 2.0f, dentro, chh - 4.0f, cor);

    /* carregando: um risco na diagonal atravessa a pilha */
    if (carregando)
        vita2d_draw_line(x + cw * 0.62f, y - 2.0f, x + cw * 0.34f, y + chh + 2.0f,
                         COL_AMBER_BRIGHT);

    text(u, (int)(dir_x - tw), (int)(cy + 5.0f), cor, T_MIUDO, txt);
    return tw + 6.0f + cw + 3.0f;
}

static void header(Ui *u, const char *estado)
{
    int atual = aba_de(u->view);
    float x = PAD_X;
    const float folga = 24.0f;   /* o vão entre uma aba e a seguinte */
    float rule_y = HEAD_Y + 18;
    float gy = (float)HEAD_Y - 5.0f;   /* centro dos glifos, na linha das abas */

    /* Os dois glifos LADEIAM a fila, e é assim que a tela ensina o atalho sem
       gastar uma linha de rodapé dizendo "L1/R1 trocam de aba": o botão está
       desenhado encostado naquilo que ele move. */
    x += glyph(u, x, gy, BTN_L1) + 12.0f;

    for (int i = 0; i < UI_NABAS; i++) {
        float w = (float)text_w(u, T_CORPO, ABA_NOME[i]);
        u->aba_x[i] = x;
        u->aba_w[i] = w;
        bool aqui = (i == atual);
        text(u, (int)x, HEAD_Y, aqui ? COL_AMBER : COL_TEXT_DIM, T_CORPO,
             ABA_NOME[i]);
        if (aqui) {
            /* o degrau que apoia a aba no filete: 3 px, e 6 de sobra dos dois
               lados para o bloco de cor ser maior que a palavra */
            vita2d_draw_rectangle(x - 6, rule_y - 2, w + 12, 3, COL_AMBER);
            /* brilho suave na aba: a difusão faz a cor "respirar" para cima */
            vita2d_draw_rectangle(x - 4, rule_y - 5, w + 8, 2, AMBER_A(40));
        }

        /* O PONTO DE "TEM SOM". Fica ao lado de PLAYING e vale em toda tela:
           sem ele, estando no Qobuz ou na conta não havia nada dizendo que a
           música seguia tocando — e o disco continua girando enquanto se
           procura outro, que é o ponto inteiro deste app. */
        if (ABAS[i] == VIEW_DECK && u->tocando) {
            alpha_fill(x + w + 10.0f, (float)HEAD_Y - 5.0f, 2.8f, 0.95f, COL_AMBER);
            alpha_fill(x + w + 10.0f, (float)HEAD_Y - 5.0f, 5.5f, 0.20f, COL_AMBER);
        }
        x += w + folga;
    }
    glyph(u, x - folga + 12.0f, gy, BTN_R1);

    /* filete da aba: centro aceso, bordas suavizadas — o olho acompanha a
       cor ao longo da tela em vez de bater num corte */
    vita2d_draw_rectangle(PAD_X, rule_y, SCRW - 2 * PAD_X, 1,
                          AMBER_A(35));
    vita2d_draw_rectangle(PAD_X, rule_y, 40, 1, AMBER_A(12));
    vita2d_draw_rectangle(SCRW - PAD_X - 40, rule_y, 40, 1, AMBER_A(12));

    /* O ESTADO SÓ ENTRA SE COUBER.

       Ele é escrito encostado na direita, na MESMA linha das abas. Com seis
       abas sobrava metade da tela; com nove (a HOME e a ARTISTS entraram) a
       fila chega perto da borda, e o "filter: ..." da estante passou a ser
       desenhado POR CIMA de SETTINGS — duas palavras no mesmo lugar, e a de
       baixo ilegível.

       `x` aqui já é o fim da fila de abas. Se o texto não couber depois
       dela, ele não é desenhado: quem chama tem outro lugar para dizer a
       mesma coisa (a estante põe o filtro numa pílula no corpo), e uma
       sobreposição é pior que uma ausência. */
    float dir = SCRW - PAD_X - desenha_bateria(u, SCRW - PAD_X, gy);

    /* AS HORAS.

       Um homebrew em tela cheia cobre a barra de status do sistema, então
       enquanto o app está aberto não há relógio em lugar nenhum. Para quem
       ouve música no ônibus isso é a pergunta mais frequente que a tela não
       respondia — e ela cabe em quatro dígitos ao lado da pilha. */
    {
        time_t agora = time(NULL);
        struct tm *lt = localtime(&agora);
        if (lt) {
            char hh[8];
            snprintf(hh, sizeof(hh), "%02d:%02d", lt->tm_hour, lt->tm_min);
            int w = text_w(u, T_MIUDO, hh);
            dir -= 12.0f;
            text(u, (int)(dir - w), (int)(gy + 5.0f), COL_TEXT_DIM, T_MIUDO, hh);
            dir -= w;
        }
    }

    if (estado && estado[0]) {
        int w = text_w(u, T_META, estado);
        float livre = dir - 14.0f - w;
        if (livre > x + 8.0f)
            text(u, (int)livre, HEAD_Y, COL_TEXT_DIM, T_META, estado);
    }
}

/* Cabeçalho com as dicas DESENHADAS. A lista termina num rótulo NULL.
   `b2` diferente de -1 vira "a + b" (as combinações com R1 segurado). */
/* O `header_hints` morreu aqui.

   Ele desenhava a fila de atalhos no rodapé de TODA tela. A lista inteira
   virou a tela de Controls (ver CONTROLES lá em cima), que se lê uma vez —
   que é quantas vezes se aprende um atalho. O rodapé agora é do que MUDA:
   quantos discos há, o que está tocando, o que a busca respondeu. */

/* ---------- a estante ---------- */

#define SHELF_COLS UI_SHELF_COLS
#define SHELF_ROWS UI_SHELF_ROWS
#define SHELF_PAGE UI_SHELF_PAGE

/* A estante vazia.

   Esta tela mudou de assunto. Enquanto o app ADIVINHAVA nomes de pasta, ela
   precisava listar os palpites e mandar a pessoa escrever um roots.txt — era
   a única saída que existia. Agora ele PROCURA (ver library_discover), então
   "ux0:music não existe" deixou de ser informação útil: a pasta pode ter
   qualquer nome, e o app teria achado.

   O que sobrou de acionável é bem menos e bem melhor: copie a música para o
   cartão, em qualquer pasta. O resto é diagnóstico, e diagnóstico fica
   embaixo e apagado — quem precisa dele sabe que precisa.

   A capa vazia à esquerda existe porque uma tela de erro cheia de códigos
   hexadecimais parece um app quebrado. Ela é o mesmo objeto da estante, só
   que sem disco dentro: diz "não há discos aqui" na mesma língua que o
   resto do app fala. */
static void shelf_empty(Ui *u, Library *lib)
{
    char st[512];
    library_status(lib, st, sizeof(st));

    /* a capa vazia, à esquerda */
    {
        float l = 168.0f, x = PAD_X + 8, y = 138.0f;
        vita2d_draw_rectangle(x + 4, y + 4, l, l, RGBA8(3, 5, 10, 160));
        vita2d_draw_rectangle(x, y, l, l, RGBA8(14, 19, 29, 255));
        vita2d_draw_rectangle(x, y, l, 2, AMBER_A(45));
        alpha_ring(x + l * 0.5f, y + l * 0.5f, l * 0.30f, 1.0f, 0.21f, COL_AMBER);
        alpha_ring(x + l * 0.5f, y + l * 0.5f, l * 0.20f, 1.0f, 0.16f, COL_AMBER);
        /* a boca da capa, aberta e sem nada dentro */
        vita2d_draw_rectangle(x + 10, y + l - 34, l - 20, 2, AMBER_A(55));
        vita2d_draw_rectangle(x + 10, y + l - 26, l * 0.42f, 1, RGBA8(138, 147, 163, 90));
    }

    float tx = PAD_X + 200;
    float tw = SCRW - tx - PAD_X;

    text(u, (int)tx, 150, COL_AMBER, T_CABECA, "the shelf is empty");
    text_elided(u, (int)tx, 182, COL_TEXT, T_DESTAQUE, tw, st);

    /* O QUE FAZER. Uma linha, e é a verdade nova: não há nome de pasta a
       acertar. */
    text_elided(u, (int)tx, 224, COL_TEXT, T_CORPO, tw,
                "the app finds the music on its own, in any folder on the card.");
    text_elided(u, (int)tx, 246, COL_TEXT, T_CORPO, tw,
                "copy your records to ux0:music — or wherever you like — and come back.");

    /* UMA linha de diagnóstico, e só quando ela muda o que a pessoa faz.

       Aqui morava uma parede: o cabeçalho "what I saw:", a listagem das oito
       primeiras pastas de ux0:, e até quatro raízes com o código do sistema
       em hexadecimal. Isso é conteúdo de relatório, não de tela — e o
       relatório existe: o library_report escreve tudo, e mais, em
       `varredura.txt` a cada arranque. Quem conserta o app lê o arquivo;
       quem está com o aparelho na mão quer saber o que fazer.

       Sobrou a única distinção que muda a ação de quem está olhando: o
       CARTÃO abre ou não abre. Se não abre, mexer em pasta não conserta
       nada — o conserto é físico. Essa frase fica; o resto foi para o
       arquivo. */
    {
        /* PERMISSÃO NEGADA É OUTRA CONVERSA, e é a que já custou meses.

           O VPK vinha sendo construído como homebrew "safe" (o vita.cmake
           passa "-s" ao vita-make-fself quando falta UNSAFE), e o sandbox do
           HENkaku nesse modo só deixa o app ver ux0:data e app0:. Resultado:
           ux0:music devolvia EPERM com a coleção INTEIRA lá dentro, e esta
           tela dizia "copie seus discos para o cartão" — mandando a pessoa
           refazer o que já estava feito.

           EPERM não se conserta mexendo em pasta: ou o VPK é unsafe, ou o
           aparelho não está deixando homebrew unsafe rodar. Dizer isso é a
           única coisa útil que esta tela pode fazer nesse caso. */
        bool proibido = false;
        for (int i = 0; i < lib->nroots; i++) {
            unsigned e = (unsigned)lib->roots[i].err;
            int errno_do_vita = ((e & 0xFFFF0000u) == 0x80010000u)
                                ? (int)(e & 0xFFFFu) : (int)e;
            if (!lib->roots[i].opened && errno_do_vita == 1) { proibido = true; break; }
        }

        if (proibido) {
            /* EPERM tem DUAS causas possíveis e conselhos opostos, e chutar
               entre elas já custou viagem. A diferença se mede aqui mesmo:
               ux0:app não é pasta de mídia nem está na lista branca do modo
               "safe". Se ELA abre e ux0:music não, então não é sandbox — é o
               Content Manager fechando as pastas de mídia, e mexer no
               HENkaku não muda nada. Se ela também não abre, é o sandbox. */
            DirIter *app = dir_open("ux0:app");
            bool so_midia = (app != NULL);
            if (app) dir_close(app);

            text_elided(u, (int)tx, 290, COL_ALARM, T_DESTAQUE, tw,
                        "the card is there — this app is not allowed to read it");
            if (so_midia) {
                text_elided(u, (int)tx, 316, COL_TEXT, T_CORPO, tw,
                            "ux0:music is a system media folder, closed to apps like this one.");
                text_elided(u, (int)tx, 338, COL_TEXT, T_CORPO, tw,
                            "move your records to ux0:data/vitastylus/music and come back.");
            } else {
                text_elided(u, (int)tx, 316, COL_TEXT, T_CORPO, tw,
                            "turn on \"Enable unsafe homebrew\" in HENkaku Settings,");
                text_elided(u, (int)tx, 338, COL_TEXT, T_CORPO, tw,
                            "then install ux0:vitastylus.vpk again from VitaShell.");
            }
        } else {
            int e = 0;
            DirIter *dev = dir_open_err("ux0:", &e);
            if (!dev) {
                text_elided(u, (int)tx, 290, COL_ALARM, T_CORPO, tw,
                            "the card (ux0:) will not open — is it seated properly?");
            } else {
                dir_close(dev);
            }
        }
    }
    float y = 372;

    /* A saída manual continua existindo, e continua sendo a última linha:
       o caminho vem do paths.h porque é ESTA linha que a pessoa vai digitar,
       e ela não pode divergir do que o scanner realmente lê. */
    text_elided(u, (int)tx, (int)y, COL_TEXT_FAINT, T_MIUDO, tw,
                "still empty? list the folders, one per line, in "
                STYLUS_ROOTS_TXT);
    text_elided(u, (int)tx, (int)y + 20, COL_TEXT_FAINT, T_MIUDO, tw,
                "what the scan saw is written to " STYLUS_DATA_DIR "/varredura.txt");
}


/* ---------- a miniatura da estante ----------

   O PROBLEMA que isto resolve: a estante desenhava DUAS COISAS DIFERENTES.
   Álbum com arte virava um quadrado; álbum sem arte virava um círculo. Lado
   a lado na mesma grade, e num acervo onde 48 discos não têm arte nenhuma, o
   resultado era uma parede em que metade dos itens não se parecia com a
   outra metade — e nada disso queria dizer coisa alguma sobre a música.

   A forma passa a ser uma só, para todo mundo: a CAPA, com o disco saindo
   por trás. É como um disco fica numa prateleira de verdade, é a mesma
   linguagem do ícone e da LiveArea, e resolve a inconsistência sem esconder
   quem não tem arte — quem não tem ganha uma capa gerada, com a inicial, em
   vez de virar outro tipo de objeto.

   O disco é desenhado ANTES e a capa POR CIMA: é a ordem que dá a leitura de
   "dentro da capa". */
static void shelf_record(float cx, float cy, float r, float angle)
{
    if (r < 6) return;
    alpha_fill(cx, cy, r, 1.0f, RGBA8(7, 10, 16, 255));
    /* Poucos sulcos e fracos: nesta escala (uns 40 px de raio) muitos anéis
       de contraste alto viram moiré, e o que precisa sobreviver é a silhueta. */
    alpha_ring(cx, cy, r * 0.86f, 1.0f, 0.23f, COL_AMBER);
    alpha_ring(cx, cy, r * 0.70f, 1.0f, 0.19f, COL_AMBER);
    alpha_ring(cx, cy, r * 0.54f, 1.0f, 0.16f, COL_AMBER);
    alpha_ring(cx, cy, r, 1.6f, 0.55f, COL_AMBER);
    /* o rótulo do disco genérico: uma versão mais escura do acento do
       tema, não um âmbar cravado */
    alpha_fill(cx, cy, r * 0.30f, 0.85f, mistura(COL_AMBER, 0.79f));
    alpha_fill(cx, cy, r * 0.075f, 1.0f, RGBA8(3, 5, 10, 255));
    /* Um respingo de luz que gira com o prato: sem ele o disco parado e o
       disco tocando são o mesmo desenho. */
    float lx = cx + cosf(angle) * r * 0.62f, ly = cy + sinf(angle) * r * 0.62f;
    alpha_fill(lx, ly, r * 0.05f, 0.5f, COL_AMBER_BRIGHT);
}

/* A inicial do álbum, pulando o prefixo de data que quase todo disco ao vivo
   deste acervo tem — senão a inicial de todos seria "1". Devolve 0 se não
   achou letra nenhuma. */
static int album_inicial(const Album *a, char *out, size_t cap)
{
    const char *nome = a->album[0] ? a->album : a->artist;
    while (*nome && !((*nome >= 'A' && *nome <= 'Z') ||
                      (*nome >= 'a' && *nome <= 'z') ||
                      (unsigned char)*nome >= 0xC0))
        nome++;
    if (!*nome) return 0;
    int nb = 1;
    if ((unsigned char)nome[0] >= 0xC0)
        while (nb < 4 && ((unsigned char)nome[nb] & 0xC0) == 0x80) nb++;
    if ((size_t)nb + 1 > cap) return 0;
    memcpy(out, nome, (size_t)nb);
    out[nb] = '\0';
    if (out[0] >= 'a' && out[0] <= 'z') out[0] = (char)(out[0] - 32);
    return 1;
}

/* A MARCA DA CAPA GERADA.

   Quase nenhum disco desta coleção tem arte embutida — 388 discos e um
   punhado de capas —, então a capa GERADA é o que a estante mostra quase
   sempre. E todas eram iguais menos a letra: oito por página, oito
   retângulos idênticos. Uma estante existe para se RECONHECER um disco de
   relance, e não se reconhece nada num muro.

   Cinco famílias de traço, sorteadas por um hash do NOME (não do índice: um
   disco tem de cair sempre no mesmo desenho, senão filtrar a estante
   embaralharia as capas e destruiria justamente o reconhecimento). A lei de
   cor do projeto continua de pé — fósforo, âmbar sobre quase-preto, nenhum
   matiz inventado. O que varia é a GEOMETRIA, que é o que a lei deixa livre. */
static unsigned capa_hash(const Album *a)
{
    unsigned h = 2166136261u;
    for (const char *p = a->artist; *p; p++) h = (h ^ (unsigned char)*p) * 16777619u;
    for (const char *p = a->album;  *p; p++) h = (h ^ (unsigned char)*p) * 16777619u;
    return h;
}

static void capa_marca(const Album *a, float ix, float cap_y, float L)
{
    unsigned h = capa_hash(a);
    float mx = ix + L * 0.5f, my = cap_y + L * 0.36f;
    float r  = L * 0.30f;

    /* Todas as marcas EVITAM o miolo: a inicial mora lá, e a primeira versão
       desta função riscava uma diagonal por cima dela — a letra, que é o que
       se lê de relance numa estante de 388, ficava cortada ao meio. */
    switch (h % 5u) {
    case 0:   /* anéis concêntricos — o sulco */
        alpha_ring(mx, my, r,         1.2f, 0.34f, COL_AMBER);
        alpha_ring(mx, my, r * 0.72f, 1.0f, 0.22f, COL_AMBER);
        break;
    case 1: {  /* barras — a capa tipográfica */
        float w[4] = { 0.86f, 0.54f, 0.70f, 0.38f };
        for (int i = 0; i < 4; i++) {
            float bw = L * w[(h >> (i * 3)) & 3u];
            vita2d_draw_rectangle(ix + L * 0.10f, my - r + i * (r * 0.42f),
                                  bw * 0.78f, 2.0f,
                                  AMBER_A(i == 0 ? 150 : 75));
        }
        break;
    }
    case 2:   /* o disco saindo pela direita */
        alpha_ring(mx + r * 0.55f, my, r * 0.95f, 1.4f, 0.32f, COL_AMBER);
        alpha_fill(mx + r * 0.55f, my, r * 0.18f, 0.30f, COL_AMBER);
        break;
    case 3: {  /* quadrados encaixados */
        for (int i = 0; i < 3; i++) {
            float q = r * (1.0f - i * 0.30f);
            unsigned al = (unsigned)(85 - i * 20);
            vita2d_draw_rectangle(mx - q, my - q, q * 2, 1, AMBER_A(al));
            vita2d_draw_rectangle(mx - q, my + q, q * 2, 1, AMBER_A(al));
            vita2d_draw_rectangle(mx - q, my - q, 1, q * 2, AMBER_A(al));
            vita2d_draw_rectangle(mx + q, my - q, 1, q * 2, AMBER_A(al));
        }
        break;
    }
    default:   /* a cunha no canto, e um ponto de luz */
        thick_line(ix + L * 0.62f, cap_y + L * 0.08f,
                   ix + L * 0.92f, cap_y + L * 0.38f, 1.6f, COL_AMBER);
        thick_line(ix + L * 0.74f, cap_y + L * 0.08f,
                   ix + L * 0.92f, cap_y + L * 0.26f, 1.0f, COL_COLD);
        alpha_fill(ix + L * 0.14f, cap_y + L * 0.16f, 2.6f, 0.60f, COL_AMBER);
        break;
    }
}

/* O DISCO SÓ SAI DA CAPA NO QUE ESTÁ MARCADO — e isso passou a QUERER DIZER
   alguma coisa.

   Com quatro discos por tela, um vinil espiando atrás de cada capa era a
   assinatura da estante. Com DEZOITO, viram dezoito pratos pretos brigando
   com dezoito artes, e a arte é o que se veio olhar.

   Agora ele sai só no marcado, e o gesto vira o do objeto: o disco que você
   está escolhendo é o que começa a deslizar para fora da capa. Os outros
   continuam guardados. É a mesma diferença entre um ritual e uma animação de
   abertura — a que a cerimônia do deck já fazia.

   E a capa do marcado ENCOLHE para o disco caber ao lado; a dos outros ocupa
   o quadro inteiro, que é o tamanho em que a arte se reconhece de longe. */
static void shelf_thumb(Ui *u, Album *a, vita2d_texture *tex,
                        float ix, float iy, float side, float angle, bool sel)
{
    float cap_l = sel ? side * 0.74f : side;
    float cy    = iy + side * 0.5f;
    float cap_y = sel ? cy - cap_l * 0.5f : iy;

    if (sel) {
        float dr  = side * 0.43f;
        float dcx = ix + side - dr;
        shelf_record(dcx, cy, dr, angle);
    }

    if (tex) {
        draw_cover_fit(tex, ix, cap_y, cap_l);
    } else {
        /* A capa gerada. Não é um aviso de falta: é uma capa sóbria, com a
           inicial, que ocupa o mesmo lugar e o mesmo peso de uma de verdade. */
        vita2d_draw_rectangle(ix, cap_y, cap_l, cap_l, RGBA8(16, 22, 33, 255));
        /* A faixa embaixo e o filete em cima são o que separa "capa gerada"
           de "retângulo vazio": dão a ela a estrutura de um objeto impresso.
           Uma capa sem arte ainda é uma CAPA. */
        vita2d_draw_rectangle(ix, cap_y, cap_l, 2, AMBER_A(70));
        vita2d_draw_rectangle(ix, cap_y + cap_l * 0.80f, cap_l, cap_l * 0.20f,
                              RGBA8(10, 14, 21, 200));
        vita2d_draw_rectangle(ix + cap_l * 0.10f, cap_y + cap_l * 0.86f,
                              cap_l * 0.52f, 2, AMBER_A(90));
        vita2d_draw_rectangle(ix + cap_l * 0.10f, cap_y + cap_l * 0.92f,
                              cap_l * 0.32f, 1, RGBA8(138, 147, 163, 110));
        capa_marca(a, ix, cap_y, cap_l);
        char ini[5];
        if (album_inicial(a, ini, sizeof(ini))) {
            float sc = cap_l / 52.0f;
            int lw = text_w(u, sc, ini);
            text(u, (int)(ix + cap_l * 0.5f - lw / 2.0f),
                 (int)(cap_y + cap_l * 0.50f), COL_AMBER, sc, ini);
        }
    }
    /* a borda da capa, que a separa do disco e do fundo */
    vita2d_draw_rectangle(ix, cap_y, cap_l, 1, AMBERB_A(46));
    vita2d_draw_rectangle(ix, cap_y, 1, cap_l, AMBERB_A(46));
    vita2d_draw_rectangle(ix, cap_y + cap_l - 1, cap_l, 1, RGBA8(0, 0, 0, 140));
}

/* A estante precisa saber da conta e da fila do last.fm, e as duas moram
   junto da tela de conta, lá embaixo. */
static const LastfmConfig *ui_conta_cfg(Ui *u);
static int ui_fila_lastfm(Ui *u);

/* "contém", sem diferenciar maiúsculas. Não usa strcasestr: ela é uma
   extensão GNU e o newlib do Vita não a tem. */
static bool contem_ci(const char *palheiro, const char *agulha)
{
    if (!agulha || !agulha[0]) return true;
    if (!palheiro) return false;
    for (const char *p = palheiro; *p; p++) {
        const char *a = agulha, *q = p;
        while (*a && *q) {
            char ca = *a, cq = *q;
            if (ca >= 'A' && ca <= 'Z') ca += 32;
            if (cq >= 'A' && cq <= 'Z') cq += 32;
            if (ca != cq) break;
            a++; q++;
        }
        if (!*a) return true;
    }
    return false;
}

/* Remonta a lista de visíveis. Só quando o termo muda ou a estante muda —
   são 388 comparações, baratas, mas não a cada quadro. */
static void filtro_remonta(Ui *u, Library *lib)
{
    if (!u->busca_suja && u->vis_para == lib->nalbums) return;
    u->busca_suja = false;
    u->vis_para = lib->nalbums;
    u->nvis = 0;
    if (!u->busca[0]) return;                 /* sem termo, sem lista */
    if (u->vis_cap < lib->nalbums) {
        int *v = realloc(u->vis, (size_t)lib->nalbums * sizeof(int));
        if (!v) { u->busca[0] = '\0'; return; }   /* sem memória: sem filtro */
        u->vis = v;
        u->vis_cap = lib->nalbums;
    }
    for (int i = 0; i < lib->nalbums; i++) {
        const Album *a = &lib->albums[i];
        if (contem_ci(a->artist, u->busca) || contem_ci(a->album, u->busca)) {
            u->vis[u->nvis++] = i;
            continue;
        }
        /* E TAMBÉM PELO NOME DA FAIXA.

           O filtro casava artista e disco, e só. Numa coleção de 3.729
           faixas isso quer dizer que procurar uma MÚSICA pelo nome não
           funcionava: quem lembra "Weird Fishes" e não lembra que está em
           In Rainbows não achava nada, e a tela respondia "nothing matches"
           com a faixa ali no cartão. Para quem usa isto como tocador do dia
           a dia, essa é a busca mais comum que existe.

           Custa uma varredura das faixas do disco, e só nos discos que já
           não casaram por artista ou título — e o filtro só é remontado
           quando o termo muda, não a cada quadro. */
        for (int t = 0; t < a->ntracks; t++) {
            if (!contem_ci(a->tracks[t].title, u->busca) &&
                !contem_ci(a->tracks[t].file,  u->busca)) continue;
            u->vis[u->nvis++] = i;
            break;
        }
    }
}

/* Quantos discos a estante mostra, e qual é o i-ésimo. Todo lugar que indexa
   a estante passa por estes dois — é o que mantém o filtro numa peça só. */
static int  shelf_n(const Ui *u, const Library *lib)
{
    return u->busca[0] ? u->nvis : lib->nalbums;
}
static Album *shelf_album(Ui *u, Library *lib, int i)
{
    if (i < 0 || i >= shelf_n(u, lib)) return NULL;
    return library_album(lib, u->busca[0] ? u->vis[i] : i);
}

/* A RÉGUA DE LETRAS, em tela cheia.

   Ela era desenhada POR CIMA da estante já pronta, com um véu a 91% — e os
   9% que sobravam eram capa de disco colorida, que é justamente o que mais
   compete com uma letra. Os cartões apareciam atrás dos "A B C" e o rodapé
   da estante por baixo do rodapé da régua. Uma tela de escolher letra tem de
   ser uma tela, não um decalque.

   Agora ela é desenhada ANTES de tudo, e o desenho da estante nem acontece:
   além de legível, sai de graça — oito cartões e oito capas a menos por
   quadro. */
static void draw_regua(Ui *u, Library *lib)
{
    int n = lib->nalbums;
    /* a régua de letras: A..Z e #, com as que existem acesas. Uma letra
       que não tem disco não pode parecer escolhível. */
    vita2d_draw_rectangle(0, 0, SCRW, SCRH, COL_FUNDO);
    text(u, (int)PAD_X, HEAD_Y, COL_AMBER, T_CABECA, "JUMP TO");
    float bw = (SCRW - 2 * PAD_X) / 9.0f;
    for (int i = 0; i < 27; i++) {
        int col = i % 9, row = i / 9;
        float x = PAD_X + col * bw, y = 140.0f + row * 74.0f;
        char L[4];
        snprintf(L, sizeof(L), "%c", i < 26 ? 'A' + i : '#');
        bool tem = false;
        for (int k = 0; k < n && !tem; k++) {
            const char *nm = lib->albums[k].artist[0] ? lib->albums[k].artist
                                                      : lib->albums[k].album;
            char c0 = nm[0];
            if (c0 >= 'a' && c0 <= 'z') c0 -= 32;
            if (i < 26) tem = (c0 == 'A' + i);
            else tem = !(c0 >= 'A' && c0 <= 'Z');
        }
        bool sel = (i == u->jump_letter);
        if (sel) vita2d_draw_rectangle(x, y - 30, bw - 8, 46, TINT_SEL);
        text(u, (int)x + 14, (int)y, tem ? (sel ? COL_AMBER : COL_TEXT)
                                         : COL_TEXT_FAINT, T_TITULO, L);
    }
    text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, T_CORPO,
         u->busca[0]
           ? "[dir] choose   [X] go   [sq] search   [O] clear filter   [tri] back"
           : "[dir] choose   [X] go   [sq] type to search   [tri] back");
}

/* Declarada aqui porque a estante a usa e ela mora lá embaixo, depois do
   `tri_cheio` de que precisa. Mover uma das duas arrastaria meia dúzia de
   dependências junto; um protótipo custa uma linha. */
static void rodape_agora(Ui *u, Player *p, const char *direita);

static void draw_shelf(Ui *u, Library *lib, Player *p)
{
    /* A RÉGUA vem ANTES de tudo: ela é uma tela inteira, não uma camada por
       cima da estante. Ver a nota no draw_regua. */
    if (u->jump_open) { draw_regua(u, lib); return; }
    filtro_remonta(u, lib);
    int n = shelf_n(u, lib);
    /* Com filtro ligado o título DIZ o filtro: uma estante que mostra 6 de
       388 discos sem explicar por quê parece uma estante quebrada. */
    /* a aba já diz SHELF; aqui sobra o que ela não diz — o filtro em vigor */
    char titulo[80];
    /* o "[O] clears" só aparece com filtro em vigor — que é exatamente
       quando a tecla faz alguma coisa */
    titulo[0] = '\0';
    header(u, titulo);
    if (n <= 0 && u->busca[0]) {
        /* Uma estante filtrada sem resultado NÃO é uma estante vazia, e a
           tela de estante vazia manda copiar música para o cartão — conselho
           errado para quem só digitou um nome que não existe. */
        char m[128];
        snprintf(m, sizeof(m), "nothing matches \"%s\"", u->busca);
        text(u, (int)PAD_X, 170, COL_AMBER, T_SECAO, m);
        /* diz O QUE a busca alcança: artista, disco E faixa. Sem isso, quem
           procurou uma música e não achou conclui que o filtro não procura
           músicas — que era verdade até agora. */
        text(u, (int)PAD_X, 206, COL_TEXT_DIM, T_CORPO,
             "the search looks at artists, records and song titles");
        char cnt2[96];
        snprintf(cnt2, sizeof(cnt2), "0 of %d records", lib->nalbums);
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, T_CORPO, cnt2);
        return;
    }
    if (n <= 0) { shelf_empty(u, lib); return; }

    if (u->sel >= n) u->sel = n - 1;
    if (u->sel < 0) u->sel = 0;

    /* ROLA POR FILEIRA, NÃO POR PÁGINA.

       Antes a estante era `page = sel / 8`: descer uma fileira no fim da tela
       trocava a página INTEIRA, os oito discos sumiam de uma vez e não
       sobrava nenhuma referência do que estava sendo visto. Com 388 discos
       isso são 49 saltos às cegas.

       Agora a janela ANDA: a fileira selecionada é mantida visível e só o
       necessário rola. O que estava na fileira de baixo continua ali, uma
       acima — que é o que deixa alguém percorrer uma estante sem se perder. */
    int nlinhas = (n + SHELF_COLS - 1) / SHELF_COLS;
    int linha_sel = u->sel / SHELF_COLS;
    if (u->shelf_top > linha_sel)                 u->shelf_top = linha_sel;
    if (u->shelf_top < linha_sel - (SHELF_ROWS - 1))
        u->shelf_top = linha_sel - (SHELF_ROWS - 1);
    if (u->shelf_top > nlinhas - SHELF_ROWS)      u->shelf_top = nlinhas - SHELF_ROWS;
    if (u->shelf_top < 0)                         u->shelf_top = 0;
    int scroll = u->shelf_top * SHELF_COLS;
    const Album *now = player_current_album(p);

    UiShelfGeom g;
    ui_shelf_geom(SCRW, SCRH, &g);
    float cw = g.card_w, ch = g.card_h, x0 = g.x0, y0 = g.y0, gap = g.gap;
    float pad = g.cover_pad, side = g.cover_side;

    for (int r = 0; r < SHELF_ROWS; r++) {
        for (int c = 0; c < SHELF_COLS; c++) {
            int idx = scroll + r * SHELF_COLS + c;
            if (idx >= n) continue;
            Album *a = shelf_album(u, lib, idx);
            if (!a) continue;
            float x = x0 + c * (cw + gap);
            float y = y0 + r * (ch + gap);
            bool is_sel = (idx == u->sel);
            bool is_now = (a == now);

            /* SEM MOLDURA. Saíram a sombra em três camadas, o fundo do card
               e as quatro bordas de seleção — nove retângulos por disco, que
               em dezoito discos eram cento e sessenta e dois desenhos só de
               decoração. E visualmente eram pior que caros: dezoito caixas
               com sombra formam um MURO, e a estante existe para se olhar o
               que está DENTRO delas.

               A seleção continua legível sem caixa nenhuma: um halo âmbar
               atrás da capa (que é como a estante do desktop marca o disco no
               prato) e o nome em âmbar. */
            if (is_sel)
                alpha_fill(x + cw / 2, y + side / 2,
                           side * 0.72f, 0.16f, COL_AMBER);

            /* CAPA E TEXTO PARTEM DA MESMA BORDA ESQUERDA.

               Com três fileiras quem limita a capa é a ALTURA (97 px), não a
               coluna (139) — então centrá-la deixava 21 px de cada lado. E se
               o texto acompanhasse a capa em vez da coluna, ele perdia esses
               42 px: "Arctic Monkeys" virava "Arctic…" em metade da tela.
               Alinhados à esquerda, a capa fica no seu tamanho e o rótulo fica
               com a coluna inteira, que é o que ele precisa. */
            float ix = x, iy = y + pad;
            vita2d_texture *tex = cover_tex(u, a);
            if (tex || a->cover_loaded) {
                shelf_thumb(u, a, tex, ix, iy, side, u->disc_angle, is_sel);
            } else {
                /* ainda carregando: um aro, e nenhuma afirmação */
                alpha_ring(ix + side / 2, iy + side / 2, side / 2.4f, 1.0f, 0.18f, COL_COLD);
            }

            if (is_now) {
                /* brilho suave, não ponta: o disco que está tocando se anuncia
                   com uma mancha âmbar que o olho pega de relance */
                alpha_fill(x + 14, y + 14, 5.0f, 0.95f, COL_AMBER);
                alpha_fill(x + 14, y + 14, 14.0f, 0.12f, COL_AMBER);
            }
            /* O FILETE SOB A CAPA é a marca de seleção. Uma régua de dois
               pixels na largura da arte diz "este" tão bem quanto uma caixa
               inteira em volta, e não constrói muro nenhum. */
            if (is_sel)
                vita2d_draw_rectangle(ix, iy + side + 3.0f, side, 2, COL_AMBER);

            /* O TEXTO ALINHA COM A ARTE, não com a célula.

               Ver a nota do `ix` acima: os dois partem de `x`. */
            float tx = x, tw = cw;
            /* o rótulo não é o nome da pasta — ver album_display no library.c */
            char rot[MAX_NAME_LEN], sub[MAX_NAME_LEN];
            album_display(a, rot, sizeof(rot), sub, sizeof(sub));
            const char *sub_p = sub;
            if (a->ndecodable == 0) sub_p = "this app cannot play this format";
            text_elided(u, (int)tx, (int)(y + g.label_dy),
                        is_sel ? COL_AMBER : COL_TEXT, T_CORPO, tw, rot);
            text_elided(u, (int)tx, (int)(y + g.sub_dy),
                        a->ndecodable == 0 ? COL_ALARM : COL_TEXT_DIM, T_META, tw, sub_p);
        }
    }

    char cnt[96];
    /* "página 7 de 49" não diz nada a quem procura um disco; a POSIÇÃO diz.
       E a barra à direita mostra de relance o tamanho do que ainda falta —
       coisa que número nenhum entrega. */
    if (u->busca[0])
        snprintf(cnt, sizeof(cnt), "%d of %d record%s   ·   %d",
                 n, lib->nalbums, lib->nalbums == 1 ? "" : "s", u->sel + 1);
    else
        snprintf(cnt, sizeof(cnt), "%d of %d record%s",
                 u->sel + 1, n, n == 1 ? "" : "s");
    /* O filtro vive AQUI, e não na barra de abas.

       Ele estava escrito encostado na direita do cabeçalho, e com nove abas
       passou a ser desenhado por cima de SETTINGS. Tentei uma pílula no
       corpo: entre o filete das abas e a primeira fileira de discos há 14 px,
       não cabe. A linha de baixo já dizia "1 of 414" e tem largura sobrando —
       é o lugar certo para dizer POR QUE são 1 e não 414. */
    char rod[192];
    if (u->busca[0])
        snprintf(rod, sizeof(rod), "filter: \"%s\"   ·   %s", u->busca, cnt);
    else
        snprintf(rod, sizeof(rod), "%s", cnt);
    rodape_agora(u, p, rod);

    if (nlinhas > SHELF_ROWS) {
        float tx = SCRW - 7.0f, ty = g.y0, th = SHELF_ROWS * ch + gap;
        vita2d_draw_rectangle(tx, ty, 3, th, RGBA8(30, 38, 52, 255));
        float frac = (float)SHELF_ROWS / (float)nlinhas;
        float hh = th * frac;
        if (hh < 22.0f) hh = 22.0f;
        float pos = (float)u->shelf_top / (float)(nlinhas - SHELF_ROWS);
        vita2d_draw_rectangle(tx, ty + (th - hh) * pos, 3, hh, COL_AMBER);
    }

    /* A FILA PRESA, dita onde se vê.

       O last.fm inteiro funciona — login no aparelho, fila no cartão, envio
       em segundo plano — e mesmo assim a fila do dono deste app tinha 139
       escutas paradas: sem credencial, o envio volta na entrada e a fila só
       cresce. Nada em tela nenhuma dizia isso. A tela de CONTA diria, mas
       ela fica a dois [R1] daqui e não é anunciada em lugar nenhum.

       Então a estante diz. Só quando há escuta parada E não há conta: quem
       já configurou nunca vê esta linha, e quem nunca ouviu nada também
       não. Um aviso que aparece sempre é um aviso que ninguém lê. */
    {
        int fila = ui_fila_lastfm(u);
        if (fila > 0 && !ui_conta_cfg(u)->configured) {
            char aviso[128];
            snprintf(aviso, sizeof(aviso),
                     "%d play%s waiting for last.fm  ·  set it up in ACCOUNT",
                     fila, fila == 1 ? "" : "s");
            int w = text_w(u, T_META, aviso);
            text(u, SCRW - (int)PAD_X - w, FOOT_Y, COL_TEXT_FAINT, T_META, aviso);
        }
    }
}

/* ---------- o deck ---------- */

static void fmt_time(char *b, size_t cap, int sec)
{
    if (sec < 0) { snprintf(b, cap, "--:--"); return; }
    snprintf(b, cap, "%02d:%02d", sec / 60, sec % 60);
}

/* ---------- os botões de transporte ----------

   O deck só respondia a GESTO: toque no disco pausa, arrasto de lado troca de
   faixa. Gesto funciona e não se descobre olhando — quem pega o aparelho não
   tem como saber que a tela responde ao dedo. Três botões desenhados dizem
   isso sem uma linha de texto.

   Eles são desenhados no vocabulário da §5.5: luz sobre o quase-preto, âmbar,
   nada de relevo nem de botão de plástico. O triângulo é preenchido por
   fatias horizontais porque o vita2d não desenha polígono — e são poucas
   fatias, contadas no orçamento de desenho. */

/* triângulo cheio apontando para a direita (dir=+1) ou esquerda (dir=-1),
   com a PONTA em (px,py) e a base a `w` dali */
static void tri_cheio(float px, float py, float w, float h, int dir,
                      unsigned int col)
{
    int n = (int)(h + 0.5f);
    if (n < 1) n = 1;
    for (int i = 0; i <= n; i++) {
        float y = py - h / 2.0f + (float)i * h / (float)n;
        float d = fabsf(y - py);
        float lw = w * (1.0f - 2.0f * d / h);   /* largura desta fatia */
        if (lw < 0.6f) continue;
        /* `dir > 0` APONTA PARA A DIREITA, que é como os três chamadores
           sempre acharam que era.

           SINTOMA: os três botões do transporte saíam espelhados. O de tocar
           mostrava um triângulo apontando para a ESQUERDA, o de faixa
           anterior mostrava ">>" e o de próxima "<<". Toda a fileira dizia o
           contrário do que fazia, e nada no código parecia errado — os
           chamadores estão certos; era esta linha que invertia.

           O que enganava: aqui NÃO se desenha um triângulo, e sim uma pilha
           de retângulos de larguras diferentes. O lado que APONTA é aquele
           cuja borda MUDA de linha para linha; o lado da borda fixa é a base.
           A conta antiga fixava a borda errada nos dois ramos. A extensão em
           x é a mesma de antes ([px, px+w] e [px-w, px]), então a posição dos
           botões não muda — só a ponta. */
        float x = (dir > 0) ? px : px - lw;
        vita2d_draw_rectangle(x, y, lw, 1.3f, col);
    }
}

/* um botão: o anel e o que ele mostra. `qual`: 0 anterior, 1 tocar/pausar,
   2 próxima. */
static void botao_transporte(float cx, float cy, float r, int qual, bool live,
                             bool aceso)
{
    unsigned int col = aceso ? COL_AMBER_BRIGHT : COL_AMBER;
    float a = aceso ? 0.95f : 0.62f;
    unsigned int c = (col & 0x00FFFFFF) | ((unsigned)(a * 255.0f) << 24);

    alpha_fill(cx, cy, r, aceso ? 0.25f : 0.12f, COL_AMBER);
    alpha_ring(cx, cy, r, 1.4f, a * 0.75f, col);

    float h = r * 0.86f, w = r * 0.52f;
    if (qual == 1) {
        if (live) {                    /* tocando: as duas barras da pausa */
            vita2d_draw_rectangle(cx - w * 0.62f, cy - h / 2, 3.0f, h, c);
            vita2d_draw_rectangle(cx + w * 0.22f, cy - h / 2, 3.0f, h, c);
        } else {                       /* parado: o triângulo de tocar */
            tri_cheio(cx - w * 0.45f, cy, w * 1.25f, h, +1, c);
        }
        return;
    }
    /* anterior e próxima: dois triângulos e a barra do batente */
    int dir = (qual == 2) ? +1 : -1;
    float x0 = cx - dir * w * 0.75f;
    tri_cheio(x0, cy, w * 0.8f, h * 0.82f, dir, c);
    tri_cheio(x0 + dir * w * 0.85f, cy, w * 0.8f, h * 0.82f, dir, c);
    vita2d_draw_rectangle(cx + dir * (w * 0.95f), cy - h * 0.41f, 2.0f,
                          h * 0.82f, c);
}

/* A PÍLULA "TOQUE A VERSÃO LOSSLESS".

   Ela mora no FIM DA LINHA DO SINAL, e o lugar é o argumento: a linha do
   sinal é onde a pessoa já está lendo "MP3 · 44100 Hz / 16 bits". Oferecer a
   troca em qualquer outro canto da tela seria mais um atalho a decorar; ali é
   uma resposta à frase que ela acabou de ler.

   Só aparece quando há o que trocar — faixa do CARTÃO, com conta do Qobuz
   configurada. Num app cheio de botões que às vezes não fazem nada, um botão
   que só existe quando funciona vale mais que um sempre visível e cinza.

   Um dono só para a geometria: o desenho pinta daqui e o dedo mira daqui.
   Escritas duas vezes elas se separam no primeiro ajuste de espaçamento, e o
   sintoma é o dedo acertar outra coisa com a tela parecendo certa. */
static const char *casa_rotulo(Ui *u, const char *kind)
{
    if (u->casando) return "looking…";
    /* O rótulo diz o GANHO, não o mecanismo. "GET FLAC" num arquivo que já é
       FLAC seria uma promessa vazia — ali o que o catálogo tem a mais é a
       versão de 24 bits. */
    bool perdeu = kind && (!strcmp(kind, "MP3") || !strcmp(kind, "OGG") ||
                           !strcmp(kind, "OPUS") || !strcmp(kind, "VORBIS") ||
                           !strcmp(kind, "AAC"));
    return perdeu ? "GET FLAC" : "GET HI-RES";
}

static void casa_pilula(Ui *u, const char *rot, float dir_x, float y,
                        float *x, float *w, float *h)
{
    float larg = (float)text_w(u, T_MIUDO, rot) + 20.0f;
    if (x) *x = dir_x - larg;
    if (w) *w = larg;
    if (h) *h = 20.0f;
    (void)y;
}

static void draw_transporte(Ui *u, const UiDeckGeom *g, bool live)
{
    for (int i = 0; i < 3; i++) {
        float bx = g->cx + (float)(i - 1) * g->tr_gap;
        botao_transporte(bx, g->tr_y, g->tr_r, i, live, u->tr_aceso == i);
    }
    if (u->tr_aceso >= 0 && --u->tr_pisca <= 0) u->tr_aceso = -1;
}

static void draw_deck(Ui *u, Library *lib, Player *p)
{
    const Album *a = player_current_album(p);
    if (!a) {
        fase("empty deck: header");
        /* DESENHADA, não escrita. O "□" que morava aqui não existe na fonte
           do aparelho: virava quadradinho na tela, e era a única dica ainda
           soletrada — as outras já eram glifo. Foi a migração pela metade do
           `header()` para o `header_hints()` que deixou esta sobrar. */
        header(u, "");
        /* disco vazio com aro sutil: diz "aqui é onde o disco aparece" */
        {
            float ecx = PAD_X + 80, ecy = 190, er = 62;
            fase("empty deck: ring");
            alpha_fill(ecx, ecy, er, 0.90f, RGBA8(11, 14, 20, 255));
            alpha_ring(ecx, ecy, er, 1.4f, 0.20f, COL_COLD);
            alpha_ring(ecx, ecy, er * 0.72f, 1.0f, 0.14f, COL_COLD);
            alpha_ring(ecx, ecy, er, 2.0f, 0.12f, COL_COLD);
            alpha_fill(ecx, ecy, 6.0f, 0.30f, COL_COLD);
        }
        fase("empty deck: text");
        text(u, (int)(PAD_X + 180), 160, COL_TEXT, T_SECAO, "nothing on the platter");
        const char *err = player_last_error(p);
        if (err && err[0]) {
            text(u, (int)(PAD_X + 180), 194, COL_ALARM, T_DESTAQUE, "the last attempt stopped here:");
            text_elided(u, (int)(PAD_X + 180), 220, COL_TEXT, T_DESTAQUE,
                        SCRW - PAD_X - 180, err);
        } else {
            text(u, (int)(PAD_X + 180), 194, COL_TEXT_DIM, T_DESTAQUE,
                 "pick a record from the shelf — [tri]");
        }
        fase("empty deck: done");
        (void)lib;
        u->deck_stage = "empty";
        u->deck_tex = 0;
        u->deck_linhas = 0;
        return;
    }
    fase("deck: start");
    const Track *t = player_current_track(p);
    if (!t && a->ntracks > 0) t = &a->tracks[0];

    bool live = player_state(p) == PLAYER_PLAYING;
    int pos = player_track_seconds(p);
    /* -1 é "não sei", e não pode virar 1: dividir por 1 punha a agulha no fim
       do disco em toda faixa. Sem duração, não há progresso a afirmar. */
    int dur = player_track_duration(p);
    if (dur <= 0 && t) dur = t->seconds;
    float progress = (dur > 0) ? (float)pos / (float)dur : 0.0f;
    if (progress < 0) progress = 0;
    if (progress > 1) progress = 1;
    u->prog = progress;
    u->dur = dur;

    /* ═══ PROGRESSO DA FAIXA vs PROGRESSO DO LADO ═══════════════════════
     *
     * No vinil, a agulha não percorre o disco inteiro por FAIXA: ela fica
     * numa faixa estreita do sulco, e o progresso é o deslocamento DENTRO
     * dessa faixa. No CD, o laser anda de dentro para fora por faixa.
     *
     * O `side_progress` diz onde no LADO a faixa atual está: soma o tempo
     * de todas as faixas anteriores + posição atual, dividido pelo total
     * do lado. A agulha mostra a faixa no lado, não a faixa sozinha. */
    float side_progress = progress;
    if (u->midia != MIDIA_CD && a->tracks && a->ntracks > 1) {
        int total_side = 0;
        int before = 0;
        int tidx = player_track_idx(p);
        for (int i = 0; i < a->ntracks && i < DISC_FAIXAS_MAX; i++) {
            total_side += a->tracks[i].seconds;
            if (i < tidx) before += a->tracks[i].seconds;
        }
        if (total_side > 0 && tidx >= 0 && tidx < a->ntracks) {
            side_progress = (float)(before + pos) / (float)total_side;
            if (side_progress < 0) side_progress = 0;
            if (side_progress > 1) side_progress = 1;
        }
    }

    /* Reduzidos ao ciclo: os dois só ALIMENTAM seno e cosseno, e um float que
       cresce sem teto perde precisão — numa sessão de horas o giro do disco
       começa a andar aos trancos, e nada na tela explica por quê. */
    u->halo_phase = fmodf(u->halo_phase + 0.05f, 6.2831853f * 4.0f);
    ritual_step(u, live);
    /* o ângulo acumula com a VELOCIDADE do prato: durante a partida ele
       acelera de verdade, e parada a música ele desacelera até parar */
    u->disc_angle = fmodf(u->disc_angle + 0.075f * u->spin, 6.2831853f);
#ifdef STYLUS_CYCLE
    if (g_congela_disco) u->disc_angle = 0.0f;   /* cena 6: a rotação morre aqui */
#endif

    float cue = 1.0f, down = 1.0f;
    if (u->rit == RIT_SPINUP)   { cue = 0.0f; down = 0.0f; }
    else if (u->rit == RIT_CUE) { cue = u->rit_t / RIT_CUE_S; down = 0.0f; }
    else if (u->rit == RIT_DROP){ cue = 1.0f; down = u->rit_t / RIT_DROP_S; }

    player_spectrum(p, u->spect, SPECT_BANDS);

    UiDeckGeom g;
    ui_deck_geom(SCRW, SCRH, &g);
    float cx = g.cx, cy = g.cy, base_r = g.r;

    if (u->deck_enxuto > 2) {
        /* ═══ O PRIMEIRO QUADRO DO DECK VEM ENXUTO ═══════════════════════
         *
         * O deck é a tela mais pesada do app, e ele entra numa troca de
         * tela — o instante em que todo GPUCRASH deste aparelho caiu: o
         * frame 47 do arranque, a pôr o deck na mão pela primeira vez.
         *
         * Estes dois quadros desenham só o essencial — fundo, corpo do
         * disco, a capa no rótulo e a identidade do que toca. Nada de
         * backdrop esborratado, halo, sulcos, lustro, agulha ou lista:
         * a lista de display deste quadro cai de ~1100 chamadas para
         * ~40, que é o espaço que a GPU tem garantido na hora da troca.
         *
         * É invisível: dois quadros a 60 Hz não se veem, e a tela inteira
         * volta no quadro seguinte. Quem entra no deck vê o disco e a capa
         * um quadro antes de ver o resto — que é exatamente como o
         * placeholder do rótulo já funcionava quando a capa ainda não
         * estava servida.
         *
         * Não é paliativo de desenho feio: a troca de tela é o único ponto
         * em que a tela ANTERIOR ainda está na tela (a swap é a última
         * coisa), e é ali que a GPU acomoda a transição. Deixar o deck
         * inteiro entrar nessa contagem foi o que o estourou.
         *
         * Depois destes dois vêm DOIS QUADROS MÉDIOS (ver o portão antes
         * da lista): o degrau 40 -> 1050 de uma vez matava mesmo com os
         * dois lite — dumps de 08/09, sempre no primeiro quadro cheio. */
        u->deck_enxuto--;
        const bool cd_enxuto = (u->midia == MIDIA_CD);
        vita2d_draw_rectangle(0, 0, SCRW, SCRH,
                              (COL_FUNDO & 0x00FFFFFFu) | (255u << 24));
        header(u, live ? "PLAYING" : "PAUSED");
        if (cd_enxuto) {
            alpha_fill(cx, cy, base_r, 0.90f, RGBA8(176, 186, 202, 255));
        } else {
            alpha_fill(cx, cy, base_r, 0.92f, RGBA8( 30,  36,  50, 255));
            alpha_fill(cx, cy, base_r, 0.12f, RGBA8(150, 162, 190, 255));
        }
        alpha_ring(cx, cy, base_r, 1.6f, 0.25f,
                   cd_enxuto ? RGBA8(226, 234, 248, 255) : COL_AMBER);
        {
            float lab = base_r * (cd_enxuto ? 0.29f : 0.33f);
            vita2d_texture *tex = deck_capa_tex(u, (Album *)a);
            if (tex) draw_cover_round(tex, cx, cy, lab);
            else     alpha_fill(cx, cy, lab, 0.24f, COL_AMBER);
        }
        text_elided(u, (int)g.text_x, 176, COL_TEXT, T_TITULO, g.text_w,
                    t ? t->title : "—");
        text_elided(u, (int)g.text_x, 208, COL_TEXT_DIM, T_DESTAQUE, g.text_w,
                    a->artist[0] ? a->artist : "—");
        /* a entrada lê a geometria que o desenho anotou — sem lista e sem
           pílula aqui, os alvos mortos do quadro anterior não podem pegar */
        u->deck_nlin = 0;
        u->casa_w = 0.0f;
        fase("deck: lite entry frame");
        u->deck_stage = "lite";
        u->deck_tex = 0;
        u->deck_linhas = 0;
        return;
    }

    /* Daqui para baixo, enxuto 2..1 é o quadro MÉDIO: disco cheio e
       agulha, mas sem lista, sem espectro e com o governador forçado ao
       modo leve. O portão que volta mais adiante (antes da letra) consome
       estes dois; o quadro cheio só entra no zero. */
    bool medio = (u->deck_enxuto > 0);

    /* o fundo é a CAPA deste disco, esborratada e escura — não uma textura
       genérica. É a única coisa na tela que diz "este disco" antes de a
       pessoa ler uma letra. Mas ela só entra no quadro CHEIO: é a maior
       tela de fill do deck (1 tela texturizada), e o degrau de entrada
       sobe em rampa — no médio o fundo é chapado. */
    if (medio)
        vita2d_draw_rectangle(0, 0, SCRW, SCRH,
                              (COL_FUNDO & 0x00FFFFFFu) | (255u << 24));
    else
        u->deck_tex = deck_backdrop(u, (Album *)a);

    draw_halo(cx, cy, base_r, u->halo_phase);
    /* ═══ O DISCO VOLTOU A SER DESENHADO INTEIRO ══════════════════════════
     *
     * Aqui estava `true` fixo: sulcos 24->12, lustro 34->17 e espectro
     * desligado, SEMPRE, com o argumento de que a lista de display cheia não
     * deixava espaço para o overlay de volume do sistema.
     *
     * Duas coisas desmentiram isso. A primeira é que o `gpu.txt` do dia 7
     * mostra `lean mode ON` num quadro de 1.082 chamadas e o aparelho travou
     * do mesmo jeito: a economia foi paga e não comprou nada. A segunda é
     * onde o custo estava de verdade — o `deck_backdrop`, com sete telas
     * cheias de preenchimento em sete chamadas (ver a nota do blur_faz).
     * Doze sulcos a menos não pesavam perto disso.
     *
     * O disco é o que o dono mais quer bonito, e ele passou a semana inteira
     * olhando para a versão pela metade sem que nada na tela dissesse isso.
     * Então volta o desenho cheio, e quem decide agora é o governador — que
     * também foi consertado, e que a partir de agora mede tempo de montagem
     * E preenchimento em vez de ficar encostado no teto do vsync. */
    /* as durações, para os vãos saírem onde as faixas acabam. Um vetor na
       pilha porque o `Track` é grande e o desenho só quer os segundos. */
    int segs_faixa[DISC_FAIXAS_MAX];
    const int *segs_ptr = NULL;
    if (a->tracks && a->ntracks > 0 && a->ntracks <= DISC_FAIXAS_MAX) {
        for (int i = 0; i < a->ntracks; i++) segs_faixa[i] = a->tracks[i].seconds;
        segs_ptr = segs_faixa;
    }
    float vinyl_prog = (u->midia != MIDIA_CD) ? side_progress : progress;
    draw_disc(cx, cy, base_r, vinyl_prog, a->ntracks, segs_ptr, player_track_idx(p),
              u->disc_angle, (medio || !live) ? NULL : u->spect,
              u->spin, u->midia, medio ? true : u->gpu_safe);
    if (u->midia != MIDIA_CD) {
        draw_needle(cx, cy, base_r, u->halo_phase, vinyl_prog, live, cue, down);
    } else {
        /* UM CD NÃO TEM BRAÇO. Deixar a agulha ali era desenhar um
           toca-discos com um CD em cima: a peça que dá nome ao app contando
           uma mentira sobre o objeto que está tocando.

           No lugar dela, o que um leitor de CD tem de verdade: a ÓPTICA, que
           corre por baixo NUMA LINHA RADIAL, do miolo para a borda. Fica em
           baixo (6 horas), parada no ângulo, andando só no raio — que é
           exatamente o movimento da peça real. */
        float rr = base_r * (0.36f + progress * 0.60f);
        float ang = 1.5707963f;                    /* 6 horas */
        float px = cx + cosf(ang) * rr, py = cy + sinf(ang) * rr;
        float bx = cx + cosf(ang) * (base_r * 0.30f);
        float by = cy + sinf(ang) * (base_r * 0.30f);
        float ex = cx + cosf(ang) * (base_r * 1.02f);
        float ey = cy + sinf(ang) * (base_r * 1.02f);
        vita2d_draw_line(bx, by, ex, ey, COLD_A(70));   /* o trilho */
        alpha_fill(px, py, live ? 3.4f : 2.6f, live ? 0.95f : 0.55f,
                   COL_AMBER_BRIGHT);
        alpha_fill(px, py, 6.5f, live ? 0.18f : 0.08f, COL_AMBER);
    }

    /* a agulha ENCOSTOU: é aqui que as faíscas nascem, uma vez */
    if (u->rit == RIT_DROP && u->rit_t < 1.2f / 60.0f) {
        float ang = agulha_angulo(u->halo_phase);
        sparks_spawn(u, cx + cosf(ang) * base_r, cy + sinf(ang) * base_r);
    }
    sparks_draw(u);

    /* A CAPA no meio do disco, no lugar do selo: é o que faz o objeto na tela
       ser ESTE disco e não um disco. */
    {
        vita2d_texture *tex = deck_capa_tex(u, (Album *)a);
        /* No CD o rótulo é menor: o furo e o cubo precisam de espaço, e uma
           capa que vai até o miolo é um vinil com a cor errada. */
        float lab = base_r * (u->midia == MIDIA_CD ? 0.29f : 0.33f);
        /* sombra um pouco maior por baixo: assenta o rótulo no prato em vez
           de deixá-lo parecendo colado por cima */
        alpha_fill(cx, cy, lab + 3.0f, 0.55f, RGBA8(5, 7, 11, 255));
        if (tex) {
            draw_cover_round(tex, cx, cy, lab);
        } else {
            /* sem capa, um rótulo liso — ainda lê como rótulo */
            alpha_fill(cx, cy, lab, 0.24f, COL_AMBER);
            alpha_ring(cx, cy, lab * 0.62f, 1.0f, 0.20f, COL_AMBER);
        }
        alpha_ring(cx, cy, lab, 1.5f, 0.55f, COL_AMBER);
        if (u->midia == MIDIA_CD) {
            /* O FURO POR CIMA. A capa acabou de tapar o miolo, e num CD é o
               miolo vazado que faz a forma ser um CD. Redesenhado aqui, e
               não no draw_disc, porque a ordem é disco → capa → furo. */
            alpha_fill(cx, cy, base_r * 0.20f, 0.55f, RGBA8(150, 162, 180, 255));
            alpha_ring(cx, cy, base_r * 0.20f, 1.0f, 0.40f, RGBA8(226, 234, 248, 255));
            cd_furo(cx, cy, base_r);
        } else {
            /* o furo do eixo é o que fecha a leitura de vinil */
            alpha_fill(cx, cy, 6.0f, 1.0f, RGBA8(5, 7, 11, 255));
            alpha_ring(cx, cy, 6.0f, 1.0f, 0.60f, COL_AMBER_BRIGHT);
        }
    }

    float tx = g.text_x;
    float tw = g.text_w;

    header(u, live ? "PLAYING" : "PAUSED");
    {
        header(u, "");
    }

    /* A HIERARQUIA DA COLUNA. Ela estava invertida: o NOME DA PASTA era a
       maior coisa da tela (escala 1,00) e o nome da faixa que está tocando
       AGORA vinha depois, menor (0,66). Numa coleção onde a pasta se chama
       "1993-04-02 - Radiohead - Tel Aviv, Roxanne", isso é o equivalente a
       imprimir o número de catálogo em cima da capa.

       A ordem agora é a de quem está ouvindo: quem toca (o artista) e ONDE
       no objeto (o lado) na primeira linha, o QUE está soando em seguida e
       grande, e o disco de onde ele veio embaixo, menor. O lado sobe para a
       linha do artista porque ele qualifica o mesmo assunto — "Radiohead,
       disco 1, lado A" é uma frase só — e porque assim sobra altura para o
       título da faixa ser grande de verdade. */
    /* UM LADO SÓ NÃO É UM LADO.

       SINTOMA, do dono: "detecting disks and sides in a weird way". Boa parte
       desta coleção são faixas soltas, EPs e shows — coisas que não são um LP.
       Um disco de 18 minutos dá n == 1 no sides_build, e a tela ainda
       carimbava "SIDE A" nele. "Lado A" só quer dizer alguma coisa quando
       existe um lado B para virar; sozinho, é um enfeite que promete um objeto
       que não está ali.

       O corte é aqui, na TELA, e não no sides_build: aquele é a
       transliteração fiel do vinyl.py do desktop e o check.sh compara os dois
       lado a lado — mexer lá faria as duas metades divergirem, que é
       exatamente o que aquele arquivo existe para impedir. */
    int lado = -1;
    if (a->lados.n > 1) lado = sides_of_track(&a->lados, player_track_idx(p));
    {
        /* cabe o artista inteiro (MAX_NAME_LEN) mais o rótulo do lado */
        char topo[MAX_NAME_LEN + 64], rot[12];
        snprintf(topo, sizeof(topo), "%s", a->artist[0] ? a->artist : "—");
        if (lado >= 0) {
            sides_label(&a->lados, lado, rot, sizeof(rot));
            size_t k = strlen(topo);
            if (a->lados.discos > 1)
                snprintf(topo + k, sizeof(topo) - k, "   ·   DISC %d  ·  %s",
                         lado / 2 + 1, rot);
            else
                snprintf(topo + k, sizeof(topo) - k, "   ·   %s", rot);
        }
        text_elided(u, (int)tx, 128, COL_AMBER, T_CORPO, tw, topo);
    }

    /* O QUE ESTÁ SOANDO. A maior coisa da coluna, e a única em branco cheio. */
    text_elided(u, (int)tx, 176, COL_TEXT, T_TITULO, tw, t ? t->title : "—");

    /* e de que disco ele veio */
    /* o disco de onde veio, pelo rótulo e não pelo nome da pasta: aqui em
       cima o artista já está escrito, então "1993-04-02 - Radiohead - Tel
       Aviv, Roxanne" gastaria a linha inteira repetindo-o e cortaria
       justamente o lugar do show. Ver album_display no library.c. */
    {
        char rot[MAX_NAME_LEN], subx[MAX_NAME_LEN];
        album_display(a, rot, sizeof(rot), subx, sizeof(subx));
        text_elided(u, (int)tx, 208, COL_TEXT_DIM, T_DESTAQUE, tw, rot);
    }

    char cur[16], tot[16], info[160];
    fmt_time(cur, sizeof(cur), pos);
    fmt_time(tot, sizeof(tot), dur);
    snprintf(info, sizeof(info), "%s / %s   ·   track %d of %d",
             cur, tot, player_track_idx(p) + 1, player_track_count(p));
    text_elided(u, (int)tx, 240, COL_TEXT_DIM, T_CORPO, tw, info);

    draw_transporte(u, &g, live);

    vita2d_draw_rectangle(tx, g.bar_y, tw, g.bar_h, COL_BAR_BED);
    if (dur > 0) {
        vita2d_draw_rectangle(tx, g.bar_y, tw * progress, g.bar_h, COL_AMBER);
        /* brilho difuso na cabeça da barra: indica onde o dedo pega, e faz
           a barra parecer tridimensional sem sombra — fósforo, não foto */
        float hx = tx + tw * progress;
        vita2d_draw_rectangle(hx - 8, g.bar_y - 3, 16, g.bar_h + 6,
                              AMBER_A(55));
        alpha_fill(hx, g.bar_y + g.bar_h / 2, 4.0f, 0.95f, COL_AMBER_BRIGHT);
    }

    /* O CAMINHO DO SINAL, medido e não prometido. Um FLAC de 96k/24 num Vita
       vira 48k/16 antes de sair — a tela diz isso em vez de imprimir a
       qualidade do arquivo e deixar a pessoa achar que ouviu aquilo. */
    {
        PlayerSignal sig;
        player_signal(p, &sig);
        char sl[200];
        if (sig.rate_file > 0) {
            char extra[96] = "";
            if (sig.resampled || sig.requantized)
                /* Era uma SETA "→" aqui. Ela não existe na fonte: virava um
                   quadradinho na tela, e o que a linha inteira promete é
                   contar o caminho do sinal sem enfeite. "sai em" diz o
                   mesmo em palavra que a fonte tem. */
                snprintf(extra, sizeof(extra), "  ·  out at %ld Hz / 16 bits",
                         sig.rate_out);
            /* O 2º plano é a mesma família de verdade que esta linha conta:
               não a qualidade prometida, mas o que o caminho de fato faz. E
               só vale com as DUAS coisas — a porta veio no arranque E a taxa
               deixa o SDL2 abrir a saída como BGM. */
            const char *bgm = (u->bgm_port_ok && sig.bgm_port)
                            ? "  ·  background: yes" : "  ·  background: no";
            /* A PALAVRA QUE A PESSOA PROCURA.

               A linha já contava o caminho inteiro — taxa do arquivo, taxa
               de saída, 16 bits — e ainda assim a pergunta que veio foi "is
               it bit perfect??". Ler três números e concluir que nada foi
               alterado é trabalho que a tela pode fazer: quando não há
               reamostragem nem requantização, o que sai do decodificador
               chega ao conversor sem passar por nada, e é isso que a palavra
               diz. Quando HÁ, o "out at ..." já está ali dizendo o contrário
               — e aí a palavra não aparece, porque seria mentira. */
            const char *fiel = (!sig.resampled && !sig.requantized)
                             ? "  ·  bit-perfect" : "";
            snprintf(sl, sizeof(sl), "%s  ·  %ld Hz / %d bits%s%s%s",
                     sig.kind, sig.rate_file, sig.bits_file, extra, fiel, bgm);
            /* Faixa da rede: o indicador fica junto do caminho do sinal porque
               é ali que se lê de onde o som vem. "network" diz o essencial — que
               o Wi-Fi é necessário — sem ocupar uma linha só para isso. */
            if (t && t->remote_id[0]) {
                size_t len = strlen(sl);
                snprintf(sl + len, sizeof(sl) - len, "  ·  network");
            }
        } else {
            /* sem medida, travessão: acusação tirada da ausência de dado é
               a doença que a tela SINAL do desktop pegou */
            snprintf(sl, sizeof(sl), "%s  ·  —", sig.kind);
        }
        /* A PÍLULA DA TROCA, à DIREITA da linha do sinal — e a linha cede a
           largura dela, senão as duas se encostam num nome comprido. Só para
           faixa do CARTÃO: numa da rede não há o que trocar, ela já é isso. */
        float linha_w = tw;
        u->casa_w = 0.0f;
        if (t && !t->remote_id[0] && u->qb_cfg.configured) {
            const char *rot = casa_rotulo(u, sig.kind);
            float px, pw, ph;
            casa_pilula(u, rot, tx + tw, g.sig_y, &px, &pw, &ph);
            float py = g.sig_y - 14.0f;
            unsigned borda = u->casando ? AMBER_A(90) : COL_AMBER;
            vita2d_draw_rectangle(px, py, pw, ph, AMBER_A(u->casando ? 14 : 26));
            vita2d_draw_rectangle(px, py, pw, 1, borda);
            vita2d_draw_rectangle(px, py + ph - 1, pw, 1, borda);
            vita2d_draw_rectangle(px, py, 1, ph, borda);
            vita2d_draw_rectangle(px + pw - 1, py, 1, ph, borda);
            text(u, (int)(px + 10), (int)(py + 14), borda, T_MIUDO, rot);
            u->casa_x = px; u->casa_y = py; u->casa_w = pw; u->casa_h = ph;
            linha_w = tw - pw - 12.0f;
            if (linha_w < 60.0f) linha_w = 60.0f;
        }
        text_elided(u, (int)tx, (int)g.sig_y,
                    (sig.resampled || sig.requantized) ? COL_TEXT_DIM : COL_AMBER,
                    T_MIUDO, linha_w, sl);

        /* O COLCHÃO, desenhado.

           Tocando pela rede, o que decide se vai haver estalo não é a taxa
           nem o formato: é quantos segundos já chegaram à frente da agulha.
           Esse número existia (o dec_colchao), e não aparecia em lugar
           nenhum — a tela só sabia dizer que a rede tinha caído, depois de
           já ter caído. Uma barrinha que encolhe avisa ANTES.

           Ela some quando a faixa é do cartão: ali não há colchão nenhum a
           mostrar, e uma barra sempre cheia só ensinaria a ignorá-la. */
        if (sig.remoto && sig.colchao_max > 0) {
            float bw = tw * 0.42f, bh = 3.0f;
            float by = g.sig_y + 9.0f;
            float f = (float)sig.colchao / (float)sig.colchao_max;
            if (f < 0.0f) f = 0.0f;
            if (f > 1.0f) f = 1.0f;
            vita2d_draw_rectangle(tx, by, bw, bh, AMBER_A(30));
            /* âmbar enquanto dá, alarme quando o colchão fica curto: abaixo
               de um oitavo do anel são poucos segundos de folga */
            unsigned cor = (f < 0.125f) ? COL_ALARM : COL_AMBER;
            vita2d_draw_rectangle(tx, by, bw * f, bh, cor);
        }
    }

    /* O QUE A TROCA ENCONTROU — ou não encontrou.

       Um botão que sai procurando na rede e volta calado é indistinguível de
       um botão quebrado. Quando dá certo isto diz QUAL gravação entrou (o
       título e o artista batem em toda versão da mesma música; o que muda é a
       gravação, e é ela que a pessoa precisa ver para saber se foi a que ela
       queria). Quando não dá, diz o que chegou perto. */
    if (u->casa_msg[0] && u->clock < u->casa_msg_ate) {
        text_elided(u, (int)tx, (int)(g.sig_y + 22.0f), COL_TEXT_DIM,
                    T_MIUDO, tw, u->casa_msg);
    } else if (u->casa_msg[0]) {
        u->casa_msg[0] = '\0';
    }

    /* a ORDEM DO LADO: onde não há letra, é para a contracapa que se olha */
    /* durante a cerimônia a tela DIZ o que está acontecendo: sem isso é uma
       animação bonita que ninguém entende */
    if (u->rit != RIT_OFF) {
        const char *frase = u->rit == RIT_SPINUP ? "the platter comes up to speed"
                          : u->rit == RIT_CUE    ? "the needle finds the groove"
                                                 : "encostou";
        text(u, (int)tx, (int)g.note_y, COL_AMBER, T_CORPO, frase);
    } else if (lado >= 0 && dur > 0) {
        /* "vira em X min": quanto falta para o FIM DO LADO, não da faixa. É a
           única coisa que este sistema diz e nenhum outro tocador diz. */
        const Side *sd = &a->lados.sides[lado];
        int falta = 0;
        for (int i = player_track_idx(p) + 1; i <= sd->last && i < a->ntracks; i++)
            if (a->tracks[i].seconds > 0) falta += a->tracks[i].seconds;
        falta += (dur - pos);
        char aviso[160];
        if (falta <= 20 && lado + 1 < a->lados.n) {
            /* o lado ACABOU: o gesto que o objeto pede — virar o disco não é
               o mesmo que trocar de disco, e num duplo isso importa */
            sides_gesture(&a->lados, lado + 1, aviso, sizeof(aviso));
            text_elided(u, (int)tx, (int)g.note_y, COL_ALARM, T_DESTAQUE, tw, aviso);
        } else if (falta > 20) {
            snprintf(aviso, sizeof(aviso), "%s in %d min",
                     (lado + 1 < a->lados.n) ? "flip" : "ends",
                     (falta + 59) / 60);
            text(u, (int)tx, (int)g.note_y, COL_TEXT_DIM, T_META, aviso);
        }
    }

    /* ═══ O QUADRO MÉDIO VOLTA AQUI ═══════════════════════════════════
     *
     * Acima já saíram backdrop, halo, disco cheio (em modo leve), agulha,
     * rótulo e a coluna de identidade — umas ~600 chamadas. O que falta
     * (letra, lista de faixas com as centenas de glifos, rodapé) é o que
     * empurra para 1050, e é isso que estes dois quadros ainda não trazem:
     * a lista de display sobe em rampa 40 -> ~600 -> 1050 em vez de
     * 40 -> 1050 de uma vez, que era o degrau que matava a GPU com as
     * listas da tela anterior ainda no triplo buffer (dumps de 08/09).
     *
     * Sem lista desenhada, sem alvo morto: a entrada lê a geometria que o
     * desenho anotou, e o que não foi anotado não pode pegar. */
    if (medio) {
        u->deck_enxuto--;
        u->deck_nlin = 0;
        u->casa_w = 0.0f;
        fase("deck: medio entry frame");
        u->deck_stage = "medio";
        u->deck_tex = 0;
        u->deck_linhas = 0;
        return;
    }

    /* A LETRA, no tempo. Só é carregada quando a faixa muda — ler o .lrc a
       cada quadro é I/O por quadro, que foi o defeito do celular. */
    if (t) lyrics_load(&u->lrc, t->path,
                       t->owner ? t->owner->artist : NULL,
                       t->owner ? t->owner->album : NULL,
                       t->title, t->seconds);
    bool tem_letra = u->lrc.n > 0;

    if (tem_letra && u->show_lyrics && u->rit == RIT_OFF) {
        int cur_line = lyrics_at(&u->lrc, pos * 1000);
        int rows = g.list_rows;
        int first = cur_line - 1;
        if (first < 0) first = 0;
        for (int r = 0; r < rows && first + r < u->lrc.n; r++) {
            int idx = first + r;
            int y = (int)(g.list_y + r * g.list_step);
            if (y > FOOT_Y - 26) break;
            bool agora = (idx == cur_line);
            /* a linha que está sendo cantada em âmbar, as outras apagadas */
        text_elided(u, (int)tx, y, agora ? COL_AMBER : COL_TEXT_FAINT,
                    agora ? T_META : T_MIUDO, tw, u->lrc.lines[idx].text);
        }
        goto lyrics_done;
    }

    /* A LISTA VIRA ALVO DE DEDO.

       Ela era só desenho. Para chegar à faixa 20 de um show de 35 eram
       dezenove apertos de [direita], cada um abrindo e fechando um arquivo —
       e as faixas estavam ali, escritas na tela, do lado do disco. Uma lista
       que a tela mostra e o dedo não alcança é a mesma família do módulo que
       a barra desenhava e ninguém acionava.

       O desenho anota onde cada linha caiu e a qual faixa ela pertence; o
       toque lê daqui. Um dono só para a geometria, como em toda outra lista
       deste arquivo. */
    int shown = 0;
    int from = player_track_idx(p) - 2;
    if (from < 0) from = 0;
    u->deck_nlin = 0;
    for (int i = from; i < a->ntracks && shown < g.list_rows && u->rit == RIT_OFF;
         i++, shown++) {
        int y = (int)(g.list_y + shown * g.list_step);
        if (y > FOOT_Y - 26) break;
        if (u->deck_nlin < DECK_LIN_MAX) {
            u->deck_lin_y[u->deck_nlin] = (float)y;
            u->deck_lin_i[u->deck_nlin] = i;
            u->deck_nlin++;
        }
        bool is_now = (t && &a->tracks[i] == t);
        char line[288];
        if (a->tracks[i].number > 0)
            snprintf(line, sizeof(line), "%2d  %.255s", a->tracks[i].number, a->tracks[i].title);
        else
            snprintf(line, sizeof(line), "    %.255s", a->tracks[i].title);
        unsigned int col = is_now ? COL_AMBER
                         : (!a->tracks[i].decodable ? COL_TEXT_FAINT : COL_TEXT_DIM);
        text_elided(u, (int)tx, y, col, T_META, tw - 54, line);
        if (a->tracks[i].seconds > 0) {
            char d[16];
            fmt_time(d, sizeof(d), a->tracks[i].seconds);
            text(u, (int)(SCRW - PAD_X - 42), y, COL_TEXT_FAINT, T_MIUDO, d);
        }
    }

lyrics_done:;
    const char *rep = "rep all";
    switch (player_repeat(p)) {
    case REPEAT_OFF: rep = "rep off"; break;
    case REPEAT_ONE: rep = "rep 1";   break;
    default: break;
    }
    /* ESTADO, e não teclado.

       Esta linha dizia "[O] pause · rep all · shuffle on": duas coisas
       diferentes com a mesma cara. "[O] pause" é uma INSTRUÇÃO — aprende-se
       uma vez e foi para a tela de Controls; "rep all" e "shuffle on" são
       ESTADO — mudam sozinhos e precisam estar visíveis enquanto se ouve.
       Ficou só o estado, escrito por extenso: numa tela que não é mais um
       teclado, "rep 1" pode voltar a ser "repeating this track". */
    const char *rep_txt = "repeat off";
    switch (player_repeat(p)) {
    case REPEAT_ONE: rep_txt = "repeating this track"; break;
    case REPEAT_OFF: rep_txt = "repeat off";           break;
    default:         rep_txt = "repeating the record"; break;
    }
    char ctl[240];
    snprintf(ctl, sizeof(ctl), "%s%s%s",
             rep_txt,
             player_shuffle(p) ? "   ·   shuffled" : "",
             (tem_letra && u->show_lyrics) ? "   ·   lyrics" : "");
    (void)rep;
    /* DUAS linhas, e não uma disputada.

       A soneca e o último erro escreviam ambos em FOOT_Y-20 e se apagavam:
       com a soneca armada, um erro de leitura simplesmente não aparecia — e
       o erro é justamente o que a pessoa precisa ver. Agora o erro fica na
       linha de cima (é o mais urgente e some sozinho quando a próxima faixa
       abre) e a soneca logo abaixo dele. */
    const char *err = player_last_error(p);
    float linha = (float)FOOT_Y - 20.0f;
    if (err && err[0]) {
        text_elided(u, (int)PAD_X, (int)linha - 18, COL_ALARM, T_META,
                    SCRW - 2 * PAD_X, err);
    }
    /* a soneca tem que APARECER quando está armada: um estado que muda o que
       o aparelho vai fazer e não se vê é o pior tipo de estado */
    {
        int sm = player_sleep_mode(p);
        if (sm == 1)
            text(u, (int)PAD_X, (int)linha, COL_ALARM, T_META,
                 "sleep: fading out   ·   [R1+sq] off");
        else if (sm == 2)
            text(u, (int)PAD_X, (int)linha, COL_ALARM, T_META,
                 "sleep: stops at end of side   ·   [R1+sq] off");
    }
    text_elided(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, T_META, SCRW - 2 * PAD_X, ctl);
    u->deck_stage = "full";
    u->deck_linhas = u->deck_nlin;
}

/* ---------- lista com miniatura (recs e playlists) ---------- */


/* A miniatura das LISTAS (recomendados, playlists).

   Tinha o mesmo defeito da estante, e sobreviveu ao conserto de lá: com arte
   virava um quadrado, sem arte virava um disco. Numa lista isso é ainda pior
   que na grade, porque as linhas ficam empilhadas e a coluna da esquerda
   vira um zigue-zague de formas.

   Aqui é sempre uma CAPA. Sem o disco atrás, ao contrário da estante: a uns
   28 px de lado, o crescente do disco vira três pixels de ruído e não
   comunica nada — a mesma decisão de desenho dá resultados opostos nas duas
   escalas, e insistir na simetria custaria a legibilidade. */
static void row_thumb(Ui *u, Album *a, float x, float y, float side)
{
    vita2d_texture *tex = a ? cover_tex(u, a) : NULL;
    if (tex) {
        draw_cover_fit(tex, x, y, side);
    } else {
        vita2d_draw_rectangle(x, y, side, side, RGBA8(16, 22, 33, 255));
        vita2d_draw_rectangle(x, y, side, 1, AMBER_A(70));
        alpha_ring(x + side * 0.5f, y + side * 0.5f, side * 0.30f, 1.0f, 0.20f, COL_AMBER);
        alpha_fill(x + side * 0.5f, y + side * 0.5f, side * 0.07f, 0.55f, COL_AMBER);
        char ini[5];
        if (a && album_inicial(a, ini, sizeof(ini))) {
            float sc = side / 42.0f;
            int lw = text_w(u, sc, ini);
            text(u, (int)(x + side * 0.5f - lw / 2.0f),
                 (int)(y + side * 0.66f), COL_AMBER, sc, ini);
        }
    }
    vita2d_draw_rectangle(x, y, 1, side, AMBERB_A(40));
    vita2d_draw_rectangle(x, y + side - 1, side, 1, RGBA8(0, 0, 0, 130));
}

static void draw_recs(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    {
        header(u, "");
    }

    if (!u->recs || u->nrecs <= 0) {
        text(u, (int)PAD_X, 130, COL_TEXT, T_SECAO, "nothing to suggest yet");
        text(u, (int)PAD_X, 162, COL_TEXT_DIM, T_CORPO,
             "suggestions come from what you played to the END — put a record on and come back");
        return;
    }
    UiListGeom lg;
    ui_list_geom(SCRW, SCRH, &lg);
    if (u->rec_sel >= u->nrecs) u->rec_sel = u->nrecs - 1;
    if (u->rec_sel < 0) u->rec_sel = 0;
    int scroll = (u->rec_sel / lg.rows) * lg.rows;

    /* A LISTA PARA DE ATRAVESSAR A TELA INTEIRA.

       Ela era uma coluna de 900 px num aparelho 16:9: o texto acabava perto do
       meio e a metade direita ficava preta em todas as dez linhas. Uma lista
       de sugestões diz o QUE tocar; o que ela não dizia era o que a coisa
       PARECE — e a capa é o que se reconhece de relance, que é o argumento
       inteiro da estante nova.

       Então a lista fica com 520 px e o disco marcado ocupa o resto, grande.
       Custa ZERO textura a mais: é a mesma capa que a linha já desenha em
       miniatura, e o cache guarda por álbum, não por tamanho. */
    const float LARG_LISTA = 520.0f;

    for (int r = 0; r < lg.rows; r++) {
        int idx = scroll + r;
        if (idx >= u->nrecs) break;
        const Track *t = u->recs[idx];
        if (!t) continue;
        float y = lg.y0 + r * lg.row_h;
        if (y + lg.row_h > FOOT_Y - 12) break;
        bool is_sel = (idx == u->rec_sel);
        if (is_sel) vita2d_draw_rectangle(PAD_X, y, LARG_LISTA, lg.row_h - 4, TINT_SEL_ROW);

        Album *a = t->owner;
        row_thumb(u, a, PAD_X + 4, y + 4, lg.row_h - 12.0f);

        float tx = PAD_X + lg.row_h + 6.0f;
        float tw = PAD_X + LARG_LISTA - tx - 10.0f;
        text_elided(u, (int)tx, (int)(y + 21), is_sel ? COL_AMBER : COL_TEXT, T_CORPO, tw, t->title);
        /* "Radiohead · 1993-02-11 - Radiohead - Signal Radio Session" gastava
           metade da linha dizendo Radiohead duas vezes. O rótulo já vem sem a
           data e sem o artista repetido — ver album_display no library.c. */
        char sub[600], rot[MAX_NAME_LEN], subx[MAX_NAME_LEN];
        rot[0] = subx[0] = '\0';
        if (a) album_display(a, rot, sizeof(rot), subx, sizeof(subx));
        snprintf(sub, sizeof(sub), "%.255s%s%.255s",
                 subx,
                 subx[0] && rot[0] ? "  ·  " : "",
                 rot);
        text_elided(u, (int)tx, (int)(y + 40), COL_TEXT_DIM, T_META, tw, sub);
    }
    /* O PAINEL DA DIREITA: o disco marcado, do tamanho que dá para olhar. */
    {
        const Track *t = (u->rec_sel >= 0 && u->rec_sel < u->nrecs)
                         ? u->recs[u->rec_sel] : NULL;
        Album *a = t ? t->owner : NULL;
        const float px = PAD_X + LARG_LISTA + 28.0f;
        const float pw = SCRW - PAD_X - px;
        float lado = pw < 236.0f ? pw : 236.0f;
        float cy = lg.y0 + 6.0f;

        /* O MESMO `row_thumb` da miniatura da linha: ele já sabe desenhar a
           capa quando existe e a marca com a inicial quando não. Uma segunda
           função para "a mesma coisa, maior" seria a família de defeito que
           este arquivo já pagou duas vezes — duas funções respondendo à mesma
           pergunta derivam, e a que ninguém olhou deriva para o lado errado. */
        if (a) row_thumb(u, a, px, cy, lado);
        float ty = cy + lado + 26.0f;
        if (t) {
            text_2linhas(u, (int)px, (int)ty, (int)(ty + 22.0f),
                         COL_AMBER, T_DESTAQUE, pw, t->title);
            char rot[MAX_NAME_LEN], subx[MAX_NAME_LEN];
            rot[0] = subx[0] = '\0';
            if (a) album_display(a, rot, sizeof(rot), subx, sizeof(subx));
            text_elided(u, (int)px, (int)(ty + 52.0f), COL_TEXT, T_CORPO, pw,
                        subx[0] ? subx : (a ? a->artist : ""));
            text_elided(u, (int)px, (int)(ty + 74.0f), COL_TEXT_DIM, T_META, pw, rot);
            if (t->seconds > 0) {
                char d[32];
                snprintf(d, sizeof(d), "%d:%02d", t->seconds / 60, t->seconds % 60);
                text(u, (int)px, (int)(ty + 96.0f), COL_TEXT_FAINT, T_META, d);
            }
        }
    }

    char cnt[64];
    snprintf(cnt, sizeof(cnt), "%d track%s   ·   %d of %d",
             u->nrecs, u->nrecs == 1 ? "" : "s", u->rec_sel + 1, u->nrecs);
    rodape_agora(u, p, cnt);
}

/* Quantas escutas esperam para subir. Recontada no máximo uma vez por
   segundo — ver o campo `fila_lastfm`. Antes disto a tela de conta abria e
   contava o arquivo A CADA QUADRO, sessenta vezes por segundo, para um
   número que só muda quando uma faixa termina. */
/* A configuração do last.fm, lida UMA vez. Ela era carregada só quando a
   tela de conta abria; a estante, que agora também precisa saber se há conta,
   veria `configured` falso mesmo com a conta pronta — e mostraria um aviso
   mentindo para quem já tinha configurado tudo. */
static const LastfmConfig *ui_conta_cfg(Ui *u)
{
    if (!u->conta_lida) {
        lastfm_config_load(&u->conta_cfg, STYLUS_DATA_DIR);
        u->conta_lida = true;
    }
    return &u->conta_cfg;
}

static int ui_fila_lastfm(Ui *u)
{
    if (!u) return 0;
    if (u->fila_quando == 0 || u->clock - u->fila_quando >= 60) {
        u->fila_lastfm = lastfm_queue_size(STYLUS_DATA_DIR);
        u->fila_quando = u->clock;
    }
    return u->fila_lastfm;
}

/* ---------- a conta ----------

   Por que esta tela existe: o last.fm estava implementado inteiro e era
   INALCANÇÁVEL. A fila enchia no cartão e nunca subia, porque configurar a
   conta pedia editar um arquivo de texto num PC — num app que roda num
   aparelho de mão, com teclado de sistema disponível, isso é o mesmo que o
   recurso não existir.

   As chaves de API são da PESSOA, não deste app: o last.fm dá uma de graça
   em last.fm/api/account/create, e uma chave embutida no VPK seria de todos
   os usuários ao mesmo tempo, com a mesma cota. São duas colagens, uma vez
   na vida. A senha é digitada, usada na hora e esquecida — o que fica no
   cartão é a chave de sessão, revogável no site. */

enum { CC_KEY = 0, CC_SECRET, CC_USER, CC_ENTRAR, CC_SAIR, CC_N };

/* A GEOMETRIA DAS LINHAS, num lugar só.

   O desenho precisa dela para pintar, e o toque precisa dela para acertar o
   alvo. Escritas duas vezes, elas se separam na primeira vez que alguém
   mexer no espaçamento — e o sintoma é o pior tipo: a tela fica certa e o
   dedo passa a marcar a linha de cima. */
static void conta_linha(int i, float *x, float *y, float *w, float *h)
{
    const float rh = 38.0f;
    if (x) *x = PAD_X;
    if (w) *w = SCRW - PAD_X - 250.0f;
    if (y) *y = 176.0f + (float)i * rh - 2.0f;
    if (h) *h = rh - 4.0f;
}

static void qobuz_linha(int i, float *x, float *y, float *w, float *h)
{
    const float rh = 44.0f;
    if (x) *x = PAD_X;
    if (w) *w = SCRW - 2 * PAD_X;
    if (y) *y = 186.0f + (float)i * rh - 4.0f;
    if (h) *h = rh - 8.0f;
}

/* As duas pílulas do painel de playlist. UM dono da geometria: o desenho
   pinta daqui e o dedo mira daqui — escritas duas vezes elas se separam no
   primeiro ajuste de espaçamento, e o sintoma é o dedo acertar o botão
   errado com a tela parecendo certa. */
static void pl_pilula(int i, float painel_x, float y0,
                      float *x, float *y, float *w, float *h)
{
    const float larg = 92.0f, alt = 26.0f, vao = 10.0f;
    if (x) *x = painel_x + (float)i * (larg + vao);
    if (y) *y = y0 + 30.0f;
    if (w) *w = larg;
    if (h) *h = alt;
}

static void ajuste_linha(int i, float *x, float *y, float *w, float *h)
{
    const float rh = 52.0f;
    if (x) *x = PAD_X;
    if (w) *w = SCRW - 2 * PAD_X;
    if (y) *y = 176.0f + (float)i * rh - 4.0f;
    if (h) *h = rh - 8.0f;
}

/* Mostra o começo e o fim e come o meio: dá para conferir que a colagem foi
   a certa sem estampar a credencial inteira na tela de quem estiver ao lado. */
static void mascara(const char *v, char *out, size_t cap)
{
    size_t n = v ? strlen(v) : 0;
    if (n == 0) { snprintf(out, cap, "(empty)"); return; }
    if (n <= 10) { snprintf(out, cap, "%.*s...", (int)(n / 2), v); return; }
    snprintf(out, cap, "%.4s…%.4s  (%d)", v, v + n - 4, (int)n);
}

static void conta_diz(Ui *u, const char *msg)
{
    snprintf(u->conta_msg, sizeof(u->conta_msg), "%s", msg);
    u->conta_msg_ate = u->clock + 60 * 8;      /* uns oito segundos */
}

static void draw_conta(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    ui_conta_cfg(u);
    header(u, "");
    {
        header(u, "");
    }

    const LastfmConfig *c = &u->conta_cfg;
    int fila = ui_fila_lastfm(u);
    bool ok = c->configured;

    /* O MOSTRADOR, à direita: um disco com o número de escutas guardadas.

       Existe porque a pergunta que traz alguém a esta tela não é "quais são
       meus campos" — é "as minhas escutas estão indo?". Um número grande
       responde isso de longe; uma lista de campos não responde nunca. E o
       anel aceso ao redor dele diz a outra metade: se há conta ligada, elas
       sobem sozinhas; se não há, ficam esperando (e não se perdem). */
    {
        float dcx = SCRW - 132.0f, dcy = 268.0f, dr = 84.0f;
        alpha_fill(dcx, dcy, dr, 1.0f, RGBA8(9, 12, 18, 255));
        alpha_ring(dcx, dcy, dr * 0.80f, 1.0f, 0.19f, COL_AMBER);
        alpha_ring(dcx, dcy, dr * 0.64f, 1.0f, 0.16f, COL_AMBER);
        alpha_ring(dcx, dcy, dr, 2.0f, ok ? 0.75f : 0.28f,
                   ok ? COL_AMBER : COL_COLD);
        alpha_fill(dcx, dcy, dr * 0.42f, 0.22f, COL_AMBER);

        char num[16];
        snprintf(num, sizeof(num), "%d", fila);
        float sc = fila > 999 ? 1.10f : 1.55f;
        int nw = text_w(u, sc, num);
        text(u, (int)(dcx - nw / 2.0f), (int)(dcy + 8), COL_AMBER_BRIGHT, sc, num);
        const char *leg = fila == 1 ? "play" : "plays";
        int lw = text_w(u, T_MIUDO, leg);
        text(u, (int)(dcx - lw / 2.0f), (int)(dcy + 32), COL_TEXT_DIM, T_MIUDO, leg);

        const char *dest = ok ? "upload on their own" : "waiting for an account";
        int dw = text_w(u, T_META, dest);
        text(u, (int)(dcx - dw / 2.0f), (int)(dcy + dr + 26),
             ok ? COL_AMBER : COL_TEXT_DIM, T_META, dest);
    }

    /* A seção, e o estado em uma frase. */
    text(u, (int)PAD_X, 116, COL_TEXT_FAINT, T_META, "LAST.FM");
    char est[160];
    if (ok)
        snprintf(est, sizeof(est), "signed in as %s", c->username);
    else if (!c->api_key[0] && !c->username[0])
        snprintf(est, sizeof(est), "enter your username and sign in");
    else if (!c->username[0])
        snprintf(est, sizeof(est), "enter your last.fm username");
    else
        snprintf(est, sizeof(est), "keys ready — still need to sign in");
    text_elided(u, (int)PAD_X, 140, ok ? COL_AMBER : COL_TEXT, T_DESTAQUE,
                SCRW - PAD_X - 250, est);

    static const char *ROT[CC_N] = {
        "API key", "API secret", "username", "sign in", "sign out"
    };
    float x0, w, rh = 38.0f, y0 = 176.0f;
    conta_linha(0, &x0, NULL, &w, NULL);
    /* o painel: dá aos campos a mesma leitura de objeto que o resto do app tem */
    vita2d_draw_rectangle(x0, y0 - 8, w, CC_N * rh + 12, COL_CARD);
    vita2d_draw_rectangle(x0, y0 - 8, w, 1, AMBER_A(40));

    for (int i = 0; i < CC_N; i++) {
        float y = y0 + i * rh, ly, lh;
        conta_linha(i, NULL, &ly, NULL, &lh);
        bool sel = (i == u->conta_sel);
        if (sel) {
            vita2d_draw_rectangle(x0, ly, w, lh, TINT_SEL_ROW);
            vita2d_draw_rectangle(x0, ly, 2, lh, COL_AMBER);
        }
        text(u, (int)x0 + 12, (int)(y + 16), sel ? COL_AMBER : COL_TEXT, T_CORPO, ROT[i]);

        char val[128];
        unsigned cor = COL_TEXT_DIM;
        if (i == CC_KEY)         mascara(c->api_key, val, sizeof(val));
        else if (i == CC_SECRET) mascara(c->api_secret, val, sizeof(val));
        else if (i == CC_USER)   snprintf(val, sizeof(val), "%s",
                                          c->username[0] ? c->username : "(empty)");
        else if (i == CC_ENTRAR) {
            snprintf(val, sizeof(val), "%s", ok ? "already signed in" : "enter password and sign in");
            cor = ok ? COL_TEXT_FAINT : COL_AMBER_BRIGHT;
        } else {
            snprintf(val, sizeof(val), "%s",
                     ok ? "forget the key on this device" : "—");
            cor = ok ? COL_ALARM : COL_TEXT_FAINT;
        }
        float vx = x0 + w * 0.46f;
        text_elided(u, (int)vx, (int)(y + 16), cor, T_META, w - (vx - x0) - 12, val);
    }

    if (u->conta_msg[0] && u->clock < u->conta_msg_ate)
        text(u, (int)PAD_X, FOOT_Y, COL_AMBER, T_CORPO, u->conta_msg);
    else
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_FAINT, T_META,
             "API key is optional — enter username and sign in to start scrobbling");
}

/* ---------- a loja ----------

   O Qobuz existia como FERRAMENTA DE PC: buscava, baixava, e a pessoa
   copiava para o cartão. Funcionava, e ainda assim era o contrário do que
   este app quer ser — quem está com o Vita na mão não deveria ter de
   levantar e ligar um computador para pôr um disco novo.

   A tela tem duas caras, e qual delas aparece não é uma opção: enquanto
   faltar credencial só existe o preenchimento, porque buscar sem conta não
   leva a lugar nenhum. Assim que houver, a tela vira a busca e o
   preenchimento sai da frente — ninguém quer olhar para uma chave de API
   depois de ter posto uma. */

/* QC_N faz DOIS papéis: é o número de campos da config E a marca do "termo da
   busca" que volta do teclado. QC_SC é o termo da OUTRA fonte — sem um valor
   próprio, o texto digitado para o SoundCloud iria para a busca do Qobuz. */
enum { QC_APPID = 0, QC_SECRET, QC_EMAIL, QC_ENTRAR, QC_N, QC_SC };

/* A LINHA DA LISTA DO SOUNDCLOUD, num lugar só.

   O desenho e o TOQUE têm de concordar sobre onde cada linha está. Nesta tela
   isso já foi escrito duas vezes uma vez (a frase do "nothing found" e as
   pílulas de busca recente colidiram porque cada uma sabia da sua altura), e
   a correção foi exatamente esta: uma função, dois usuários. */
#define SC_LINHA_Y0  166.0f
#define SC_LINHA_H   46.0f
static bool sc_linha(int i, float *y, float *h)
{
    if (i < 0 || i >= SC_MAX_RES) return false;
    float yy = SC_LINHA_Y0 + (float)i * SC_LINHA_H;
    if (yy + SC_LINHA_H >= FOOT_Y - 10.0f) return false;
    if (y) *y = yy;
    if (h) *h = SC_LINHA_H;
    return true;
}

/* O TECLADO QUE NÃO ABRE PRECISA DIZER ISSO.

   Todos os `ime_abrir` daqui eram `if (... == 0) guarda o campo;` sem else:
   quando o diálogo recusava, a tecla não fazia NADA e a tela não mudava. Foi
   assim que "a busca do Qobuz não funciona" passou por rede, API e parser
   antes de alguém olhar para o teclado. */
static void ime_falhou(char *dest, size_t cap)
{
    int e = ime_erro();
    if (e == (int)0x80020407)
        snprintf(dest, cap, "%s", "the keyboard is not configured");
    else
        snprintf(dest, cap, "the keyboard would not open (0x%08X)", (unsigned)e);
}

static void qb_diz(Ui *u, const char *msg)
{
    snprintf(u->qb_msg, sizeof(u->qb_msg), "%s", msg);
    u->qb_msg_ate = u->clock + 60 * 8;
}

static const char *qb_nome_formato(int f)
{
    if (f == QB_FLAC)  return "FLAC 16/44.1";
    if (f == QB_HIRES) return "FLAC 24-bit";
    return "MP3 320";
}

/* ═══ AS BUSCAS RECENTES ══════════════════════════════════════════════

   Do SpotiFLAC (docs/referencias-visuais.md): "Recent Searches: (taylor
   swift) (golden)" — pílulas que se toca para repetir. Aqui isso vale mais
   que num PC, e o motivo é o teclado: digitar "polaroid yung lixo" no
   teclado do Vita, num aparelho na mão, é meia dúzia de segundos de mira.
   Repetir uma busca de ontem virava digitá-la de novo, inteira.

   O `rede.txt` do cartão do dono mostra as dele: radiohead, yung lixo,
   polaroid, polaroid yung lixo, in rainbows. Cinco termos, e nenhum deles
   sobrevivia a fechar o app.

   Seis, em arquivo, mais novo na frente. Seis porque é o que cabe numa
   linha da tela — uma lista que rola seria uma segunda tela de navegação
   para resolver um problema de digitação. */
#define QB_RECENTES 6
#define QB_TERMO_MAX 64

typedef struct { char t[QB_TERMO_MAX]; } QbTermo;
static QbTermo g_qb_rec[QB_RECENTES];
static int     g_qb_nrec;
static bool    g_qb_rec_lidas;

static void qb_recentes_carrega(void)
{
    if (g_qb_rec_lidas) return;
    g_qb_rec_lidas = true;
    FILE *f = fopen(STYLUS_DATA_DIR "/buscas.txt", "r");
    if (!f) return;
    char linha[QB_TERMO_MAX + 8];
    while (g_qb_nrec < QB_RECENTES && fgets(linha, sizeof(linha), f)) {
        linha[strcspn(linha, "\r\n")] = '\0';
        if (!linha[0]) continue;
        snprintf(g_qb_rec[g_qb_nrec].t, QB_TERMO_MAX, "%s", linha);
        g_qb_nrec++;
    }
    fclose(f);
}

static void qb_recentes_grava(void)
{
    FILE *f = fopen(STYLUS_DATA_DIR "/buscas.txt", "w");
    if (!f) return;
    for (int i = 0; i < g_qb_nrec; i++) fprintf(f, "%s\n", g_qb_rec[i].t);
    fclose(f);
}

/* Põe na frente, sem repetir. Um termo buscado de novo SOBE em vez de virar
   uma segunda pílula igual — repetir é o sinal de que ele importa. */
static void qb_recentes_poe(const char *termo)
{
    if (!termo || !termo[0]) return;
    qb_recentes_carrega();
    int achou = -1;
    for (int i = 0; i < g_qb_nrec; i++)
        if (!strcasecmp(g_qb_rec[i].t, termo)) { achou = i; break; }
    if (achou < 0) {
        if (g_qb_nrec < QB_RECENTES) g_qb_nrec++;
        achou = g_qb_nrec - 1;
    }
    for (int i = achou; i > 0; i--) g_qb_rec[i] = g_qb_rec[i - 1];
    snprintf(g_qb_rec[0].t, QB_TERMO_MAX, "%.*s", QB_TERMO_MAX - 1, termo);
    qb_recentes_grava();
}

/* A lista de artistas mora na tela ARTISTS, mais abaixo neste arquivo. A loja
   a empresta para sugerir buscas — ver `qb_art_pilula`. */
static void artistas_remonta(Library *lib);
static int         artista_quantos(void);
static const char *artista_nome(int i);

/* AS SUGESTÕES DA LOJA: os artistas que a pessoa JÁ TEM no cartão.

   A tela da loja, sem busca feita, era uma linha de texto e sessenta por
   cento de preto. E a pergunta que ela faz — "o que você quer procurar?" —
   tem uma resposta óbvia parada na memória do app: os 109 artistas da
   estante. Quem abre a loja de um tocador de música quer mais do que já
   gosta, e adivinhar isso não custa uma requisição de rede: custa ler uma
   lista que a tela ARTISTS já monta.

   Três colunas e não quatro: "Vitamin String Quartet" não cabe em 217 px, e
   um nome cortado não é um botão — é um enigma.

   Um dono só para a geometria, como nas pílulas acima: o desenho e o dedo
   leem as duas coisas daqui, que é o que impede a colisão que já nasceu
   nesta tela duas vezes. */
#define QB_ART_COLS 3
#define QB_ART_LINS 4
#define QB_ART_MAX  (QB_ART_COLS * QB_ART_LINS)

/* OS DOZE ARTISTAS COM MAIS DISCO NO CARTÃO, e não os doze primeiros.

   A ordem da tela ARTISTS é a da estante, que aqui saía "Radiohead, despaiR,
   subjectobjectnoun, Alec Benjamin…" — três nomes que parecem sorteados
   seguidos do começo do alfabeto. Uma sugestão em ordem de estante não é uma
   sugestão: é uma amostra.

   Quantos discos alguém tem de um artista é a única medida de gosto que este
   app tem sem depender do histórico (que começa vazio). Doze nomes, seleção
   direta — com 109 artistas não vale ordenar a lista inteira para mostrar
   doze. */
static const char *g_qb_art[QB_ART_MAX];
static int         g_qb_nart;
static int         g_qb_art_para = -1;

static void qb_sugestoes_remonta(Library *lib)
{
    if (!lib) { g_qb_nart = 0; return; }
    if (g_qb_art_para == lib->nalbums) return;
    g_qb_art_para = lib->nalbums;
    g_qb_nart = 0;

    artistas_remonta(lib);
    int n = artista_quantos();
    int melhor_q[QB_ART_MAX] = {0};

    for (int i = 0; i < n; i++) {
        const char *nome = artista_nome(i);
        if (!nome || !nome[0]) continue;
        int q = 0;
        for (int a = 0; a < lib->nalbums; a++)
            if (!strcasecmp(lib->albums[a].artist, nome)) q++;
        /* insere na posição certa e empurra o resto — doze slots, então a
           inserção direta é mais barata (e mais curta) que ordenar 109 */
        for (int k = 0; k < QB_ART_MAX; k++) {
            if (q <= melhor_q[k]) continue;
            for (int j = QB_ART_MAX - 1; j > k; j--) {
                melhor_q[j] = melhor_q[j - 1];
                g_qb_art[j] = g_qb_art[j - 1];
            }
            melhor_q[k] = q;
            g_qb_art[k] = nome;
            if (g_qb_nart < QB_ART_MAX) g_qb_nart++;
            break;
        }
    }
}

static bool qb_art_pilula(int i, float *x, float *y, float *w, float *h)
{
    if (i < 0 || i >= QB_ART_MAX) return false;
    const float larg = (SCRW - 2 * PAD_X - (QB_ART_COLS - 1) * 10.0f) / QB_ART_COLS;
    const float alt = 34.0f;
    if (x) *x = PAD_X + (i % QB_ART_COLS) * (larg + 10.0f);
    if (y) *y = 258.0f + (i / QB_ART_COLS) * (alt + 8.0f);
    if (w) *w = larg;
    if (h) *h = alt;
    return true;
}

/* A GEOMETRIA das pílulas — um dono só, desenho e dedo saem daqui. */
static bool qb_rec_pilula(Ui *u, int i, float *x, float *y, float *w, float *h)
{
    if (i < 0 || i >= g_qb_nrec) return false;
    float px = PAD_X;
    for (int k = 0; k < i; k++)
        px += (float)text_w(u, T_META, g_qb_rec[k].t) + 26.0f + 8.0f;
    float pw = (float)text_w(u, T_META, g_qb_rec[i].t) + 26.0f;
    if (px + pw > (float)SCRW - PAD_X) return false;   /* não coube: some */
    if (x) *x = px;
    if (y) *y = 184.0f;
    if (w) *w = pw;
    if (h) *h = 26.0f;
    return true;
}

/* ═══ A MESMA ABA, A OUTRA FONTE ══════════════════════════════════════════
 *
 * O SoundCloud devolve FAIXAS SOLTAS, não discos: não há capa para pedir, não
 * há formato para escolher e não há o que baixar — aperta-se e toca. Por isso
 * ele tem corpo próprio em vez de mais três ramos dentro do desenho da loja,
 * que já carrega config, chaves, formato, capas e download.
 *
 * A escolha da fonte mora nos AJUSTES, e a ramificação acontece ANTES da
 * porteira do `configured` do Qobuz de propósito: quem não tem conta na loja
 * ainda assim pode ouvir daqui, e exigir chaves de um serviço para usar outro
 * é a definição de porta trancada por engano.
 */
static const ScConfig *ui_sc_cfg(Ui *u)
{
    if (u && !u->sc_lida) {
        sc_config_load(&u->sc_cfg, STYLUS_DATA_DIR);
        u->sc_lida = true;
    }
    return u ? &u->sc_cfg : NULL;
}

static void draw_soundcloud(Ui *u)
{
    header(u, "");
    const ScConfig *scc = ui_sc_cfg(u);

    /* SEM CHAVE NÃO HÁ BUSCA, e a tela tem de dizer isso em vez de devolver
       "nothing found" para sempre. O `pro-cartao.sh` escreve o
       `soundcloud.config`; sem ele o app segue igual, só sem esta fonte. */
    if (!scc || !scc->ok) {
        text(u, (int)PAD_X, 150, COL_ALARM, T_SECAO, "SoundCloud is not set up");
        text_elided(u, (int)PAD_X, 184, COL_TEXT, T_CORPO, SCRW - 2 * PAD_X,
                    "there is no soundcloud.config on the card");
        text_elided(u, (int)PAD_X, 212, COL_TEXT_DIM, T_MIUDO, SCRW - 2 * PAD_X,
                    "run tools/pro-cartao.sh on the computer — it writes the key for you");
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_FAINT, T_MIUDO,
             "the source is on the SETTINGS tab");
        return;
    }

    ScTrack tr[SC_MAX_RES];
    int n = 0;
    bool ativo = false;
    sc_busca_estado(tr, SC_MAX_RES, &n, &ativo);

    /* a linha da busca, com a mesma cara da do Qobuz: é a mesma tela */
    vita2d_draw_rectangle(PAD_X, 112, SCRW - 2 * PAD_X, 34, COL_CARD);
    vita2d_draw_rectangle(PAD_X, 112, 2, 34, COL_AMBER);
    vita2d_draw_rectangle(PAD_X, 144, SCRW - 2 * PAD_X, 1, AMBER_A(25));
    text_elided(u, (int)PAD_X + 14, 134,
                u->qb_termo[0] ? COL_TEXT : COL_TEXT_FAINT,
                T_DESTAQUE, SCRW * 0.6f,
                u->qb_termo[0] ? u->qb_termo : "[square] to search SoundCloud");
    {
        const char *marca = "SOUNDCLOUD";
        int w = text_w(u, T_META, marca);
        text(u, (int)(SCRW - PAD_X - 14 - w), 134, COL_AMBER, T_META, marca);
    }

    if (ativo) {
        text(u, (int)PAD_X, 190, COL_TEXT_DIM, T_DESTAQUE, "looking…");
        return;
    }
    if (n < 0) {
        text(u, (int)PAD_X, 190, COL_ALARM, T_DESTAQUE, "the search did not go through");
        const char *pq = sc_motivo();
        text_elided(u, (int)PAD_X, 218, COL_TEXT, T_CORPO, SCRW - 2 * PAD_X,
                    pq && pq[0] ? pq : "no reason reported — is the Wi-Fi on?");
        text(u, (int)PAD_X, 246, COL_TEXT_DIM, T_META,
             "[square] to try again  ·  the source is on the SETTINGS tab");
        return;
    }
    if (n == 0) {
        text(u, (int)PAD_X, 190, COL_TEXT_DIM, T_CORPO,
             u->qb_termo[0] ? "nothing playable found"
                            : "search a track, an artist, a remix");
        text(u, (int)PAD_X, 218, COL_TEXT_FAINT, T_MIUDO,
             "previews and label uploads are left out — they stop after 30 s");
        return;
    }

    if (u->sc_sel >= n) u->sc_sel = n - 1;
    if (u->sc_sel < 0) u->sc_sel = 0;

    for (int i = 0; i < n; i++) {
        float y, rh;
        if (!sc_linha(i, &y, &rh)) break;
        const ScTrack *t = &tr[i];
        bool sel = (i == u->sc_sel);
        if (sel) {
            vita2d_draw_rectangle(PAD_X, y - 2, SCRW - 2 * PAD_X, rh - 6, TINT_SEL_ROW);
            vita2d_draw_rectangle(PAD_X, y - 2, 3, rh - 6, COL_AMBER);
            vita2d_draw_rectangle(PAD_X + 3, y - 2, 6, rh - 6, AMBER_A(20));
        }
        const int TX = (int)(PAD_X + 12.0f);
        const float TW = SCRW - PAD_X - 110 - (PAD_X + 12.0f);
        text_elided(u, TX, (int)(y + 16), sel ? COL_AMBER : COL_TEXT,
                    T_CORPO, TW, t->titulo);
        text_elided(u, TX, (int)(y + 33), COL_TEXT_DIM, T_MIUDO, TW, t->artista);

        char dur[24];
        if (t->segundos > 0)
            snprintf(dur, sizeof(dur), "%d:%02d", t->segundos / 60, t->segundos % 60);
        else
            snprintf(dur, sizeof(dur), "—");
        int w = text_w(u, T_META, dur);
        text(u, (int)(SCRW - PAD_X - 12 - w), (int)(y + 24),
             sel ? COL_AMBER : COL_TEXT_FAINT, T_META, dur);
    }

    if (u->qb_msg[0] && u->clock < u->qb_msg_ate)
        text(u, (int)PAD_X, FOOT_Y, COL_AMBER, T_CORPO, u->qb_msg);
}

static void draw_qobuz(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    /* a fonte é escolha da pessoa, e vem ANTES da porteira das chaves */
    if (u->fonte == FONTE_SC) { draw_soundcloud(u); return; }
    if (!u->qb_lida) {
        qobuz_config_load(&u->qb_cfg, STYLUS_DATA_DIR);
        u->qb_lida = true;
    }
    QobuzConfig *c = &u->qb_cfg;
    bool pronto = c->configured;

    header(u, "");

    QobuzJob job;
    qobuz_job_estado(&job);

    /* --- baixando: nada mais importa nesta tela --- */
    if (job.ativo || job.ok || job.falhou) {
        {
            header(u, "");
        }
        text_elided(u, (int)PAD_X, 130, COL_AMBER, T_SECAO, SCRW - 2 * PAD_X,
                    job.album[0] ? job.album : "baixando");

        char sub[200];
        if (job.ativo)
            snprintf(sub, sizeof(sub), "track %d of %d  ·  %s",
                     job.faixa, job.total, job.titulo);
        else if (job.ok)
            snprintf(sub, sizeof(sub), "done — %d track%s on the card%s%s",
                     job.total, job.total == 1 ? "" : "s",
                     job.erro[0] ? "  ·  " : "", job.erro);
        else
            snprintf(sub, sizeof(sub), "%s", job.erro[0] ? job.erro : "failed");
        text_elided(u, (int)PAD_X, 162, job.falhou ? COL_ALARM : COL_TEXT,
                    T_CORPO, SCRW - 2 * PAD_X, sub);

        /* A barra mede a FAIXA, não o disco: é o número que se move, e uma
           barra parada por três minutos não informa nada. O disco vai no
           texto acima, que é onde ele cabe. */
        float bw = SCRW - 2 * PAD_X;
        float fr = 0.0f;
        if (job.bytes_total > 0) fr = (float)job.bytes / (float)job.bytes_total;
        else if (job.ok) fr = 1.0f;
        if (fr < 0) fr = 0;
        if (fr > 1) fr = 1;
        vita2d_draw_rectangle(PAD_X, 200, bw, 5, COL_BAR_BED);
        vita2d_draw_rectangle(PAD_X, 200, bw * fr, 5,
                              job.falhou ? COL_ALARM : COL_AMBER);
        if (job.bytes_total > 0) {
            char kb[64];
            snprintf(kb, sizeof(kb), "%ld / %ld MB",
                     job.bytes / 1048576, job.bytes_total / 1048576);
            text(u, (int)PAD_X, 226, COL_TEXT_DIM, T_META, kb);
        }
        if (job.ok)
            text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, T_META,
                 "[O] rescan the shelf and go back — stop the music first, if any");
        else if (job.falhou)
            text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, T_META, "[O] back");
        return;
    }

    /* --- ainda sem credencial: só o preenchimento --- */
    if (!pronto) {
        {
            header(u, "");
        }
        text(u, (int)PAD_X, 116, COL_TEXT_FAINT, T_META, "GETTING STARTED");
        text_elided(u, (int)PAD_X, 140, COL_TEXT, T_DESTAQUE, SCRW - 2 * PAD_X,
                    "the keys are your account's, not this app's — and never leave the card");

        static const char *ROT[QC_N] = {
            "app_id", "secret (there may be more than one, comma separated)",
            "e-mail", "sign in"
        };
        float y0 = 186.0f, rh = 44.0f;
        for (int i = 0; i < QC_N; i++) {
            float y = y0 + i * rh, lx, ly, lw, lh;
            qobuz_linha(i, &lx, &ly, &lw, &lh);
            bool sel = (i == u->qb_sel);
            if (sel) {
                vita2d_draw_rectangle(lx, ly, lw, lh, TINT_SEL_ROW);
                vita2d_draw_rectangle(lx, ly, 2, lh, COL_AMBER);
            }
            text_elided(u, (int)PAD_X + 12, (int)(y + 16),
                        sel ? COL_AMBER : COL_TEXT, T_CORPO, SCRW * 0.55f, ROT[i]);
            char val[128];
            unsigned cor = COL_TEXT_DIM;
            if (i == QC_APPID)       mascara(c->app_id, val, sizeof(val));
            else if (i == QC_SECRET) mascara(c->app_secret, val, sizeof(val));
            else if (i == QC_EMAIL)  snprintf(val, sizeof(val), "%s",
                                              c->email[0] ? c->email : "(empty)");
            else {
                snprintf(val, sizeof(val), "asks for the password and connects");
                cor = COL_AMBER_BRIGHT;
            }
            text_elided(u, (int)(SCRW * 0.62f), (int)(y + 16), cor, T_META,
                        SCRW * 0.38f - PAD_X, val);
        }
        if (u->qb_msg[0] && u->clock < u->qb_msg_ate)
            text(u, (int)PAD_X, FOOT_Y, COL_AMBER, T_CORPO, u->qb_msg);
        else
            text(u, (int)PAD_X, FOOT_Y, COL_TEXT_FAINT, T_MIUDO,
                 "the app_id and secret come from the same account you use on the site");
        return;
    }

    /* --- pronto: buscar e baixar --- */
    {
        header(u, "");
    }

    /* --- abrindo um disco para tocar pela rede --- */
    if (u->qb_abrindo) {
        text_elided(u, (int)PAD_X, 130, COL_AMBER, T_SECAO, SCRW - 2 * PAD_X,
                    u->qb_ab_alb.titulo[0] ? u->qb_ab_alb.titulo : "abrindo");
        text(u, (int)PAD_X, 162, COL_TEXT_DIM, T_CORPO, "fetching tracks over the network…");
        return;
    }

    bool buscando = false;
    int nres = 0;
    qobuz_busca_estado(u->qb_res, (int)(sizeof(u->qb_res) / sizeof(u->qb_res[0])),
                       &nres, &buscando);
    u->qb_nres = nres > 0 ? nres : 0;

    /* LEVA NOVA? peça as capas UMA vez.

       O primeiro id identifica a leva. Sem esta marca a thread seria pedida
       a cada quadro — sessenta vezes por segundo — e o `g_cap_ativo` só
       esconderia o desperdício. */
    if (nres > 0 && strcmp(g_capas_de, u->qb_res[0].id) != 0) {
        snprintf(g_capas_de, sizeof(g_capas_de), "%.31s", u->qb_res[0].id);
        qb_capas_esquece();
        qobuz_capas_async(u->qb_res, nres, STYLUS_DATA_DIR);
    }

    /* a linha da busca, com cara de campo */
    vita2d_draw_rectangle(PAD_X, 112, SCRW - 2 * PAD_X, 34, COL_CARD);
    vita2d_draw_rectangle(PAD_X, 112, 2, 34, COL_AMBER);
    vita2d_draw_rectangle(PAD_X, 144, SCRW - 2 * PAD_X, 1, AMBER_A(25));
    text_elided(u, (int)PAD_X + 14, 134, u->qb_termo[0] ? COL_TEXT : COL_TEXT_FAINT,
                T_DESTAQUE, SCRW * 0.6f,
                u->qb_termo[0] ? u->qb_termo : "[square] to search for a record");
    /* A DIREITA DO CAMPO TEM UM DONO SÓ.
    
       O nome do serviço e o formato foram escritos por dois blocos que não se
       conheciam, cada um alinhado à direita: saiu "~8 MQOBUZB/track", um por
       cima do outro. É a mesma colisão que a frase do "nothing found" já teve
       com as pílulas de busca recente, e o conserto é o mesmo — uma linha,
       montada uma vez.
    
       QOBUZ vai junto porque a aba agora diz "SEARCH" (há duas fontes) e o
       serviço precisa aparecer onde se olha antes de digitar. O formato vai
       junto com o TAMANHO: escolher entre "MP3" e "FLAC" sem saber que um
       custa quatro vezes o outro não é escolher — num cartão de Vita isso
       decide se cabem dez discos ou dois. */
    {
        char f[128];
        snprintf(f, sizeof(f), "QOBUZ  ·  %s  ·  ~%d MB/track",
                 qb_nome_formato(c->formato), qobuz_mb_por_faixa(c->formato));
        int w = text_w(u, T_META, f);
        text(u, (int)(SCRW - PAD_X - w), 134, COL_AMBER, T_META, f);
    }

    /* AS BUSCAS RECENTES, em pílulas — só quando não há resultado na tela.
       Com resultados elas competiriam com o que se veio ver; sem eles, a tela
       era duas linhas e quatrocentos pixels de preto. */
    qb_recentes_carrega();
    u->qb_nrec_vis = 0;
    if (!buscando && nres <= 0 && g_qb_nrec > 0) {
        text(u, (int)PAD_X, 174, COL_TEXT_FAINT, T_MIUDO, "RECENT");
        for (int i = 0; i < g_qb_nrec; i++) {
            float x, y, w, h;
            if (!qb_rec_pilula(u, i, &x, &y, &w, &h)) break;
            bool marc = (u->qb_rec_sel == i);
            vita2d_draw_rectangle(x, y, w, h, marc ? TINT_SEL : COL_CARD);
            unsigned cor = AMBER_A(marc ? 200 : 70);
            vita2d_draw_rectangle(x, y, w, 1, cor);
            vita2d_draw_rectangle(x, y + h - 1, w, 1, cor);
            vita2d_draw_rectangle(x, y, 1, h, cor);
            vita2d_draw_rectangle(x + w - 1, y, 1, h, cor);
            text(u, (int)(x + 13), (int)(y + 18),
                 marc ? COL_AMBER : COL_TEXT_DIM, T_META, g_qb_rec[i].t);
            u->qb_nrec_vis = i + 1;
        }
    }

    if (buscando) {
        text(u, (int)PAD_X, 190, COL_TEXT_DIM, T_DESTAQUE, "looking…");
        return;
    }
    if (nres < 0) {
        text(u, (int)PAD_X, 190, COL_ALARM, T_DESTAQUE, "the search did not go through");
        /* o motivo de verdade, e não "is the Wi-Fi on?" para cinco causas
           diferentes — ver qobuz_motivo() no qobuz.c */
        const char *pq = qobuz_motivo();
        text_elided(u, (int)PAD_X, 218, COL_TEXT, T_CORPO, SCRW - 2 * PAD_X,
                    pq && pq[0] ? pq : "no reason reported — is the Wi-Fi on?");
        text(u, (int)PAD_X, 246, COL_TEXT_DIM, T_META,
             "[square] to try again  ·  the keys are on the ACCOUNT tab");
        return;
    }
    if (nres == 0) {
        /* ABAIXO das pílulas quando elas existem. Fixo em 190, a frase caía
           EM CIMA delas — o texto e as pílulas escritos em dois lugares que
           não se conheciam, que é como toda colisão desta tela nasceu. */
        float y0 = (u->qb_nrec_vis > 0) ? 232.0f : 190.0f;
        text(u, (int)PAD_X, (int)y0, COL_TEXT_DIM, T_CORPO,
             u->qb_termo[0] ? "nothing found" : "search an artist, a record, a year");

        /* E A ESTANTE VIRA SUGESTÃO. Ver a nota do `qb_art_pilula`. */
        u->qb_nart_vis = 0;
        qb_sugestoes_remonta(lib);
        int nart = g_qb_nart;
        if (nart > 0) {
            text(u, (int)PAD_X, (int)(y0 + 26.0f), COL_AMBER, T_META,
                 "ARTISTS YOU ALREADY HAVE");
            for (int i = 0; i < QB_ART_MAX && i < nart; i++) {
                const char *nome = g_qb_art[i];
                if (!nome) break;
                float x, y, w, h;
                if (!qb_art_pilula(i, &x, &y, &w, &h)) break;
                bool marc = (u->qb_art_sel == i);
                /* a MESMA receita das pílulas de busca recente, oito linhas
                   acima: duas coisas selecionáveis na mesma tela que se
                   marcam de jeitos diferentes leem como dois controles */
                vita2d_draw_rectangle(x, y, w, h, marc ? TINT_SEL : COL_CARD);
                unsigned int cor = AMBER_A(marc ? 200 : 70);
                vita2d_draw_rectangle(x, y, w, 1, cor);
                vita2d_draw_rectangle(x, y + h - 1, w, 1, cor);
                vita2d_draw_rectangle(x, y, 1, h, cor);
                vita2d_draw_rectangle(x + w - 1, y, 1, h, cor);
                text_elided(u, (int)(x + 12), (int)(y + 23),
                            marc ? COL_AMBER : COL_TEXT, T_CORPO, w - 24.0f, nome);
                u->qb_nart_vis = i + 1;
            }
        }
        if (u->qb_nrec_vis > 0 || u->qb_nart_vis > 0)
            text(u, (int)PAD_X, (int)(FOOT_Y - 6.0f), COL_TEXT_FAINT, T_MIUDO,
                 "pick one with the d-pad and [X], or just touch it");
        return;
    }

    if (u->qb_sel >= nres) u->qb_sel = nres - 1;
    if (u->qb_sel < 0) u->qb_sel = 0;

    float y = 166.0f, rh = 46.0f;
    for (int i = 0; i < nres && y + rh < FOOT_Y - 10; i++, y += rh) {
        const QobuzAlbum *a = &u->qb_res[i];
        bool sel = (i == u->qb_sel);
        if (sel) {
            vita2d_draw_rectangle(PAD_X, y - 2, SCRW - 2 * PAD_X, rh - 6, TINT_SEL_ROW);
            vita2d_draw_rectangle(PAD_X, y - 2, 3, rh - 6, COL_AMBER);
            /* difusão na borda: o olho segue a âmbar para dentro da lista */
            vita2d_draw_rectangle(PAD_X + 3, y - 2, 6, rh - 6, AMBER_A(20));
        }
        /* A CAPA, à esquerda. Enquanto não chega, fica o lugar dela marcado —
           a linha não pode pular para o lado quando a imagem aparecer. */
        const float CAPA = 38.0f, CAPA_X = PAD_X + 10.0f;
        vita2d_texture *ctex = qb_capa_tex(u, a);
        if (ctex) {
            draw_cover_fit(ctex, CAPA_X, y + 4.0f, CAPA);
        } else {
            vita2d_draw_rectangle(CAPA_X, y + 4.0f, CAPA, CAPA, COL_CARD);
        }

        const int TX = (int)(CAPA_X + CAPA + 10.0f);
        const float TW = SCRW - PAD_X - 190 - (CAPA_X + CAPA + 10.0f);
        text_elided(u, TX, (int)(y + 16), sel ? COL_AMBER : COL_TEXT,
                    T_CORPO, TW, a->titulo);
        char sub[200];
        snprintf(sub, sizeof(sub), "%s%s%s", a->artista,
                 a->ano > 0 ? "   ·   " : "", a->ano > 0 ? "" : "");
        if (a->ano > 0) {
            char ano[16];
            snprintf(ano, sizeof(ano), "%d", a->ano);
            strncat(sub, ano, sizeof(sub) - strlen(sub) - 1);
        }
        if (a->hires) strncat(sub, "   ·   hi-res", sizeof(sub) - strlen(sub) - 1);
        text_elided(u, TX, (int)(y + 33), COL_TEXT_DIM, T_MIUDO, TW, sub);

        /* Quanto o disco vai ocupar, em cada linha: é a informação que
           decide, e ela tem de estar onde a escolha acontece. */
        char peso[64];
        int mb = a->faixas > 0 ? a->faixas * qobuz_mb_por_faixa(c->formato) : 0;
        if (mb > 0) snprintf(peso, sizeof(peso), "%d tracks  ·  ~%d MB", a->faixas, mb);
        else        snprintf(peso, sizeof(peso), "—");
        int w = text_w(u, T_META, peso);
        text(u, (int)(SCRW - PAD_X - 12 - w), (int)(y + 24),
             sel ? COL_AMBER : COL_TEXT_FAINT, T_META, peso);
    }

    if (u->qb_msg[0] && u->clock < u->qb_msg_ate)
        text(u, (int)PAD_X, FOOT_Y, COL_AMBER, T_CORPO, u->qb_msg);
}

/* ---------- AJUSTES ----------

   Duas escolhas, e as duas eram antes decisões minhas escritas no código: a
   mídia do prato (que era só vinil) e a almofada de trás (que eu tinha
   DESLIGADO num #define). Desligar por decreto conserta o incômodo de quem
   reclamou e tira a peça de quem gostava dela. Aqui a pessoa decide, a tela
   diz o que cada uma faz, e o dedo alcança. */
static void draw_ajustes(Ui *u, Player *p)
{
    header(u, "");
    text(u, (int)PAD_X, 132, COL_AMBER, T_SECAO, "Settings");

    float x0, w;
    ajuste_linha(0, &x0, NULL, &w, NULL);
    vita2d_draw_rectangle(x0, 168, w, AJ_N * 52.0f + 8, COL_CARD);
    vita2d_draw_rectangle(x0, 168, w, 1, AMBER_A(40));

    static const char *ROT[AJ_N] = { "theme", "record on the platter",
                                     "rear touch pad", "sleep",
                                     "keep playing when I leave",
                                     "search source", "controls" };
    static const char *AJUDA[AJ_N] = {
        "amber phosphor, or the blue the Vita itself speaks",
        "what spins while a track plays",
        "the pad behind the Vita — it is where your fingers rest",
        "stop on its own — the side ending is the record's own clock",
        "holds the PS button so the console cannot suspend this app",
        "Qobuz sells records; SoundCloud streams single tracks, free",
        "every button, in one list",
    };

    for (int i = 0; i < AJ_N; i++) {
        float ly, lh;
        ajuste_linha(i, NULL, &ly, NULL, &lh);
        bool sel = (i == u->aj_sel);
        if (sel) {
            vita2d_draw_rectangle(x0, ly, w, lh, TINT_SEL_ROW);
            vita2d_draw_rectangle(x0, ly, 2, lh, COL_AMBER);
        }
        text(u, (int)x0 + 12, (int)(ly + 20), sel ? COL_AMBER : COL_TEXT,
             T_CORPO, ROT[i]);
        text_elided(u, (int)x0 + 12, (int)(ly + 38), COL_TEXT_FAINT, T_MIUDO,
                    w * 0.60f, AJUDA[i]);

        /* O VALOR à direita, e o valor é a coisa que muda — por isso ele é
           que fica em âmbar, não o rótulo. */
        const char *val;
        if (i == AJ_TEMA)           val = TEMA.nome;
        else if (i == AJ_MIDIA)     val = (u->midia == MIDIA_CD) ? "compact disc" : "vinyl";
        else if (i == AJ_TRASEIRA)  val = u->toque_tras ? "on" : "off";
        else if (i == AJ_FUNDO)     val = u->bg_trava ? "on" : "off";
        else if (i == AJ_FONTE)     val = (u->fonte == FONTE_SC) ? "SoundCloud"
                                                                 : "Qobuz";
        else if (i == AJ_SONECA) {
            switch (player_sleep_mode(p)) {
            case 1:  val = "fade out";        break;
            case 2:  val = "end of the side"; break;
            default: val = "off";             break;
            }
        }
        else                        val = "see the list";
        int vw = text_w(u, T_DESTAQUE, val);
        text(u, (int)(x0 + w - 16 - vw), (int)(ly + 30),
             sel ? COL_AMBER_BRIGHT : COL_TEXT_DIM, T_DESTAQUE, val);
    }

    text(u, (int)PAD_X, FOOT_Y, COL_TEXT_FAINT, T_META,
         "tap a row to change it  ·  every choice is remembered");
}

/* A LISTA DE CONTROLES.

   Duas colunas porque são vinte e uma linhas e a tela tem 544 px: numa
   coluna só, a metade de baixo cairia fora — e uma lista de atalhos que
   esconde metade dos atalhos é pior que não ter lista.

   Os grupos têm o nome da tela, e a ordem é a de quem procura: primeiro o
   que se faz ouvindo, por último o que vale em qualquer lugar. */
static void draw_controles(Ui *u)
{
    header(u, "");
    text(u, (int)PAD_X, 132, COL_AMBER, T_SECAO, "Controls");
    text(u, (int)PAD_X, 154, COL_TEXT_FAINT, T_MIUDO,
         "everything the buttons do — the screens keep the music instead");

    const float COL_W = (SCRW - 2 * PAD_X) * 0.5f;
    const float TOPO = 186.0f, FUNDO = SCRH - 60.0f;
    float x = PAD_X, y = TOPO;
    int coluna = 0;

    for (const Controle *c = CONTROLES; c->txt; c++) {
        if (c->tela) {
            /* UM GRUPO NÃO SE PARTE AO MEIO.

               Quebrando por linha, "Lists" ficava sozinho no pé da primeira
               coluna e os itens dele continuavam no topo da segunda, sem
               título — dois atalhos órfãos que pareciam ser do grupo de
               cima. Mede-se o grupo inteiro ANTES: se não couber, ele começa
               na outra coluna. */
            int n = 1;
            for (const Controle *k = c + 1; k->txt && !k->tela; k++) n++;
            float alto = 18.0f + (float)n * 20.0f + (y > TOPO ? 10.0f : 0.0f);
            if (y + alto > FUNDO && coluna == 0) {
                coluna = 1;
                x = PAD_X + COL_W;
                y = TOPO;
            }
            if (y > TOPO) y += 10.0f;
            text(u, (int)x, (int)y, COL_AMBER, T_META, c->tela);
            y += 18.0f;
        }
        hint2(u, x + 6.0f, y - 5.0f, c->b, c->b2, c->txt);
        y += 20.0f;
    }
}

/* ---------- A FAIXA DO QUE ESTÁ TOCANDO ----------

   Ideia do Sonara (ver docs/referencias-visuais.md): a barra do tocador fica
   em TODA tela, não só na do tocador. O problema que ela resolve é simples e
   diário — saber o que está tocando sem sair de onde se está. Até aqui era
   preciso VIAJAR até o deck, perder o lugar na estante, e voltar.

   No Vita não cabe a barra inteira do Sonara (capa, coração, volume, cinco
   botões, fila): a tela tem 544 px de altura e o conteúdo precisa deles. O
   que cabe, e é o que importa, é UMA LINHA — a mesma linha do rodapé que já
   existia, que passa a carregar o disco à esquerda e a contagem da tela à
   direita, com o progresso num fio de 2 px na borda de baixo.

   Custo de espaço: zero. O rodapé já estava ali. */
static void rodape_agora(Ui *u, Player *p, const char *direita)
{
    const Album *a = player_current_album(p);
    const Track *t = player_current_track(p);
    float dir_x = SCRW - PAD_X;

    if (direita && direita[0]) {
        int w = text_w(u, T_META, direita);
        text(u, (int)(dir_x - w), (int)FOOT_Y, COL_TEXT_DIM, T_META, direita);
        dir_x -= w + 18.0f;
    }
    if (!a || !t) {
        /* sem disco no prato o rodapé é só a contagem, como sempre foi */
        return;
    }

    const float lado = 22.0f;
    float y = FOOT_Y - lado + 4.0f;
    vita2d_texture *tex = cover_tex(u, (Album *)a);
    if (tex) draw_cover_fit(tex, PAD_X, y, lado);
    else     vita2d_draw_rectangle(PAD_X, y, lado, lado, COL_CARD);
    vita2d_draw_rectangle(PAD_X, y, lado, 1, AMBER_A(60));

    /* o triângulo/pausa em duas barras: diz o ESTADO sem escrever a palavra */
    float px = PAD_X + lado + 10.0f;
    bool live = (player_state(p) == PLAYER_PLAYING);
    if (live) {
        tri_cheio(px + 7.0f, FOOT_Y - 5.0f, 7.0f, 9.0f, 1, COL_AMBER);
    } else {
        vita2d_draw_rectangle(px, FOOT_Y - 9.0f, 2.5f, 9.0f, COL_AMBER);
        vita2d_draw_rectangle(px + 4.5f, FOOT_Y - 9.0f, 2.5f, 9.0f, COL_AMBER);
    }

    /* +8: os dois nomes cabem inteiros MAIS o separador. Sem isso o
       snprintf trunca — inofensivo aqui, porque o text_elided corta de
       novo, mas um aviso de compilação que não aponta defeito nenhum é
       um aviso que se aprende a ignorar. */
    char linha[MAX_NAME_LEN * 2 + 8];
    snprintf(linha, sizeof(linha), "%s   ·   %s",
             t->title[0] ? t->title : t->file,
             a->artist[0] ? a->artist : a->album);
    float tx = px + 16.0f;
    text_elided(u, (int)tx, (int)FOOT_Y, COL_TEXT, T_META, dir_x - tx, linha);

    /* O FIO DO PROGRESSO, na borda de baixo da tela.

       Dois pixels na última linha: é a única coisa que se pode desenhar sem
       tirar espaço de ninguém, e responde "quanto falta" de longe, sem
       número. */
    int dur = player_track_duration(p), pos = player_track_seconds(p);
    if (dur > 0) {
        float f = (float)pos / (float)dur;
        if (f < 0) f = 0;
        if (f > 1) f = 1;
        vita2d_draw_rectangle(0, SCRH - 2, SCRW, 2, COL_BAR_BED);
        vita2d_draw_rectangle(0, SCRH - 2, SCRW * f, 2, COL_AMBER);
    }
}

/* ---------- ARTISTAS ----------

   Faltava uma resposta para "o que eu tenho DESTE artista?". Com 388 discos,
   a estante em ordem alfabética responde "onde está tal disco", que é outra
   pergunta — e a régua de letras também. Quem daily-driva um tocador procura
   por artista tanto quanto por disco.

   O retrato é um CÍRCULO, e quando não há capa ele carrega as INICIAIS —
   ideia do Sonara (ver docs/referencias-visuais.md). Buraco não é fallback:
   uma grade de vazios ensina que a tela está quebrada; uma grade de iniciais
   continua sendo uma grade que se lê. */
/* ART_COLS/ART_ROWS/ART_PAG moram junto do COVER_CACHE — ver a nota lá. */
#define ART_MAX  512

typedef struct { const char *nome; int alb; } Artista;
static Artista g_art[ART_MAX];
static int     g_art_n;
static int     g_art_para;        /* de quantos álbuns esta lista foi feita */

static void artistas_remonta(Library *lib)
{
    if (g_art_para == lib->nalbums && g_art_n > 0) return;
    g_art_para = lib->nalbums;
    g_art_n = 0;
    for (int i = 0; i < lib->nalbums && g_art_n < ART_MAX; i++) {
        const char *nome = lib->albums[i].artist;
        if (!nome || !nome[0]) continue;
        bool ja = false;
        for (int k = 0; k < g_art_n; k++)
            if (!strcasecmp(g_art[k].nome, nome)) { ja = true; break; }
        if (ja) continue;
        g_art[g_art_n].nome = nome;
        g_art[g_art_n].alb = i;
        g_art_n++;
    }
}

static int         artista_quantos(void) { return g_art_n; }
static const char *artista_nome(int i)
{ return (i >= 0 && i < g_art_n) ? g_art[i].nome : NULL; }

/* Até duas iniciais: "Arctic Monkeys" -> "AM", "Radiohead" -> "R".

   SÓ LETRA CONTA como inicial. Sem isso, a coleção deste aparelho — em que
   quase todo disco ao vivo se chama "1993-02-11 - Radiohead - Signal Radio
   Session" — enchia a home de cards marcados "10", "11", "19" e "20": dois
   discos diferentes com a MESMA marca, e nenhuma delas dizendo nada. Uma
   marca gerada existe para se reconhecer o disco de relance; repetida, ela é
   pior que o buraco que veio substituir.

   É a mesma regra que o `album_inicial` da estante já seguia — e essa é a
   armadilha de fundo: duas funções respondendo "qual a inicial disto?" em
   telas diferentes derivam, e a que ninguém olhou deriva para o lado errado.
   Aqui a diferença fica só no NÚMERO de letras (duas, porque um artista se
   reconhece melhor por "AM" que por "A"), não na regra. */
static void iniciais(const char *nome, char *out, size_t cap)
{
    size_t o = 0;
    bool nova = true;
    for (const char *p = nome; *p && o + 1 < cap && o < 2; p++) {
        unsigned char c = (unsigned char)*p;
        int letra = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c >= 0xC0;
        if (!letra) { nova = true; continue; }
        if (nova) {
            out[o++] = (char)toupper(c);
            nova = false;
        }
    }
    out[o] = '\0';
}

static void draw_artistas(Ui *u, Library *lib, Player *p)
{
    header(u, "");
    artistas_remonta(lib);

    if (g_art_n <= 0) {
        text(u, (int)PAD_X, 130, COL_TEXT, T_SECAO, "no artists yet");
        text(u, (int)PAD_X, 162, COL_TEXT_DIM, T_CORPO,
             "the shelf has to find music first");
        return;
    }
    if (u->art_sel >= g_art_n) u->art_sel = g_art_n - 1;
    if (u->art_sel < 0) u->art_sel = 0;

    const int pag = (u->art_sel / ART_PAG) * ART_PAG;
    const float cw = (SCRW - 2 * PAD_X) / (float)ART_COLS;
    const float ch = (FOOT_Y - 20.0f - BODY_Y) / (float)ART_ROWS;
    /* O RAIO SAI DA CÉLULA, e a célula encolheu ao virar três fileiras: sem
       teto, o círculo cresceria pela largura (cw é 150) e invadiria o rótulo
       de baixo. O menor lado manda, e a altura ainda cede o que o rótulo
       precisa — quando dois pisos dividem uma medida, quem cede é o desenho. */
    float r = (cw < ch ? cw : ch) * 0.34f;
    if (r > (ch - 30.0f) * 0.5f) r = (ch - 30.0f) * 0.5f;
    if (r < 18.0f) r = 18.0f;

    for (int k = 0; k < ART_PAG; k++) {
        int i = pag + k;
        if (i >= g_art_n) break;
        float cx = PAD_X + (k % ART_COLS) * cw + cw * 0.5f;
        /* 0.42 e não 0.40: com três fileiras a célula encolheu e o rótulo,
           que fica ABAIXO do círculo, passou a encostar na fileira seguinte.
           Centrar o conjunto (círculo + rótulo) e não só o círculo. */
        float cy = BODY_Y + (k / ART_COLS) * ch + ch * 0.42f;
        bool sel = (i == u->art_sel);

        if (sel) alpha_fill(cx, cy, r + 8.0f, 0.16f, COL_AMBER);

        Album *a = &lib->albums[g_art[i].alb];
        vita2d_texture *tex = cover_tex(u, a);
        if (tex) {
            draw_cover_round(tex, cx, cy, r);
        } else {
            /* o retrato que não existe, com dignidade */
            alpha_fill(cx, cy, r, 0.22f, COL_COLD);
            char ini[8];
            iniciais(g_art[i].nome, ini, sizeof(ini));
            int w = text_w(u, T_SECAO, ini);
            text(u, (int)(cx - w / 2.0f), (int)(cy + 8.0f),
                 sel ? COL_AMBER : COL_TEXT_DIM, T_SECAO, ini);
        }
        alpha_ring(cx, cy, r, 1.2f, sel ? 0.55f : 0.22f, COL_AMBER);

        text_elided(u, (int)(cx - cw * 0.46f), (int)(cy + r + 22.0f),
                    sel ? COL_AMBER : COL_TEXT, T_META, cw * 0.92f,
                    g_art[i].nome);
    }

    char rod[96];
    snprintf(rod, sizeof(rod), "%d artists  ·  %d of %d",
             g_art_n, u->art_sel + 1, g_art_n);
    rodape_agora(u, p, rod);
}

/* ---------- HOME ----------

   A pergunta que nenhuma tela respondia: "abri o app, e agora?".

   A estante responde "onde está tal disco" — que é outra pergunta, e só
   serve para quem já sabe o que quer. Numa coleção de 388 discos em ordem
   alfabética, a primeira tela era a letra A.

   O desenho vem do Sonara (ver docs/referencias-visuais.md): faixas
   horizontais, cada uma respondendo uma coisa. Aqui elas saem de dado que
   já existia e nunca tinha virado tela — o `rec.c` conta há meses quantas
   vezes cada faixa foi ouvida INTEIRA, e ninguém nunca viu esse número.

     continuar    o disco que estava tocando
     a coleção    quantos discos, artistas, faixas
     mais tocados os de maior afinidade (soma das escutas das faixas)
     ainda não    os que nunca tocaram — o que a estante esconde no meio */
/* HOME_FILA mora junto do COVER_CACHE — ver a nota lá. */

static void home_capa(Ui *u, Album *a, float x, float y, float lado, bool sel)
{
    /* A MARCA É QUADRADA porque a capa é.

       Era um `alpha_fill` — um CÍRCULO âmbar — atrás de uma capa quadrada:
       de longe virava uma auréola saindo pelos cantos, e a capa parecia
       colada num prato. Uma moldura que acompanha a forma do que ela marca
       não precisa ser explicada. */
    if (sel) {
        vita2d_draw_rectangle(x - 4, y - 4, lado + 8, lado + 8, TINT_SEL);
        vita2d_draw_rectangle(x - 4, y - 4, lado + 8, 2, COL_AMBER);
    }
    vita2d_texture *tex = a ? cover_tex(u, a) : NULL;
    if (tex) {
        draw_cover_fit(tex, x, y, lado);
    } else {
        /* mesma regra do resto do app: sem capa, uma capa SÓBRIA — nunca um
           buraco. A inicial do disco faz o card continuar sendo um card. */
        vita2d_draw_rectangle(x, y, lado, lado, RGBA8(16, 22, 33, 255));
        vita2d_draw_rectangle(x, y, lado, 2, AMBER_A(70));
        if (a && a->album[0]) {
            /* pelo nome que se LÊ, não pelo da pasta: o `album_display` já
               tira a data da frente e o artista repetido, que é justamente o
               que fazia a marca sair sem letra nenhuma dentro. */
            char rot[MAX_NAME_LEN], ini[8];
            album_display(a, rot, sizeof(rot), NULL, 0);
            iniciais(rot[0] ? rot : a->album, ini, sizeof(ini));
            int w = text_w(u, T_SECAO, ini);
            text(u, (int)(x + lado / 2 - w / 2.0f), (int)(y + lado / 2 + 8),
                 COL_TEXT_DIM, T_SECAO, ini);
        }
    }
    vita2d_draw_rectangle(x, y, lado, 1, AMBER_A(sel ? 120 : 40));
}

/* Uma faixa horizontal: título da seção e até HOME_FILA capas.

   Devolve a ALTURA que gastou — uma seção vazia não pode reservar o espaço
   de cinco capas que não existem. Sem isso, um histórico novo (nada tocado
   ainda) deixava um buraco de 130 px no meio da tela com um travessão
   solitário dentro. */
static float home_fila(Ui *u, Library *lib, const char *titulo, Album **albs,
                       int n, float y, float lado, int base)
{
    text(u, (int)PAD_X, (int)y, COL_AMBER, T_META, titulo);
    if (n <= 0) {
        text(u, (int)(PAD_X + text_w(u, T_META, titulo) + 14), (int)y,
             COL_TEXT_FAINT, T_MIUDO, "nothing here yet");
        return 26.0f;
    }
    float x = PAD_X;
    const float passo = lado + 12.0f;
    /* QUANTAS CABEM DE VERDADE. Com a capa grande (poucas seções na tela) o
       passo cresce e oito não entram; desenhar a nona meio fora da tela é
       pior que não desenhar a nona. */
    int cabem = (int)((SCRW - 2 * PAD_X + 12.0f) / passo);
    if (cabem > HOME_FILA) cabem = HOME_FILA;
    if (cabem < 1) cabem = 1;
    for (int i = 0; i < n && i < cabem; i++, x += passo) {
        bool sel = (u->home_sel == base + i);
        /* qual álbum da estante está sob a marca — é ele que o [X] toca */
        if (sel) u->home_alvo = (int)(albs[i] - lib->albums);
        home_capa(u, albs[i], x, y + 10.0f, lado, sel);
        /* O NOME QUE SE LÊ, e não o da pasta.

           Num card de 86 px cabem uns dez caracteres, e quase todo disco ao
           vivo deste acervo se chama "1993-02-11 - Radiohead - ...": a fila
           inteira saía com a legenda "1993-…", "1993-…", "1996-…" — cinco
           cards que só se distinguem pelo ANO, e dois deles nem por isso. O
           `album_display` tira a data da frente e o artista repetido, que é
           exatamente o que estava comendo a largura toda. */
        char rot[MAX_NAME_LEN];
        album_display(albs[i], rot, sizeof(rot), NULL, 0);
        text_elided(u, (int)x, (int)(y + 10.0f + lado + 16.0f),
                    sel ? COL_AMBER : COL_TEXT_DIM, T_MIUDO, lado,
                    rot[0] ? rot : (albs[i]->album[0] ? albs[i]->album
                                                      : albs[i]->artist));
    }
    return lado + 44.0f;
}

static void draw_home(Ui *u, Library *lib, Player *p)
{
    header(u, "");
    if (!lib || lib->nalbums <= 0) {
        text(u, (int)PAD_X, 140, COL_TEXT, T_SECAO, "nothing on the card yet");
        text(u, (int)PAD_X, 172, COL_TEXT_DIM, T_CORPO,
             "put music in ux0:music and the shelf will find it");
        return;
    }
    artistas_remonta(lib);

    /* ── as duas listas, montadas aqui e não guardadas: são 388 comparações
          por quadro no pior caso, e o preview mede a tela inteira em ~600
          chamadas de desenho. Guardar exigiria invalidar. ── */
    Album *mais[HOME_FILA] = {0}, *novos[HOME_FILA] = {0}, *chegou[HOME_FILA] = {0};
    int nmais = 0, nnovos = 0, nchegou = 0;

    /* OS RECÉM-CHEGADOS. É a pergunta de quem BAIXA música — e o dono desta
       máquina baixa: numa estante de 388 discos em ordem alfabética, achar o
       que entrou ontem é rolar até adivinhar. Sai da data da PASTA, que a
       varredura já lia para conferir o índice e não guardava (ver Album.mtime).

       Inserção direta num vetor de cinco, e não uma ordenação: são 388
       comparações contra 388·log(388), e isto roda por quadro. */
    {
        long long q[HOME_FILA] = {0};
        for (int i = 0; i < lib->nalbums; i++) {
            long long t = lib->albums[i].mtime;
            if (t <= 0) continue;
            for (int k = 0; k < HOME_FILA; k++) {
                if (t <= q[k]) continue;
                for (int j = HOME_FILA - 1; j > k; j--) {
                    q[j] = q[j - 1]; chegou[j] = chegou[j - 1];
                }
                q[k] = t; chegou[k] = &lib->albums[i];
                if (nchegou < HOME_FILA) nchegou++;
                break;
            }
        }
    }
    if (u->rec) {
        int melhor[HOME_FILA] = {0};
        for (int i = 0; i < lib->nalbums; i++) {
            int af = rec_album_affinity(u->rec, &lib->albums[i]);
            if (af <= 0) continue;
            for (int k = 0; k < HOME_FILA; k++) {
                if (af > melhor[k]) {
                    for (int j = HOME_FILA - 1; j > k; j--) {
                        melhor[j] = melhor[j - 1]; mais[j] = mais[j - 1];
                    }
                    melhor[k] = af; mais[k] = &lib->albums[i];
                    if (nmais < HOME_FILA) nmais++;
                    break;
                }
            }
        }
        for (int i = 0; i < lib->nalbums && nnovos < HOME_FILA; i++)
            if (rec_album_unheard(u->rec, &lib->albums[i]))
                novos[nnovos++] = &lib->albums[i];
    }

    /* O TAMANHO DA CAPA SAI DO ESPAÇO QUE SOBRA, e não de um número fixo.

       Com três faixas, 86 px estouravam a tela em 130 — e o defeito seria o
       mesmo de sempre neste projeto: um número escolhido na tela de quem
       escreveu. Pior, ele depende de QUANTAS faixas têm conteúdo: um
       histórico vazio colapsa "mais tocados" e sobra espaço que um número
       fixo não sabe usar.

       Então conta as faixas que têm disco, divide o que resta e limita: 96 é
       onde uma capa começa a competir com o resto da tela, 56 é onde ela
       deixa de ser reconhecível de relance, que é a única coisa que ela
       precisa fazer aqui. */
    u->home_alvo = -1;
    float y = 92.0f;

    int filas = (nchegou > 0) + (nmais > 0) + (nnovos > 0);
    if (filas < 1) filas = 1;
    const float TOPO = 92.0f + 76.0f + 48.0f;   /* continuar + a contagem */
    float sobra = (FOOT_Y - 14.0f) - TOPO - (float)filas * 8.0f;
    float lado = sobra / (float)filas - 44.0f;
    if (lado > 96.0f) lado = 96.0f;
    if (lado < 56.0f) lado = 56.0f;
    /* E A LARGURA TAMBÉM MANDA.

       Só a altura decidia, e por isso a fila acabava onde a quinta capa
       acabasse — não onde a tela acaba. Aqui a capa encolhe, se precisar,
       até as HOME_FILA caberem de ponta a ponta; e o `home_fila` desenha
       quantas couberem, que com poucas seções é o número cheio e com três
       seções cheias é menos. Nos dois casos a fila vai até a borda. */
    const float LARGURA = SCRW - 2 * PAD_X;
    float por_largura = (LARGURA - (HOME_FILA - 1) * 12.0f) / (float)HOME_FILA;
    if (lado > por_largura) lado = por_largura;

    /* continuar de onde parou */
    const Album *ag = player_current_album(p);
    text(u, (int)PAD_X, (int)y, COL_AMBER, T_META, "CONTINUE");
    if (ag) {
        Album *aa = (Album *)ag;
        bool sel = (u->home_sel == 0);
        if (sel) u->home_alvo = (int)(aa - lib->albums);
        /* 66 fixo, e não `lado`: o topo tem de ter altura PREVISÍVEL, senão a
           conta do espaço que sobra depende do que ela mesma decidiu. */
        const float LADO_CONT = 66.0f;
        home_capa(u, aa, PAD_X, y + 8.0f, LADO_CONT, sel);
        const Track *t = player_current_track(p);
        float tx = PAD_X + LADO_CONT + 16;
        float tw = SCRW - PAD_X * 2 - LADO_CONT - 16;
        text_elided(u, (int)tx, (int)(y + 32),
                    sel ? COL_AMBER : COL_TEXT, T_DESTAQUE, tw,
                    t && t->title[0] ? t->title : aa->album);
        text_elided(u, (int)tx, (int)(y + 54), COL_TEXT_DIM, T_META, tw,
                    aa->artist[0] ? aa->artist : aa->album);
    } else {
        text(u, (int)PAD_X, (int)(y + 30), COL_TEXT_FAINT, T_CORPO,
             "nothing on the platter — pick a record from the shelf");
    }
    /* A COLEÇÃO EM NÚMEROS, no vazio à DIREITA do que está tocando.

       Ela tinha uma linha inteira só para si — rótulo em cima, números
       embaixo, 48 px — enquanto ao lado da capa do CONTINUE sobravam
       setecentos pixels de nada. Com três faixas de capa embaixo, esses 48 px
       eram a diferença entre a última fileira caber e sair pela borda.

       E o lugar melhorou: a contagem responde "o que eu tenho", que é a mesma
       pergunta de quem está olhando para a tela inicial. */
    {
        int faixas = 0;
        for (int i = 0; i < lib->nalbums; i++) faixas += lib->albums[i].ntracks;
        char linha[160];
        snprintf(linha, sizeof(linha), "%d records   ·   %d artists   ·   %d tracks",
                 lib->nalbums, g_art_n, faixas);
        int lw = text_w(u, T_META, linha);
        text(u, (int)(SCRW - PAD_X - lw), (int)(y + 54), COL_TEXT_FAINT,
             T_META, linha);
        /* ═══ PÍLULAS DE SHUFFLE ═════════════════════════════════════════════
           Square: embaralha tudo (faixas). Circle: embaralha discos.
           Abaixo da linha de contagem, alinhadas à direita. */
        {
            const char *labels[2] = { "album shuffle", "shuffle all" };
            float px = SCRW - PAD_X;
            for (int i = 1; i >= 0; i--) {
                int tw2 = text_w(u, T_META, labels[i]);
                px -= tw2 + 24.0f;
                text(u, (int)px, (int)(y + 74), COL_TEXT_FAINT, T_META,
                     labels[i]);
                px -= 12.0f;
            }
        }
    }
    y += 92.0f;      /* casa com o TOPO da conta lá em cima */

    /* A ORDEM DAS FAIXAS não é acidental: "acabei de pôr" vem antes de
       "toco muito", que vem antes de "nunca toquei". É da mais recente para a
       mais antiga em atenção — que é a mesma ordem em que a pessoa procura. */
    y += home_fila(u, lib, "JUST ADDED", chegou, nchegou, y, lado, 1);
    y += 8.0f;
    y += home_fila(u, lib, "MOST PLAYED", mais, nmais, y, lado, 1 + HOME_FILA);
    y += 8.0f;
    home_fila(u, lib, "NEVER PLAYED", novos, nnovos, y, lado, 1 + 2 * HOME_FILA);

    /* a marca caiu num lugar vazio (seção mais curta): volta para o começo */
    if (u->home_alvo < 0 && u->home_sel != 0) u->home_sel = 0;
    /* estado, não teclado — a mesma regra do rodapé do deck */
    rodape_agora(u, p, "the shelf has all of it");
}

/* O teclado da loja devolveu texto. */
static void qb_recebeu(Ui *u, int campo, const char *txt)
{
    QobuzConfig *c = &u->qb_cfg;
    if (campo == QC_APPID) {
        snprintf(c->app_id, sizeof(c->app_id), "%.*s", (int)sizeof(c->app_id) - 1, txt);
        qobuz_config_save(c, STYLUS_DATA_DIR);
        qb_diz(u, "app_id saved");
    } else if (campo == QC_SECRET) {
        snprintf(c->app_secret, sizeof(c->app_secret), "%.*s",
                 (int)sizeof(c->app_secret) - 1, txt);
        qobuz_config_save(c, STYLUS_DATA_DIR);
        qb_diz(u, "secret saved");
    } else if (campo == QC_EMAIL) {
        snprintf(c->email, sizeof(c->email), "%.*s", (int)sizeof(c->email) - 1, txt);
        qobuz_config_save(c, STYLUS_DATA_DIR);
        qb_diz(u, "e-mail saved");
    } else if (campo == QC_ENTRAR) {
        snprintf(u->qb_senha, sizeof(u->qb_senha), "%.*s",
                 (int)sizeof(u->qb_senha) - 1, txt);
        qb_diz(u, "signing in…");
    } else if (campo == QC_N) {           /* o termo da busca, no Qobuz */
        snprintf(u->qb_termo, sizeof(u->qb_termo), "%.*s",
                 (int)sizeof(u->qb_termo) - 1, txt);
        u->qb_sel = 0;
        qb_recentes_poe(u->qb_termo);
        qobuz_busca_async(c, u->qb_termo);
    } else if (campo == QC_SC) {          /* o mesmo, no SoundCloud */
        snprintf(u->qb_termo, sizeof(u->qb_termo), "%.*s",
                 (int)sizeof(u->qb_termo) - 1, txt);
        u->sc_sel = 0;
        qb_recentes_poe(u->qb_termo);
        /* O RETORNO NÃO SE IGNORA. Cinco saídas -1 do lado do Qobuz ficaram
           mudas por semanas e a tela dizia "nothing found" para todas elas. */
        if (sc_busca_async(ui_sc_cfg(u), u->qb_termo) != 0)
            qb_diz(u, sc_motivo());
    }
}

/* O login, um quadro depois de a tela já ter dito "signing in…". */
static void qb_tenta_entrar(Ui *u)
{
    QobuzConfig *c = &u->qb_cfg;
    int r = qobuz_login(c, c->email, u->qb_senha);
    memset(u->qb_senha, 0, sizeof(u->qb_senha));   /* a senha sai da memória */
    if (r == 0) {
        qobuz_config_save(c, STYLUS_DATA_DIR);
        qb_diz(u, "entrou");
    } else if (r == -2) qb_diz(u, "enter the app_id and secret first");
    else if (r == -3)   qb_diz(u, "no network: turn the Wi-Fi on and try again");
    else if (r == -4)   qb_diz(u, "Qobuz rejected the e-mail or password");
    else                qb_diz(u, "e-mail is missing");
}

/* O teclado devolveu texto: guarda onde for e, se for o caso, entra.

   Roda no laço de desenho porque é ali que o resultado aparece — mas o
   LOGIN fala com a internet, e por isso ele não é chamado daqui: quem chama
   é a linha de baixo, depois de a tela já ter dito "entrando...". Sem isso a
   pessoa aperta e o aparelho fica alguns segundos parecendo travado. */
static void conta_recebeu(Ui *u, int campo, const char *txt)
{
    LastfmConfig *c = &u->conta_cfg;
    /* O `%.*s` com a precisão do destino não é enfeite: sem ele o compilador
       acusa truncamento, e ele tem razão — o teclado aceita mais caracteres
       do que qualquer destes campos guarda. Cortar é o comportamento certo
       (uma chave de API tem 32 caracteres), mas cortar EM SILÊNCIO no meio
       de um snprintf genérico é como se perde um conserto. */
    if (campo == CC_KEY) {
        snprintf(c->api_key, sizeof(c->api_key), "%.*s",
                 (int)sizeof(c->api_key) - 1, txt);
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "API key saved");
    } else if (campo == CC_SECRET) {
        snprintf(c->api_secret, sizeof(c->api_secret), "%.*s",
                 (int)sizeof(c->api_secret) - 1, txt);
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "secret saved");
    } else if (campo == CC_USER) {
        snprintf(c->username, sizeof(c->username), "%.*s",
                 (int)sizeof(c->username) - 1, txt);
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "username saved");
    } else if (campo == CC_ENTRAR) {
        snprintf(u->conta_senha, sizeof(u->conta_senha), "%.*s",
                 (int)sizeof(u->conta_senha) - 1, txt);
        conta_diz(u, "signing in…");
    }
}

/* A tentativa de login de verdade. Separada para acontecer um quadro DEPOIS
   de o "signing in…" já ter sido pintado. */
static void conta_tenta_entrar(Ui *u)
{
    LastfmConfig *c = &u->conta_cfg;
    int r = lastfm_login(c, c->username, u->conta_senha);
    /* A senha sai da memória assim que a chamada volta, dando certo ou não. */
    memset(u->conta_senha, 0, sizeof(u->conta_senha));

    if (r == 0) {
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "signed in — the queue uploads on its own from here");
        lastfm_sync_async(STYLUS_DATA_DIR);
    } else if (r == -3)   conta_diz(u, "no network: turn the Wi-Fi on and try again");
    else if (r == -4)   conta_diz(u, "last.fm rejected the username or password");
    else                conta_diz(u, "username is missing");
}

/* O NOME QUE SE LÊ de um caminho de faixa.

   A playlist guarda caminho absoluto (é um M3U). Mostrar caminho para
   alguém é mostrar o encanamento — o que a pessoa reconhece é o título. A
   estante já sabe todos, então pergunta-se a ela; e quando a faixa não está
   mais lá (disco apagado, cartão trocado), cai no nome do arquivo, que ainda
   diz mais que o caminho inteiro. */
static const char *nome_da_faixa(Library *lib, const char *caminho)
{
    if (!caminho || !caminho[0]) return "";
    if (lib) {
        Album *alb = NULL;
        int ti = library_find_track_by_path(lib, &alb, caminho);
        if (ti >= 0 && alb && ti < alb->ntracks && alb->tracks[ti].title[0])
            return alb->tracks[ti].title;
    }
    const char *barra = strrchr(caminho, '/');
    return barra ? barra + 1 : caminho;
}

/* O DISCO de onde sai a capa de uma lista: o primeiro arquivo dela que a
   estante ainda reconhece. Não é o "álbum da lista" — uma lista é de vários —
   mas é o que a pessoa vê primeiro quando a toca, e reconhecer isso de
   relance é a única coisa que um ícone de lista precisa fazer. */
static Album *pl_capa(Library *lib, const Playlist *pl)
{
    if (!lib || !pl) return NULL;
    for (int i = 0; i < pl->n && i < 8; i++) {
        Album *alb = NULL;
        if (library_find_track_by_path(lib, &alb, pl->files[i]) >= 0 && alb)
            return alb;
    }
    return NULL;
}

static void draw_playlists(Ui *u, Library *lib, Player *p)
{
    header(u, "");
    {
        header(u, "");
    }

    if (!u->plists || u->nplists <= 0) {
        text(u, (int)PAD_X, 130, COL_TEXT, T_SECAO, "no lists saved");
        text(u, (int)PAD_X, 162, COL_TEXT_DIM, T_CORPO,
             "put a record on and press [square] here to save the night");
        return;
    }
    UiListGeom lg;
    ui_list_geom(SCRW, SCRH, &lg);
    /* 44% para a lista: o suficiente para um nome de mix inteiro, e ainda
       sobra largura para os títulos das faixas do outro lado. */
    const float COL_ESQ = PAD_X + (SCRW - 2 * PAD_X) * 0.44f;
    if (u->pl_sel >= u->nplists) u->pl_sel = u->nplists - 1;
    if (u->pl_sel < 0) u->pl_sel = 0;
    int scroll = (u->pl_sel / lg.rows) * lg.rows;

    for (int r = 0; r < lg.rows; r++) {
        int idx = scroll + r;
        if (idx >= u->nplists) break;
        Playlist *pl = &u->plists[idx];
        float y = lg.y0 + r * lg.row_h;
        if (y + lg.row_h > FOOT_Y - 12) break;
        bool is_sel = (idx == u->pl_sel);
        if (is_sel)
            vita2d_draw_rectangle(PAD_X, y, COL_ESQ - PAD_X, lg.row_h - 4,
                                  u->pl_armed ? TINT_ARMED : TINT_SEL_ROW);
        /* A CAPA DA LISTA é a do primeiro disco que ela toca.

           Eram quatro discos genéricos idênticos, um por linha — exatamente
           o "ícone genérico repetido" que as notas do Sonara chamam de pior
           que buraco. Uma lista não tem arte própria, mas tem a arte do que
           ela contém, e é por ela que se reconhece qual é qual. */
        row_thumb(u, pl_capa(lib, pl), PAD_X + 4, y + 4, lg.row_h - 12.0f);

        float tx = PAD_X + lg.row_h + 6.0f;
        float tw = COL_ESQ - tx;
        text_elided(u, (int)tx, (int)(y + 21), is_sel ? COL_AMBER : COL_TEXT, T_CORPO, tw,
                    pl->name[0] ? pl->name : "(unnamed)");
        char sub[64];
        snprintf(sub, sizeof(sub), "%d track%s", pl->n, pl->n == 1 ? "" : "s");
        text(u, (int)tx, (int)(y + 40), COL_TEXT_DIM, T_META, sub);
    }

    /* O QUE TEM DENTRO, à direita.

       A tela era uma coluna de nomes com dois terços de preto ao lado, e
       "Mix 3 · 8 tracks" não diz nada sobre o que é o Mix 3 — para saber era
       preciso ABRIR e perder o lugar. Lista à esquerda, conteúdo à direita é
       como o app de música do próprio aparelho (e o iPod antes dele) resolve
       isso: a escolha e a consequência ficam visíveis ao mesmo tempo. */
    {
        const Playlist *pl = &u->plists[u->pl_sel];
        float x = COL_ESQ + 18.0f;
        float w = SCRW - PAD_X - x;
        vita2d_draw_rectangle(x - 12.0f, lg.y0, 1, FOOT_Y - 12.0f - lg.y0,
                              AMBER_A(28));
        text_elided(u, (int)x, (int)(lg.y0 + 16), COL_AMBER, T_DESTAQUE, w,
                    pl->name[0] ? pl->name : "(unnamed)");

        /* AS PÍLULAS DE AÇÃO, antes da lista.

           Do Sonara (docs/referencias-visuais.md): a ação principal fica
           ANTES do conteúdo e do tamanho de um alvo de dedo, não escondida
           numa tecla. Tocar uma lista inteira era [X] — uma tecla que a tela
           não desenhava em lugar nenhum.

           Elas são DESENHO e ALVO ao mesmo tempo: a geometria sai daqui e o
           toque lê a mesma (ver pl_pilula). */
        {
            float bx, by, bw, bh;
            /* A PRINCIPAL É CHEIA, a outra é contorno.

               As duas eram iguais — fundo de cartão e um filete âmbar no
               topo — e num painel escuro isso lê como dois botões
               DESABILITADOS. Do Sonara: a ação principal é a única coisa em
               cor cheia da tela, e é assim que ela se lê como "aperte aqui"
               sem legenda nenhuma.

               "play all" é a principal porque é o que se quer em nove de
               cada dez vezes; embaralhar é uma variação dela. */
            for (int k = 0; k < 2; k++) {
                pl_pilula(k, x, lg.y0, &bx, &by, &bw, &bh);
                bool marcada = (u->pl_botao == k);
                bool cheia = (k == 0);
                if (cheia) {
                    vita2d_draw_rectangle(bx, by, bw, bh,
                                          marcada ? COL_AMBER : AMBER_A(180));
                } else {
                    vita2d_draw_rectangle(bx, by, bw, bh,
                                          marcada ? TINT_SEL : COL_CARD);
                    unsigned c = AMBER_A(marcada ? 200 : 90);
                    vita2d_draw_rectangle(bx, by, bw, 1, c);
                    vita2d_draw_rectangle(bx, by + bh - 1, bw, 1, c);
                    vita2d_draw_rectangle(bx, by, 1, bh, c);
                    vita2d_draw_rectangle(bx + bw - 1, by, 1, bh, c);
                }
                const char *rot = k == 0 ? "play all" : "shuffle";
                int tw2 = text_w(u, T_META, rot);
                /* sobre âmbar cheio o texto é o FUNDO da tela, não branco:
                   é o que dá contraste sem inventar uma cor nova */
                text(u, (int)(bx + (bw - tw2) / 2.0f), (int)(by + 17.0f),
                     cheia ? COL_FUNDO : (marcada ? COL_AMBER : COL_TEXT),
                     T_META, rot);
            }
        }
        float y = lg.y0 + 84.0f;
        int cabem = (int)((FOOT_Y - 16.0f - y) / 22.0f);
        for (int i = 0; i < pl->n && i < cabem; i++, y += 22.0f) {
            char linha[MAX_NAME_LEN + 16];
            snprintf(linha, sizeof(linha), "%2d   %s", i + 1,
                     nome_da_faixa(lib, pl->files[i]));
            text_elided(u, (int)x, (int)y, COL_TEXT_DIM, T_META, w, linha);
        }
        if (pl->n > cabem) {
            char mais[48];
            snprintf(mais, sizeof(mais), "and %d more", pl->n - cabem);
            text(u, (int)x, (int)y, COL_TEXT_FAINT, T_MIUDO, mais);
        }
        if (pl->n == 0)
            text(u, (int)x, (int)(lg.y0 + 44), COL_TEXT_FAINT, T_META, "empty");
    }
    if (u->pl_armed)
        text(u, (int)PAD_X, FOOT_Y, COL_ALARM, T_CORPO,
             "delete this list? [select] again confirms, any other key cancels");
    else {
        /* "4 lists" já estava escrito na tela em forma de quatro linhas.
           O que a contagem NÃO diz é quanto tempo a lista escolhida dura —
           que é a pergunta de quem está decidindo o que pôr agora, e o
           número que este sistema inteiro trata como a unidade. */
        char cnt[96];
        const Playlist *sel = &u->plists[u->pl_sel];
        int segs = 0, sabidos = 0;
        for (int i = 0; i < sel->n; i++) {
            Album *alb = NULL;
            int ti = library_find_track_by_path(lib, &alb, sel->files[i]);
            if (ti >= 0 && alb && ti < alb->ntracks && alb->tracks[ti].seconds > 0) {
                segs += alb->tracks[ti].seconds;
                sabidos++;
            }
        }
        if (sabidos > 0 && segs >= 60)
            snprintf(cnt, sizeof(cnt), "%d track%s   ·   %d min%s   ·   %d list%s",
                     sel->n, sel->n == 1 ? "" : "s", (segs + 30) / 60,
                     sabidos < sel->n ? " so far" : "",
                     u->nplists, u->nplists == 1 ? "" : "s");
        else
            snprintf(cnt, sizeof(cnt), "%d list%s",
                     u->nplists, u->nplists == 1 ? "" : "s");
        rodape_agora(u, p, cnt);
    }
}

/* ---------- ouvir enquanto joga ---------- */

/* O plugin Music Premium (cuevavirus) destrava o áudio em segundo plano.

   ESTE COMENTÁRIO ESTAVA MAIS CATEGÓRICO DO QUE OS FATOS. Ele afirmava que o
   plugin só serve ao app MÚSICA da Sony e "não faz um homebrew qualquer
   continuar tocando". A documentação do autor diz o contrário — "background
   music play for ANY game or application" — e cita playback com o VitaShell
   e o ElevenMPV, que são homebrew.

   O que se sabe hoje, e é menos do que qualquer uma das duas afirmações:
   pedir a porta BGM não bastou aqui, e o ElevenMPV-A (que comprovadamente
   toca em segundo plano) faz uma coisa a mais que este app não fazia —
   `sceShellUtilLock`, o papel de TOCADOR DE MÚSICA na Shell. Isso agora é
   pedido no main.c. Se ainda assim não seguir, o degrau seguinte é o
   LOCK_TYPE_PS_BTN, que é o que o ElevenMPV-A usa de fato.

   Enquanto não houver a resposta do aparelho, a tela mostra o estado e
   oferece o caminho do app Música, que é o que o sistema garante. */
static bool plugin_instalado(void)
{
    static int cache = -1;
    if (cache >= 0) return cache != 0;
    const char *onde[] = {
        "ur0:tai/music_premium.skprx",
        "ux0:tai/music_premium.skprx",
        "ur0:tai/music_nonstop.skprx",
        NULL
    };
    cache = 0;
    for (int i = 0; onde[i]; i++) {
        FILE *f = fopen(onde[i], "rb");
        if (f) { fclose(f); cache = 1; break; }
    }
    return cache != 0;
}

static void draw_handoff(Ui *u, Library *lib, Player *p)
{
    (void)lib;
    {
        header(u, "LISTEN WHILE GAMING");
    }

    const Album *a = player_current_album(p);
    bool tem = plugin_instalado();
    PlayerSignal sig;
    player_signal(p, &sig);
    /* As DUAS condições que decidem, medidas — não prometidas. */
    bool porta = u->bgm_port_ok;
    bool taxa  = sig.bgm_port;

    int y = 96;

    /* ESTA TELA ERA UM RELATÓRIO. Abria com três linhas de diagnóstico —
       plugin, porta BGM, taxa da faixa — e só depois dizia o que fazer. Quem
       chega aqui quer ouvir música dentro de um jogo, não auditar o aparelho.

       Agora ela abre com os DOIS CAMINHOS, e o diagnóstico virou uma linha
       só. A ordem também mudou de dono: o caminho pelo app Música da Sony é
       o que o sistema SUPORTA — ele é um app do sistema e pode ficar vivo
       com o jogo na frente; um VPK comum é morto. Por isso ele vem primeiro,
       e desde que a estante foi escrita no banco do sistema
       (tools/musica-para-o-vita.py) ele passou a ter as músicas para tocar. */
    text(u, (int)PAD_X, y, COL_AMBER, T_SECAO, "Two ways in.");
    y += 34;

    text(u, (int)PAD_X, y, COL_TEXT, T_DESTAQUE, "1.  the Vita's own Music app");
    y += 24;
    text_elided(u, (int)PAD_X + 14, y, COL_TEXT_DIM, T_META, SCRW - 2 * PAD_X - 14,
        "it is a system app, so the console keeps it alive inside a game. "
        "this is the one that always works.");
    y += 26;

    if (a && a->key[0]) {
        char linha[MAX_PATH_LEN + 64];
        snprintf(linha, sizeof(linha), "same folder:  %s", a->key);
        text_elided(u, (int)PAD_X + 14, y, COL_AMBER, T_META, SCRW - 2 * PAD_X - 14, linha);
        y += 22;
        const Track *t = player_current_track(p);
        if (t) {
            snprintf(linha, sizeof(linha), "same track:   %s", t->file);
            text_elided(u, (int)PAD_X + 14, y, COL_TEXT_DIM, T_META,
                        SCRW - 2 * PAD_X - 14, linha);
            y += 22;
        }
    } else {
        text(u, (int)PAD_X + 14, y, COL_TEXT_DIM, T_META,
             "put a record on and this will name the folder to open");
        y += 22;
    }
    text_elided(u, (int)PAD_X + 14, y, COL_TEXT_DIM, T_META, SCRW - 2 * PAD_X - 14,
        "[start] leaves this app with the track and position saved — "
        "coming back resumes exactly there.");
    y += 34;

    text(u, (int)PAD_X, y, COL_TEXT, T_DESTAQUE, "2.  straight from here");
    y += 24;
    text_elided(u, (int)PAD_X + 14, y, COL_TEXT_DIM, T_META, SCRW - 2 * PAD_X - 14,
        tem ? "the plugin is installed and this app asks the system for the "
              "music-player role — go into a game and see if the sound follows."
            : "needs the Music Premium kernel plugin; without it the console "
              "suspends this app the moment it leaves the foreground.");
    y += 26;

    /* O INTERRUPTOR, AQUI — e não só lá nos ajustes.

       Isto foi descoberto lendo o `last_session` do cartão do dono: ele dizia
       `bg_trava=0`. A trava do botão PS é O QUE faz o caminho 2 funcionar (a
       Shell não suspende quem a segura — é o que o ElevenMPV-A faz), ela
       existia desde sempre, e a queixa dele durante a sessão inteira foi
       "background not working". O interruptor estava a duas abas de distância
       da tela que explica o assunto.

       Um recurso que só existe atrás de um ajuste que ninguém liga ao problema
       é um recurso que não existe. Ele fica ONDE a pergunta é feita, com o
       estado à vista e o gesto ao lado. Continua desligado por padrão porque
       ligá-lo custa o botão PS parar de levar à tela inicial — mas agora
       ligá-lo é uma tecla, na tela certa, no momento certo. */
    {
        float bx = PAD_X + 14.0f, bw = SCRW - 2 * PAD_X - 28.0f, bh = 34.0f;
        bool on = u->bg_trava;
        vita2d_draw_rectangle(bx, y - 2, bw, bh, on ? AMBER_A(26) : COL_CARD);
        vita2d_draw_rectangle(bx, y - 2, bw, 1, on ? COL_AMBER : AMBER_A(40));
        vita2d_draw_rectangle(bx, y - 2 + bh - 1, bw, 1, on ? COL_AMBER : AMBER_A(40));
        vita2d_draw_rectangle(bx, y - 2, 2, bh, on ? COL_AMBER : AMBER_A(40));
        text(u, (int)(bx + 12), (int)(y + 20), on ? COL_AMBER : COL_TEXT,
             T_CORPO, "[]  keep playing when I leave");
        const char *v = on ? "ON" : "OFF";
        int vw = text_w(u, T_DESTAQUE, v);
        text(u, (int)(bx + bw - 14 - vw), (int)(y + 20),
             on ? COL_AMBER_BRIGHT : COL_ALARM, T_DESTAQUE, v);
        u->hoff_x = bx; u->hoff_y = y - 2; u->hoff_w = bw; u->hoff_h = bh;
        /* +18 e não +6: o `text` desenha pela LINHA DE BASE, então o texto
           sobe a partir do y — com 6 os acentos e as maiúsculas encostavam na
           borda de baixo da caixa, e duas coisas encostadas leem como uma. */
        y += bh + 18.0f;
        text_elided(u, (int)bx, (int)y, COL_TEXT_FAINT, T_MIUDO,
                    bw, on ? "the PS button will not take you home while this app runs "
                             "— that is the price, and it is what keeps the sound alive"
                           : "without this the console suspends this app and the sound "
                             "stops the moment you leave");
        y += 26.0f;
    }

    /* O DIAGNÓSTICO, EM UMA LINHA. Continua aqui porque quando o som NÃO
       segue, é a diferença entre "falta o plugin" e "a faixa é 48 kHz". A
       TRAVA entrou na conta: sem ela as outras três podem estar todas certas
       e o som morre assim mesmo, que foi exatamente o caso deste aparelho. */
    char diag[260];
    snprintf(diag, sizeof(diag),
             "plugin: %s   ·   bgm port: %s   ·   rate: %s   ·   PS lock: %s",
             tem ? "installed" : "not found",
             porta ? "granted" : "refused",
             sig.rate_out > 0 ? (taxa ? "ok for background" : "too high for background")
                              : "put a record on",
             u->bg_trava ? "held" : "OFF");
    text_elided(u, (int)PAD_X, y,
                (tem && porta && taxa && u->bg_trava) ? COL_TEXT_FAINT : COL_ALARM,
                T_MIUDO, SCRW - 2 * PAD_X, diag);

    text(u, (int)PAD_X, FOOT_Y, COL_TEXT_FAINT, T_META,
         tem ? "with the screen off this app keeps playing for hours"
             : "the plugin goes in ur0:tai as music_premium.skprx, under *KERNEL");
}

/* ---------- a varredura ---------- */

void ui_draw_scanning(Ui *u, const char *where, int files)
{
    if (!u || !u->font) return;
    u->clock++;
    u->halo_phase += 0.12f;
    vita2d_start_drawing();
    /* ESTA TELA TAMBÉM É UM QUADRO, e esquecer isso mentiu no relatório.
    
       O `gg_quadro()` só era chamado no `ui_frame`. A varredura abre e fecha
       os PRÓPRIOS quadros — centenas deles, um por punhado de arquivos — e o
       contador nunca zerava entre eles: a primeira caixa-preta anunciou
       "pior quadro 10.731" quando o pior quadro de verdade é da ordem de
       1.200. Aquilo era a varredura INTEIRA somada num pseudo-quadro.
    
       Pior que o número errado: o teto de 12.000 estava a um passo de pegar
       no meio da varredura e cortar a tela que diz "estou lendo o cartão" —
       e numa coleção maior que esta ele pegaria. Um guarda que dispara no
       lugar errado é pior que guarda nenhum. */
    gg_quadro((int)u->view);
    vita2d_clear_screen();
    draw_bg();

    float cx = SCRW / 2.0f, cy = SCRH / 2.0f - 20;
    draw_halo(cx, cy, 78, u->halo_phase);
    draw_disc(cx, cy, 76, 0.0f, 12, NULL, -1, u->halo_phase * 3.0f, NULL, 1.0f,
              u->midia, false);

    const char *t = "looking for records";
    text(u, (int)(cx - text_w(u, T_SECAO, t) / 2), (int)cy + 130, COL_AMBER, T_SECAO, t);

    char line[160];
    snprintf(line, sizeof(line), "%d file%s", files, files == 1 ? "" : "s");
    text(u, (int)(cx - text_w(u, T_CORPO, line) / 2), (int)cy + 156, COL_TEXT, T_CORPO, line);

    if (where && where[0]) {
        char b[512];
        elide(u, b, sizeof(b), T_MIUDO, SCRW - 2 * PAD_X, where);
        text(u, (int)(cx - text_w(u, T_MIUDO, b) / 2), (int)cy + 178, COL_TEXT_DIM, T_MIUDO, b);
    }
    vita2d_end_drawing();
    vita2d_swap_buffers();
}

/* ---------- frame ---------- */

/* O REPOUSO. A tela apaga, a música segue.
 *
 * É o mais perto de "ouvir enquanto faz outra coisa" que um aplicativo comum
 * de Vita chega: o sistema SUSPENDE qualquer app que saia da frente, e isso
 * não é contornável de dentro de um VPK — só um plugin de CFW, que roda no
 * SceShell e é outro programa. O que dá para fazer é o que importa quase
 * tanto no sofá: a tela OLED apagada gasta pouquíssimo, e o disco continua.
 *
 * Fica um pulso âmbar mínimo, não um preto absoluto: preto total lê como
 * "desligou" e a pessoa aperta o botão de força. */
static void draw_rest(Ui *u, Player *p)
{
    vita2d_draw_rectangle(0, 0, SCRW, SCRH, RGBA8(0, 0, 0, 255));
    bool live = player_state(p) == PLAYER_PLAYING;
    if (!live) return;
    u->halo_phase += 0.02f;
    float a = 0.10f + 0.06f * sinf(u->halo_phase);
    alpha_fill(SCRW / 2.0f, SCRH / 2.0f, 15.0f, a, COL_AMBER);
    const Track *t = player_current_track(p);
    if (t) {
        char b[300];
        elide(u, b, sizeof(b), T_MIUDO, SCRW - 120.0f, t->title);
        text(u, (int)(SCRW / 2 - text_w(u, T_MIUDO, b) / 2), SCRH / 2 + 46,
             RGBA8(60, 46, 20, 255), T_MIUDO, b);
    }
}

#ifdef STYLUS_CYCLE
/* DIAGNÓSTICO EM CICLO: o deck vira um carrossel de cenas numeradas, 1,5 s
   cada. O objetivo é descobrir QUAL desenho trava a GPU quando o overlay do
   volume compõe. Cena 0 = quase nada; cena 5 = o deck real. Se o volume
   derrubar a GPU só numa das cenas, o culpado é aquele grupo de primitivas. */
static void draw_rotacoes(float cx, float cy, float r, unsigned int col)
{
    for (int s = 0; s < 18; s++) {
        float a0 = s * (6.2831853f / 18.0f);
        float a1 = a0 + 6.2831853f / 18.0f;
        vita2d_draw_line(cx + cosf(a0) * r, cy + sinf(a0) * r,
                         cx + cosf(a1) * r, cy + sinf(a1) * r, col);
    }
}

static void ciclo_diagnostico(Ui *u, Library *lib, Player *p)
{
    int n = (int)((u->clock / 90) % 8);
    g_congela_disco = (n == 6);   /* cena 6: disco parado */
    g_disco_plano   = (n == 7);   /* cena 7: disco liso */
    char tag[8];
    snprintf(tag, sizeof(tag), "%d", n);
    switch (n) {
    case 0:   /* PLANO: só limpar — o piso de qualquer cena */
        vita2d_clear_screen();
        break;
    case 1:   /* LINHAS soltas, sem sobreposição */
        vita2d_clear_screen();
        for (int i = 0; i < 200; i++) {
            float a0 = i * 0.017f, a1 = a0 + 1.2f;
            float x0 = SCRW / 2.0f + cosf(a0) * 230, y0 = SCRH / 2.0f + sinf(a0) * 230;
            float x1 = SCRW / 2.0f + cosf(a1) * 230, y1 = SCRH / 2.0f + sinf(a1) * 230;
            vita2d_draw_line(x0, y0, x1, y1, RGBA8(120, 120, 255, 180));
        }
        break;
    case 2:   /* ANÉIS translúcidos sobrepostos — o tipo de coisa que o deck mais faz */
        vita2d_clear_screen();
        for (int i = 0; i < 24; i++)
            draw_rotacoes(SCRW / 2.0f, SCRH / 2.0f, 60.0f + i * 9.2f,
                          RGBA8(i * 8, 255 - i * 8, 60, 140));
        break;
    case 3:   /* TEXTURA em tela cheia — o backdrop do deck */
        vita2d_clear_screen();
        deck_backdrop(u, lib && lib->nalbums ? &lib->albums[0] : NULL);
        break;
    case 4:   /* TEXTO PVF em vários corpos */
        vita2d_clear_screen();
        for (int k = 0; k < 8; k++) {
            char linha[64];
            snprintf(linha, sizeof(linha), "teste linha %d", k + 1);
            text(u, 30, 40 + k * 58, RGBA8(255, 170, 40, 255),
                 (k % 2) ? T_SECAO : T_DESTAQUE, linha);
        }
        break;
    default:  /* DECK REAL, modo enxuto permanente */
        draw_deck(u, lib, p);
        break;
    }
    text(u, 30, 28, COL_AMBER_BRIGHT, T_DESTAQUE, tag);
}
#endif

/* ═══ A CAIXA-PRETA DA GPU ════════════════════════════════════════════════

   Uma trava de GPU no Vita não deixa bilhete: ela derruba o sistema inteiro,
   o `psp2core-*-GPUCRASH.psp2dmp` que sobra no `ux0:data` guarda os
   registradores do SGX e a pilha do app PARADA no `vita2d_swap_buffers` —
   isto é, esperando por uma GPU que já morreu. O dump diz que morreu; não diz
   desenhando o quê.

   Foi por isso que este defeito custou uma semana: o dono dizia "travou
   trocando de aba" e não havia como saber QUAL aba, nem se a aba era mesmo
   o assunto.

   Então o app escreve antes. Este arquivo é gravado ANTES do desenho do
   quadro — fora da cena, onde escrever no cartão é seguro — e diz que tela
   está prestes a ser desenhada. Sobrevive à queda porque já está fechado
   quando ela acontece: o que estiver escrito aqui depois de um GPUCRASH é a
   tela que travou.

   O CUSTO: um `fopen`+`fclose` por TROCA DE TELA e um a cada cinco segundos.
   Não é por quadro de propósito — sessenta gravações por segundo num cartão
   exFAT custam mais que o desenho, e o que se procura não muda dentro de um
   quadro.

   Ver a porteira da GPU lá em cima: os números de recusa e de desenho que
   saem aqui vêm dela. */
static void caixa_preta(const Ui *u, int forcado)
{
    static View ultima = (View)-1;
    static View anterior = (View)-1;
    static unsigned long proxima_batida;
    static int rajada;          /* quadros a escrever depois de trocar de tela */

    int mudou = (u->view != ultima);

    /* A RAJADA: os trinta quadros seguintes a uma troca de tela saem um a um.
     *
     * A queda que sobrou acontece SEGUNDOS depois de entrar no deck, e um
     * arquivo escrito a cada cinco segundos não pega o quadro certo. Trinta
     * gravações pequenas por troca de aba é preço que se paga; sessenta por
     * segundo para sempre, não. Quando a rajada acaba, volta a batida lenta. */
    if (mudou) rajada = 30;
    else if (rajada > 0) rajada--;

    if (!mudou && rajada <= 0 && !forcado &&
        (unsigned long)u->clock < proxima_batida) return;
    if (mudou) { anterior = ultima; ultima = u->view; }
    proxima_batida = (unsigned long)u->clock + 300;   /* ~5 s a 60 fps */

    FILE *f = fopen(STYLUS_DATA_DIR "/gpu.txt", "w");
    if (!f) return;
    int a = aba_de(u->view), b = aba_de(anterior);
    fprintf(f, "vitastylus  build %s %s\n", __DATE__, __TIME__);
    fprintf(f, "frame       %lu\n", (unsigned long)u->clock);
    fprintf(f, "screen      %s (view %d)   <- about to be drawn\n",
            a >= 0 ? ABA_NOME[a] : "(not a tab)", (int)u->view);
    fprintf(f, "came from   %s\n", b >= 0 ? ABA_NOME[b] : "(none yet)");
    {
        int pt = ui_gpu_pior_tela();
        int pa = pt >= 0 ? aba_de((View)pt) : -1;
        char porTipo[192];
        ui_gpu_pior_por_tipo(porTipo, (int)sizeof(porTipo));
        fprintf(f, "draws       last frame %ld\n", ui_gpu_ultimo());
        fprintf(f, "worst       %ld on %s (cap %d)\n", ui_gpu_pior(),
                pa >= 0 ? ABA_NOME[pa] : "(not a tab)", GG_TETO_QUADRO);
        fprintf(f, "  by kind   %s\n", porTipo);
        /* O NÚMERO QUE FALTAVA. Calls are cheap; pixels are not — the frame
           that took the device down was clean by every call counter and was
           painting seven full screens. Ver o `gg_px_caixa` no ui.c. */
        fprintf(f, "fill        last frame %.1f screens, worst %.1f "
                   "(1.0 = 960x544 painted once)\n",
                ui_gpu_telas_ultimo(), ui_gpu_telas_pior());
        fprintf(f, "lean mode   %s\n", u->gpu_safe ? "ON" : "off");
        fprintf(f, "deck entry  %d more lite frame(s) queued\n", u->deck_enxuto);
        fprintf(f, "deck stage  last deck frame was '%s' tex=%d linhas=%d\n",
                u->deck_stage ? u->deck_stage : "never",
                u->deck_tex, u->deck_linhas);
        fprintf(f, "last phase  %s   <- how far the PREVIOUS frame got\n", g_fase);
    }
    fprintf(f, "cap hit     %s\n", ui_gpu_estourou() ? "YES - a frame was cut short"
                                                     : "no");
    fprintf(f, "rejected    %lu coordinate(s) refused before reaching the GPU\n",
            ui_gpu_recusas());
    fprintf(f, "clamped     %lu texture window(s) that ran past the texture\n",
            ui_gpu_aparadas());
    fprintf(f, "  first     %s\n", ui_gpu_apara1());
    fprintf(f, "off-screen  %lu primitive(s) far outside the 960x544 screen\n",
            ui_gpu_longe());
    fprintf(f, "  first     %s\n", ui_gpu_longe1());
    fprintf(f, "first one   %s\n", ui_gpu_primeira());
    /* ESTA LINHA DIZIA `covers 29 local, 12 qobuz` E ERAM AS CAPACIDADES.
       Lida depois de uma queda, parecia estado — "havia 29 capas vivas" — e
       não era: os dois números são constantes de compilação e nunca mudam.
       Um diagnóstico que se lê como medida tem de SER medida. */
    {
        int vivas = 0, vivas_bl = 0, vivas_qb = 0;
        for (int i = 0; i < COVER_CACHE; i++) {
            if (u->cache[i].tex)  vivas++;
            if (u->cache[i].blur) vivas_bl++;
        }
        for (int i = 0; i < QB_CAPA_CACHE; i++)
            if (g_qbcapa[i].tex) vivas_qb++;
        fprintf(f, "covers      %d/%d local (+%d blur), %d/%d qobuz  <- live/capacity\n",
                vivas, COVER_CACHE, vivas_bl, vivas_qb, QB_CAPA_CACHE);
    }
    fprintf(f, "tex leaked  %lu (dead-texture queue full; ALWAYS 0 in a sane run)\n",
            g_tex_vazadas);

    /* QUEM MAIS ESTÁ DENTRO DESTE PROCESSO.
     *
     * Os dois `psp2core-*-GPUCRASH` deste aparelho listam **VitaGrafix**
     * carregado DENTRO do nosso processo. Ele é um plugin de taiHEN que
     * engancha o caminho de render para trocar a resolução dos JOGOS — num
     * homebrew que ele não conhece deveria ficar quieto, mas engancha do
     * mesmo jeito. O cartão também traz PSVshell, que mexe em frequência de
     * relógio.
     *
     * Isto não acusa ninguém: acusar sem medir foi o que fez três sessões
     * consertarem a coisa errada. Mas "que código de terceiro está dentro do
     * meu processo quando a GPU trava" é uma pergunta que só o aparelho
     * responde, e até agora nada a fazia. Se a lista vier vazia numa execução
     * que não trava e cheia numa que trava, isso é mais do que qualquer
     * leitura de código daria.
     */
#ifdef __vita__
    {
        SceUID uids[64];
        SceSize n = 64;
        if (sceKernelGetModuleList(0xFF, uids, &n) >= 0) {
            fprintf(f, "modules     %d in this process\n", (int)n);
            for (SceSize i = 0; i < n; i++) {
                SceKernelModuleInfo mi;
                memset(&mi, 0, sizeof(mi));
                mi.size = sizeof(mi);
                if (sceKernelGetModuleInfo(uids[i], &mi) < 0) continue;
                /* Só o que NÃO é da Sony nem nosso: é isso que interessa. */
                if (!strncmp(mi.module_name, "Sce", 3)) continue;
                if (!strcmp(mi.module_name, "vitastylus")) continue;
                fprintf(f, "  foreign   %s\n", mi.module_name);
            }
        }
    }
#endif
    fclose(f);
}

/* Fecha a medida do governador: quanto custou MONTAR a lista deste quadro.
   Chamada logo depois do end_drawing, antes do swap — a espera do vsync não
   entra, e era justamente ela que mantinha o modo enxuto ligado para sempre. */
static void gpu_marca_fim(Ui *u)
{
#ifdef __vita__
    SceRtcTick t1;
    sceRtcGetCurrentTick(&t1);
    unsigned long long res = sceRtcGetTickResolution();
    if (!res) res = 1;
    u->gpu_ms = (unsigned long)((t1.tick - u->gpu_t0.tick) * 1000ULL / res);
#else
    (void)u;
#endif
}

/* Quem desenha o quê: o latim pega o que cabe em U+2E80 para baixo. */
static int grupo_latino(unsigned int c) { return c <  0x2E80; }
static int grupo_cjk(unsigned int c)    { return c >= 0x2E80; }

static const vita2d_system_pvf_config FONTES_DA_TELA[] = {
    { SCE_PVF_LANGUAGE_LATIN, grupo_latino },
    { SCE_PVF_LANGUAGE_J,     grupo_cjk    },
};

int ui_frame(Ui *u, Library *lib, Player *p)
{
    u->clock++;

    /* ═══ REINICIALIZAÇÃO APÓS SUSPENSÃO (CRASH NO WAKE) ══════════════════
     *
     * SINTOMA: o app trava quando a tela é ligada depois de desligada.
     * CAUSA: quando o Vita suspende (ou a tela desliga por timeout), a GPU
     * perde o contexto de renderização. Ao voltar, vita2d_start_drawing()
     * opera num contexto morto e a GPU trava o sistema.
     *
     * DETECÇÃO: mais de 2 segundos entre quadros = o app foi suspenso.
     * Em 60 Hz cada quadro tem ~16 ms; 2 s é 120 quadros perdidos.
     *
     * CONSERTO: destruir e reconstruir o contexto vita2d. As texturas do
     * cache são colecionadas (tex_coletar) e recriadas sob demanda; a fonte
     * precisa ser recarregada. O custo é um quadro preto — invisível: a
     * pessoa acabou de ligar a tela e ainda não viu nada. */
#ifdef __vita__
    {
        static SceRtcTick wake_t0 = {0};
        SceRtcTick now;
        sceRtcGetCurrentTick(&now);
        if (wake_t0.tick) {
            unsigned long long res = sceRtcGetTickResolution();
            if (!res) res = 1;
            unsigned long long gap_ms = (now.tick - wake_t0.tick) * 1000ULL / res;
            if (gap_ms > 2000) {
                /* Reconstrói o contexto da GPU — e NÃO LIBERA NADA DEPOIS.
                 *
                 * O que estava escrito aqui liberava a fonte e as texturas
                 * do cache DEPOIS do fini — mas o fini já as destruiu. É
                 * double-free: corrompe o heap e a queda vem QUADROS DEPOIS,
                 * longe da causa (o rastro típico: pausou, largou o aparelho,
                 * a tela dormiu, ao voltar morreu "do nada"). Pior: a fila
                 * de mortos guardava texturas do contexto morto e as
                 * liberava 4 quadros depois — outra queda adiada.
                 *
                 * O conserto é só ESQUECER os ponteiros: o fini já recolheu
                 * o lado da GPU. Tudo se refaz sob demanda (capa, borrão) ou
                 * agora (fonte). */
                for (int i = 0; i < COVER_CACHE; i++) {
                    u->cache[i].tex = NULL;
                    u->cache[i].blur = NULL;
                    u->cache[i].blur_tentado = false;
                }
                for (int i = 0; i < QB_CAPA_CACHE; i++) {
                    g_qbcapa[i].tex = NULL;
                    g_qbcapa[i].cheio = 0;
                }
                for (int i = 0; i < TEX_MORTAS; i++) {
                    g_mortas[i] = NULL;
                    g_mortas_qd[i] = 0;
                }
                u->font = NULL;
                vita2d_fini();
                vita2d_init();
                /* Recarrega a fonte: a antiga morreu com o fini */
                u->font = vita2d_load_system_pvf(2, FONTES_DA_TELA);
                pvf_filtro_linear(u->font);
                u->pede_capa = NULL;
                u->pede_blur = NULL;
            }
        }
        wake_t0 = now;
    }
#endif

    /* O PRIMEIRO QUADRO DO DECK VEM ENXUTO — toda entrada é a primeira
       aparição. Ver o consumo no `draw_deck` (que decrementa); aqui só se
       arma quando a tela NÃO é o deck, então o deck que já está de pé nunca
       é tocado. */
    if (u->view != VIEW_DECK) u->deck_enxuto = DECK_ENXUTO_QUADROS;

    caixa_preta(u, 0);   /* que tela vai ser desenhada — ver a caixa-preta */

    /* ORÇAMENTO DE GPU — ANTES de qualquer desenho.
       Mede quanto o quadro anterior gastou (do start_drawing ao
       swap_buffers anterior). Se passou do teto, ativa o modo enxuto
       para este quadro. A GPU do Vita é compartilhada com o sistema —
       overlay de volume, notificações, composição — e quando a lista
       de display fica cheia demais, o compositor do sistema não consegue
        encaixar o overlay dele: a GPU trava e derruba o sistema.

        O teto de 16 ms (de 16,67 ms de um quadro a 60 Hz) é o quadro
        inteiro — sem margem para o compositor, mas o custo real do deck
        com sulcos, lustro e espectro fica em ~8 ms. O governador mede
        o TEMPO DE MONTAGEM da lista de desenho, não o período entre
        quadros — a espera do vsync fica de fora. Quando o cartão enche
        o ring e o decoder gasta mais, o compositor leva o que precisa
        e o app segue no quadro seguinte. No host (preview/testes), sem
        GPU real, o modo seguro nunca ativa. */
#ifdef __vita__
    {
        /* ═══ ESTE GOVERNADOR ESTEVE PRESO NO CHÃO DESDE QUE NASCEU ═══════
         *
         * SINTOMA: o `gpu.txt` do cartão diz `lean mode ON` com 1.082
         * desenhos — um terço do gatilho por número de chamadas. Só podia ter
         * vindo do tempo. E vinha: o `gpu_t0` era carimbado UMA VEZ por
         * quadro, aqui no topo, então `dt` media o PERÍODO ENTRE QUADROS —
         * que a 60 Hz é 16,7 ms porque o `vita2d_swap_buffers` espera o
         * vsync. Sempre maior que 12. Dois quadros depois do arranque o modo
         * enxuto ligava e NUNCA MAIS desligava.
         *
         * O que isso custou: os sulcos do disco pela metade (24->12), o
         * lustro pela metade (34->17) e o espectro desligado, para sempre,
         * em todas as telas — sem que nada dissesse por quê. E, do outro
         * lado, ZERO proteção: um medidor encostado no teto não distingue
         * quadro caro de quadro barato.
         *
         * Agora mede-se o que a frase acima sempre disse que media: o tempo
         * de MONTAR a lista de desenho (start_drawing -> end_drawing), que é
         * o trabalho que este app entrega à GPU. A espera do vsync fica de
         * fora porque não é trabalho nosso.
         *
         * E o preenchimento entra junto: o `deck_backdrop` provou que o custo
         * pode ser sete telas cheias em sete chamadas, e nenhum contador de
         * chamada nem de tempo de CPU vê isso. Ver o `gg_px_caixa`. */
        unsigned long ms = u->gpu_ms;
        if (ms > 8) {
            u->gpu_slow_frames++;
            if (u->gpu_slow_frames >= 2) u->gpu_safe = true;
        } else {
            u->gpu_slow_frames = 0;
            u->gpu_safe = false;
        }

        /* O GOVERNADOR OLHA O NÚMERO, E NÃO SÓ O RELÓGIO.
        
           O teto de tempo não pegou nada: o aparelho desenhou 10.731 chamadas
           num quadro e o modo enxuto continuou desligado. Faz sentido — a GPU
           engole a lista, devolve o quadro dentro dos 12 ms, e quem não cabe é
           o COMPOSITOR DO SISTEMA quando ele precisa encaixar o overlay de
           volume por cima. O sintoma que o dono relatou é literalmente esse:
           "increasing volume" derruba.
        
           Então o número de chamadas do quadro ANTERIOR também aciona o modo
           enxuto. O PC mede 1.177 no pior caso das onze telas; 3.000 é o dobro
           e meio disso e um terço do que o aparelho fez — nunca pega num
           quadro são e pega SEMPRE num quadro como aquele. */
        if (g_gg_ultimo > GG_ENXUTO) u->gpu_safe = true;

        /* E O PREENCHIMENTO. Este é o gatilho que faltava: o quadro que
           derrubou o aparelho tinha 1.082 chamadas (limpo por qualquer
           contador de chamada) e SETE TELAS de pixel. Três telas cheias por
           quadro é o dobro do que um quadro são deste app pinta.

           O TETO ORIGINAL ERA 3.0 — e era ARMADILHA: o backdrop ocupa ~2
           telas (textura + véu), o corpo do disco ~1 tela, e o resto ~0,7.
           Total ~3,7: SEMPRE acima de 3,0. O modo enxuto ligava no primeiro
           quadro e nunca desligava, cortando lustro e espectro para sempre.
           O rework do disco (96 arcos) existia no código mas nunca chegava
           à tela. Agora o teto é 4,5: acima do custo normal (~3,7) e bem
           abaixo das 7 telas que travavam. */
        if (ui_gpu_telas_ultimo() > 4.5) u->gpu_safe = true;
    }
#endif

    tex_coletar();      /* libera o que morreu há quatro quadros — ver o cemitério */

    /* AS CAPAS PEDIDAS NO QUADRO PASSADO, carregadas AQUI: fora da cena, onde
       mapear memória de GPU é seguro. Uma de cada tipo por quadro. */
    capa_serve(u);
    qb_capa_serve(u);
    blur_serve(u);

    /* entra em repouso sozinho depois de um tempo parado COM música tocando:
       parado sem música é alguém escolhendo um disco, e apagar a tela na cara
       de quem está escolhendo é hostil */
    if (!u->resting && player_state(p) == PLAYER_PLAYING) {
        if (++u->rest_idle > 60 * 90) u->resting = true;
    } else if (player_state(p) != PLAYER_PLAYING) {
        u->rest_idle = 0;
    }

    /* o relógio começa AQUI: o que vem antes (coletar textura, servir capa,
       escrever a caixa-preta) não é lista de desenho */
#ifdef __vita__
    sceRtcGetCurrentTick(&u->gpu_t0);
#endif
    vita2d_start_drawing();
    gg_quadro((int)u->view);   /* zera o contador e guarda quem foi o pior */
    if (u->resting) {
        vita2d_clear_screen();
        draw_rest(u, p);
        vita2d_end_drawing();
        gpu_marca_fim(u);
        vita2d_swap_buffers();
        return 0;
    }
#ifdef STYLUS_NODRAW
    /* DIAGNÓSTICO: quadro PRETO. Nenhuma chamada de desenho entre o start e o
       end, mas o app inteiro continua rodando — SDL, decodificador, threads de
       rede, porta BGM. Se o GPUCRASH do volume continuar AQUI, o desenho está
       absolvido e o suspeito é o resto do app ou o próprio sistema fazendo a
       composição do overlay. Se parar, o passo seguinte é voltar a desenhar
       a tela aos poucos para achar qual primitiva. */
    vita2d_clear_screen();
    vita2d_end_drawing();
    ime_desenhar();
    vita2d_swap_buffers();
    return 0;
#endif
#ifdef STYLUS_CYCLE
    ciclo_diagnostico(u, lib, p);
    vita2d_end_drawing();
    ime_desenhar();
    vita2d_swap_buffers();
    return 0;
#endif
    vita2d_clear_screen();
    draw_bg();
    u->tocando = (player_state(p) == PLAYER_PLAYING);
    /* Aqui, e não no draw_shelf: a entrada não recebe uma Library, e amarrar
       uma decisão de TECLA ao que foi DESENHADO é como o teste dos atalhos
       travou — ele bate teclas sem desenhar nada, e o [X] nunca mais saía da
       estante. O que a entrada lê tem de ser atualizado por quem sempre roda. */
    u->tem_disco = (lib && lib->nalbums > 0);

    fase("ui_frame: bg");
    if (u->view == VIEW_SHELF)      draw_shelf(u, lib, p);
    else if (u->view == VIEW_DECK)  draw_deck(u, lib, p);
    else if (u->view == VIEW_RECS)  draw_recs(u, lib, p);
    else if (u->view == VIEW_HANDOFF) draw_handoff(u, lib, p);
    else if (u->view == VIEW_AJUSTES) draw_ajustes(u, p);
    else if (u->view == VIEW_CONTROLES) draw_controles(u);
    else if (u->view == VIEW_ARTISTAS) draw_artistas(u, lib, p);
    else if (u->view == VIEW_HOME)     draw_home(u, lib, p);
    else if (u->view == VIEW_CONTA) draw_conta(u, lib, p);
    else if (u->view == VIEW_QOBUZ) draw_qobuz(u, lib, p);
    else                            draw_playlists(u, lib, p);

    fase("ui_frame: end_drawing");
    vita2d_end_drawing();
    gpu_marca_fim(u);   /* fecha a medida do governador — ver a nota lá em cima */

    /* O TECLADO DO SISTEMA PINTA ENTRE O end_drawing E O swap_buffers.

       SINTOMA, do dono: "i press square to search nothing shows up". E não
       aparecia mesmo — nem aqui, nem na conta, nem no filtro da estante:
       nenhuma caixa de texto do app jamais desenhou no aparelho.

       O comentário antigo já sabia o QUE tinha de acontecer ("pinta DEPOIS
       de tudo") e a chamada estava um passo cedo, ANTES do end_drawing — ou
       seja, dentro do passe de desenho, onde o diálogo do sistema não compõe.
       O sceImeDialogInit funcionava, o ime_poll ficava esperando um resultado
       que nunca vinha, e a tela seguia igual. Um recurso inteiro morto por
       uma linha de ordem.

       A ordem certa do vita2d é start → desenho → end → common_dialog_update
       → swap, e é a mesma para qualquer diálogo do sistema. */
    fase("ui_frame: ime/common_dialog");
    ime_desenhar();

    fase("ui_frame: swap");
    vita2d_swap_buffers();
    fase("ui_frame: whole frame OK");
    return 0;
}

/* ---------- entrada ---------- */

/* O direcional REPETE quando segurado. Sem isto, andar por uma estante de
   quatrocentos discos é quatrocentos toques — a entrada era só de borda, e o
   d-pad é a única navegação que existe. Só o direcional repete: uma tecla de
   ação repetida apagaria a playlist duas vezes. */
#define REPEAT_DELAY 26   /* quadros segurando antes de começar */
#define REPEAT_EVERY 4    /* e um passo a cada tantos depois */
#define DPAD (SCE_CTRL_UP | SCE_CTRL_DOWN | SCE_CTRL_LEFT | SCE_CTRL_RIGHT)

/* CONVERTER A COORDENADA DO PAINEL PARA A DA TELA.

   O painel da frente devolve 0..1919 x 0..1087 — o DOBRO da tela, porque ele
   tem resolução maior que ela. Usar as coordenadas cruas põe todo toque no
   canto superior esquerdo, e é o erro que se comete uma vez.

   O de TRÁS não se resolve com o mesmo "divide por 2". A almofada traseira é
   MENOR que a tela: ela não alcança as bordas de cima e de baixo, e o painel
   reporta isso deslocando a área ativa (o y começa perto de 108, não de 0).
   Dividir por 2 ali deixaria todo arrasto no terço de cima e o rodapé
   inalcançável — um defeito que não aparece lendo o código, só com o dedo.

   Por isso a conversão vem do sceTouchGetPanelInfo, que é o painel dizendo a
   sua própria área ativa, e não de um número escrito à mão. Os valores de
   emergência abaixo só entram se a chamada falhar. */
typedef struct { float ox, oy, sx, sy; } Painel;
static Painel g_painel[SCE_TOUCH_PORT_MAX_NUM];

static void painel_medir(int porta, float fx0, float fy0, float fx1, float fy1)
{
    SceTouchPanelInfo pi;
    float x0 = fx0, y0 = fy0, x1 = fx1, y1 = fy1;
    memset(&pi, 0, sizeof(pi));
    if (sceTouchGetPanelInfo((uint32_t)porta, &pi) >= 0 &&
        pi.maxAaX > pi.minAaX && pi.maxAaY > pi.minAaY) {
        x0 = pi.minAaX; y0 = pi.minAaY;
        x1 = pi.maxAaX; y1 = pi.maxAaY;
    }
    g_painel[porta].ox = x0;
    g_painel[porta].oy = y0;
    g_painel[porta].sx = (float)SCRW / (x1 - x0);
    g_painel[porta].sy = (float)SCRH / (y1 - y0);
}

static void touch_setup(void)
{
    /* Sem ligar a amostragem, o painel de trás devolve reportNum 0 para
       sempre — e o sintoma é idêntico ao de "ninguém encostou". */
    sceTouchSetSamplingState(SCE_TOUCH_PORT_FRONT, SCE_TOUCH_SAMPLING_STATE_START);
    sceTouchSetSamplingState(SCE_TOUCH_PORT_BACK,  SCE_TOUCH_SAMPLING_STATE_START);
    painel_medir(SCE_TOUCH_PORT_FRONT, 0.0f,   0.0f, 1919.0f, 1087.0f);
    painel_medir(SCE_TOUCH_PORT_BACK,  0.0f, 108.0f, 1919.0f,  889.0f);
}

/* um painel, um quadro: onde o dedo está, se andou, há quanto tempo */
static void toque_ler(Toque *t, int porta)
{
    SceTouchData td;
    memset(&td, 0, sizeof(td));
    t->was_down = t->down;
    t->down = false;
    if (sceTouchPeek((uint32_t)porta, &td, 1) >= 0 && td.reportNum > 0) {
        const Painel *pn = &g_painel[porta];
        float x = ((float)td.report[0].x - pn->ox) * pn->sx;
        float y = ((float)td.report[0].y - pn->oy) * pn->sy;
        /* a área ativa do painel de trás é menor que a tela: o dedo na borda
           dele cai FORA da tela depois da conta, e um índice negativo em
           in_rect é um item errado marcado */
        if (x < 0) x = 0; else if (x > SCRW - 1) x = SCRW - 1;
        if (y < 0) y = 0; else if (y > SCRH - 1) y = SCRH - 1;
        t->down = true;
        t->x = (int)x;
        t->y = (int)y;
    }
    if (t->down && !t->was_down) {
        t->start_x = t->x;
        t->start_y = t->y;
        t->frames = 0;
        t->moved = false;
    } else if (t->down) {
        t->frames++;
        int dx = t->x - t->start_x;
        int dy = t->y - t->start_y;
        if (dx * dx + dy * dy > 18 * 18) t->moved = true;
    }
}

/* A ALMOFADA DE TRÁS, DESLIGADA — a pedido de quem usa.

   "it is making me skip shit accidentally": atrás os dedos SEGURAM o
   aparelho, e um deslize involuntário ali virava trocar de faixa ou arrastar
   a agulha. Um gesto que a mão faz sem querer não é um atalho, é um defeito
   — e não há como olhar para o dedo para corrigir a mira.

   Desligado AQUI, num lugar só: tudo que lê `u->tras` (o arrasto, o cue do
   disco) fica inerte sozinho, sem espalhar `if` pela tela inteira. A
   amostragem do painel continua ligada e a medição de área continua sendo
   feita, então voltar atrás é trocar este 0 por 1 — o caminho inteiro
   continua aqui, testado, só não está ligado à mão de ninguém. */
static void touch_read(Ui *u)
{
    toque_ler(&u->frente, SCE_TOUCH_PORT_FRONT);
    if (u->toque_tras) {
        toque_ler(&u->tras, SCE_TOUCH_PORT_BACK);
    } else {
        /* "ninguém encostou", todo quadro. O `was_down` tem de continuar
           sendo atualizado, senão um toque que já estava acontecendo quando
           isto foi desligado ficaria preso em "está descendo" para sempre. */
        u->tras.was_down = u->tras.down;
        u->tras.down = false;
        u->tras.moved = false;
    }
}

static bool tap_released(const Ui *u)
{
    /* Um toque é curto e parado. Sem exigir as duas coisas, todo arrasto
       termina disparando o item onde o dedo largou.

       Só o painel da FRENTE dispara toque. Atrás os dedos estão segurando o
       aparelho: um "toque" ali não é uma intenção, é a mão. Por isso o de
       trás só entende ARRASTO — ver arrasto_tras(). */
    return u->frente.was_down && !u->frente.down && !u->frente.moved &&
           u->frente.frames < 30;
}

/* Um arrasto que ACABOU no painel de trás, em pixels de TELA. Devolve o eixo
   dominante: 1 se foi horizontal, 2 se vertical, 0 se não houve arrasto.

   O eixo dominante, e não os dois: atrás ninguém vê o dedo, e uma diagonal
   sem querer disparando as duas coisas de uma vez é indistinguível de um
   defeito. */
static int arrasto_tras(const Ui *u, int *dx, int *dy)
{
    *dx = 0; *dy = 0;
    if (!(u->tras.was_down && !u->tras.down && u->tras.moved)) return 0;
    int ax = u->tras.x - u->tras.start_x;
    int ay = u->tras.y - u->tras.start_y;
    if (abs(ax) >= abs(ay)) { *dx = ax; return 1; }
    *dy = ay; return 2;
}

static bool in_rect(int x, int y, float rx, float ry, float rw, float rh)
{
    return x >= rx && x < rx + rw && y >= ry && y < ry + rh;
}

bool ui_resting(const Ui *u) { return u && u->resting; }
/* ARRASTAR A BARRA NÃO BUSCAVA NADA. O deck marcava `scrubbing = false` no
   mesmo quadro em que emitia a ação 18, e esta função devolvia -1 justamente
   quando o main perguntava: `f >= 0` falhava e o player nunca era mandado.
   Na mão isso lê como "a barra é enfeite" — ela se movia sob o dedo, porque
   o desenho usa o scrub_to, e a música seguia de onde estava.
   Agora o valor SOBREVIVE à soltura, em scrub_pend, que é o que o main lê. */
float ui_scrub(const Ui *u)
{
    if (!u) return -1.0f;
    return u->scrubbing ? u->scrub_to : u->scrub_pend;
}

int ui_handle_input(Ui *u)
{
    static uint32_t prev = 0;
    static uint32_t held_dir = 0;
    static int held_frames = 0;

    SceCtrlData c;
    memset(&c, 0, sizeof(c));
    sceCtrlPeekBufferPositive(0, &c, 1);
    uint32_t cur = c.buttons;

    /* OS OMBROS DO VITA NÃO CHEGAM COMO L1/R1.

       SINTOMA, nas palavras do dono: "r1 and l1 dont do shit". E não faziam
       mesmo — nunca, em aparelho nenhum, desde sempre. O psp2common/ctrl.h
       diz na própria nota do enum:

         "Vita's L Trigger and R Trigger are mapped to L1 and R1 WHEN USING
          sceCtrlPeekBufferPositiveExt2 and sceCtrlReadBufferPositiveExt2"

       Este app lê com o sceCtrlPeekBufferPositive, o SEM Ext2. Por ele, o
       ombro esquerdo acende SCE_CTRL_LTRIGGER (0x100) e o direito
       SCE_CTRL_RTRIGGER (0x200). O código inteiro testava SCE_CTRL_L1
       (0x400) e SCE_CTRL_R1 (0x800), que só acendem para controle externo
       (PSTV, DS3/DS4). Ou seja: TODA tecla de ombro do app era letra morta —
       a fila de abas, as recomendações, as listas, a conta, o Qobuz e os três
       combos do deck (ouvir jogando, soneca, apagar a tela). Isso explica
       "qobuz simply doesn't exist" melhor que qualquer coisa: o único caminho
       até lá passava por um botão que não existia.

       Um comentário antigo aqui do lado já tinha chegado perto e concluído o
       contrário — que o Vita "não tem L2/R2 e o Peek nunca põe esse bit". Põe:
       SCE_CTRL_L2 É o LTRIGGER, o mesmo 0x100 do ombro esquerdo.

       Normalizar na ENTRADA, e não trocar 40 testes espalhados: assim o
       aparelho e um controle externo entram pelo mesmo lugar, e nada mais no
       arquivo precisa saber que existe essa diferença. */
    if (cur & SCE_CTRL_LTRIGGER) cur |= SCE_CTRL_L1;
    if (cur & SCE_CTRL_RTRIGGER) cur |= SCE_CTRL_R1;

    uint32_t edge = cur & ~prev;
    uint32_t solto = prev & ~cur;      /* botões que acabaram de ser LARGADOS */
    prev = cur;

    /* [R1] é MODIFICADOR no deck, e por isso a ação dele é na SOLTURA.
       Antes ele agia na apertada: no instante em que se segurava R1 a tela
       já pulava para as playlists, e os três atalhos que o próprio rodapé
       anuncia — R1+triângulo (ouvir jogando), R1+quadrado (soneca) e
       R1+L1 (apaga a tela) — eram IMPOSSÍVEIS de alcançar. Três recursos
       inteiros anunciados e mortos.
       Agora: segurar não faz nada; se soltar sem ter usado nenhum combo,
       aí sim vai para as playlists. */
    static int r1_usado = 0;
    if (edge & SCE_CTRL_R1) r1_usado = 0;

    /* de onde este quadro partiu — o passo de aba lá embaixo só vale se
       nada mais tiver trocado de tela antes */
    View view_no_inicio = u->view;

    /* ═══ INPUT LOCK (L1+R1, NESTA ORDEM) ═════════════════════════════
     *
     * R1+L1 (R1 primeiro) é "apaga a tela", do deck — documentado, testado.
     * L1+R1 (L1 primeiro) é a trava: congela tudo até repetir o gesto.
     * A ordem é a única coisa que separa os dois, e a tela de Controls
     * mostra "R1 + L1" num e "L1 + R1" no outro por esse motivo.
     *
     * Era por NÍVEL (as duas seguradas): no host, sem o anti-bounce que só
     * existe no Vita, cada quadro com as duas apertadas alternava a trava
     * — e travado o teste não navega, então o atalhos_test girava para
     * sempre a 100% nos `while` de navegação. Por BORDA não há repetição
     * em plataforma nenhuma: segurar não re-dispara. */
    if ((edge & SCE_CTRL_R1) && (cur & SCE_CTRL_L1)) {
        u->input_locked = !u->input_locked;
        r1_usado = 1;
        /* anti-bounce: espera o usuario soltar */
#ifdef __vita__
        while (1) {
            SceCtrlData temp;
            sceCtrlPeekBufferPositive(0, &temp, 1);
            if (!(temp.buttons & SCE_CTRL_L1) && !(temp.buttons & SCE_CTRL_R1)) break;
            sceKernelDelayThread(10000);
        }
#endif
    }
    if (u->input_locked) return 0;

    /* Com o teclado do sistema na frente, ele é o dono da entrada. Sem esta
       porta, o [X] que confirma o texto ALSO confirmava a faixa marcada
       atrás, e o [O] que cancela saía da tela junto — a pessoa digitava uma
       chave de API e voltava para a estante com um disco tocando.

       O `prev` já foi atualizado lá em cima, então nada fica "preso": ao
       fechar o teclado, o próximo quadro vê os botões no estado real. */
    if (ime_aberto()) {
        char txt[256];
        int r = ime_poll(txt, sizeof(txt));
        if (r == 1) {
            /* Qual tela pediu o teclado. Só uma pode estar esperando: o
               diálogo do sistema é único. */
            if (u->busca_pedida) {
                /* a precisão limita a LEITURA: o teclado devolve até 256
                   bytes e o termo guarda 48; sem ela o compilador avisa, com
                   razão, que a conta pode passar do buffer */
                snprintf(u->busca, sizeof(u->busca), "%.*s",
                         (int)sizeof(u->busca) - 1, txt);
                u->busca_suja = true;
                u->sel = 0;
                u->jump_open = false;   /* o resultado é a estante, não a régua */
            }
            else if (u->conta_campo >= 0)   conta_recebeu(u, u->conta_campo, txt);
            else if (u->qb_campo >= 0) qb_recebeu(u, u->qb_campo, txt);
        }
        if (r != 0) { u->conta_campo = -1; u->qb_campo = -1; u->busca_pedida = false; }
        memset(txt, 0, sizeof(txt));   /* pode ter sido uma senha */
        return 0;
    }
    /* O login foi pedido no quadro passado e o "signing in…" já apareceu: é
       agora que se fala com a internet. */
    if (u->conta_senha[0]) { conta_tenta_entrar(u); return 0; }
    if (u->qb_senha[0])    { qb_tenta_entrar(u); return 0; }

    /* ── A TROCA POR LOSSLESS, esperando a rede ────────────────────────

       ANTES da cadeia por tela, e não dentro do ramo do deck: a busca leva um
       ou dois segundos e a pessoa pode ter ido olhar a estante nesse meio
       tempo. Amarrada à tela em que ela começou, sair dali no segundo errado
       perderia a resposta — e um botão que às vezes responde e às vezes não é
       pior que um que nunca responde, porque não dá para aprender. */
    if (u->casando) {
        QobuzCasamento c;
        int est = 0;
        bool ativo = false;
        qobuz_casa_estado(&c, &est, &ativo);
        if (!ativo) {
            u->casando = false;
            if (est == 1) {
                /* DIZ QUAL GRAVAÇÃO ENTROU. Título e artista batem em toda
                   versão da mesma música — estúdio, acústica, quatro ao vivo;
                   o que a pessoa precisa conferir é se veio a que ela queria,
                   e quem responde isso é o ÁLBUM e a DURAÇÃO. */
                char dur[16] = "";
                if (c.segundos > 0)
                    snprintf(dur, sizeof(dur), "  %d:%02d",
                             c.segundos / 60, c.segundos % 60);
                snprintf(u->casa_msg, sizeof(u->casa_msg),
                         "from Qobuz: %.40s — %.28s%s%s",
                         c.album[0] ? c.album : c.titulo, c.artista, dur,
                         c.hires ? "  ·  24-bit" : "");
                u->casa_msg_ate = u->clock + 60 * 12;
                u->view = VIEW_DECK;
                return 25;               /* tocar a faixa casada */
            }
            snprintf(u->casa_msg, sizeof(u->casa_msg), "%.120s",
                     qobuz_motivo()[0] ? qobuz_motivo()
                                       : "nothing on Qobuz matched this track");
            u->casa_msg_ate = u->clock + 60 * 10;
        }
    }

    /* ── GET FLAC: abre_async terminou enquanto o usuário estava noutra tela ──

       O casamento (25) encontrou um album_id e lançou qobuz_abre_async.
       Quando a thread termina, aqui detectamos e devolvemos ação 28 para o
       main carregar as faixas. Sem isto, o resultado ficaria preso: o
       qb_abrindo só dispara na tela da loja, e o GET FLAC começou do deck. */
    if (qobuz_getflac_pending()) {
        bool ativo = false;
        int nfx = 0;
        qobuz_abre_estado(NULL, 0, &nfx, &ativo, NULL);
        if (!ativo) {
            u->view = VIEW_DECK;
            return 28;
        }
    }

    touch_read(u);

    /* No repouso, QUALQUER coisa acorda e nada mais acontece: senão a tecla
       que acorda também troca de disco no escuro. */
    if (u->resting) {
        if (edge || u->frente.down) { u->resting = false; u->rest_idle = 0; u->rest_skip = 0; }
        return 0;
    }
    if (edge || u->frente.down) u->rest_idle = 0;

    uint32_t dir_now = cur & DPAD;
    if (dir_now != held_dir) { held_dir = dir_now; held_frames = 0; }
    else if (dir_now) {
        held_frames++;
        if (held_frames > REPEAT_DELAY &&
            ((held_frames - REPEAT_DELAY) % REPEAT_EVERY) == 0)
            edge |= dir_now;
    }

    int action = 0;
    if (u->view == VIEW_SHELF && u->jump_open) {
        if (edge & SCE_CTRL_RIGHT) u->jump_letter++;
        if (edge & SCE_CTRL_LEFT)  u->jump_letter--;
        if (edge & SCE_CTRL_DOWN)  u->jump_letter += 9;
        if (edge & SCE_CTRL_UP)    u->jump_letter -= 9;
        if (u->jump_letter < 0) u->jump_letter = 0;
        if (u->jump_letter > 26) u->jump_letter = 26;
        if (edge & SCE_CTRL_TRIANGLE) u->jump_open = false;
        /* Limpar tem de ser UMA tecla. Sem isto, desfazer uma busca custava
           abrir a régua, abrir o teclado, apagar o que estava lá e confirmar
           — quatro passos para voltar ao estado normal do app, e um filtro
           do qual não se sai é uma estante quebrada. */
        if (edge & SCE_CTRL_CIRCLE) {
            if (u->busca[0]) { u->busca[0] = '\0'; u->busca_suja = true; u->sel = 0; }
            u->jump_open = false;
        }
        if (edge & SCE_CTRL_CROSS) { u->jump_open = false; action = 19; }
        /* A LETRA e o TERMO são a mesma pergunta em duas resoluções: "onde
           está isso na estante?". Por isso o teclado abre daqui, e não de um
           atalho novo na estante — a régua já é a tela de procurar. */
        if (edge & SCE_CTRL_SQUARE) {
            if (ime_abrir("search records, artists, songs", u->busca,
                          sizeof(u->busca) - 1, false) == 0)
                u->busca_pedida = true;
        }
        if (edge & SCE_CTRL_START) return -1;

        /* A RÉGUA ACEITA O DEDO.

           Ela desenha 27 células grandes, numa grade, com a letra escolhida
           acesa — a coisa mais parecida com um botão que este app tem. E
           ignorava o toque: a função voltava aqui antes de qualquer código
           de toque rodar. Uma tela cheia de alvos que não respondem ensina
           que a tela inteira não responde. Um toque marca a letra E vai,
           que é o que o dedo espera de uma grade assim. */
        if (tap_released(u)) {
            float bw = (SCRW - 2 * PAD_X) / 9.0f;
            for (int i = 0; i < 27; i++) {
                float x = PAD_X + (i % 9) * bw;
                float y = 140.0f + (i / 9) * 74.0f - 30.0f;
                if (!in_rect(u->frente.x, u->frente.y, x, y, bw - 8, 46))
                    continue;
                u->jump_letter = i;
                u->jump_open = false;
                action = 19;
                break;
            }
        }
        return action;
    }
    if (u->view == VIEW_SHELF) {
        if (edge & SCE_CTRL_DOWN)  { u->sel += SHELF_COLS; action = 1; }
        if (edge & SCE_CTRL_UP)    { if (u->sel >= SHELF_COLS) u->sel -= SHELF_COLS; action = 1; }
        if (edge & SCE_CTRL_RIGHT) { u->sel++; action = 1; }
        if (edge & SCE_CTRL_LEFT)  { if (u->sel > 0) u->sel--; action = 1; }
        /* SEM DISCO, O [X] NÃO LEVA A LUGAR NENHUM.

           Com a estante vazia ele mandava para o deck assim mesmo, o main
           tentava carregar o álbum 0 de 0, falhava, e a pessoa terminava
           num deck que diz "nothing on the platter" — de onde o [X] e o [O]
           também não fazem nada, porque não há o que pausar. Três teclas
           seguidas sem resposta, e a conclusão de quem está com o aparelho
           na mão é "as teclas não funcionam". Não era: era não haver disco.
           Ficar na estante deixa a tela que EXPLICA o vazio à vista. */
        if ((edge & SCE_CTRL_CROSS) && u->tem_disco) { u->view = VIEW_DECK; action = 2; }
        /* [O] LIMPA O FILTRO em vez de ser um segundo [X].

           Os dois botões faziam a mesma coisa — pôr o disco marcado —, e um
           botão que duplica outro é um botão perdido. Perdido justamente onde
           fazia falta: com a estante filtrada, a única forma de voltar aos 388
           discos era a instrução escrita na tela, "[square] then [O]", que é
           uma dança de duas teclas para desfazer uma. Agora [O] desfaz.

           Sem filtro em vigor ele não faz nada — e isso é de propósito: na
           estante não há para onde voltar, e um [O] que tocasse um disco sem
           querer é pior que um [O] que descansa. */
        if ((edge & SCE_CTRL_CIRCLE) && u->busca[0]) {
            ui_set_busca(u, "");
            action = 0;
        }
        /* [tri] leva ao que já está tocando SEM trocar de disco: o [tri] do
           deck volta para cá, e uma tecla que só funciona num sentido é
           metade de um caminho. */
        if ((edge & SCE_CTRL_TRIANGLE) && u->tem_disco) { u->view = VIEW_DECK; action = 0; }
        if (edge & SCE_CTRL_SELECT) action = 15;
        if (edge & SCE_CTRL_SQUARE) { u->jump_open = true; action = 0; }
    } else if (u->view == VIEW_RECS) {
        if (edge & SCE_CTRL_DOWN) { u->rec_sel++; action = 1; }
        if (edge & SCE_CTRL_UP)   { if (u->rec_sel > 0) u->rec_sel--; action = 1; }
        if (edge & SCE_CTRL_RIGHT) { u->rec_sel += 10; action = 1; }
        if (edge & SCE_CTRL_LEFT)  { u->rec_sel -= 10; if (u->rec_sel < 0) u->rec_sel = 0; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CROSS)    { u->view = VIEW_DECK; action = 11; }
        if (edge & SCE_CTRL_CIRCLE)   { u->view = VIEW_DECK; action = 11; }
    } else if (u->view == VIEW_PLAYLISTS) {
        bool armed_before = u->pl_armed;
        if (edge & SCE_CTRL_DOWN) { u->pl_sel++; action = 1; }
        if (edge & SCE_CTRL_UP)   { if (u->pl_sel > 0) u->pl_sel--; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CROSS)    { u->view = VIEW_DECK; action = 12; }
        if (edge & SCE_CTRL_CIRCLE)   { u->view = VIEW_DECK; action = 12; }
        if (edge & SCE_CTRL_SQUARE)   action = 13;

        /* AS PÍLULAS RESPONDEM AO DEDO.

           É para isso que elas existem: o [X] já tocava a lista, mas uma
           tecla que a tela não desenha não existe para quem está olhando.
           O alvo sai do mesmo `pl_pilula` que as desenha. */
        u->pl_botao = -1;
        if (u->nplists > 0) {
            UiListGeom lgp;
            ui_list_geom(SCRW, SCRH, &lgp);
            float painel_x = PAD_X + (SCRW - 2 * PAD_X) * 0.44f + 18.0f;
            for (int k = 0; k < 2; k++) {
                float bx, by, bw, bh;
                pl_pilula(k, painel_x, lgp.y0, &bx, &by, &bw, &bh);
                if (!in_rect(u->frente.x, u->frente.y, bx, by, bw, bh)) continue;
                u->pl_botao = k;
                if (tap_released(u)) {
                    u->view = VIEW_DECK;
                    action = (k == 0) ? 12 : 23;
                }
            }
        }
        /* Apagar era [R2], e foi para o [SELECT]. A razão escrita aqui antes
           estava ERRADA — dizia que o Peek "nunca põe esse bit". Põe: o
           SCE_CTRL_R2 É o RTRIGGER, o mesmo 0x200 do ombro direito. A razão
           certa é outra e continua valendo: agora o ombro direito é o [R1] que
           anda na fila de abas (ver a normalização na leitura), então apagar
           no [R2] seria a MESMA tecla física fazendo duas coisas. */
        if (edge & SCE_CTRL_SELECT) {
            if (u->pl_armed) { action = 17; u->pl_armed = false; }
            else u->pl_armed = true;
        }
        /* qualquer outra tecla desarma: confirmar tem que exigir a MESMA */
        if (armed_before && action && action != 17) u->pl_armed = false;
    } else if (u->view == VIEW_CONTA) {
        /* O DEDO ESCOLHE E ATIVA.

           Tocar numa linha marca a linha E dispara o mesmo caminho do [X].
           Ele SINTETIZA o botão em vez de repetir o que a ativação faz: o
           que acontece ao entrar numa conta, abrir o teclado ou sair mora
           logo abaixo, num lugar só, e uma segunda cópia aqui se separaria
           dela no primeiro ajuste.

           Antes destas linhas, um toque aqui caía no ramo das listas lá
           embaixo e ia para o deck TOCANDO uma playlist — mexer numa senha
           não pode tocar música. */
        if (tap_released(u)) {
            for (int i = 0; i < CC_N; i++) {
                float x, y, w, h;
                conta_linha(i, &x, &y, &w, &h);
                if (!in_rect(u->frente.x, u->frente.y, x, y, w, h)) continue;
                u->conta_sel = i;
                edge |= SCE_CTRL_CROSS;
                break;
            }
        }
        if (edge & SCE_CTRL_UP)   { if (--u->conta_sel < 0) u->conta_sel = CC_N - 1; action = 1; }
        if (edge & SCE_CTRL_DOWN) { if (++u->conta_sel >= CC_N) u->conta_sel = 0; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & (SCE_CTRL_CROSS | SCE_CTRL_CIRCLE)) {
            LastfmConfig *cf = &u->conta_cfg;
            int i = u->conta_sel;
            if (i == CC_ENTRAR) {
                if (!cf->username[0])
                    conta_diz(u, "enter the username first");
                else if (ime_abrir("last.fm password", "", 63, true) == 0)
                    u->conta_campo = CC_ENTRAR;
                else {
                    char m[96];
                    ime_falhou(m, sizeof(m));
                    conta_diz(u, m);
                }
            } else if (i == CC_SAIR) {
                if (cf->configured) {
                    /* Só a chave de sessão vai embora. As chaves de API
                       ficam: são da pessoa, custaram uma visita ao site, e
                       apagá-las junto transformaria "sign out" em "recomeçar do
                       zero". A FILA também fica — sair de uma conta não é
                       motivo para jogar escuta fora. */
                    cf->sk[0] = '\0';
                    cf->configured = false;
                    lastfm_config_save(cf, STYLUS_DATA_DIR);
                    conta_diz(u, "signed out — listening is still being recorded");
                }
            } else {
                static const char *TIT[] = { "last.fm API key",
                                             "API secret", "last.fm username" };
                const char *ini = i == CC_KEY ? cf->api_key
                                : i == CC_SECRET ? cf->api_secret : cf->username;
                if (ime_abrir(TIT[i], ini, 100, i == CC_SECRET) == 0)
                    u->conta_campo = i;
                else {
                    char m[96];
                    ime_falhou(m, sizeof(m));
                    conta_diz(u, m);
                }
            }
        }
    } else if (u->view == VIEW_QOBUZ && u->fonte == FONTE_SC) {
        /* ═══ A OUTRA FONTE ══════════════════════════════════════════════
         * Faixas soltas: não há disco para abrir, formato para escolher nem
         * download. Aperta-se e toca — e por isso a entrada daqui é curta.
         * Ver o `draw_soundcloud`, que é o outro lado desta tela. */
        ScTrack tr[SC_MAX_RES];
        int n = 0;
        bool ativo = false;
        sc_busca_estado(tr, SC_MAX_RES, &n, &ativo);

        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }

        if (!ativo) {
            if (edge & SCE_CTRL_UP)   { if (u->sc_sel > 0) u->sc_sel--; action = 1; }
            if (edge & SCE_CTRL_DOWN) { if (u->sc_sel + 1 < n) u->sc_sel++; action = 1; }

            /* O DEDO. É um Vita: uma lista que só responde ao d-pad é meia
               lista. O retângulo vem do `sc_linha`, o mesmo que desenha. */
            if (tap_released(u)) {
                for (int i = 0; i < n; i++) {
                    float y, h;
                    if (!sc_linha(i, &y, &h)) break;
                    if (!in_rect(u->frente.x, u->frente.y,
                                 PAD_X, y - 2.0f, SCRW - 2 * PAD_X, h - 6.0f))
                        continue;
                    /* tocar na linha JÁ escolhida toca a faixa; na outra,
                       escolhe — a mesma regra da estante */
                    if (u->sc_sel == i) { u->view = VIEW_DECK; return 27; }
                    u->sc_sel = i;
                    action = 1;
                    break;
                }
            }

            if (edge & SCE_CTRL_SQUARE) {
                if (ime_abrir("search SoundCloud", u->qb_termo, 90, false) == 0)
                    u->qb_campo = QC_SC;
                else {
                    /* um teclado que não abre TEM de dizer isso: foi um
                       `ime_abrir` sem `else` que deixou o [quadrado] mudo
                       por três versões */
                    char m[96];
                    ime_falhou(m, sizeof(m));
                    qb_diz(u, m);
                }
                action = 1;
            }
            if ((edge & SCE_CTRL_CROSS) && n > 0) { u->view = VIEW_DECK; return 27; }
        }
    } else if (u->view == VIEW_QOBUZ) {
        QobuzJob job;
        qobuz_job_estado(&job);
        QobuzConfig *qc = &u->qb_cfg;

        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }

        /* Streaming: o qobuz_abre_async está em curso. Enquanto não termina,
           ninguém aperta nada — a lista não existe ainda. Quando termina, a
           lista de faixas está pronta e o main monta a sessão. */
        if (u->qb_abrindo) {
            QobuzFaixa fx[64];
            int nfx = 0;
            bool ativo = false;
            qobuz_abre_estado(fx, 64, &nfx, &ativo, NULL);
            if (!ativo) {
                u->qb_abrindo = false;
                if (nfx > 0) {
                    /* VAI PARA O DECK, como toda outra ação de tocar. Sem
                       isto o disco começava a tocar e a tela continuava na
                       lista de busca — sem prato, sem agulha, sem nada
                       dizendo que tinha dado certo.

                       E devolve AGORA: o resto desta função ainda trata
                       UP/DOWN/SELECT, e qualquer um deles sobrescrevia o
                       `action` no mesmo quadro. O álbum abria, a ação era
                       trocada por "navigate", e o `qobuz_abre_limpa()` do main
                       nunca acontecia — o resultado seguinte vinha velho. */
                    u->view = VIEW_DECK;
                    return 22;      /* tocar da rede */
                }
                qb_diz(u, "could not open the record");
            }
        }

        if (job.ativo) {
            /* Baixando, só existe uma ação: parar. Qualquer outra tecla
               mexeria numa lista que a tela nem está mostrando. */
            if (edge & SCE_CTRL_CIRCLE) qobuz_job_cancela();
        } else if (job.ok || job.falhou) {
            /* Terminou: [O] limpa o resumo e volta à busca. Um novo download
               zera o estado, então basta começar outro. */
            if (edge & (SCE_CTRL_CIRCLE | SCE_CTRL_CROSS)) {
                bool valeu = job.ok;
                qobuz_job_limpa();
                u->qb_lida = false;     /* relê a config, que pode ter mudado */
                /* Deu certo? revarre, para o disco aparecer AGORA. "Baixei e
                   não está lá" é indistinguível de "o download falhou". */
                action = valeu ? 21 : 1;
            }
        } else if (!qc->configured) {
            /* mesma ideia da tela de conta: o toque marca a linha e sintetiza
               o [X], para a ativação continuar tendo um dono só */
            if (tap_released(u)) {
                for (int i = 0; i < QC_N; i++) {
                    float x, y, w, h;
                    qobuz_linha(i, &x, &y, &w, &h);
                    if (!in_rect(u->frente.x, u->frente.y, x, y, w, h)) continue;
                    u->qb_sel = i;
                    edge |= SCE_CTRL_CROSS;
                    break;
                }
            }
            if (edge & SCE_CTRL_UP)   { if (--u->qb_sel < 0) u->qb_sel = QC_N - 1; action = 1; }
            if (edge & SCE_CTRL_DOWN) { if (++u->qb_sel >= QC_N) u->qb_sel = 0; action = 1; }
            if (edge & (SCE_CTRL_CROSS | SCE_CTRL_CIRCLE)) {
                int i = u->qb_sel;
                if (i == QC_ENTRAR) {
                    if (!qc->app_id[0] || !qc->app_secret[0])
                        qb_diz(u, "enter the app_id and secret first");
                    else if (!qc->email[0])
                        qb_diz(u, "enter the e-mail first");
                    else if (ime_abrir("Qobuz password", "", 63, true) == 0)
                        u->qb_campo = QC_ENTRAR;
                    else {
                        char m[96];
                        ime_falhou(m, sizeof(m));
                        qb_diz(u, m);
                    }
                } else {
                    static const char *TIT[] = { "Qobuz app_id",
                                                 "secret (or secrets, comma separated)",
                                                 "account e-mail" };
                    const char *ini = i == QC_APPID ? qc->app_id
                                    : i == QC_SECRET ? qc->app_secret : qc->email;
                    if (ime_abrir(TIT[i], ini, 200, i == QC_SECRET) == 0)
                        u->qb_campo = i;
                    else {
                        char m[96];
                        ime_falhou(m, sizeof(m));
                        qb_diz(u, m);
                    }
                }
            }
        } else {
            /* AS BUSCAS RECENTES. Só existem quando não há resultado na tela
               (é o que o desenho decide, e o `qb_nrec_vis` conta) — então
               esquerda/direita e o dedo só as alcançam nesse estado, e não
               competem com nada.

               Repetir a busca de ontem passou a ser um toque em vez de
               redigitar o termo inteiro num teclado de aparelho na mão. */
            if (u->qb_nrec_vis > 0 || u->qb_nart_vis > 0) {
                /* DUAS FILEIRAS DE SUGESTÃO, UMA MARCA SÓ.

                   Em cima as buscas recentes, embaixo a grade de artistas que
                   a pessoa já tem. `qb_art_sel < 0` quer dizer "estou nas de
                   cima" — assim não há dois cursores acesos ao mesmo tempo,
                   que é o defeito que faz o [X] fazer a coisa da outra
                   fileira. */
                int col = QB_ART_COLS;
                if (u->qb_art_sel < 0) {
                    if (u->qb_nrec_vis > 0) {
                        if (edge & SCE_CTRL_LEFT) {
                            if (--u->qb_rec_sel < 0) u->qb_rec_sel = u->qb_nrec_vis - 1;
                            action = 1;
                        }
                        if (edge & SCE_CTRL_RIGHT) {
                            if (++u->qb_rec_sel >= u->qb_nrec_vis) u->qb_rec_sel = 0;
                            action = 1;
                        }
                    }
                    if ((edge & SCE_CTRL_DOWN) && u->qb_nart_vis > 0) {
                        u->qb_art_sel = 0; action = 1;
                    }
                } else {
                    if (edge & SCE_CTRL_LEFT)  { if (u->qb_art_sel > 0) u->qb_art_sel--; action = 1; }
                    if (edge & SCE_CTRL_RIGHT) { if (u->qb_art_sel + 1 < u->qb_nart_vis) u->qb_art_sel++; action = 1; }
                    if (edge & SCE_CTRL_DOWN) {
                        if (u->qb_art_sel + col < u->qb_nart_vis) u->qb_art_sel += col;
                        action = 1;
                    }
                    if (edge & SCE_CTRL_UP) {
                        /* da primeira fileira da grade sobe para as recentes;
                           sem esta saída a grade seria uma sala sem porta */
                        if (u->qb_art_sel >= col) u->qb_art_sel -= col;
                        else u->qb_art_sel = -1;
                        action = 1;
                    }
                }

                /* O QUE O [X] VAI BUSCAR — um lugar só decide, e é o mesmo
                   que o dedo alimenta logo abaixo. */
                const char *termo = NULL;
                if (u->qb_art_sel >= 0 && u->qb_art_sel < g_qb_nart)
                    termo = g_qb_art[u->qb_art_sel];
                else if (u->qb_rec_sel >= 0 && u->qb_rec_sel < g_qb_nrec)
                    termo = g_qb_rec[u->qb_rec_sel].t;

                bool tocou = false;
                if (tap_released(u)) {
                    for (int i = 0; i < u->qb_nrec_vis; i++) {
                        float x, y, w, h;
                        if (!qb_rec_pilula(u, i, &x, &y, &w, &h)) break;
                        if (!in_rect(u->frente.x, u->frente.y,
                                     x, y - 8.0f, w, h + 16.0f)) continue;
                        u->qb_rec_sel = i;
                        u->qb_art_sel = -1;
                        termo = g_qb_rec[i].t;
                        tocou = true;
                        break;
                    }
                    for (int i = 0; !tocou && i < u->qb_nart_vis; i++) {
                        float x, y, w, h;
                        if (!qb_art_pilula(i, &x, &y, &w, &h)) break;
                        if (!in_rect(u->frente.x, u->frente.y, x, y, w, h)) continue;
                        u->qb_art_sel = i;
                        termo = g_qb_art[i];
                        tocou = true;
                        break;
                    }
                }
                if ((tocou || ((edge & SCE_CTRL_CROSS) && u->qb_nres <= 0))
                    && termo && termo[0]) {
                    snprintf(u->qb_termo, sizeof(u->qb_termo), "%.*s",
                             (int)sizeof(u->qb_termo) - 1, termo);
                    u->qb_sel = 0;
                    qb_recentes_poe(u->qb_termo);
                    qobuz_busca_async(qc, u->qb_termo);
                    action = 1;
                }
            }
            if (edge & SCE_CTRL_UP)   { if (u->qb_sel > 0) u->qb_sel--; action = 1; }
            if (edge & SCE_CTRL_DOWN) { if (u->qb_sel + 1 < u->qb_nres) u->qb_sel++; action = 1; }
            if (edge & SCE_CTRL_SQUARE) {
                if (ime_abrir("search Qobuz", u->qb_termo, 90, false) == 0)
                    u->qb_campo = QC_N;
                else {
                    char m[96];
                    ime_falhou(m, sizeof(m));
                    qb_diz(u, m);
                }
            }
            if (edge & SCE_CTRL_SELECT) {
                /* Cicla o formato. Fica guardado: quem escolheu MP3 uma vez
                   porque o cartão é pequeno não quer reescolher a cada disco. */
                qc->formato = qc->formato == QB_MP3 ? QB_FLAC
                            : qc->formato == QB_FLAC ? QB_HIRES : QB_MP3;
                qobuz_config_save(qc, STYLUS_DATA_DIR);
                action = 1;
            }
            if ((edge & SCE_CTRL_CROSS) && u->qb_nres > 0 &&
                u->qb_sel < u->qb_nres) {
                if (qobuz_baixa_album(qc, &u->qb_res[u->qb_sel], qc->formato,
                                      STYLUS_OWN_MUSIC) != 0)
                    qb_diz(u, "could not start the download");
            }
            /* CIRCLE: tocar direto da rede, sem baixar. O disco experimental
               que talvez não valha 400 MB de cartão — ouvir agora, sem esperar. */
            if ((edge & SCE_CTRL_CIRCLE) && u->qb_nres > 0 &&
                u->qb_sel < u->qb_nres && !u->qb_abrindo) {
                if (qobuz_abre_async(qc, &u->qb_res[u->qb_sel]) == 0) {
                    u->qb_abrindo = true;
                    u->qb_ab_alb = u->qb_res[u->qb_sel];
                } else {
                    qb_diz(u, "could not open the record");
                }
            }
        }
    } else if (u->view == VIEW_HOME) {
        /* A home é uma fila de capas: esquerda/direita anda, [X] toca.
           A primeira posição é o "continuar"; as outras duas faixas vêm
           depois dela na mesma numeração. */
        const int NHOME = 1 + HOME_FILA * 2;
        if (edge & SCE_CTRL_RIGHT) { if (u->home_sel + 1 < NHOME) u->home_sel++; action = 1; }
        if (edge & SCE_CTRL_LEFT)  { if (u->home_sel > 0) u->home_sel--; action = 1; }
        if (edge & SCE_CTRL_DOWN)  { u->home_sel = (u->home_sel < 1) ? 1
                                                 : (u->home_sel < 1 + HOME_FILA
                                                    ? u->home_sel + HOME_FILA
                                                    : u->home_sel);
                                     if (u->home_sel >= NHOME) u->home_sel = NHOME - 1;
                                     action = 1; }
        if (edge & SCE_CTRL_UP)    { u->home_sel = (u->home_sel >= 1 + HOME_FILA)
                                                 ? u->home_sel - HOME_FILA : 0;
                                     action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        /* ═══ SHUFFLE DESDE A HOME ═══════════════════════════════════════════
           Square: embaralha TODAS as faixas da coleção (átomo).
           Circle: embaralha OS DISCOS — cada disco toca inteiro, mas a
           ordem dos discos é aleatória. Dois modos de não escolher. */
        if (edge & SCE_CTRL_SQUARE)  action = 30;
        if (edge & SCE_CTRL_CIRCLE)  action = 31;
        /* Tocar o que está marcado é a MESMA ação de tocar na estante: a home
           marca um álbum e manda a estante abri-lo, em vez de ter um segundo
           caminho para começar um disco. */
        if ((edge & SCE_CTRL_CROSS) && u->home_alvo >= 0) {
            u->sel = u->home_alvo;
            u->busca[0] = '\0';
            u->busca_suja = true;
            u->view = VIEW_DECK;
            action = 2;
        }
    } else if (u->view == VIEW_ARTISTAS) {
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (g_art_n > 0) {
            if (edge & SCE_CTRL_RIGHT) { if (u->art_sel + 1 < g_art_n) u->art_sel++; action = 1; }
            if (edge & SCE_CTRL_LEFT)  { if (u->art_sel > 0) u->art_sel--; action = 1; }
            if (edge & SCE_CTRL_DOWN)  { u->art_sel += ART_COLS;
                                         if (u->art_sel >= g_art_n) u->art_sel = g_art_n - 1;
                                         action = 1; }
            if (edge & SCE_CTRL_UP)    { u->art_sel -= ART_COLS;
                                         if (u->art_sel < 0) u->art_sel = 0;
                                         action = 1; }
            /* ABRIR UM ARTISTA É FILTRAR A ESTANTE POR ELE.

               Não há tela nova: o filtro da estante já casa por artista OU
               por disco (ver filtro_remonta), e a estante já sabe desenhar
               uma lista filtrada. Uma tela a mais aqui seria uma segunda
               forma de mostrar discos, com os mesmos defeitos para consertar
               duas vezes. */
            if (edge & SCE_CTRL_CROSS) {
                snprintf(u->busca, sizeof(u->busca), "%.*s",
                         (int)sizeof(u->busca) - 1, g_art[u->art_sel].nome);
                u->busca_suja = true;
                u->sel = 0;
                u->view = VIEW_SHELF;
                action = 1;
            }
        }
    } else if (u->view == VIEW_AJUSTES) {
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_UP)   { if (--u->aj_sel < 0) u->aj_sel = AJ_N - 1; action = 1; }
        if (edge & SCE_CTRL_DOWN) { if (++u->aj_sel >= AJ_N) u->aj_sel = 0; action = 1; }
        /* O dedo marca a linha E já muda o valor. Numa tela de duas opções,
           exigir "toque para marcar, aperte para confirmar" é uma etapa a
           mais para nada — e é o mesmo que a tela de conta já faz. */
        if (tap_released(u)) {
            for (int i = 0; i < AJ_N; i++) {
                float x, y, w, h;
                ajuste_linha(i, &x, &y, &w, &h);
                if (!in_rect(u->frente.x, u->frente.y, x, y, w, h)) continue;
                u->aj_sel = i;
                edge |= SCE_CTRL_CROSS;
                break;
            }
        }
        if (edge & SCE_CTRL_CROSS) {
            if (u->aj_sel == AJ_TEMA) {
                g_tema = (g_tema + 1) % N_TEMAS;
                /* o véu vai assado no borrão com a cor do tema: trocar de
                   tema aposenta todos os borrões, que se refazem sozinhos
                   um por quadro. Pela fila de mortos, como qualquer despejo. */
                for (int bi = 0; bi < COVER_CACHE; bi++)
                    if (u->cache[bi].blur) {
                        tex_matar(u->cache[bi].blur);
                        u->cache[bi].blur = NULL;
                        u->cache[bi].blur_tentado = false;
                    }
            }
            else if (u->aj_sel == AJ_MIDIA)     u->midia = (u->midia + 1) % MIDIA_N;
            else if (u->aj_sel == AJ_TRASEIRA)  u->toque_tras = !u->toque_tras;
            else if (u->aj_sel == AJ_FUNDO)     u->bg_trava = !u->bg_trava;
            else if (u->aj_sel == AJ_FONTE)     u->fonte = (u->fonte + 1) % FONTE_N;
            else if (u->aj_sel == AJ_CONTROLES) u->view = VIEW_CONTROLES;
            /* a soneca é do PLAYER e depende do disco (o "fim do lado" só
               existe se o álbum tiver lados): quem sabe disso é o main */
            action = (u->aj_sel == AJ_SONECA) ? 20 : 1;
        }
    } else if (u->view == VIEW_CONTROLES) {
        /* qualquer tecla de "voltar" serve: é uma tela de leitura */
        if (edge & (SCE_CTRL_TRIANGLE | SCE_CTRL_CIRCLE | SCE_CTRL_CROSS))
            { u->view = VIEW_AJUSTES; action = 1; }
    } else if (u->view == VIEW_HANDOFF) {
        /* O INTERRUPTOR DO 2º PLANO. [] liga e desliga, e o dedo também —
           é a tela em que a pergunta é feita, então é onde a resposta mora.
           Vem ANTES das teclas de voltar: senão um [] sairia da tela. */
        bool virou = (edge & SCE_CTRL_SQUARE) != 0;
        if (!virou && u->hoff_w > 0.0f && tap_released(u) &&
            in_rect(u->frente.x, u->frente.y,
                    u->hoff_x, u->hoff_y - 6.0f, u->hoff_w, u->hoff_h + 12.0f))
            virou = true;
        if (virou) {
            u->bg_trava = !u->bg_trava;
            /* quem aplica a trava de verdade é o main, lendo este campo */
            return 1;
        }
        if (edge & (SCE_CTRL_TRIANGLE | SCE_CTRL_CIRCLE | SCE_CTRL_CROSS)) {
            u->view = VIEW_DECK;
            action = 0;
        }
        if (edge & SCE_CTRL_START) action = -1;
        return action;
    } else { /* deck */
        if (edge & SCE_CTRL_TRIANGLE) {
            /* com [R1] segurado, a tela do "ouvir enquanto joga" */
            if (cur & SCE_CTRL_R1) { u->view = VIEW_HANDOFF; action = 0; r1_usado = 1; }
            else { u->view = VIEW_SHELF; action = 10; }
        }
        if (edge & SCE_CTRL_CIRCLE)   action = 4;
        if (edge & SCE_CTRL_CROSS)    action = 4;
        if (edge & SCE_CTRL_RIGHT)    action = 5;
        if (edge & SCE_CTRL_LEFT)     action = 6;
        if (edge & SCE_CTRL_UP)       action = 16;
        if (edge & SCE_CTRL_DOWN)     action = 7;
        /* [quad] alterna letra ↔ ordem do lado. Era um segundo "seek -10s",
           duplicando o [baixo] — uma tecla gasta em nada. */
        /* [quad] alterna letra ↔ ordem do lado; com [R1] segurado, cicla a
           soneca. Uma tecla que a tela desenha e não anuncia não existe, e
           as duas estão escritas no rodapé. */
        if (edge & SCE_CTRL_SQUARE) {
            if (cur & SCE_CTRL_R1) { action = 20; r1_usado = 1; }
            else u->show_lyrics = !u->show_lyrics;
        }
        if (edge & SCE_CTRL_SELECT)   action = 14;
        /* [R1] segurado + [L1]: apaga a tela e continua tocando. Duas teclas
           porque uma sozinha se aperta no bolso. */
        if ((edge & SCE_CTRL_L1) && (cur & SCE_CTRL_R1)) {
            r1_usado = 1;
            u->resting = true;
            u->view = VIEW_DECK;
            action = 0;
        }

        /* ── TOCAR A VERSÃO LOSSLESS DESTA MÚSICA ──────────────────────
           O jeito de chamar é TOCAR A PÍLULA, que está desenhada na linha
           do sinal. [R1]+[O] existe como atalho para quem já sabe — o Vita
           não tem L2/R2 de verdade, e o R1 já é o modificador do deck
           (R1+△, R1+□, R1+L1), então ele entra na convenção que existe em
           vez de inventar uma segunda. Está escrito na tela de Controls:
           tecla que a tela não anuncia não existe. */
        {
            bool pediu = false;
            if ((edge & SCE_CTRL_CIRCLE) && (cur & SCE_CTRL_R1)) {
                pediu = true; r1_usado = 1;
                action = 0;      /* o [O] solto é play/pause; segurado, não */
            }
            if (u->casa_w > 0.0f && tap_released(u) &&
                in_rect(u->frente.x, u->frente.y,
                        u->casa_x - 6.0f, u->casa_y - 8.0f,
                        u->casa_w + 12.0f, u->casa_h + 16.0f))
                pediu = true;
            if (pediu && !u->casando) action = 24;
        }
    }
    if (edge & SCE_CTRL_START) action = -1;

    /* ---------- L1 / R1: ANDAR NA FILA DE ABAS ----------

       Um lugar só, e vale em toda tela. Antes cada tela tinha o seu par de
       saltos — na estante o R1 ia para as listas, nas listas ia para a conta,
       na conta ia para o Qobuz — e o resultado era um anel que só se conhecia
       decorando. Ver a nota da fila de abas lá em cima.

       Roda DEPOIS do trecho por tela, de propósito: no deck o R1 é
       modificador (R1+△ ouvir jogando, R1+□ soneca, R1+L1 apaga a tela), e
       esses combos precisam ter a chance de marcar `r1_usado` primeiro. Por
       isso o R1 age na SOLTURA — segurar não navega.

       E só anda se a tela ainda for a mesma: um △ que já levou ao deck não
       pode ganhar um passo de aba por cima. */
    {
        int ia = aba_de(u->view);
        if (ia >= 0 && u->view == view_no_inicio) {
            if ((edge & SCE_CTRL_L1) && !(cur & SCE_CTRL_R1)) {
                u->view = ABAS[(ia + UI_NABAS - 1) % UI_NABAS];
                action = 0;
            } else if ((solto & SCE_CTRL_R1) && !r1_usado &&
                       !(cur & SCE_CTRL_L1)) {
                u->view = ABAS[(ia + 1) % UI_NABAS];
                action = 0;
            }
        }
    }

    /* ---------- o toque ----------
       O Vita tem uma tela sensível ao toque e o app inteiro a ignorava: pôr
       um disco era navegar uma grade com o direcional, item por item, com a
       coisa desenhada bem ali. */
    /* A ALMOFADA DE TRÁS. Ela fica exatamente onde os dedos já estão para
       segurar o aparelho, e é por isso que ela só entende ARRASTO: um toque
       ali não é uma intenção, é a mão. E é por isso também que ela nunca
       ACIONA nada — só NAVEGA. O pior resultado possível de um encosto sem
       querer é virar uma página; nunca pôr um disco ou apagar uma lista. */
    int tras_dx = 0, tras_dy = 0;
    arrasto_tras(u, &tras_dx, &tras_dy);

    /* O DEDO NA FILA DE ABAS. É um Vita: a fila está desenhada bem ali, e
       exigir dois toques de L1 para chegar ao Qobuz quando ele está escrito
       na tela seria desenhar um botão que não é botão.

       O alvo vai do topo da tela até o filete — bem mais alto que a palavra,
       porque o alvo do dedo não é o tamanho da letra. */
    if (tap_released(u) && u->frente.y < HEAD_Y + 20) {
        for (int i = 0; i < UI_NABAS; i++) {
            if (!in_rect(u->frente.x, u->frente.y,
                         u->aba_x[i] - 10.0f, 0.0f,
                         u->aba_w[i] + 20.0f, (float)HEAD_Y + 20.0f))
                continue;
            u->view = ABAS[i];
            action = 0;
            break;
        }
    }

    if (u->view == VIEW_SHELF) {
        UiShelfGeom g;
        ui_shelf_geom(SCRW, SCRH, &g);
        /* de lado vira a página, para cima e para baixo anda uma fileira —
           tudo isso SEM cobrir a arte com o polegar, que é o ponto de uma
           estante de capas */
        if (tras_dx < -TRAS_PAGINA) { u->sel += UI_SHELF_PAGE; action = 1; }
        else if (tras_dx > TRAS_PAGINA) {
            u->sel -= UI_SHELF_PAGE;
            if (u->sel < 0) u->sel = 0;
            action = 1;
        } else if (tras_dy < -TRAS_FILEIRA) {
            u->sel -= UI_SHELF_COLS;
            if (u->sel < 0) u->sel = 0;
            action = 1;
        } else if (tras_dy > TRAS_FILEIRA) {
            u->sel += UI_SHELF_COLS;
            action = 1;
        }
        if (tap_released(u)) {
            for (int r = 0; r < UI_SHELF_ROWS; r++)
                for (int cix = 0; cix < UI_SHELF_COLS; cix++) {
                    float x = g.x0 + cix * (g.card_w + g.gap);
                    float y = g.y0 + r * (g.card_h + g.gap);
                    if (!in_rect(u->frente.x, u->frente.y, x, y, g.card_w, g.card_h))
                        continue;
                    int idx = (u->sel / UI_SHELF_PAGE) * UI_SHELF_PAGE
                              + r * UI_SHELF_COLS + cix;
                    u->sel = idx;
                    u->view = VIEW_DECK;
                    action = 2;
                }
        } else if (u->frente.was_down && !u->frente.down && u->frente.moved) {
            /* arrastar de lado vira página; a grade é paginada, não rolada */
            int dx = u->frente.x - u->frente.start_x;
            if (dx < -60) { u->sel += UI_SHELF_PAGE; action = 1; }
            else if (dx > 60) { u->sel -= UI_SHELF_PAGE; if (u->sel < 0) u->sel = 0; action = 1; }
        }
    } else if (u->view == VIEW_DECK) {
        UiDeckGeom g;
        ui_deck_geom(SCRW, SCRH, &g);
        /* arrastar a barra busca: enquanto o dedo estiver nela, o main lê o
           ui_scrub() e manda o player. Soltar confirma. */
        float bx = g.text_x, bw = g.text_w;
        float band_y = g.bar_y - 14, band_h = g.bar_h + 28;

        /* O CUE PELA ALMOFADA DE TRÁS.

           Atrás do prato é onde a mão de quem toca disco encosta para
           empurrar o vinil, e aqui é literalmente atrás: a almofada fica nas
           costas do aparelho, embaixo do desenho do disco. Arrastar ali anda
           na faixa.

           O deslocamento é RELATIVO ao ponto onde o dedo pousou, não
           absoluto como na barra: atrás não há nada para ver, e uma busca
           absoluta seria pedir para adivinhar onde o dedo caiu. A tela
           inteira de arrasto vale CUE_SEGUNDOS — fino o bastante para achar
           o começo de um verso, que é o que a barra não dá.

           Quem manda continua sendo a barra: se o dedo da frente já está
           arrastando, o de trás não entra. Dois donos do mesmo valor seriam
           dois seeks brigando por quadro. */
        if (u->tras.down && u->tras.moved && u->dur > 0 &&
            (u->cue_tras || !u->scrubbing)) {
            if (!u->cue_tras) { u->cue_tras = true; u->cue_base = u->prog; }
            float dx = (float)(u->tras.x - u->tras.start_x);
            float f = u->cue_base +
                      (dx / (float)SCRW) * (CUE_SEGUNDOS / (float)u->dur);
            if (f < 0) f = 0;
            if (f > 1) f = 1;
            u->scrubbing = true;
            u->scrub_to = f;
        } else if (u->cue_tras && !u->tras.down) {
            u->cue_tras = false;
            u->scrubbing = false;
            u->scrub_pend = u->scrub_to;
            action = 18;
        } else if (u->frente.down && (u->scrubbing ||
            in_rect(u->frente.start_x, u->frente.start_y, bx, band_y, bw, band_h))) {
            u->scrubbing = true;
            float f = ((float)u->frente.x - bx) / (bw > 1 ? bw : 1);
            if (f < 0) f = 0;
            if (f > 1) f = 1;
            u->scrub_to = f;
        } else if (u->scrubbing && !u->frente.down) {
            u->scrubbing = false;
            /* o valor precisa SOBREVIVER a este quadro: é agora que o main
               vai perguntar, e o ui_scrub já não pode dizer "ninguém está
               arrastando" (ver ui_scrub) */
            u->scrub_pend = u->scrub_to;
            action = 18;                     /* confirma a busca */
        } else if (tap_released(u)) {
            /* os três botões primeiro: eles ficam POR CIMA da faixa do disco
               em telas baixas, e quem desenha por cima recebe o toque */
            int botao = -1;
            for (int i = 0; i < 3; i++) {
                /* `btx` e não `bx`: o `bx` de fora é o começo da BARRA de
                   progresso, e ter os dois com o mesmo nome no mesmo escopo é
                   como se pega o retângulo errado sem o compilador reclamar. */
                float btx = g.cx + (float)(i - 1) * g.tr_gap;
                float dbx = (float)u->frente.x - btx;
                float dby = (float)u->frente.y - g.tr_y;
                if (dbx * dbx + dby * dby < g.tr_toque * g.tr_toque) botao = i;
            }
            if (botao >= 0) {
                u->tr_aceso = botao;
                u->tr_pisca = 8;         /* o dedo precisa VER que pegou */
                action = (botao == 0) ? 6 : (botao == 1) ? 4 : 5;
            } else {
                float dx = (float)u->frente.x - g.cx, dy = (float)u->frente.y - g.cy;
                if (dx * dx + dy * dy < g.r * g.r) {
                    action = 4;                       /* o disco: pausa */
                } else {
                    /* A LISTA DE FAIXAS, que agora é alvo. Um toque numa linha
                       PÕE aquela faixa — a alternativa era apertar [direita]
                       dezenove vezes com as faixas escritas ali do lado.

                       A faixa do alvo é a linha inteira mais meio passo para
                       cada lado: a linha tem 24 px de altura e uma ponta de
                       dedo mira uns 6 mm, então mirar o texto seria mirar
                       metade do que se acerta. */
                    for (int k = 0; k < u->deck_nlin; k++) {
                        if (u->frente.x < g.text_x - 8.0f) break;   /* é o lado do disco */
                        float ly = u->deck_lin_y[k];
                        if ((float)u->frente.y < ly - g.list_step * 0.75f) continue;
                        if ((float)u->frente.y > ly + g.list_step * 0.35f) continue;
                        u->deck_alvo = u->deck_lin_i[k];
                        action = 26;                  /* pula para esta faixa */
                        break;
                    }
                }
            }
        } else if (u->frente.was_down && !u->frente.down && u->frente.moved &&
                   !u->scrubbing) {
            int dx = u->frente.x - u->frente.start_x;
            if (dx < -70) action = 5;
            else if (dx > 70) action = 6;
        }
    } else if (u->view == VIEW_RECS || u->view == VIEW_PLAYLISTS) {
        /* AS DUAS LISTAS, nomeadas. Este ramo era um `else` solto, e por isso
           pegava também a CONTA e o QOBUZ — que não são listas de disco e não
           têm toque nenhum de propósito. Um toque no formulário do last.fm
           caía no braço de baixo, punha VIEW_DECK e disparava a ação 12: a
           tela pulava para o deck TOCANDO uma playlist. Mexer numa senha não
           pode tocar música. */
        UiListGeom lg;
        ui_list_geom(SCRW, SCRH, &lg);
        /* nas listas a almofada anda também: é a mesma mão, o mesmo gesto —
           de lado uma página, para cima e para baixo uma linha */
        int passo = 0;
        if (tras_dx < -TRAS_PAGINA)      passo =  lg.rows;
        else if (tras_dx > TRAS_PAGINA)  passo = -lg.rows;
        else if (tras_dy < -TRAS_FILEIRA) passo = -1;
        else if (tras_dy > TRAS_FILEIRA)  passo =  1;
        if (passo) {
            if (u->view == VIEW_RECS) u->rec_sel += passo;
            else                      u->pl_sel  += passo;
            action = 1;
        }
        if (tap_released(u)) {
            for (int r = 0; r < lg.rows; r++) {
                float y = lg.y0 + r * lg.row_h;
                if (!in_rect(u->frente.x, u->frente.y, lg.x, y, lg.w, lg.row_h)) continue;
                if (u->view == VIEW_RECS) {
                    u->rec_sel = (u->rec_sel / lg.rows) * lg.rows + r;
                    u->view = VIEW_DECK;
                    action = 11;
                } else {
                    u->pl_sel = (u->pl_sel / lg.rows) * lg.rows + r;
                    u->view = VIEW_DECK;
                    action = 12;
                }
            }
        }
    }

    if (u->sel < 0) u->sel = 0;
    if (u->rec_sel < 0) u->rec_sel = 0;
    if (u->pl_sel < 0) u->pl_sel = 0;
    return action;
}

/* ---------- vida ---------- */

Ui *ui_create(void)
{
    Ui *u = calloc(1, sizeof(*u));
    if (!u) return NULL;
    /* zero é uma FAIXA VÁLIDA: sem isto, um main que lesse o alvo sem a ação
       26 ter acontecido receberia "a primeira" em vez de "nenhuma" */
    u->deck_alvo = -1;
    /* A FONTE, EM GRUPO — e é por isso que "coração" mostrava "cora?ão".

       O `vita2d_load_default_pvf()` abre UMA fonte do sistema, e ela não
       cobre o latim acentuado. Glifo que falta não fica em branco no PVF: o
       scePvf desenha o "alt character", que por padrão é '?'. Era esse o
       ponto de interrogação no meio das palavras — não era tag estragada nem
       UTF-8 mal lido (o `tela_texto` já trata os dois, e de propósito NUNCA
       troca nada por '?').

       Carregar em GRUPO resolve: o latim atende tudo abaixo de U+2E80 (que é
       onde moram ã, ç, é, ü…) e o japonês atende o resto, para um título em
       CJK continuar tendo chance de aparecer. Se o grupo falhar, cai na
       fonte antiga em vez de ficar sem fonte nenhuma. */
    u->font = vita2d_load_system_pvf(2, FONTES_DA_TELA);
    if (!u->font) u->font = vita2d_load_default_pvf();
    if (!u->font) { free(u); return NULL; }
    pvf_filtro_linear(u->font);
    u->tem_disco = true;
    u->deck_stage = "boot";
    u->view = VIEW_SHELF;
    /* -1 = "nenhum campo esperando o teclado". O calloc deixa 0, que é um
       campo VÁLIDO (a chave de API, o app_id) — sem isto, o primeiro texto
       digitado em qualquer tela cairia na primeira linha da outra. */
    u->conta_campo = -1;
    u->qb_campo = -1;
    /* -1 = a marca começa nas buscas RECENTES, não na grade de artistas. O
       calloc deixaria 0, que é o primeiro artista — e aí o [X] de quem nunca
       buscou nada faria a busca errada. */
    u->qb_art_sel = -1;
    u->scrub_pend = -1.0f;
    u->tr_aceso = -1;
#ifdef __vita__
    sceRtcGetCurrentTick(&u->gpu_t0);
#endif
    touch_setup();
    return u;
}

void ui_destroy(Ui *u)
{
    if (!u) return;
    cache_clear(u);
    qb_capas_esquece();
    tex_cemiterio_esvazia();
    free(u->vis);
    if (u->font) vita2d_free_pvf(u->font);
    free(u);
}

int ui_selected(const Ui *u)
{
    /* O índice REAL da biblioteca. Fora daqui ninguém sabe que existe filtro,
       e é por isso que o main não precisou mudar uma linha. */
    if (!u) return 0;
    if (u->busca[0] && u->vis && u->sel >= 0 && u->sel < u->nvis)
        return u->vis[u->sel];
    return u->sel;
}
int ui_playlist_idx(const Ui *u)  { return u ? u->pl_sel : 0; }
int ui_rec_idx(const Ui *u)       { return u ? u->rec_sel : 0; }
int ui_jump_letter(const Ui *u)   { return u ? u->jump_letter : 0; }
void ui_set_sel(Ui *u, int i)     { if (u) u->sel = i < 0 ? 0 : i; }
QobuzConfig *ui_qobuz_cfg(Ui *u)  { return u ? &u->qb_cfg : NULL; }

/* PARA O PREVIEW, e só. A tela da loja relê o `qobuz.config` do cartão na
   primeira vez que é desenhada, o que no PC apaga qualquer conta de mentira
   e faz a foto sair sempre do formulário de configuração — a tela que a
   pessoa vê UMA vez na vida, no lugar da que ela usa sempre. É a mesma
   lição das duas lojas medidas vazias: uma foto do estado inicial não é uma
   foto da tela. */
void ui_qobuz_finge_conta(Ui *u)
{
    if (!u) return;
    u->qb_lida = true;
}

int ui_deck_alvo(const Ui *u) { return u ? u->deck_alvo : -1; }

void ui_set_casando(Ui *u, bool on)
{
    if (!u) return;
    u->casando = on;
    if (on) {
        /* O recado velho SAI ao começar uma busca nova. Sem isto, o "nothing
           matched" da tentativa anterior fica na tela enquanto a seguinte
           procura — e ler um fracasso ao lado de um "looking…" é a tela
           dizendo duas coisas contrárias ao mesmo tempo. */
        u->casa_msg[0] = '\0';
    }
}

void ui_diz_casa(Ui *u, const char *msg)
{
    if (!u || !msg) return;
    snprintf(u->casa_msg, sizeof(u->casa_msg), "%.*s",
             (int)sizeof(u->casa_msg) - 1, msg);
    u->casa_msg_ate = u->clock + 60 * 10;
}


void ui_set_busca(Ui *u, const char *termo)
{
    if (!u) return;
    snprintf(u->busca, sizeof(u->busca), "%s", termo ? termo : "");
    u->busca_suja = true;
    u->sel = 0;
}

int ui_shelf_count_dbg(const Ui *u)
{
    if (!u) return 0;
    return u->busca[0] ? u->nvis : u->vis_para;
}

int ui_view_dbg(const Ui *u) { return u ? (int)u->view : 0; }

void ui_set_bgm(Ui *u, bool ok) { if (u) u->bgm_port_ok = ok; }

int  ui_midia(const Ui *u) { return u ? u->midia : MIDIA_VINIL; }
void ui_set_midia(Ui *u, int m)
{
    if (!u) return;
    u->midia = (m >= 0 && m < MIDIA_N) ? m : MIDIA_VINIL;
}
bool ui_toque_tras(const Ui *u) { return u ? u->toque_tras : false; }
bool ui_bg_trava(const Ui *u) { return u ? u->bg_trava : false; }
void ui_set_bg_trava(Ui *u, bool on) { if (u) u->bg_trava = on; }

int  ui_fonte(const Ui *u) { return u ? u->fonte : FONTE_QOBUZ; }
void ui_set_fonte(Ui *u, int f)
{
    if (!u) return;
    u->fonte = (f >= 0 && f < FONTE_N) ? f : FONTE_QOBUZ;
}

int ui_sc_escolhida(const Ui *u, char *id, int id_cap,
                    char *artista, int art_cap,
                    char *titulo, int tit_cap, int *segundos)
{
    if (!u) return 0;
    ScTrack tr[SC_MAX_RES];
    int n = 0;
    bool ativo = false;
    sc_busca_estado(tr, SC_MAX_RES, &n, &ativo);
    if (n <= 0 || u->sc_sel < 0 || u->sc_sel >= n) return 0;
    const ScTrack *t = &tr[u->sc_sel];
    if (!t->id[0]) return 0;
    if (id && id_cap > 0)        snprintf(id, (size_t)id_cap, "%s", t->id);
    if (artista && art_cap > 0)  snprintf(artista, (size_t)art_cap, "%s", t->artista);
    if (titulo && tit_cap > 0)   snprintf(titulo, (size_t)tit_cap, "%s", t->titulo);
    if (segundos)                *segundos = t->segundos;
    return 1;
}
int  ui_tema(const Ui *u) { (void)u; return g_tema; }
void ui_set_tema(Ui *u, int t)
{
    (void)u;
    g_tema = (t >= 0 && t < N_TEMAS) ? t : 0;
}
void ui_set_toque_tras(Ui *u, bool on) { if (u) u->toque_tras = on; }

void ui_texto_dbg(char *dst, size_t cap, const char *src)
{
    tela_texto(dst, cap, src);
}

void ui_set_rec(Ui *u, const Rec *rec) { if (u) u->rec = rec; }

void ui_set_data(Ui *u, Playlist *plists, int nplists,
                 const Track **recs, int nrecs)
{
    if (!u) return;
    u->plists = plists;
    u->nplists = nplists;
    u->recs = recs;
    u->nrecs = nrecs;
    if (u->pl_sel >= u->nplists) u->pl_sel = u->nplists > 0 ? u->nplists - 1 : 0;
    if (u->rec_sel >= u->nrecs) u->rec_sel = u->nrecs > 0 ? u->nrecs - 1 : 0;
}

