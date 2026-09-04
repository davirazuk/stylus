#include "ui.h"
#include "ime.h"
#include "lastfm.h"
#include "fsutil.h"
#include "paths.h"
#include "ui_layout.h"
#include "sides.h"
#include "lyrics.h"

#include <vita2d.h>
#include <psp2/ctrl.h>
#include <psp2/touch.h>
#include <psp2/kernel/processmgr.h>

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define SCRW 960
#define SCRH 544

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
#define COL_AMBER        RGBA8(255, 170,  40, 255)
#define COL_AMBER_BRIGHT RGBA8(255, 197, 107, 255)
#define COL_TEXT         RGBA8(184, 192, 208, 255)
#define COL_TEXT_DIM     RGBA8( 90,  98, 112, 255)
#define COL_TEXT_FAINT   RGBA8( 58,  66,  80, 255)
#define COL_COLD         RGBA8( 32,  48,  74, 255)
#define COL_ALARM        RGBA8(255, 102,  85, 255)

/* tintas (o alfa entra por fora, então o RGBA8 vai com alfa 0) */
#define TINT_SEL         (RGBA8(255, 170, 40, 0) | (0x1Du << 24))
#define TINT_SEL_ROW     (RGBA8(255, 170, 40, 0) | (0x14u << 24))
#define TINT_ARMED       (RGBA8(255, 102, 85, 0) | (0x33u << 24))
#define COL_CARD         RGBA8( 10,  14,  21, 200)
#define COL_BAR_BED      RGBA8( 24,  32,  44, 255)

/* As margens e as faixas da tela vêm do ui_layout.c, que é puro e por isso
   MEDÍVEL: o teste de host varre resoluções e exige que todo retângulo caiba.
   Número solto no meio do desenho é sempre a tela de quem escreveu. */
#define PAD_X    28.0f
#define HEAD_Y   26
#define BODY_Y   58.0f
#define FOOT_Y   (SCRH - 34)
#define HINT_Y   (SCRH - 14)

typedef enum { VIEW_SHELF = 0, VIEW_DECK, VIEW_RECS, VIEW_PLAYLISTS,
               VIEW_HANDOFF, VIEW_CONTA } View;

/* ---------- cache de capas ----------
   O desenho antigo chamava vita2d_load_JPEG_buffer e vita2d_free_texture DENTRO
   do laço de cada quadro: nove JPEGs decodificados e jogados fora sessenta
   vezes por segundo na estante, onze nas recomendações. Não é lentidão de
   margem — é o quadro inteiro gasto decodificando a mesma imagem de novo. */
#define COVER_CACHE 10

