#include "ui.h"
#include "paths.h"
#include "ui_layout.h"

#include <vita2d.h>
#include <psp2/ctrl.h>

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

typedef enum { VIEW_SHELF = 0, VIEW_DECK, VIEW_RECS, VIEW_PLAYLISTS } View;

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

struct Ui {
    vita2d_pvf *font;
    View view;
    int sel;
    int pl_sel;
    int rec_sel;
    float halo_phase;
    float disc_angle;      /* acumula: o disco PÁRA quando a música pára */

    CoverSlot cache[COVER_CACHE];
    unsigned clock;

    /* orçamento de carga: no máximo um álbum por quadro ganha tags e capa,
       senão rolar a estante trava a cada disco novo */
    int loaded_this_frame;

    Playlist *plists;
    int nplists;
    const Track **recs;
    int nrecs;
    bool pl_armed;
};

/* ---------- primitivas ---------- */

static void fill_circle(float cx, float cy, float r, unsigned int color)
{
    if (r <= 0) return;
    int y0 = (int)(cy - r), y1 = (int)(cy + r);
    for (int y = y0; y <= y1; y++) {
        float dy = (float)y - cy;
        float d2 = r * r - dy * dy;
        if (d2 < 0) continue;
        float half = sqrtf(d2);
        int hx0 = (int)(cx - half), hx1 = (int)(cx + half);
        if (hx1 > hx0) vita2d_draw_rectangle(hx0, y, (float)(hx1 - hx0 + 1), 1, color);
    }
}

