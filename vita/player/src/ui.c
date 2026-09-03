#include "ui.h"

#include <vita2d.h>
#include <psp2/ctrl.h>
#include <psp2/touch.h>

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define SCRW 960
#define SCRH 544

/* paleta Fri: quase-preto frio + âmbar (única cor viva) */
#define COL_AMBER        0xFFFFAA28
#define COL_AMBER_BRIGHT 0xFFFFC56B
#define COL_TEXT         0xFFB8C0D0
#define COL_TEXT_DIM     0xFF5A6270
#define COL_COLD         0xFF20304A

typedef enum { VIEW_SHELF = 0, VIEW_DECK, VIEW_RECS, VIEW_PLAYLISTS } View;

struct Ui {
    vita2d_pvf *font;
    View view;
    int sel;
    int pl_sel;        /* playlist selecionada */
    int rec_sel;       /* faixa recomendada selecionada */
    int shelf_scroll;
    float halo_phase;

    /* dados carregados e injetados pelo main a cada loop */
    Playlist *plists;
    int nplists;
    const Track **recs;
    int nrecs;
};

/* ---------- círculos (vita2d não tem primitiva de círculo) ---------- */
static void fill_circle(float cx, float cy, float r, unsigned int color)
{
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
    int ymin = (int)(cy - r - th), ymax = (int)(cy + r + th);
    for (int y = ymin; y <= ymax; y++) {
        float dy = (float)y - cy;
        if (fabsf(dy) > r + th) continue;
        float halfO = sqrtf((r + th) * (r + th) - dy * dy);
        int xo0 = (int)(cx - halfO), xo1 = (int)(cx + halfO);
        float dI = (r - th) * (r - th) - dy * dy;
        if (dI >= 0) {
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
    unsigned int c = (rgb & 0x00FFFFFF) | ((unsigned int)(a * 255.0f) << 24);
    fill_circle(cx, cy, r, c);
}

static void alpha_ring(float cx, float cy, float r, float th, float a, unsigned int rgb)
{
    unsigned int c = (rgb & 0x00FFFFFF) | ((unsigned int)(a * 255.0f) << 24);
    ring_circle(cx, cy, r, th, c);
}

/* ---------- capa ---------- */
static vita2d_texture *cover_to_tex(const Album *a)
{
    if (!a->cover || a->cover_len < 4) return NULL;
    char m[3]; memcpy(m, a->cover, 3);
    if (m[0] == (char)0xFF && m[1] == (char)0xD8)
        return vita2d_load_JPEG_buffer(a->cover, (unsigned long)a->cover_len);
    if (m[0] == (char)0x89 && m[1] == 'P' && m[2] == 'N')
        return vita2d_load_PNG_buffer(a->cover);
    return NULL;
}

/* ---------- disco (AGORA) ---------- */
static void draw_disc(float cx, float cy, float r, float progress, int ntracks)
{
    alpha_fill(cx, cy, r, 0.10f, COL_AMBER);
    float read_r = r * (1.0f - progress); /* raio é tempo: borda -> centro */

    /* sulcos: um anel por faixa */
    for (int i = 0; i < ntracks; i++) {
        float rr = r * (1.0f - (float)(i + 1) / (float)(ntracks + 2));
        alpha_ring(cx, cy, rr, 1.0f, 0.12f, COL_AMBER);
    }
    /* anel de leitura vivo */
    alpha_ring(cx, cy, read_r, 3.0f, 0.34f, COL_AMBER_BRIGHT);
    alpha_fill(cx, cy, 5.0f, 0.8f, COL_AMBER);
}

static void draw_needle(float cx, float cy, float r, float phase, float progress)
{
    float ang = -M_PI_2 + phase * 0.35f;
    float read_r = r * (1.0f - progress);
    float px = cx + cosf(ang) * read_r;
    float py = cy + sinf(ang) * read_r;
    vita2d_draw_line(cx, cy, px, py, 0x2AFFAA28);
    alpha_fill(px, py, 6.0f, 0.9f, COL_AMBER_BRIGHT);
    alpha_fill(px, py, 14.0f, 0.25f, COL_AMBER);
}

static void draw_halo(float cx, float cy, float base_r, float phase)
{
    float r = base_r * (1.0f + 0.03f * sinf(phase * 1.7f));
    alpha_ring(cx, cy, r * 1.12f, 18.0f, 0.05f, COL_COLD);
    alpha_ring(cx, cy, r * 1.05f, 8.0f, 0.09f, COL_COLD);
}

/* ---------- estante ---------- */
static void shelf_cover_at(float x, float y, float cw, Album *a, int is_sel)
{
    vita2d_texture *tex = cover_to_tex(a);
    float cw_area = cw - 14.0f;
    if (tex) {
        float sx = cw_area / (float)vita2d_texture_get_width(tex);
        float sy = cw_area / (float)vita2d_texture_get_height(tex);
        vita2d_draw_texture_scale(tex, x + 7, y + 7, sx, sy);
        vita2d_free_texture(tex);
    } else {
        draw_disc(x + 7 + cw_area / 2, y + 7 + cw_area / 2, cw_area / 2.3f, 0.2f, a->ntracks);
    }

    /* moldura âmbar no selecionado */
    if (is_sel) {
        vita2d_draw_rectangle(x, y, cw, 3, COL_AMBER);
        vita2d_draw_rectangle(x, y + cw_area + 13, cw, 3, COL_AMBER);
        vita2d_draw_rectangle(x, y, 3, cw_area + 13, COL_AMBER);
        vita2d_draw_rectangle(x + cw, y, 3, cw_area + 13, COL_AMBER);
    }
}

static void draw_shelf(Ui *u, Library *lib, Player *p)
{
    (void)p;
    int n = lib->nalbums;
    const int COLS = 3;
    int vis = COLS * 3;
    int scroll = u->sel / vis * vis;
    if (scroll < 0) scroll = 0;
    u->shelf_scroll = scroll;

    float card_w = 296, card_h = 330, gap = 26;
    float mx0 = (SCRW - (COLS * card_w + (COLS - 1) * gap)) / 2.0f;
    float my0 = 76;

    for (int r = 0; r < 3; r++) {
        for (int c = 0; c < COLS; c++) {
            int idx = scroll + r * COLS + c;
            if (idx >= n) continue;
            Album *a = library_album(lib, idx);
            if (!a) continue;
            float x = mx0 + c * (card_w + gap);
            float y = my0 + r * (card_h + gap);
            if (y > SCRH - 60) continue;
            int is_sel = (idx == u->sel);
            vita2d_draw_rectangle(x, y, card_w, card_h, is_sel ? 0x1DFFAA28 : 0x0A0E15);
            shelf_cover_at(x, y, card_w, a, is_sel);
            /* rótulo */
            unsigned int acol = is_sel ? COL_AMBER : COL_TEXT_DIM;
            vita2d_pvf_draw_text(u->font, (int)x + 8, (int)(y + card_h - 44), acol, 0.78f, a->album);
            vita2d_pvf_draw_text(u->font, (int)x + 8, (int)(y + card_h - 24), COL_TEXT_DIM, 0.56f, a->artist);
        }
    }

    vita2d_pvf_draw_text(u->font, 24, 22, COL_AMBER, 1.0f, "ESTANTE");
    char cnt[48];
    snprintf(cnt, sizeof(cnt), "%d discos", n);
    vita2d_pvf_draw_text(u->font, 24, SCRH - 54, COL_TEXT_DIM, 0.6f, cnt);
    vita2d_pvf_draw_text(u->font, 24, SCRH - 38, COL_TEXT_DIM, 0.55f,
                         "[cross] toca  [sel] sorteio  [L1] recs  [R1] playlists");
}

static void draw_deck(Ui *u, Library *lib, Player *p)
{
    const Album *a = player_current_album(p);
    if (!a) { draw_shelf(u, lib, p); return; }
    const Track *t = player_current_track(p);
    if (!t) t = &a->tracks[0];

    int dur = t->seconds > 0 ? t->seconds : 1;
    int pos = player_track_seconds(p);
    float progress = (float)pos / (float)dur;
    if (progress < 0) progress = 0;
    if (progress > 1) progress = 1;

    u->halo_phase += 0.05f;

    float cx = 300, cy = 280, base_r = 150;
    draw_halo(cx, cy, base_r, u->halo_phase);
    draw_disc(cx, cy, base_r, progress, a->ntracks);
    draw_needle(cx, cy, base_r, u->halo_phase, progress);

    float tx = cx + base_r + 34;
    vita2d_pvf_draw_text(u->font, (int)tx, 150, COL_AMBER, 0.9f, a->artist);
    vita2d_pvf_draw_text(u->font, (int)tx, 196, COL_TEXT, 1.1f, a->album);
    vita2d_pvf_draw_text(u->font, (int)tx, 246, COL_TEXT_DIM, 0.7f, t->title);

    char info[96];
    int tt = dur / 60, ts = dur % 60, ct = pos / 60, cs = pos % 60;
    int tn = player_track_idx(p) + 1;
    int tc = player_track_count(p);
    snprintf(info, sizeof(info), "%02d:%02d / %02d:%02d   ·   faixa %d/%d",
             ct, cs, tt, ts, tn, tc);
    vita2d_pvf_draw_text(u->font, (int)tx, 272, COL_TEXT_DIM, 0.6f, info);

    float bw = 330;
    vita2d_draw_rectangle(tx, 306, bw, 4, 0x18202C);
    vita2d_draw_rectangle(tx, 306, bw * progress, 4, COL_AMBER);

    const char *glow = (p && player_state(p) == PLAYER_PLAYING)
                       ? "[O] pausa   " : "[O] recome\u00E7a   ";
    const char *rep = "rep:??";
    if (p) {
        switch (player_repeat(p)) {
        case REPEAT_OFF: rep = "rep:deslig"; break;
        case REPEAT_ONE: rep = "rep:1"; break;
        default:         rep = "rep:todas"; break;
        }
    }
    char ctl[150];
    snprintf(ctl, sizeof(ctl), "%s[dir] troca   [quad] -10s   [sel] %s %s",
             glow, rep, (p && player_shuffle(p)) ? "sorteio:sim" : "sorteio:não");
    vita2d_pvf_draw_text(u->font, (int)tx, 348, COL_TEXT_DIM, 0.55f, ctl);

    vita2d_pvf_draw_text(u->font, 24, 22, COL_AMBER, 0.9f, "AGORA  ·  TOUCANDO");
    vita2d_pvf_draw_text(u->font, 24, SCRH - 38, COL_TEXT_DIM, 0.55f,
                         "[tri] estante   [L1] recs   [R1] playlists");
}

/* ---------- recomendações ---------- */
static void draw_recs(Ui *u, Library *lib, Player *p)
{
    (void)lib;
    (void)p;
    int vis = 12;
    int scroll = (u->rec_sel / vis) * vis;
    if (scroll < 0) scroll = 0;
    vita2d_pvf_draw_text(u->font, 24, 22, COL_AMBER, 1.0f, "RECOMENDADO");
    vita2d_pvf_draw_text(u->font, 24, SCRH - 38, COL_TEXT_DIM, 0.55f,
                         "[tri] estante   [O] tocar   [DIR] navega");

    if (!u->recs || u->nrecs <= 0) {
        vita2d_pvf_draw_text(u->font, 40, 120, COL_TEXT_DIM, 0.8f,
                             "sem sugestões ainda — toque algo e volte");
        return;
    }
    for (int r = 0; r < vis; r++) {
        int idx = scroll + r;
        if (idx >= u->nrecs) break;
        const Track *t = u->recs[idx];
        int y = 70 + r * 34;
        int is_sel = (idx == u->rec_sel);
        if (is_sel)
            vita2d_draw_rectangle(24, y, SCRW - 48, 30, 0x14FFAA28);
        char line[160];
        const char *artist = t->owner ? t->owner->artist : "";
        snprintf(line, sizeof(line), "%3d.  %.40s  —  %.40s",
                 idx + 1, t->title, artist);
        vita2d_pvf_draw_text(u->font, 32, (int)(y + 4), is_sel ? COL_AMBER : COL_TEXT,
                             0.62f, line);
        if (t->owner)
            vita2d_pvf_draw_text(u->font, 32, (int)(y + 18), COL_TEXT_DIM, 0.5f,
                                 t->owner->album);
    }
}

/* ---------- playlists ---------- */
static void draw_playlists(Ui *u, Library *lib, Player *p)
{
    (void)lib;
    (void)p;
    vita2d_pvf_draw_text(u->font, 24, 22, COL_AMBER, 1.0f, "PLAYLISTS");
    vita2d_pvf_draw_text(u->font, 24, SCRH - 38, COL_TEXT_DIM, 0.55f,
                         "[tri] estante   [O] tocar   [quad] salvar o atual como nova");

    if (!u->plists || u->nplists <= 0) {
        vita2d_pvf_draw_text(u->font, 40, 120, COL_TEXT_DIM, 0.8f,
                             "nenhuma playlist — toque algo e salve com [quad]");
        return;
    }
    int vis = 12;
    int scroll = (u->pl_sel / vis) * vis;
    if (scroll < 0) scroll = 0;
    for (int r = 0; r < vis; r++) {
        int idx = scroll + r;
        if (idx >= u->nplists) break;
        Playlist *pl = &u->plists[idx];
        int y = 70 + r * 34;
        int is_sel = (idx == u->pl_sel);
        if (is_sel)
            vita2d_draw_rectangle(24, y, SCRW - 48, 30, 0x14FFAA28);
        char line[180];
        snprintf(line, sizeof(line), "♪  %s", pl->name[0] ? pl->name : "(sem nome)");
        vita2d_pvf_draw_text(u->font, 32, (int)(y + 4), is_sel ? COL_AMBER : COL_TEXT,
                             0.62f, line);
        snprintf(line, sizeof(line), "%d faixa(s)", pl->n);
        vita2d_pvf_draw_text(u->font, 32, (int)(y + 18), COL_TEXT_DIM, 0.5f, line);
    }
}

/* ---------- frame ---------- */
int ui_frame(Ui *u, Library *lib, Player *p)
{
    vita2d_start_drawing();
    vita2d_clear_screen();

    for (int y = 0; y < SCRH; y += 8) {
        float t = (float)y / (float)SCRH;
        int r = (int)(6 + (13 - 6) * t);
        int g = (int)(8 + (18 - 8) * t);
        int b = (int)(13 + (28 - 13) * t);
        unsigned int c = 0xFF000000 | ((unsigned int)r << 16) | ((unsigned int)g << 8) | (unsigned int)b;
        vita2d_draw_rectangle(0, (float)y, SCRW, 8, c);
    }

    /* grão sutil: alguns pontos frios espalhados (determinístico) */
    static const unsigned short grain_pt[][2] = {
        {137, 89}, {512, 41}, {803, 130}, {66, 430}, {910, 470},
        {245, 512}, {700, 505}, {420, 60}, {880, 200}, {150, 250}
    };
    for (int i = 0; i < 10; i++) {
        unsigned int g = 0x14 << 24 | 0xFFA0B0C0;
        vita2d_draw_pixel(grain_pt[i][0], grain_pt[i][1], g);
    }

    if (u->view == VIEW_SHELF)
        draw_shelf(u, lib, p);
    else if (u->view == VIEW_DECK)
        draw_deck(u, lib, p);
    else if (u->view == VIEW_RECS)
        draw_recs(u, lib, p);
    else
        draw_playlists(u, lib, p);

    vita2d_end_drawing();
    vita2d_swap_buffers();
    return 0;
}

/* ---------- input ---------- */
static void ctrl_read(SceCtrlData *data)
{
    memset(data, 0, sizeof(*data));
    sceCtrlPeekBufferPositive(0, data, 1);
}

int ui_handle_input(Ui *u)
{
    static uint32_t prev = 0;
    SceCtrlData c;
    ctrl_read(&c);
    uint32_t cur = c.buttons;
    uint32_t edge = cur & ~prev;
    prev = cur;

    int action = 0;
    if (u->view == VIEW_SHELF) {
        if (edge & SCE_CTRL_DOWN) { u->sel += 3; action = 1; }
        if (edge & SCE_CTRL_UP)   { if (u->sel >= 3) u->sel -= 3; action = 1; }
        if (edge & SCE_CTRL_RIGHT) { u->sel++; action = 1; }
        if (edge & SCE_CTRL_LEFT)  { if (u->sel > 0) u->sel--; action = 1; }
        if (edge & SCE_CTRL_CROSS)  { u->view = VIEW_DECK; action = 2; }
        if (edge & SCE_CTRL_L1)   { u->view = VIEW_RECS; u->rec_sel = 0; action = 8; }
        if (edge & SCE_CTRL_R1)   { u->view = VIEW_PLAYLISTS; u->pl_sel = 0; action = 9; }
        if (edge & SCE_CTRL_SELECT) { action = 15; } /* sorteio */
    } else if (u->view == VIEW_RECS) {
        if (edge & SCE_CTRL_DOWN) { u->rec_sel++; action = 1; }
        if (edge & SCE_CTRL_UP)   { if (u->rec_sel > 0) u->rec_sel--; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CROSS)    { action = 11; } /* tocar recomendações */
        if (edge & SCE_CTRL_RIGHT)    { action = 11; }
    } else if (u->view == VIEW_PLAYLISTS) {
        if (edge & SCE_CTRL_DOWN) { u->pl_sel++; action = 1; }
        if (edge & SCE_CTRL_UP)   { if (u->pl_sel > 0) u->pl_sel--; action = 1; }
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CROSS)    { action = 12; } /* tocar playlist */
        if (edge & SCE_CTRL_RIGHT)    { action = 12; }
        if (edge & SCE_CTRL_SQUARE)   { action = 13; } /* add atual p/ playlist */
    } else {
        if (edge & SCE_CTRL_TRIANGLE) { u->view = VIEW_SHELF; action = 10; }
        if (edge & SCE_CTRL_CIRCLE)   { action = 4; }   /* toggle play */
        if (edge & SCE_CTRL_RIGHT)    { action = 5; }   /* next */
        if (edge & SCE_CTRL_LEFT)     { action = 6; }   /* prev */
        if (edge & SCE_CTRL_SQUARE)   { action = 7; }   /* seek -10s */
        if (edge & SCE_CTRL_L1)        { u->view = VIEW_RECS; u->rec_sel = 0; action = 8; }
        if (edge & SCE_CTRL_R1)        { u->view = VIEW_PLAYLISTS; u->pl_sel = 0; action = 9; }
        if (edge & SCE_CTRL_SELECT)    { action = 14; } /* repetição */
    }
    if (edge & SCE_CTRL_START) action = -1; /* sair */

    if (u->view == VIEW_SHELF && u->sel < 0) u->sel = 0;
    return action;
}

/* ---------- vida ---------- */
Ui *ui_create(void)
{
    Ui *u = calloc(1, sizeof(*u));
    if (!u) return NULL;
    u->font = vita2d_load_default_pvf();
    u->view = VIEW_SHELF;
    u->sel = 0;
    u->halo_phase = 0.0f;
    return u;
}

void ui_destroy(Ui *u)
{
    if (u->font) vita2d_free_pvf(u->font);
    free(u);
}

int ui_selected(const Ui *u)
{
    return u ? u->sel : 0;
}

int ui_playlist_idx(const Ui *u) { return u ? u->pl_sel : 0; }

int ui_view(const Ui *u) { return u ? (int)u->view : (int)VIEW_SHELF; }

void ui_set_data(Ui *u, Playlist *plists, int nplists,
                 const Track **recs, int nrecs)
{
    if (!u) return;
    u->plists = plists;
    u->nplists = nplists;
    u->recs = recs;
    u->nrecs = nrecs;
    if (u->pl_sel >= u->nplists && u->nplists > 0) u->pl_sel = u->nplists - 1;
    if (u->pl_sel < 0) u->pl_sel = 0;
    if (u->rec_sel >= u->nrecs && u->nrecs > 0) u->rec_sel = u->nrecs - 1;
}

void ui_set_recs(Ui *u, const Track **recs, int nrecs)
{
    if (!u) return;
    u->recs = recs;
    u->nrecs = nrecs;
    if (u->rec_sel >= u->nrecs && u->nrecs > 0) u->rec_sel = u->nrecs - 1;
}