typedef struct {
    const Album *owner;
    vita2d_texture *tex;
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

#define SPECT_BANDS 16
#define SPARKS 14

typedef struct { float x, y, vx, vy, life; } Spark;

struct Ui {
    bool bgm_port_ok;    /* o main conseguiu a porta BGM no arranque */
    vita2d_pvf *font;
    View view;
    int sel;
    int pl_sel;
    int rec_sel;
    float halo_phase;
    float disc_angle;      /* acumula: o disco PÁRA quando a música pára */
    float spin;            /* velocidade do prato, 0..1 — a cerimônia a sobe */

    RitualPhase rit;
    float rit_t;

    float spect[SPECT_BANDS];
    Spark sparks[SPARKS];

    /* toque */
    float scrub_to;
    int   touch_x, touch_y;
    bool  touch_down, touch_was_down;
    int   touch_start_x, touch_start_y;
    int   touch_frames;
    bool  touch_moved;
    bool  scrubbing;

    Lyrics lrc;
    bool  show_lyrics;

    /* busca por letra inicial: uma estante de quatrocentos discos não se
       navega item por item, e o d-pad é tudo que existe */
    bool  jump_open;
    int   jump_letter;   /* 0..25 = A..Z, 26 = # */

    /* repouso: a tela apaga e a música segue */
    bool  resting;
    int   rest_idle;

    CoverSlot cache[COVER_CACHE];
    unsigned clock;

    /* orçamento de carga: no máximo um álbum por quadro ganha tags e capa,
       senão rolar a estante trava a cada disco novo */
    int loaded_this_frame;

    /* a tela da conta: ver draw_conta */
    int  conta_sel;
    int  conta_campo;         /* que campo o teclado está editando, -1 nenhum */
    char conta_msg[96];
    unsigned conta_msg_ate;   /* o recado some sozinho; erro que fica é ruído */
    LastfmConfig conta_cfg;
    bool conta_lida;
    char conta_senha[64];     /* só até o login; nunca vai para o cartão */

    Playlist *plists;
    int nplists;
    const Track **recs;
    int nrecs;
    bool pl_armed;
};

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
static void ring_segmentos(float cx, float cy, float r, unsigned int color)
{
    int n = (int)(6.0f * sqrtf(r));        /* erro de corda < 0,5 px */
    if (n < 12) n = 12;
    if (n > 96) n = 96;
    float passo = 6.2831853f / (float)n;
    float px = cx + r, py = cy;
    for (int i = 1; i <= n; i++) {
        float a = passo * (float)i;
        float qx = cx + cosf(a) * r, qy = cy + sinf(a) * r;
        vita2d_draw_line(px, py, qx, qy, color);
        px = qx; py = qy;
    }
}

static void ring_circle(float cx, float cy, float r, float th, unsigned int color)
{
    if (r <= 0 || th <= 0) return;
    /* fino = circunferência; grosso continua no laço, que sabe fazer largura */
    if (th <= 1.6f) { ring_segmentos(cx, cy, r, color); return; }
    int ymin = (int)(cy - r - th), ymax = (int)(cy + r + th);
    for (int y = ymin; y <= ymax; y++) {
        float dy = (float)y - cy;
        if (fabsf(dy) > r + th) continue;
        float halfO = sqrtf((r + th) * (r + th) - dy * dy);
        int xo0 = (int)(cx - halfO), xo1 = (int)(cx + halfO);
        float dI = (r - th) * (r - th) - dy * dy;
        if (dI >= 0 && r > th) {
            float halfI = sqrtf(dI);
            int xi0 = (int)(cx - halfI), xi1 = (int)(cx + halfI);
            if (xi0 - 1 >= xo0) vita2d_draw_rectangle(xo0, y, (float)(xi0 - 1 - xo0 + 1), 1, color);
            if (xo1 - (xi1 + 1) + 1 > 0) vita2d_draw_rectangle(xi1 + 1, y, (float)(xo1 - (xi1 + 1) + 1), 1, color);
        } else {
            if (xo1 >= xo0) vita2d_draw_rectangle(xo0, y, (float)(xo1 - xo0 + 1), 1, color);
        }
    }
}

static void alpha_fill(float cx, float cy, float r, float a, unsigned int rgb)
{
    if (a <= 0) return;
    unsigned int c = (rgb & 0x00FFFFFF) | ((unsigned int)(a * 255.0f) << 24);
    fill_circle(cx, cy, r, c);
}

static void alpha_ring(float cx, float cy, float r, float th, float a, unsigned int rgb)
{
    if (a <= 0) return;
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

static float text_w(Ui *u, float scale, const char *s)
{
    return (float)vita2d_pvf_text_width(u->font, scale, s);
}

/* Corta no SEPARADOR quando dá, senão no caractere — terminar em "· p…" lê
   como defeito; terminar numa palavra inteira lê como resumo. */
static void elide(Ui *u, char *dst, size_t cap, float scale, float maxw, const char *src)
{
    snprintf(dst, cap, "%s", src);
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
    BTN_L1, BTN_R1, BTN_L2R2, BTN_SEL, BTN_START,
    BTN_DPAD, BTN_UPDOWN, BTN_TOUCH
} Btn;

#define GLIFO_R 8.5f

static float pill(Ui *u, float x, float cy, const char *txt)
{
    float tw2 = text_w(u, 0.45f, txt);
    float w = tw2 + 10.0f, h = 15.0f, y = cy - h / 2.0f;
    vita2d_draw_rectangle(x, y, w, 1, COL_AMBER);
    vita2d_draw_rectangle(x, y + h - 1, w, 1, COL_AMBER);
    vita2d_draw_rectangle(x, y, 1, h, COL_AMBER);
    vita2d_draw_rectangle(x + w - 1, y, 1, h, COL_AMBER);
    text(u, (int)(x + 5), (int)(cy + 4), COL_AMBER, 0.45f, txt);
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
    case BTN_TOUCH:   /* um dedo tocando: o arco é a ponta, os traços o toque */
        alpha_ring(cx, cy + 2, r * 0.62f, 1.3f, 0.85f, COL_AMBER);
        thick_line(cx - r * 0.75f, cy - r * 0.75f, cx - r * 0.35f, cy - r * 0.3f, 1.4f, COL_AMBER);
        thick_line(cx + r * 0.75f, cy - r * 0.75f, cx + r * 0.35f, cy - r * 0.3f, 1.4f, COL_AMBER);
        return 2 * r;
    case BTN_L1:    return pill(u, x, cy, "L1");
    case BTN_R1:    return pill(u, x, cy, "R1");
    case BTN_L2R2:  return pill(u, x, cy, "L2/R2");
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
        text(u, (int)x, (int)(cy + 4), COL_AMBER, 0.45f, "+");
        x += text_w(u, 0.45f, "+") + 3.0f;
        x += glyph(u, x, cy, b) + 3.0f;
    }
    x += 2.0f;
    text(u, (int)x, (int)(cy + 5), COL_TEXT_DIM, 0.50f, txt);
    return x + text_w(u, 0.50f, txt) + 14.0f;
}

static void text(Ui *u, int x, int y, unsigned int col, float scale, const char *s)
{
    vita2d_pvf_draw_text(u->font, x, y, col, scale, s);
}

static void text_elided(Ui *u, int x, int y, unsigned int col, float scale,
                        float maxw, const char *s)
{
    char b[512];
    elide(u, b, sizeof(b), scale, maxw, s);
    vita2d_pvf_draw_text(u->font, x, y, col, scale, b);
}

/* ---------- capa ---------- */

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
static vita2d_texture *cover_tex(Ui *u, Album *a)
{
    if (!a) return NULL;
    for (int i = 0; i < COVER_CACHE; i++)
        if (u->cache[i].owner == a) { u->cache[i].age = u->clock; return u->cache[i].tex; }

    if (u->loaded_this_frame > 0) return NULL;   /* fica para o quadro seguinte */

    if (!a->cover_loaded) {
        u->loaded_this_frame++;
        album_load_cover(a);
    }
    if (!a->cover) return NULL;

    vita2d_texture *tex = decode_cover(a);
    u->loaded_this_frame++;
    /* Os BYTES CRUS já cumpriram o papel — quem fica é a textura, e o cache
       dela tem teto. Sem soltá-los, cada capa vista ficava na memória para
       sempre: 17,6 MB nesta coleção, e num acervo com capas de 500 KB seriam
       200 MB, que é o mesmo estouro de heap que deixa a estante vazia.
       O album_free_cover também zera o `cover_loaded`, então voltar ao disco
       depois de ele sair do cache relê do arquivo — que é justamente o que
       carregar sob demanda quer dizer. */
    if (a->cover) album_free_cover(a);
    if (!tex) return NULL;

    /* despeja o mais velho */
    int victim = 0;
    for (int i = 1; i < COVER_CACHE; i++)
        if (u->cache[i].age < u->cache[victim].age) victim = i;
    if (u->cache[victim].tex) vita2d_free_texture(u->cache[victim].tex);
    u->cache[victim].tex = tex;
    u->cache[victim].owner = a;
    u->cache[victim].age = u->clock;
    return tex;
}

static void cache_clear(Ui *u)
{
    for (int i = 0; i < COVER_CACHE; i++) {
        if (u->cache[i].tex) vita2d_free_texture(u->cache[i].tex);
        u->cache[i].tex = NULL;
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
    int y0 = (int)(cy - r), y1 = (int)(cy + r);
    for (int y = y0; y <= y1; y++) {
        float dy = (float)y - cy;
        float d2 = r * r - dy * dy;
        if (d2 <= 0) continue;
        float half = sqrtf(d2);
        float sx = cx - half;
        vita2d_draw_texture_part_scale(tex, sx, (float)y,
                                       (sx - dx0) / s, ((float)y - dy0) / s,
                                       (2.0f * half) / s, 1.0f / s, s, s);
    }
}

/* ---------- o fundo do deck: a capa, esborratada ---------- */

/* Não é um blur de verdade — não há shader aqui. São seis cópias deslocadas e
   quase transparentes, que a esta escala lê como desfoque e custa seis blits.
   Escala COBRINDO: uma capa quadrada esticada numa tela 16:9 sai com quase o
   dobro da largura, e o olho pega isso na hora. */
static void deck_backdrop(Ui *u, Album *a)
{
    vita2d_texture *tex = cover_tex(u, a);
    if (!tex) return;
    float tw = (float)vita2d_texture_get_width(tex);
    float th = (float)vita2d_texture_get_height(tex);
    if (tw <= 0 || th <= 0) return;

    float s = SCRW / tw;
    if (th * s < SCRH) s = SCRH / th;
    s *= 1.12f;                       /* folga para os deslocamentos */
    float dw = tw * s, dh = th * s;
    float x = (SCRW - dw) / 2, y = (SCRH - dh) / 2;

    static const float off[6][2] = {
        {0,0}, {-9,-6}, {9,6}, {-6,7}, {6,-7}, {0,11}
    };
    for (int i = 0; i < 6; i++)
        vita2d_draw_texture_tint_scale(tex, x + off[i][0], y + off[i][1], s, s,
                                       RGBA8(255, 255, 255, 26));

    /* escurece de novo: o texto vem por cima e o fundo é cenário, não assunto */
    vita2d_draw_rectangle(0, 0, SCRW, SCRH, RGBA8(7, 9, 13, 176));
}

/* ---------- o disco ---------- */

/* Os sulcos são as faixas DESTE disco, e o anel aceso é onde a agulha está.
   Cinco anéis fixos desenhariam o mesmo objeto para um single e para um LP.

   No aro vai o ESPECTRO: raio = energia, grave no alto, espelhado nos dois
   lados. Parado, é uma circunferência — e é isso que ele tem que ser quando
   não há som, porque o anel é a única fonte e ausência de dado não vira
   afirmação de nível. */
static void draw_disc(float cx, float cy, float r, float progress,
                      int ntracks, int track_idx, float angle,
                      const float *spect, float spin)
{
    if (r < 6) { alpha_fill(cx, cy, r, 0.5f, COL_AMBER); return; }
    /* O corpo é quase PRETO. Com um preenchimento âmbar a 10% o prato saía
       marrom leitoso e a capa no rótulo afundava dentro dele; num disco de
       verdade a luz pega no ARO e nos sulcos, não na massa. */
    alpha_fill(cx, cy, r, 0.92f, RGBA8(11, 14, 20, 255));
    alpha_ring(cx, cy, r,          1.6f, 0.42f, COL_AMBER);
    alpha_ring(cx, cy, r * 0.975f, 1.0f, 0.16f, COL_AMBER);

    /* Quantos sulcos cabem sem virar ruído — e sem torrar a GPU. Um anel
       custa ~2 chamadas de desenho por linha de tela que ele cruza, e não
       há primitiva de anel: num card de raio 73 os 24 anéis fixos eram
       ~3500 chamadas por CARD, oito cards por tela. O limite passa a sair do
       RAIO: um sulco a cada ~5 px, que é o que o olho separa de qualquer
       forma — abaixo disso já era moiré, não contagem. */
    int cabem = (int)(r / 5.0f);
    if (cabem < 3) cabem = 3;
    if (cabem > 24) cabem = 24;
    int n = ntracks > 0 ? ntracks : 1;
    if (n > cabem) n = cabem;
    for (int i = 0; i < n; i++) {
        float rr = r * (1.0f - (float)(i + 1) / (float)(n + 2));
        bool here = (track_idx >= 0 && ntracks > 0 &&
                     i == (track_idx * n) / (ntracks > 0 ? ntracks : 1));
        alpha_ring(cx, cy, rr, here ? 1.6f : 1.0f, here ? 0.30f : 0.11f, COL_AMBER);
    }

    /* raio é tempo: da borda para o centro */
    float read_r = r * (1.0f - progress * 0.86f);
    alpha_ring(cx, cy, read_r, 2.5f, 0.34f, COL_AMBER_BRIGHT);

    if (spect) {
        for (int i = 0; i < SPECT_BANDS; i++) {
            float v = spect[i];
            /* grave no alto, espelhado: a fatia i vai para os dois lados */
            float a0 = -1.5707963f + (float)i * 3.14159265f / (float)SPECT_BANDS;
            float step = 3.14159265f / (float)SPECT_BANDS;
            for (int side = 0; side < 2; side++) {
                float a = side ? -1.5707963f - (float)i * step - step * 0.5f
                               : a0 + step * 0.5f;
                float len = 3.0f + v * r * 0.20f;
                float x0 = cx + cosf(a) * (r + 2.0f);
                float y0 = cy + sinf(a) * (r + 2.0f);
                float x1 = cx + cosf(a) * (r + 2.0f + len);
                float y1 = cy + sinf(a) * (r + 2.0f + len);
                unsigned int c = (COL_AMBER & 0x00FFFFFF) |
                                 ((unsigned int)(60.0f + v * 150.0f) << 24);
                vita2d_draw_line(x0, y0, x1, y1, c);
            }
        }
    }

    /* o selo, com uma marca que gira — é o que diz que ele ESTÁ girando */
    alpha_fill(cx, cy, r * 0.16f, 0.16f, COL_AMBER);
    float mx = cx + cosf(angle) * r * 0.12f;
    float my = cy + sinf(angle) * r * 0.12f;
    alpha_fill(mx, my, 2.5f, 0.55f + 0.4f * spin, COL_AMBER_BRIGHT);
    alpha_fill(cx, cy, 3.0f, 0.85f, COL_AMBER);
}

/* O braço é o FACHO, não um tubo de alumínio: quase toda a luz mora na ponta,
   o corpo começa a 38% do caminho, e levantado ele apaga.

   `cue` é 0 no descanso (fora do disco) e 1 no sulco; `down` é 0 suspenso e
   1 encostado. A cerimônia move os dois; fora dela valem 1 e 1. */
static void draw_needle(float cx, float cy, float r, float phase, float progress,
                        bool live, float cue, float down)
{
    float park = -1.5707963f + 0.95f;         /* o descanso, fora do prato */
    float play = -1.5707963f + phase * 0.18f;
    float ang = park + (play - park) * cue;

    float rest_r = r * 1.30f;                 /* suspenso, fora do sulco */
    float groove_r = r * (1.0f - progress * 0.86f);
    float read_r = rest_r + (groove_r - rest_r) * cue;

    float px = cx + cosf(ang) * read_r;
    float py = cy + sinf(ang) * read_r;
    /* suspenso, a agulha paira um pouco acima do sulco */
    py -= (1.0f - down) * 9.0f;

    float ox = cx + cosf(ang) * (r * 1.55f);
    float oy = cy + sinf(ang) * (r * 1.55f);

    float a = (live || cue > 0.01f) ? (0.30f + 0.70f * down) : 0.25f;
    for (int i = 4; i <= 10; i++) {
        float t0 = 0.38f + (float)(i - 4) * 0.062f;
        float t1 = t0 + 0.062f;
        float x0 = ox + (px - ox) * t0, y0 = oy + (py - oy) * t0;
        float x1 = ox + (px - ox) * t1, y1 = oy + (py - oy) * t1;
        float k = powf(t1, 2.2f);
        unsigned int c = (COL_AMBER & 0x00FFFFFF) |
                         ((unsigned int)(k * 150.0f * a) << 24);
        vita2d_draw_line(x0, y0, x1, y1, c);
    }
    if (down > 0.5f && live) {
        vita2d_draw_line(px - 4, py, px + 4, py, COL_AMBER_BRIGHT);
        vita2d_draw_line(px, py - 4, px, py + 4, COL_AMBER_BRIGHT);
    }
    alpha_fill(px, py, 3.5f, 0.85f * a, COL_AMBER_BRIGHT);
    alpha_fill(px, py, 11.0f, 0.16f * a, COL_AMBER);
}

static void draw_halo(float cx, float cy, float base_r, float phase)
{
    float r = base_r * (1.0f + 0.03f * sinf(phase * 1.7f));
    alpha_ring(cx, cy, r * 1.12f, 16.0f, 0.05f, COL_COLD);
    alpha_ring(cx, cy, r * 1.05f, 7.0f, 0.09f, COL_COLD);
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
        if (u->rit_t >= RIT_DROP_S) { u->rit = RIT_OFF; u->rit_t = 0; }
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

static void draw_bg(void)
{
    for (int y = 0; y < SCRH; y += 8) {
        float t = (float)y / (float)SCRH;
        int r = (int)(6 + (13 - 6) * t);
        int g = (int)(8 + (18 - 8) * t);
        int b = (int)(13 + (28 - 13) * t);
        unsigned int c = 0xFF000000 | ((unsigned int)b << 16) |
                         ((unsigned int)g << 8) | (unsigned int)r;
        vita2d_draw_rectangle(0, (float)y, SCRW, 8, c);
    }
}

static void header(Ui *u, const char *title, const char *hint)
{
    text(u, (int)PAD_X, HEAD_Y, COL_AMBER, 0.95f, title);
    if (hint) text_elided(u, (int)PAD_X, HINT_Y, COL_TEXT_DIM, 0.52f,
                          SCRW - 2 * PAD_X, hint);
}

/* Cabeçalho com as dicas DESENHADAS. A lista termina num rótulo NULL.
   `b2` diferente de -1 vira "a + b" (as combinações com R1 segurado). */
typedef struct { Btn b, b2; const char *txt; } Dica;

static void header_hints(Ui *u, const char *title, const Dica *d)
{
    text(u, (int)PAD_X, HEAD_Y, COL_AMBER, 0.95f, title);
    float x = PAD_X, y = (float)HINT_Y - 4.0f;
    for (; d && d->txt; d++) {
        /* não deixa a fila vazar pela direita: melhor faltar dica que
           desenhar meia palavra na borda */
        if (x > SCRW - PAD_X - 90.0f) break;
        x = hint2(u, x, y, d->b, d->b2, d->txt);
    }
}

/* ---------- a estante ---------- */

#define SHELF_COLS UI_SHELF_COLS
#define SHELF_ROWS UI_SHELF_ROWS
#define SHELF_PAGE UI_SHELF_PAGE

static void shelf_empty(Ui *u, Library *lib)
{
    char st[512];
    library_status(lib, st, sizeof(st));

    text(u, (int)PAD_X, 120, COL_AMBER, 0.90f, "a estante está vazia");
    text_elided(u, (int)PAD_X, 152, COL_TEXT, 0.62f, SCRW - 2 * PAD_X, st);

    /* Dizer ONDE se olhou é o que transforma "não acha as músicas" num
       conserto de trinta segundos. Antes a tela mostrava "0 discos" e a
       pessoa não tinha como saber sequer em que pasta o app tinha ido. */
    text(u, (int)PAD_X, 196, COL_TEXT_DIM, 0.55f,
         lib->roots_from_config ? "pastas do seu roots.txt:" : "procurei em:");
    int y = 218;
    for (int i = 0; i < lib->nroots && i < 6; i++) {
        char line[MAX_PATH_LEN + 32];
        /* NÃO diz "não existe" sem saber: "não existe" e "sem permissão"
           pedem consertos opostos, e a tela mandava procurar a pasta que já
           estava lá. Agora mostra o que o sistema respondeu, com o código —
           que é o que dá para me repassar quando nada mais explica. */
        if (lib->roots[i].opened)
            snprintf(line, sizeof(line), "%s   (abriu)", lib->roots[i].path);
        else
            snprintf(line, sizeof(line), "%s   %s  [0x%08X]",
                     lib->roots[i].path, scan_err_str(lib->roots[i].err),
                     (unsigned)lib->roots[i].err);
        text_elided(u, (int)PAD_X + 12, y, lib->roots[i].opened ? COL_TEXT : COL_TEXT_FAINT,
                    0.54f, SCRW - 2 * PAD_X - 12, line);
        y += 22;
    }
    /* A PERGUNTA DECISIVA, respondida na tela: o DISPOSITIVO abre?

       Se `ux0:` abre e `ux0:music` não, a pasta é que não está lá. Se nem
       `ux0:` abre, o problema não tem nada a ver com música — é o caminho
       inteiro, e nenhuma mudança de pasta conserta. As duas coisas se
       parecem na tela ("não achou nada") e pedem consertos que não têm
       relação, então a tela passa a separá-las.

       E LISTA o que viu ali: se o app enxerga "app", "data", "music" na
       raiz, a pasta existe e o problema é outro. */
    y += 12;
    {
        int e = 0;
        DirIter *dev = dir_open_err("ux0:", &e);
        if (!dev) {
            char l[160];
            snprintf(l, sizeof(l), "ux0: (o cartão) tambem NAO abre: %s  [0x%08X]",
                     scan_err_str(e), (unsigned)e);
            text_elided(u, (int)PAD_X, y, COL_ALARM, 0.55f, SCRW - 2 * PAD_X, l);
            y += 22;
        } else {
            char l[420];
            size_t n = (size_t)snprintf(l, sizeof(l), "ux0: abre, e tem: ");
            const char *nome;
            int isdir, vistos = 0;
            while (vistos < 8 && dir_next(dev, &nome, &isdir)) {
                if (nome[0] == '.') continue;
                n += (size_t)snprintf(l + n, sizeof(l) - n, "%s%s",
                                      vistos ? ", " : "", nome);
                vistos++;
                if (n > sizeof(l) - 40) break;
            }
            if (!vistos) snprintf(l, sizeof(l), "ux0: abre, mas esta VAZIO");
            dir_close(dev);
            text_elided(u, (int)PAD_X, y, COL_TEXT, 0.55f, SCRW - 2 * PAD_X, l);
            y += 22;
        }
    }

    y += 8;
    text(u, (int)PAD_X, y, COL_TEXT_DIM, 0.54f,
         "ponha a música em ux0:music/Artista/Album/*.mp3 — ou escreva as suas");
    /* o caminho vem do paths.h: é ESTA linha que a pessoa vai digitar quando
       o app não achar a coleção dela, e ela não pode divergir do que o
       scanner realmente lê */
    text(u, (int)PAD_X, y + 20, COL_TEXT_DIM, 0.54f,
         "pastas, uma por linha, em " STYLUS_ROOTS_TXT);
}

static void draw_shelf(Ui *u, Library *lib, Player *p)
{
    int n = lib->nalbums;
    header(u, "ESTANTE",
           NULL);
    {
        static const Dica d[] = {
            { BTN_CROSS,    (Btn)-1, "tocar" },
            { BTN_DPAD,     (Btn)-1, "navegar" },
            { BTN_SQUARE,   (Btn)-1, "ir para" },
            { BTN_TRIANGLE, (Btn)-1, "o que toca" },
            { BTN_SEL,      (Btn)-1, "sorteio" },
            { BTN_L1,       (Btn)-1, "recs" },
            { BTN_R1,       (Btn)-1, "playlists" },
            { 0, 0, NULL }
        };
        header_hints(u, "", d);
    }

    if (n <= 0) { shelf_empty(u, lib); return; }

    if (u->sel >= n) u->sel = n - 1;
    if (u->sel < 0) u->sel = 0;

    int page = u->sel / SHELF_PAGE;
    int scroll = page * SHELF_PAGE;
    const Album *now = player_current_album(p);

    UiShelfGeom g;
    ui_shelf_geom(SCRW, SCRH, &g);
    float cw = g.card_w, ch = g.card_h, x0 = g.x0, y0 = g.y0, gap = g.gap;
    float pad = g.cover_pad, side = g.cover_side;

    for (int r = 0; r < SHELF_ROWS; r++) {
        for (int c = 0; c < SHELF_COLS; c++) {
            int idx = scroll + r * SHELF_COLS + c;
            if (idx >= n) continue;
            Album *a = library_album(lib, idx);
            if (!a) continue;
            float x = x0 + c * (cw + gap);
            float y = y0 + r * (ch + gap);
            bool is_sel = (idx == u->sel);
            bool is_now = (a == now);

            vita2d_draw_rectangle(x, y, cw, ch, is_sel ? TINT_SEL : COL_CARD);

            float ix = x + (cw - side) / 2, iy = y + pad;
            vita2d_texture *tex = cover_tex(u, a);
            if (tex) {
                draw_cover_fit(tex, ix, iy, side);
            } else if (a->cover_loaded) {
                /* sem capa: o disco É o desenho, não um aviso de falta */
                float dcx = ix + side / 2, dcy = iy + side / 2, dr = side / 2.2f;
                draw_disc(dcx, dcy, dr, 0.18f, a->ntracks, -1, u->disc_angle,
                          NULL, 0.0f);
                /* A INICIAL no rótulo. Sem capa, um disco fica igual ao
                   vizinho e a estante vira uma parede sem alvo — e neste
                   acervo 48 álbuns não têm arte em lugar nenhum. A letra
                   devolve o que a capa daria: algo diferente por card para
                   o olho mirar. Pula o prefixo de data que quase todo disco
                   ao vivo daqui tem, senão a inicial de todos seria "1". */
                {
                    const char *nome = a->album[0] ? a->album : a->artist;
                    while (*nome && !((*nome >= 'A' && *nome <= 'Z') ||
                                      (*nome >= 'a' && *nome <= 'z') ||
                                      (unsigned char)*nome >= 0xC0))
                        nome++;
                    if (*nome) {
                        char ini[5] = {0};
                        int nb = 1;
                        if ((unsigned char)nome[0] >= 0xC0)
                            while (nb < 4 && ((unsigned char)nome[nb] & 0xC0) == 0x80) nb++;
                        memcpy(ini, nome, (size_t)nb);
                        if (ini[0] >= 'a' && ini[0] <= 'z') ini[0] = (char)(ini[0] - 32);
                        /* chão para a letra: solta sobre os anéis ela some */
                        alpha_fill(dcx, dcy, dr * 0.46f, 0.95f, RGBA8(14, 18, 25, 255));
                        alpha_ring(dcx, dcy, dr * 0.46f, 1.2f, 0.40f, COL_AMBER);
                        float sc = 1.05f;
                        int lw = text_w(u, sc, ini);
                        text(u, (int)(dcx - lw / 2.0f), (int)(dcy + dr * 0.17f),
                             COL_AMBER_BRIGHT, sc, ini);
                    }
                }
            } else {
                /* ainda carregando: um aro, e nenhuma afirmação */
                alpha_ring(ix + side / 2, iy + side / 2, side / 2.4f, 1.0f, 0.10f, COL_COLD);
            }

            if (is_now) {
                alpha_fill(x + 14, y + 14, 5.0f, 0.95f, COL_AMBER);
                alpha_fill(x + 14, y + 14, 11.0f, 0.20f, COL_AMBER);
            }
            if (is_sel) {
                vita2d_draw_rectangle(x, y, cw, 2, COL_AMBER);
                vita2d_draw_rectangle(x, y + ch - 2, cw, 2, COL_AMBER);
                vita2d_draw_rectangle(x, y, 2, ch, COL_AMBER);
                vita2d_draw_rectangle(x + cw - 2, y, 2, ch, COL_AMBER);
            }

            float tw = cw - 14;
            text_elided(u, (int)x + 7, (int)(y + g.label_dy), is_sel ? COL_AMBER : COL_TEXT,
                        0.60f, tw, a->album);
            const char *sub = a->artist[0] ? a->artist : "—";
            if (a->ndecodable == 0) sub = "formato que este app não toca";
            text_elided(u, (int)x + 7, (int)(y + g.sub_dy),
                        a->ndecodable == 0 ? COL_ALARM : COL_TEXT_DIM, 0.50f, tw, sub);
        }
    }

    if (u->jump_open) {
        /* a régua de letras: A..Z e #, com as que existem acesas. Uma letra
           que não tem disco não pode parecer escolhível. */
        vita2d_draw_rectangle(0, 0, SCRW, SCRH, RGBA8(7, 9, 13, 232));
        text(u, (int)PAD_X, HEAD_Y, COL_AMBER, 0.95f, "IR PARA");
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
                                             : COL_TEXT_FAINT, 1.1f, L);
        }
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.55f,
             "[dir] escolhe   [X] vai   [tri] volta");
        return;
    }

    char cnt[96];
    int pages = (n + SHELF_PAGE - 1) / SHELF_PAGE;
    snprintf(cnt, sizeof(cnt), "%d disco%s   ·   página %d de %d",
             n, n == 1 ? "" : "s", page + 1, pages);
    text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.55f, cnt);
}