static void ring_circle(float cx, float cy, float r, float th, unsigned int color)
{
    if (r <= 0 || th <= 0) return;
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

/* ---------- o disco ---------- */

/* Os sulcos são as faixas DESTE disco, e o anel aceso é onde a agulha está.
   Cinco anéis fixos desenhariam o mesmo objeto para um single e para um LP. */
static void draw_disc(float cx, float cy, float r, float progress,
                      int ntracks, int track_idx, float angle)
{
    if (r < 6) { alpha_fill(cx, cy, r, 0.5f, COL_AMBER); return; }
    alpha_fill(cx, cy, r, 0.10f, COL_AMBER);

    int n = ntracks > 0 ? ntracks : 1;
    if (n > 24) n = 24;             /* mais que isso vira ruído, não contagem */
    for (int i = 0; i < n; i++) {
        float rr = r * (1.0f - (float)(i + 1) / (float)(n + 2));
        bool here = (track_idx >= 0 && ntracks > 0 &&
                     i == (track_idx * n) / (ntracks > 0 ? ntracks : 1));
        alpha_ring(cx, cy, rr, here ? 1.6f : 1.0f, here ? 0.30f : 0.11f, COL_AMBER);
    }

    /* raio é tempo: da borda para o centro */
    float read_r = r * (1.0f - progress * 0.86f);
    alpha_ring(cx, cy, read_r, 2.5f, 0.34f, COL_AMBER_BRIGHT);

    /* o selo, com uma marca que gira — é o que diz que ele ESTÁ girando */
    alpha_fill(cx, cy, r * 0.16f, 0.16f, COL_AMBER);
    float mx = cx + cosf(angle) * r * 0.12f;
    float my = cy + sinf(angle) * r * 0.12f;
    alpha_fill(mx, my, 2.5f, 0.9f, COL_AMBER_BRIGHT);
    alpha_fill(cx, cy, 3.0f, 0.85f, COL_AMBER);
}

/* O braço é o FACHO, não um tubo de alumínio: quase toda a luz mora na ponta,
   o corpo começa a 38% do caminho, e levantado ele apaga. */
static void draw_needle(float cx, float cy, float r, float phase, float progress, bool live)
{
    float ang = -1.5707963f + phase * 0.18f;
    float read_r = r * (1.0f - progress * 0.86f);
    float px = cx + cosf(ang) * read_r;
    float py = cy + sinf(ang) * read_r;
    float ox = cx + cosf(ang) * (r * 1.45f);
    float oy = cy + sinf(ang) * (r * 1.45f);

    float a = live ? 1.0f : 0.25f;
    /* corpo: começa longe do pivô e vai acendendo */
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
    /* a agulha: uma cruz curta e quente */
    if (live) {
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
        snprintf(line, sizeof(line), "%s   %s", lib->roots[i].path,
                 lib->roots[i].opened ? "(abriu)" : "(não existe)");
        text_elided(u, (int)PAD_X + 12, y, lib->roots[i].opened ? COL_TEXT : COL_TEXT_FAINT,
                    0.54f, SCRW - 2 * PAD_X - 12, line);
        y += 22;
    }
    y += 14;
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
           "[X] toca   [tri] o que toca   [sel] sorteio   [L1] recs   [R1] playlists   [start] sai");

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
                draw_disc(ix + side / 2, iy + side / 2, side / 2.2f,
                          0.18f, a->ntracks, -1, u->disc_angle);
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
    if (live) u->disc_angle += 0.06f;   /* o disco PÁRA quando a música pára */

    UiDeckGeom g;
    ui_deck_geom(SCRW, SCRH, &g);
    float cx = g.cx, cy = g.cy, base_r = g.r;
    draw_halo(cx, cy, base_r, u->halo_phase);
    draw_disc(cx, cy, base_r, progress, a->ntracks, player_track_idx(p), u->disc_angle);
    draw_needle(cx, cy, base_r, u->halo_phase, progress, live);

    float tx = g.text_x;
    float tw = g.text_w;

    header(u, live ? "AGORA  ·  TOCANDO" : "AGORA  ·  PAUSADO",
           "[tri] estante   [L1] recs   [R1] playlists");

    text_elided(u, (int)tx, 126, COL_AMBER, 0.72f, tw, a->artist[0] ? a->artist : "—");
    text_elided(u, (int)tx, 168, COL_TEXT, 1.00f, tw, a->album);
    text_elided(u, (int)tx, 214, COL_TEXT, 0.66f, tw, t ? t->title : "—");

    char cur[16], tot[16], info[160];
    fmt_time(cur, sizeof(cur), pos);
    fmt_time(tot, sizeof(tot), dur);
    snprintf(info, sizeof(info), "%s / %s   ·   faixa %d de %d",
             cur, tot, player_track_idx(p) + 1, player_track_count(p));
    text_elided(u, (int)tx, 244, COL_TEXT_DIM, 0.56f, tw, info);

    vita2d_draw_rectangle(tx, 262, tw, 3, COL_BAR_BED);
    if (dur > 0) vita2d_draw_rectangle(tx, 262, tw * progress, 3, COL_AMBER);

    /* a ORDEM DO LADO: onde não há letra, é para a contracapa que se olha */
    int shown = 0;
    int from = player_track_idx(p) - 2;
    if (from < 0) from = 0;
    for (int i = from; i < a->ntracks && shown < g.list_rows; i++, shown++) {
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

    const char *rep = "rep todas";
    switch (player_repeat(p)) {
    case REPEAT_OFF: rep = "rep off"; break;
    case REPEAT_ONE: rep = "rep 1";   break;
    default: break;
    }
    char ctl[200];
    snprintf(ctl, sizeof(ctl), "%s   ·   %s   ·   %s",
             live ? "[O] pausa" : "[O] recomeça",
             rep, player_shuffle(p) ? "sorteio ligado" : "sorteio desligado");
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
    else draw_disc(x + side / 2, y + side / 2, side / 2.2f, 0.18f, ntracks, -1, u->disc_angle);
}

static void draw_recs(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    header(u, "RECOMENDADO", "[tri] estante   [O] toca daqui   [cima/baixo] navega");

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

static void draw_playlists(Ui *u, Library *lib, Player *p)
{
    (void)lib; (void)p;
    header(u, "PLAYLISTS",
           "[tri] estante   [O] toca   [quad] salva o que toca   [sel] apaga (2x)");

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
    draw_disc(cx, cy, 76, 0.0f, 12, -1, u->halo_phase * 3.0f);

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

int ui_frame(Ui *u, Library *lib, Player *p)
{
    u->clock++;
    u->loaded_this_frame = 0;

    vita2d_start_drawing();
    vita2d_clear_screen();
    draw_bg();

    if (u->view == VIEW_SHELF)      draw_shelf(u, lib, p);
    else if (u->view == VIEW_DECK)  draw_deck(u, lib, p);
    else if (u->view == VIEW_RECS)  draw_recs(u, lib, p);
    else                            draw_playlists(u, lib, p);

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
    prev = cur;

    uint32_t dir_now = cur & DPAD;
    if (dir_now != held_dir) { held_dir = dir_now; held_frames = 0; }
    else if (dir_now) {
        held_frames++;
        if (held_frames > REPEAT_DELAY &&
            ((held_frames - REPEAT_DELAY) % REPEAT_EVERY) == 0)
            edge |= dir_now;
    }

    int action = 0;
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
        if (edge & SCE_CTRL_R1) { u->view = VIEW_SHELF; action = 10; }
        /* Apagar era [R2]. O Vita NÃO TEM R2 — nem L2: o hardware tem quatro
           gatilhos de menos, e o sceCtrlPeekBufferPositive nunca põe esse bit.
           A tecla estava escrita no rodapé e não existia em aparelho nenhum. */
        if (edge & SCE_CTRL_SELECT) {
            if (u->pl_armed) { action = 17; u->pl_armed = false; }
            else u->pl_armed = true;
        }
        /* qualquer outra tecla desarma: confirmar tem que exigir a MESMA */
        if (armed_before && action && action != 17) u->pl_armed = false;
    } else { /* deck */
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CIRCLE)   action = 4;
        if (edge & SCE_CTRL_CROSS)    action = 4;
        if (edge & SCE_CTRL_RIGHT)    action = 5;
        if (edge & SCE_CTRL_LEFT)     action = 6;
        if (edge & SCE_CTRL_UP)       action = 16;
        if (edge & SCE_CTRL_DOWN)     action = 7;
        if (edge & SCE_CTRL_SQUARE)   action = 7;
        if (edge & SCE_CTRL_L1) { u->view = VIEW_RECS; action = 8; }
        if (edge & SCE_CTRL_R1) { u->view = VIEW_PLAYLISTS; action = 9; }
        if (edge & SCE_CTRL_SELECT)   action = 14;
    }
    if (edge & SCE_CTRL_START) action = -1;

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
int ui_view(const Ui *u)          { return u ? (int)u->view : (int)VIEW_SHELF; }

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

void ui_set_recs(Ui *u, const Track **recs, int nrecs)
{
    if (!u) return;
    u->recs = recs;
    u->nrecs = nrecs;
    if (u->rec_sel >= u->nrecs) u->rec_sel = u->nrecs > 0 ? u->nrecs - 1 : 0;
}