/* ---------- o deck ---------- */

static void fmt_time(char *b, size_t cap, int sec)
{
    if (sec < 0) { snprintf(b, cap, "--:--"); return; }
    snprintf(b, cap, "%02d:%02d", sec / 60, sec % 60);
}

static void draw_deck(Ui *u, Library *lib, Player *p)
{
    const Album *a = player_current_album(p);
    if (!a) {
        header(u, "AGORA", "[tri] estante   [L1] recs   [R1] playlists");
        text(u, (int)PAD_X, 130, COL_TEXT, 0.80f, "nada no prato");
        const char *err = player_last_error(p);
        if (err && err[0]) {
            text(u, (int)PAD_X, 166, COL_ALARM, 0.62f, "a última tentativa parou aqui:");
            text_elided(u, (int)PAD_X, 190, COL_TEXT, 0.60f, SCRW - 2 * PAD_X, err);
        } else {
            text(u, (int)PAD_X, 166, COL_TEXT_DIM, 0.60f,
                 "escolha um disco na estante — [tri]");
        }
        (void)lib;
        return;
    }
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

    u->halo_phase += 0.05f;
    ritual_step(u, live);
    /* o ângulo acumula com a VELOCIDADE do prato: durante a partida ele
       acelera de verdade, e parada a música ele desacelera até parar */
    u->disc_angle += 0.075f * u->spin;

    float cue = 1.0f, down = 1.0f;
    if (u->rit == RIT_SPINUP)   { cue = 0.0f; down = 0.0f; }
    else if (u->rit == RIT_CUE) { cue = u->rit_t / RIT_CUE_S; down = 0.0f; }
    else if (u->rit == RIT_DROP){ cue = 1.0f; down = u->rit_t / RIT_DROP_S; }

    player_spectrum(p, u->spect, SPECT_BANDS);

    UiDeckGeom g;
    ui_deck_geom(SCRW, SCRH, &g);
    float cx = g.cx, cy = g.cy, base_r = g.r;
    /* o fundo é a CAPA deste disco, esborratada e escura — não uma textura
       genérica. É a única coisa na tela que diz "este disco" antes de a
       pessoa ler uma letra. */
    deck_backdrop(u, (Album *)a);

    draw_halo(cx, cy, base_r, u->halo_phase);
    draw_disc(cx, cy, base_r, progress, a->ntracks, player_track_idx(p),
              u->disc_angle, live ? u->spect : NULL, u->spin);
    draw_needle(cx, cy, base_r, u->halo_phase, progress, live, cue, down);

    /* a agulha ENCOSTOU: é aqui que as faíscas nascem, uma vez */
    if (u->rit == RIT_DROP && u->rit_t < 1.2f / 60.0f) {
        float ang = -1.5707963f + u->halo_phase * 0.18f;
        sparks_spawn(u, cx + cosf(ang) * base_r, cy + sinf(ang) * base_r);
    }
    sparks_draw(u);

    /* A CAPA no meio do disco, no lugar do selo: é o que faz o objeto na tela
       ser ESTE disco e não um disco. */
    {
        vita2d_texture *tex = cover_tex(u, (Album *)a);
        float lab = base_r * 0.33f;
        /* sombra um pouco maior por baixo: assenta o rótulo no prato em vez
           de deixá-lo parecendo colado por cima */
        alpha_fill(cx, cy, lab + 3.0f, 0.55f, RGBA8(5, 7, 11, 255));
        if (tex) {
            draw_cover_round(tex, cx, cy, lab);
        } else {
            /* sem capa, um rótulo liso — ainda lê como rótulo */
            alpha_fill(cx, cy, lab, 0.16f, COL_AMBER);
            alpha_ring(cx, cy, lab * 0.62f, 1.0f, 0.20f, COL_AMBER);
        }
        alpha_ring(cx, cy, lab, 1.5f, 0.55f, COL_AMBER);
        /* o furo do eixo é o que fecha a leitura de vinil */
        alpha_fill(cx, cy, 6.0f, 1.0f, RGBA8(5, 7, 11, 255));
        alpha_ring(cx, cy, 6.0f, 1.0f, 0.60f, COL_AMBER_BRIGHT);
    }

    float tx = g.text_x;
    float tw = g.text_w;

    header(u, live ? "AGORA  ·  TOCANDO" : "AGORA  ·  PAUSADO",
           NULL);
    {
        static const Dica d[] = {
            { BTN_TRIANGLE, (Btn)-1, "estante" },
            { BTN_L1,       (Btn)-1, "recs" },
            { BTN_R1,       (Btn)-1, "playlists" },
            { BTN_R1, BTN_L1,       "apaga a tela" },
            { BTN_R1, BTN_SQUARE,   "soneca" },
            { BTN_R1, BTN_TRIANGLE, "jogando" },
            { BTN_TOUCH,    (Btn)-1, "no disco pausa" },
            { 0, 0, NULL }
        };
        header_hints(u, "", d);
    }

    text_elided(u, (int)tx, 126, COL_AMBER, 0.72f, tw, a->artist[0] ? a->artist : "—");
    text_elided(u, (int)tx, 168, COL_TEXT, 1.00f, tw, a->album);

    /* O LADO. É a tese do sistema e o tocador do Vita não a tinha: um álbum
       aqui era uma fila de arquivos, como em qualquer outro tocador. */
    int lado = -1;
    if (a->lados.n > 0) lado = sides_of_track(&a->lados, player_track_idx(p));
    if (lado >= 0) {
        char rot[12], linha[96];
        sides_label(&a->lados, lado, rot, sizeof(rot));
        if (a->lados.discos > 1)
            snprintf(linha, sizeof(linha), "DISCO %d  ·  %s", lado / 2 + 1, rot);
        else
            snprintf(linha, sizeof(linha), "%s", rot);
        text(u, (int)tx, 194, COL_AMBER, 0.56f, linha);
    }

    text_elided(u, (int)tx, 214, COL_TEXT, 0.66f, tw, t ? t->title : "—");

    char cur[16], tot[16], info[160];
    fmt_time(cur, sizeof(cur), pos);
    fmt_time(tot, sizeof(tot), dur);
    snprintf(info, sizeof(info), "%s / %s   ·   faixa %d de %d",
             cur, tot, player_track_idx(p) + 1, player_track_count(p));
    text_elided(u, (int)tx, 244, COL_TEXT_DIM, 0.56f, tw, info);

    vita2d_draw_rectangle(tx, g.bar_y, tw, g.bar_h, COL_BAR_BED);
    if (dur > 0) {
        vita2d_draw_rectangle(tx, g.bar_y, tw * progress, g.bar_h, COL_AMBER);
        /* a cabeça da barra: sem ela não dá para ver onde tocar para buscar */
        alpha_fill(tx + tw * progress, g.bar_y + g.bar_h / 2, 4.0f, 0.9f, COL_AMBER_BRIGHT);
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
                snprintf(extra, sizeof(extra), "  ·  sai em %ld Hz / 16 bits",
                         sig.rate_out);
            /* O 2º plano é a mesma família de verdade que esta linha conta:
               não a qualidade prometida, mas o que o caminho de fato faz. E
               só vale com as DUAS coisas — a porta veio no arranque E a taxa
               deixa o SDL2 abrir a saída como BGM. */
            const char *bgm = (u->bgm_port_ok && sig.bgm_port)
                            ? "  ·  2º plano: sim" : "  ·  2º plano: não";
            snprintf(sl, sizeof(sl), "%s  ·  %ld Hz / %d bits%s%s",
                     sig.kind, sig.rate_file, sig.bits_file, extra, bgm);
        } else {
            /* sem medida, travessão: acusação tirada da ausência de dado é
               a doença que a tela SINAL do desktop pegou */
            snprintf(sl, sizeof(sl), "%s  ·  —", sig.kind);
        }
        text_elided(u, (int)tx, (int)g.sig_y, 
                    (sig.resampled || sig.requantized) ? COL_TEXT_DIM : COL_AMBER,
                    0.48f, tw, sl);
    }

    /* a ORDEM DO LADO: onde não há letra, é para a contracapa que se olha */
    /* durante a cerimônia a tela DIZ o que está acontecendo: sem isso é uma
       animação bonita que ninguém entende */
    if (u->rit != RIT_OFF) {
        const char *frase = u->rit == RIT_SPINUP ? "o prato ganha rotação"
                          : u->rit == RIT_CUE    ? "a agulha vai ao sulco"
                                                 : "encostou";
        text(u, (int)tx, (int)g.note_y, COL_AMBER, 0.56f, frase);
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
            text_elided(u, (int)tx, (int)g.note_y, COL_ALARM, 0.60f, tw, aviso);
        } else if (falta > 20) {
            snprintf(aviso, sizeof(aviso), "%s em %d min",
                     (lado + 1 < a->lados.n) ? "vira" : "acaba",
                     (falta + 59) / 60);
            text(u, (int)tx, (int)g.note_y, COL_TEXT_DIM, 0.52f, aviso);
        }
    }

    /* A LETRA, no tempo. Só é carregada quando a faixa muda — ler o .lrc a
       cada quadro é I/O por quadro, que foi o defeito do celular. */
    if (t) lyrics_load(&u->lrc, t->path);
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
                        agora ? 0.60f : 0.52f, tw, u->lrc.lines[idx].text);
        }
        goto lyrics_done;
    }

    int shown = 0;
    int from = player_track_idx(p) - 2;
    if (from < 0) from = 0;
    for (int i = from; i < a->ntracks && shown < g.list_rows && u->rit == RIT_OFF;
         i++, shown++) {
        int y = (int)(g.list_y + shown * g.list_step);
        if (y > FOOT_Y - 26) break;
        bool is_now = (t && &a->tracks[i] == t);
        char line[288];
        if (a->tracks[i].number > 0)
            snprintf(line, sizeof(line), "%2d  %.255s", a->tracks[i].number, a->tracks[i].title);
        else
            snprintf(line, sizeof(line), "    %.255s", a->tracks[i].title);
        unsigned int col = is_now ? COL_AMBER
                         : (!a->tracks[i].decodable ? COL_TEXT_FAINT : COL_TEXT_DIM);
        text_elided(u, (int)tx, y, col, 0.53f, tw - 54, line);
        if (a->tracks[i].seconds > 0) {
            char d[16];
            fmt_time(d, sizeof(d), a->tracks[i].seconds);
            text(u, (int)(SCRW - PAD_X - 42), y, COL_TEXT_FAINT, 0.50f, d);
        }
    }

lyrics_done:;
    const char *rep = "rep todas";
    switch (player_repeat(p)) {
    case REPEAT_OFF: rep = "rep off"; break;
    case REPEAT_ONE: rep = "rep 1";   break;
    default: break;
    }
    char ctl[240];
    snprintf(ctl, sizeof(ctl), "%s   ·   %s   ·   %s%s",
             live ? "[O] pausa" : "[O] recomeça",
             rep, player_shuffle(p) ? "sorteio ligado" : "sorteio desligado",
             /* uma tecla que a tela desenha e não anuncia não existe */
             tem_letra ? (u->show_lyrics ? "   ·   [quad] ordem do lado"
                                         : "   ·   [quad] letra") : "");
    /* a soneca tem que APARECER quando está armada: um estado que muda o que
       o aparelho vai fazer e não se vê é o pior tipo de estado */
    {
        int sm = player_sleep_mode(p);
        if (sm == 1)
            text(u, (int)PAD_X, FOOT_Y - 20, COL_ALARM, 0.54f,
                 "soneca: esmaecendo   ·   [R1+quad] desliga");
        else if (sm == 2)
            text(u, (int)PAD_X, FOOT_Y - 20, COL_ALARM, 0.54f,
                 "soneca: para no fim do lado   ·   [R1+quad] desliga");
    }
    text_elided(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.54f, SCRW - 2 * PAD_X, ctl);

    const char *err = player_last_error(p);
    if (err && err[0])
        text_elided(u, (int)PAD_X, FOOT_Y - 20, COL_ALARM, 0.52f,
                    SCRW - 2 * PAD_X, err);
}

/* ---------- lista com miniatura (recs e playlists) ---------- */

#define ROW_H 38

static void row_thumb(Ui *u, Album *a, float x, float y, float side, int ntracks)
{
    vita2d_texture *tex = a ? cover_tex(u, a) : NULL;
    if (tex) draw_cover_fit(tex, x, y, side);
    else draw_disc(x + side / 2, y + side / 2, side / 2.2f, 0.18f, ntracks, -1,
                   u->disc_angle, NULL, 0.0f);
}

static void draw_recs(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    {
        static const Dica d[] = {
            { BTN_TRIANGLE, (Btn)-1, "estante" },
            { BTN_CIRCLE,   (Btn)-1, "toca daqui" },
            { BTN_UPDOWN,   (Btn)-1, "navegar" },
            { 0, 0, NULL }
        };
        header_hints(u, "RECOMENDADO", d);
    }

    if (!u->recs || u->nrecs <= 0) {
        text(u, (int)PAD_X, 130, COL_TEXT, 0.72f, "ainda não há o que sugerir");
        text(u, (int)PAD_X, 162, COL_TEXT_DIM, 0.58f,
             "as sugestões saem do que você ouviu até o FIM — ponha um disco e volte");
        return;
    }
    UiListGeom lg;
    ui_list_geom(SCRW, SCRH, &lg);
    if (u->rec_sel >= u->nrecs) u->rec_sel = u->nrecs - 1;
    if (u->rec_sel < 0) u->rec_sel = 0;
    int scroll = (u->rec_sel / lg.rows) * lg.rows;

    for (int r = 0; r < lg.rows; r++) {
        int idx = scroll + r;
        if (idx >= u->nrecs) break;
        const Track *t = u->recs[idx];
        if (!t) continue;
        float y = lg.y0 + r * lg.row_h;
        if (y + ROW_H > FOOT_Y - 12) break;
        bool is_sel = (idx == u->rec_sel);
        if (is_sel) vita2d_draw_rectangle(PAD_X, y, SCRW - 2 * PAD_X, ROW_H - 4, TINT_SEL_ROW);

        Album *a = t->owner;
        row_thumb(u, a, PAD_X + 4, y + 3, (float)(ROW_H - 10), a ? a->ntracks : 1);

        float tx = PAD_X + ROW_H + 4;
        float tw = SCRW - PAD_X - tx;
        text_elided(u, (int)tx, (int)(y + 15), is_sel ? COL_AMBER : COL_TEXT, 0.58f, tw, t->title);
        char sub[600];
        snprintf(sub, sizeof(sub), "%.255s%s%.255s",
                 a && a->artist[0] ? a->artist : "",
                 a && a->artist[0] && a->album[0] ? "  ·  " : "",
                 a ? a->album : "");
        text_elided(u, (int)tx, (int)(y + 30), COL_TEXT_DIM, 0.50f, tw, sub);
    }
    char cnt[64];
    snprintf(cnt, sizeof(cnt), "%d faixa%s   ·   %d de %d",
             u->nrecs, u->nrecs == 1 ? "" : "s", u->rec_sel + 1, u->nrecs);
    text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.55f, cnt);
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

/* Mostra o começo e o fim e come o meio: dá para conferir que a colagem foi
   a certa sem estampar a credencial inteira na tela de quem estiver ao lado. */
static void mascara(const char *v, char *out, size_t cap)
{
    size_t n = v ? strlen(v) : 0;
    if (n == 0) { snprintf(out, cap, "(vazio)"); return; }
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
    if (!u->conta_lida) {
        lastfm_config_load(&u->conta_cfg, STYLUS_DATA_DIR);
        u->conta_lida = true;
    }
    header(u, "CONTA", NULL);
    {
        static const Dica d[] = {
            { BTN_CROSS,    (Btn)-1, "editar" },
            { BTN_CIRCLE,   (Btn)-1, "confirmar" },
            { BTN_UPDOWN,   (Btn)-1, "navegar" },
            { BTN_TRIANGLE, (Btn)-1, "estante" },
            { 0, 0, NULL }
        };
        header_hints(u, "", d);
    }

    const LastfmConfig *c = &u->conta_cfg;
    int fila = lastfm_queue_size(STYLUS_DATA_DIR);

    /* O estado, primeiro e em âmbar: é a pergunta que a pessoa veio fazer. */
    char est[160];
    if (c->configured)
        snprintf(est, sizeof(est), "ligado como %s", c->username);
    else if (!c->api_key[0] || !c->api_secret[0])
        snprintf(est, sizeof(est), "falta a chave de API (last.fm/api/account/create)");
    else
        snprintf(est, sizeof(est), "chaves prontas — falta entrar");
    text(u, (int)PAD_X, 118, c->configured ? COL_AMBER : COL_TEXT, 0.66f, est);

    char fl[96];
    if (fila > 0)
        snprintf(fl, sizeof(fl), "%d escuta%s guardada%s no cartão%s",
                 fila, fila == 1 ? "" : "s", fila == 1 ? "" : "s",
                 c->configured ? " — sobem sozinhas" : " — esperando uma conta");
    else
        snprintf(fl, sizeof(fl), "nenhuma escuta esperando");
    text(u, (int)PAD_X, 140, COL_TEXT_DIM, 0.54f, fl);

    static const char *ROT[CC_N] = {
        "chave de API", "segredo da API", "usuário", "entrar", "sair da conta"
    };
    float y0 = 176.0f, rh = 40.0f;
    for (int i = 0; i < CC_N; i++) {
        float y = y0 + i * rh;
        bool sel = (i == u->conta_sel);
        if (sel)
            vita2d_draw_rectangle(PAD_X, y - 4, SCRW - 2 * PAD_X, rh - 8, TINT_SEL_ROW);
        text(u, (int)PAD_X + 6, (int)(y + 14), sel ? COL_AMBER : COL_TEXT, 0.58f, ROT[i]);

        char val[128];
        unsigned cor = COL_TEXT_DIM;
        if (i == CC_KEY)         mascara(c->api_key, val, sizeof(val));
        else if (i == CC_SECRET) mascara(c->api_secret, val, sizeof(val));
        else if (i == CC_USER)   snprintf(val, sizeof(val), "%s",
                                          c->username[0] ? c->username : "(vazio)");
        else if (i == CC_ENTRAR) {
            snprintf(val, sizeof(val), "%s",
                     c->configured ? "já está ligado" : "pede a senha e liga");
            cor = c->configured ? COL_TEXT_FAINT : COL_AMBER_BRIGHT;
        } else {
            snprintf(val, sizeof(val), "%s",
                     c->configured ? "esquece a chave deste aparelho" : "—");
            cor = c->configured ? COL_ALARM : COL_TEXT_FAINT;
        }
        text_elided(u, (int)(SCRW / 2), (int)(y + 14), cor, 0.54f,
                    SCRW / 2 - PAD_X, val);
    }

    if (u->conta_msg[0] && u->clock < u->conta_msg_ate)
        text(u, (int)PAD_X, FOOT_Y, COL_AMBER, 0.56f, u->conta_msg);
    else
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_FAINT, 0.52f,
             "a escuta é guardada mesmo sem conta — nada se perde aqui");
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
        conta_diz(u, "chave de API guardada");
    } else if (campo == CC_SECRET) {
        snprintf(c->api_secret, sizeof(c->api_secret), "%.*s",
                 (int)sizeof(c->api_secret) - 1, txt);
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "segredo guardado");
    } else if (campo == CC_USER) {
        snprintf(c->username, sizeof(c->username), "%.*s",
                 (int)sizeof(c->username) - 1, txt);
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "usuário guardado");
    } else if (campo == CC_ENTRAR) {
        snprintf(u->conta_senha, sizeof(u->conta_senha), "%.*s",
                 (int)sizeof(u->conta_senha) - 1, txt);
        conta_diz(u, "entrando…");
    }
}

/* A tentativa de login de verdade. Separada para acontecer um quadro DEPOIS
   de o "entrando…" já ter sido pintado. */
static void conta_tenta_entrar(Ui *u)
{
    LastfmConfig *c = &u->conta_cfg;
    int r = lastfm_login(c, c->username, u->conta_senha);
    /* A senha sai da memória assim que a chamada volta, dando certo ou não. */
    memset(u->conta_senha, 0, sizeof(u->conta_senha));

    if (r == 0) {
        lastfm_config_save(c, STYLUS_DATA_DIR);
        conta_diz(u, "entrou — a fila sobe sozinha daqui em diante");
        lastfm_sync_async(STYLUS_DATA_DIR);
    } else if (r == -2) conta_diz(u, "ponha a chave e o segredo da API antes");
    else if (r == -3)   conta_diz(u, "sem rede: ligue o Wi-Fi e tente de novo");
    else if (r == -4)   conta_diz(u, "o last.fm recusou o usuário ou a senha");
    else                conta_diz(u, "faltou o usuário");
}

static void draw_playlists(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    header(u, "PLAYLISTS",
           NULL);
    {
        static const Dica d[] = {
            { BTN_TRIANGLE, (Btn)-1, "estante" },
            { BTN_CIRCLE,   (Btn)-1, "toca" },
            { BTN_UPDOWN,   (Btn)-1, "navegar" },
            { BTN_SQUARE,   (Btn)-1, "salva o que toca" },
            { BTN_SEL,      (Btn)-1, "apaga (2x)" },
            { BTN_R1,       (Btn)-1, "conta" },
            { 0, 0, NULL }
        };
        header_hints(u, "", d);
    }

    if (!u->plists || u->nplists <= 0) {
        text(u, (int)PAD_X, 130, COL_TEXT, 0.72f, "nenhuma lista guardada");
        text(u, (int)PAD_X, 162, COL_TEXT_DIM, 0.58f,
             "ponha um disco e aperte [quadrado] aqui para guardar a noite");
        return;
    }
    UiListGeom lg;
    ui_list_geom(SCRW, SCRH, &lg);
    if (u->pl_sel >= u->nplists) u->pl_sel = u->nplists - 1;
    if (u->pl_sel < 0) u->pl_sel = 0;
    int scroll = (u->pl_sel / lg.rows) * lg.rows;

    for (int r = 0; r < lg.rows; r++) {
        int idx = scroll + r;
        if (idx >= u->nplists) break;
        Playlist *pl = &u->plists[idx];
        float y = lg.y0 + r * lg.row_h;
        if (y + ROW_H > FOOT_Y - 12) break;
        bool is_sel = (idx == u->pl_sel);
        if (is_sel)
            vita2d_draw_rectangle(PAD_X, y, SCRW - 2 * PAD_X, ROW_H - 4,
                                  u->pl_armed ? TINT_ARMED : TINT_SEL_ROW);
        row_thumb(u, NULL, PAD_X + 4, y + 3, (float)(ROW_H - 10), pl->n > 0 ? pl->n : 1);

        float tx = PAD_X + ROW_H + 4;
        float tw = SCRW - PAD_X - tx;
        text_elided(u, (int)tx, (int)(y + 15), is_sel ? COL_AMBER : COL_TEXT, 0.58f, tw,
                    pl->name[0] ? pl->name : "(sem nome)");
        char sub[64];
        snprintf(sub, sizeof(sub), "%d faixa%s", pl->n, pl->n == 1 ? "" : "s");
        text(u, (int)tx, (int)(y + 30), COL_TEXT_DIM, 0.50f, sub);
    }
    if (u->pl_armed)
        text(u, (int)PAD_X, FOOT_Y, COL_ALARM, 0.58f,
             "apagar esta lista? [select] de novo confirma, qualquer outra tecla desiste");
    else {
        char cnt[64];
        snprintf(cnt, sizeof(cnt), "%d lista%s", u->nplists, u->nplists == 1 ? "" : "s");
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.55f, cnt);
    }
}

/* ---------- ouvir enquanto joga ---------- */

/* O plugin Music Premium (cuevavirus) libera o app MÚSICA OFICIAL da Sony
   para continuar tocando dentro dos jogos. Ele NÃO faz um homebrew qualquer
   continuar tocando: o Vita SUSPENDE todo aplicativo que sai da frente, e
   isso não é contornável de dentro de um VPK — o plugin roda no kernel e
   destrava o caminho de áudio DAQUELE app, não deste.
   Dizer isso é melhor do que prometer o que não acontece. */
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
        static const Dica d[] = {
            { BTN_TRIANGLE, (Btn)-1, "volta" },
            { 0, 0, NULL }
        };
        header_hints(u, "OUVIR ENQUANTO JOGA", d);
    }

    const Album *a = player_current_album(p);
    bool tem = plugin_instalado();
    PlayerSignal sig;
    player_signal(p, &sig);
    /* As DUAS condições que decidem, medidas — não prometidas. */
    bool porta = u->bgm_port_ok;
    bool taxa  = sig.bgm_port;

    int y = 92;
    /* Esta tela já afirmou que o Music Premium "destrava o app MÚSICA da
       Sony, não este VPK". Isso foi escrito quando o app NÃO pedia a porta
       BGM — e sem pedir, nenhum plugin teria como manter processo nenhum
       vivo. O autor do plugin anuncia "background music play for ANY game or
       application", e cita o VitaShell e o ElevenMPV, que são homebrew.
       Agora que a porta é pedida, a resposta honesta é: não sabemos daqui,
       dá para saber em dez segundos no aparelho. Então a tela MOSTRA o
       estado e manda experimentar, em vez de decidir pela pessoa. */
    text(u, (int)PAD_X, y, tem ? COL_AMBER : COL_TEXT_DIM, 0.66f,
         tem ? "Music Premium: instalado"
             : "Music Premium: não achei o plugin");
    y += 30;

    char lin[160];
    snprintf(lin, sizeof(lin), "porta BGM pedida no arranque:  %s",
             porta ? "sim" : "não");
    text(u, (int)PAD_X, y, porta ? COL_AMBER : COL_ALARM, 0.56f, lin);
    y += 24;
    if (sig.rate_out > 0)
        snprintf(lin, sizeof(lin), "taxa da faixa (<= 47999 Hz):   %s  (%ld Hz)",
                 taxa ? "sim" : "não", sig.rate_out);
    else
        snprintf(lin, sizeof(lin), "taxa da faixa:                  ponha um disco");
    text(u, (int)PAD_X, y, taxa ? COL_AMBER : COL_TEXT_DIM, 0.56f, lin);
    y += 32;

    if (tem && porta && taxa) {
        text_elided(u, (int)PAD_X, y, COL_AMBER, 0.58f, SCRW - 2 * PAD_X,
            "as duas valem: ENTRE NUM JOGO e veja se o som segue.");
        y += 24;
        text_elided(u, (int)PAD_X, y, COL_TEXT_DIM, 0.54f, SCRW - 2 * PAD_X,
            "se seguir, é isto e mais nada. se não, o desvio abaixo funciona sempre.");
    } else {
        text_elided(u, (int)PAD_X, y, COL_TEXT, 0.56f, SCRW - 2 * PAD_X,
            "O Vita suspende qualquer aplicativo que sai da frente. Só a porta");
        y += 22;
        text_elided(u, (int)PAD_X, y, COL_TEXT, 0.56f, SCRW - 2 * PAD_X,
            "BGM, com o plugin de kernel, o impede — e ela pede as duas acima.");
    }
    y += 34;

    text(u, (int)PAD_X, y, COL_AMBER, 0.60f, "o desvio, que funciona sempre:");
    y += 26;
    const char *passos[] = {
        "1.  aqui: [start] sai — a faixa e a posição ficam guardadas",
        "2.  abra o app MÚSICA e ponha o mesmo disco (é a MESMA pasta)",
        "3.  entre no jogo; o plugin mantém o som",
        "4.  ao voltar, este app retoma exatamente onde parou, em pausa",
        NULL
    };
    for (int i = 0; passos[i]; i++, y += 24)
        text_elided(u, (int)PAD_X + 10, y, COL_TEXT, 0.54f,
                    SCRW - 2 * PAD_X - 10, passos[i]);

    y += 18;
    if (a && a->key[0]) {
        /* O app Música navega PASTAS. Dizer qual é poupa a busca — é a mesma
           ux0:music que esta estante varreu. */
        char linha[MAX_PATH_LEN + 64];
        snprintf(linha, sizeof(linha), "no app Música, a pasta é:  %s", a->key);
        text_elided(u, (int)PAD_X, y, COL_AMBER, 0.54f, SCRW - 2 * PAD_X, linha);
        y += 24;
        const Track *t = player_current_track(p);
        if (t) {
            snprintf(linha, sizeof(linha), "e a faixa:  %s", t->file);
            text_elided(u, (int)PAD_X, y, COL_TEXT_DIM, 0.52f, SCRW - 2 * PAD_X, linha);
        }
    } else {
        text(u, (int)PAD_X, y, COL_TEXT_DIM, 0.54f,
             "ponha um disco e volte aqui para ver a pasta dele");
    }

    if (!tem)
        text_elided(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.52f, SCRW - 2 * PAD_X,
            "o plugin vai em ur0:tai/music_premium.skprx, na seção *KERNEL do config.txt");
    else
        text(u, (int)PAD_X, FOOT_Y, COL_TEXT_DIM, 0.52f,
             "com a tela apagada ([R1+L1]) este app segue tocando por horas");
}

/* ---------- a varredura ---------- */

void ui_draw_scanning(Ui *u, const char *where, int files)
{
    if (!u || !u->font) return;
    u->clock++;
    u->halo_phase += 0.12f;
    vita2d_start_drawing();
    vita2d_clear_screen();
    draw_bg();

    float cx = SCRW / 2.0f, cy = SCRH / 2.0f - 20;
    draw_halo(cx, cy, 78, u->halo_phase);
    draw_disc(cx, cy, 76, 0.0f, 12, -1, u->halo_phase * 3.0f, NULL, 1.0f);

    const char *t = "procurando os discos";
    text(u, (int)(cx - text_w(u, 0.78f, t) / 2), (int)cy + 130, COL_AMBER, 0.78f, t);

    char line[160];
    snprintf(line, sizeof(line), "%d arquivo%s", files, files == 1 ? "" : "s");
    text(u, (int)(cx - text_w(u, 0.58f, line) / 2), (int)cy + 156, COL_TEXT, 0.58f, line);

    if (where && where[0]) {
        char b[512];
        elide(u, b, sizeof(b), 0.50f, SCRW - 2 * PAD_X, where);
        text(u, (int)(cx - text_w(u, 0.50f, b) / 2), (int)cy + 178, COL_TEXT_DIM, 0.50f, b);
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
        elide(u, b, sizeof(b), 0.46f, SCRW - 120.0f, t->title);
        text(u, (int)(SCRW / 2 - text_w(u, 0.46f, b) / 2), SCRH / 2 + 46,
             RGBA8(60, 46, 20, 255), 0.46f, b);
    }
}

int ui_frame(Ui *u, Library *lib, Player *p)
{
    u->clock++;
    u->loaded_this_frame = 0;

    /* entra em repouso sozinho depois de um tempo parado COM música tocando:
       parado sem música é alguém escolhendo um disco, e apagar a tela na cara
       de quem está escolhendo é hostil */
    if (!u->resting && player_state(p) == PLAYER_PLAYING) {
        if (++u->rest_idle > 60 * 90) u->resting = true;
    } else if (player_state(p) != PLAYER_PLAYING) {
        u->rest_idle = 0;
    }

    vita2d_start_drawing();
    if (u->resting) {
        vita2d_clear_screen();
        draw_rest(u, p);
        vita2d_end_drawing();
        vita2d_swap_buffers();
        return 0;
    }
    vita2d_clear_screen();
    draw_bg();

    if (u->view == VIEW_SHELF)      draw_shelf(u, lib, p);
    else if (u->view == VIEW_DECK)  draw_deck(u, lib, p);
    else if (u->view == VIEW_RECS)  draw_recs(u, lib, p);
    else if (u->view == VIEW_HANDOFF) draw_handoff(u, lib, p);
    else if (u->view == VIEW_CONTA) draw_conta(u, lib, p);
    else                            draw_playlists(u, lib, p);

    /* O teclado do sistema pinta DEPOIS de tudo, senão fica atrás da tela.
       Chamada em todo quadro, tenha ou não caixa aberta. */
    ime_desenhar();
    vita2d_end_drawing();
    vita2d_swap_buffers();
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

/* O painel de toque devolve 0..1919 x 0..1087 — o DOBRO da tela, porque ele
   tem resolução maior que ela. Usar as coordenadas cruas põe todo toque no
   canto superior esquerdo, e é o erro que se comete uma vez. */
static void touch_read(Ui *u)
{
    SceTouchData td;
    memset(&td, 0, sizeof(td));
    u->touch_was_down = u->touch_down;
    u->touch_down = false;
    if (sceTouchPeek(SCE_TOUCH_PORT_FRONT, &td, 1) >= 0 && td.reportNum > 0) {
        u->touch_down = true;
        u->touch_x = td.report[0].x / 2;
        u->touch_y = td.report[0].y / 2;
    }
    if (u->touch_down && !u->touch_was_down) {
        u->touch_start_x = u->touch_x;
        u->touch_start_y = u->touch_y;
        u->touch_frames = 0;
        u->touch_moved = false;
    } else if (u->touch_down) {
        u->touch_frames++;
        int dx = u->touch_x - u->touch_start_x;
        int dy = u->touch_y - u->touch_start_y;
        if (dx * dx + dy * dy > 18 * 18) u->touch_moved = true;
    }
}

static bool tap_released(const Ui *u)
{
    /* Um toque é curto e parado. Sem exigir as duas coisas, todo arrasto
       termina disparando o item onde o dedo largou. */
    return u->touch_was_down && !u->touch_down && !u->touch_moved &&
           u->touch_frames < 30;
}

static bool in_rect(int x, int y, float rx, float ry, float rw, float rh)
{
    return x >= rx && x < rx + rw && y >= ry && y < ry + rh;
}

bool ui_resting(const Ui *u) { return u && u->resting; }
float ui_scrub(const Ui *u) { return (u && u->scrubbing) ? u->scrub_to : -1.0f; }

int ui_handle_input(Ui *u)
{
    static uint32_t prev = 0;
    static uint32_t held_dir = 0;
    static int held_frames = 0;

    SceCtrlData c;
    memset(&c, 0, sizeof(c));
    sceCtrlPeekBufferPositive(0, &c, 1);
    uint32_t cur = c.buttons;
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

    /* Com o teclado do sistema na frente, ele é o dono da entrada. Sem esta
       porta, o [X] que confirma o texto ALSO confirmava a faixa marcada
       atrás, e o [O] que cancela saía da tela junto — a pessoa digitava uma
       chave de API e voltava para a estante com um disco tocando.

       O `prev` já foi atualizado lá em cima, então nada fica "preso": ao
       fechar o teclado, o próximo quadro vê os botões no estado real. */
    if (ime_aberto()) {
        char txt[256];
        int r = ime_poll(txt, sizeof(txt));
        if (r == 1 && u->conta_campo >= 0) conta_recebeu(u, u->conta_campo, txt);
        if (r != 0) u->conta_campo = -1;
        memset(txt, 0, sizeof(txt));   /* pode ter sido uma senha */
        return 0;
    }
    /* O login foi pedido no quadro passado e o "entrando…" já apareceu: é
       agora que se fala com a internet. Ver conta_tenta_entrar. */
    if (u->conta_senha[0]) { conta_tenta_entrar(u); return 0; }

    touch_read(u);

    /* No repouso, QUALQUER coisa acorda e nada mais acontece: senão a tecla
       que acorda também troca de disco no escuro. */
    if (u->resting) {
        if (edge || u->touch_down) { u->resting = false; u->rest_idle = 0; }
        return 0;
    }
    if (edge || u->touch_down) u->rest_idle = 0;

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
        if (edge & (SCE_CTRL_TRIANGLE | SCE_CTRL_CIRCLE)) u->jump_open = false;
        if (edge & SCE_CTRL_CROSS) { u->jump_open = false; action = 19; }
        if (edge & SCE_CTRL_START) return -1;
        return action;
    }
    if (u->view == VIEW_SHELF) {
        if (edge & SCE_CTRL_DOWN)  { u->sel += SHELF_COLS; action = 1; }
        if (edge & SCE_CTRL_UP)    { if (u->sel >= SHELF_COLS) u->sel -= SHELF_COLS; action = 1; }
        if (edge & SCE_CTRL_RIGHT) { u->sel++; action = 1; }
        if (edge & SCE_CTRL_LEFT)  { if (u->sel > 0) u->sel--; action = 1; }
        if (edge & SCE_CTRL_CROSS)  { u->view = VIEW_DECK; action = 2; }
        if (edge & SCE_CTRL_CIRCLE) { u->view = VIEW_DECK; action = 2; }
        /* [tri] leva ao que já está tocando SEM trocar de disco: o [tri] do
           deck volta para cá, e uma tecla que só funciona num sentido é
           metade de um caminho. */
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_DECK; action = 0; }
        if (edge & SCE_CTRL_L1) { u->view = VIEW_RECS; action = 8; }
        if (edge & SCE_CTRL_R1) { u->view = VIEW_PLAYLISTS; action = 9; }
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
        if (edge & SCE_CTRL_L1) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_R1) { u->view = VIEW_PLAYLISTS; action = 9; }
    } else if (u->view == VIEW_PLAYLISTS) {
        bool armed_before = u->pl_armed;
        if (edge & SCE_CTRL_DOWN) { u->pl_sel++; action = 1; }
        if (edge & SCE_CTRL_UP)   { if (u->pl_sel > 0) u->pl_sel--; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CROSS)    { u->view = VIEW_DECK; action = 12; }
        if (edge & SCE_CTRL_CIRCLE)   { u->view = VIEW_DECK; action = 12; }
        if (edge & SCE_CTRL_SQUARE)   action = 13;
        if (edge & SCE_CTRL_L1) { u->view = VIEW_RECS; action = 8; }
        if (edge & SCE_CTRL_R1) { u->view = VIEW_CONTA; action = 0; }
        /* Apagar era [R2]. O Vita NÃO TEM R2 — nem L2: o hardware tem quatro
           gatilhos de menos, e o sceCtrlPeekBufferPositive nunca põe esse bit.
           A tecla estava escrita no rodapé e não existia em aparelho nenhum. */
        if (edge & SCE_CTRL_SELECT) {
            if (u->pl_armed) { action = 17; u->pl_armed = false; }
            else u->pl_armed = true;
        }
        /* qualquer outra tecla desarma: confirmar tem que exigir a MESMA */
        if (armed_before && action && action != 17) u->pl_armed = false;
    } else if (u->view == VIEW_CONTA) {
        if (edge & SCE_CTRL_UP)   { if (--u->conta_sel < 0) u->conta_sel = CC_N - 1; action = 1; }
        if (edge & SCE_CTRL_DOWN) { if (++u->conta_sel >= CC_N) u->conta_sel = 0; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_L1) { u->view = VIEW_PLAYLISTS; action = 9; }
        if (edge & SCE_CTRL_R1) { u->view = VIEW_SHELF; action = 10; }
        if (edge & (SCE_CTRL_CROSS | SCE_CTRL_CIRCLE)) {
            LastfmConfig *cf = &u->conta_cfg;
            int i = u->conta_sel;
            if (i == CC_ENTRAR) {
                if (!cf->api_key[0] || !cf->api_secret[0])
                    conta_diz(u, "ponha a chave e o segredo da API antes");
                else if (!cf->username[0])
                    conta_diz(u, "ponha o usuário antes");
                else if (ime_abrir("senha do last.fm", "", 63, true) == 0)
                    u->conta_campo = CC_ENTRAR;
            } else if (i == CC_SAIR) {
                if (cf->configured) {
                    /* Só a chave de sessão vai embora. As chaves de API
                       ficam: são da pessoa, custaram uma visita ao site, e
                       apagá-las junto transformaria "sair" em "recomeçar do
                       zero". A FILA também fica — sair de uma conta não é
                       motivo para jogar escuta fora. */
                    cf->sk[0] = '\0';
                    cf->configured = false;
                    lastfm_config_save(cf, STYLUS_DATA_DIR);
                    conta_diz(u, "saiu — a escuta continua sendo guardada");
                }
            } else {
                static const char *TIT[] = { "chave de API do last.fm",
                                             "segredo da API", "usuário do last.fm" };
                const char *ini = i == CC_KEY ? cf->api_key
                                : i == CC_SECRET ? cf->api_secret : cf->username;
                if (ime_abrir(TIT[i], ini, 100, i == CC_SECRET) == 0)
                    u->conta_campo = i;
            }
        }
    } else if (u->view == VIEW_HANDOFF) {
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
        if ((edge & SCE_CTRL_L1) && !(cur & SCE_CTRL_R1)) { u->view = VIEW_RECS; action = 8; }
        /* na SOLTURA, e só se nenhum combo tiver consumido o R1 */
        if ((solto & SCE_CTRL_R1) && !r1_usado && !(cur & SCE_CTRL_L1)) {
            u->view = VIEW_PLAYLISTS; action = 9;
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
    }
    if (edge & SCE_CTRL_START) action = -1;

    /* ---------- o toque ----------
       O Vita tem uma tela sensível ao toque e o app inteiro a ignorava: pôr
       um disco era navegar uma grade com o direcional, item por item, com a
       coisa desenhada bem ali. */
    if (u->view == VIEW_SHELF) {
        UiShelfGeom g;
        ui_shelf_geom(SCRW, SCRH, &g);
        if (tap_released(u)) {
            for (int r = 0; r < UI_SHELF_ROWS; r++)
                for (int cix = 0; cix < UI_SHELF_COLS; cix++) {
                    float x = g.x0 + cix * (g.card_w + g.gap);
                    float y = g.y0 + r * (g.card_h + g.gap);
                    if (!in_rect(u->touch_x, u->touch_y, x, y, g.card_w, g.card_h))
                        continue;
                    int idx = (u->sel / UI_SHELF_PAGE) * UI_SHELF_PAGE
                              + r * UI_SHELF_COLS + cix;
                    u->sel = idx;
                    u->view = VIEW_DECK;
                    action = 2;
                }
        } else if (u->touch_was_down && !u->touch_down && u->touch_moved) {
            /* arrastar de lado vira página; a grade é paginada, não rolada */
            int dx = u->touch_x - u->touch_start_x;
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
        if (u->touch_down && (u->scrubbing ||
            in_rect(u->touch_start_x, u->touch_start_y, bx, band_y, bw, band_h))) {
            u->scrubbing = true;
            float f = ((float)u->touch_x - bx) / (bw > 1 ? bw : 1);
            if (f < 0) f = 0;
            if (f > 1) f = 1;
            u->scrub_to = f;
        } else if (u->scrubbing && !u->touch_down) {
            u->scrubbing = false;
            action = 18;                     /* confirma a busca */
        } else if (tap_released(u)) {
            float dx = (float)u->touch_x - g.cx, dy = (float)u->touch_y - g.cy;
            if (dx * dx + dy * dy < g.r * g.r) action = 4;   /* o disco: pausa */
        } else if (u->touch_was_down && !u->touch_down && u->touch_moved &&
                   !u->scrubbing) {
            int dx = u->touch_x - u->touch_start_x;
            if (dx < -70) action = 5;
            else if (dx > 70) action = 6;
        }
    } else {
        UiListGeom lg;
        ui_list_geom(SCRW, SCRH, &lg);
        if (tap_released(u)) {
            for (int r = 0; r < lg.rows; r++) {
                float y = lg.y0 + r * lg.row_h;
                if (!in_rect(u->touch_x, u->touch_y, lg.x, y, lg.w, lg.row_h)) continue;
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
    u->font = vita2d_load_default_pvf();
    if (!u->font) { free(u); return NULL; }
    u->view = VIEW_SHELF;
    return u;
}

void ui_destroy(Ui *u)
{
    if (!u) return;
    cache_clear(u);
    if (u->font) vita2d_free_pvf(u->font);
    free(u);
}

int ui_selected(const Ui *u)      { return u ? u->sel : 0; }
int ui_playlist_idx(const Ui *u)  { return u ? u->pl_sel : 0; }
int ui_rec_idx(const Ui *u)       { return u ? u->rec_sel : 0; }
int ui_jump_letter(const Ui *u)   { return u ? u->jump_letter : 0; }
void ui_set_sel(Ui *u, int i)     { if (u) u->sel = i < 0 ? 0 : i; }


int ui_view_dbg(const Ui *u) { return u ? (int)u->view : 0; }

void ui_set_bgm(Ui *u, bool ok) { if (u) u->bgm_port_ok = ok; }

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

