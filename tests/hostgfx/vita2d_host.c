/* Implementação das primitivas do vita2d num framebuffer de PC, para dar pra
   VER a UI sem o aparelho. Saída em PNG.

   ==== O QUE É FIEL ====
   - Ordem de canal: decodifica a cor exatamente como o vita2d (ABGR,
     RGBA8 = a<<24|b<<16|g<<8|r). Cor errada aqui é cor errada lá — foi
     assim que o bug do "app todo azul" teria aparecido na hora.
   - Mistura alfa padrão (src-over), resolução 960x544, geometria das
     primitivas (retângulo, linha, pixel, textura escalada).
   - As capas são os JPEG/PNG reais dos álbuns, decodificados de verdade.

   ==== O QUE É APROXIMAÇÃO (não "conserte" layout confiando nisto) ====
   - FONTE: o Vita usa a PVF do sistema; aqui é Noto Sans via FreeType. As
     larguras de glifo e a altura de linha NÃO batem exatamente. Serve pra
     ver se um texto estoura a caixa por muito, não por 2 px.
   - A escala do vita2d_pvf_draw_text é calibrada por HOSTGFX_PVF_BASE_PX;
     é um chute informado, não um valor medido no aparelho.
   - O `y` do texto é tratado como linha de base (é o que o vita2d faz),
     mas o pico de altura dos glifos difere da PVF.
   - Sem filtragem bilinear nas texturas (o Vita filtra); bordas de capa
     saem um tico mais duras aqui.  */

#include <vita2d.h>
#include <psp2/ctrl.h>
#include <psp2/touch.h>
#include <psp2/kernel/processmgr.h>
#include <time.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include <png.h>
#include <jpeglib.h>
#include <setjmp.h>

#include <ft2build.h>
#include FT_FREETYPE_H

#define SCRW 960
#define SCRH 544

/* Altura em px de um texto com scale=1.0. Chute informado: a PVF padrão do
   vita2d fica por volta disso. Se o preview divergir muito do aparelho,
   é ESTE número que se ajusta. */
#define HOSTGFX_PVF_BASE_PX 25.0f

static unsigned char fb[SCRH][SCRW][3];   /* RGB, já composto */

/* CONTADOR DE CHAMADAS DE DESENHO.
   No Vita cada vita2d_draw_rectangle vira um sceGxmDraw — uma chamada de
   desenho de verdade, não um pixel. O custo lá é o NÚMERO delas, e o tempo
   que este shim leva (que rasteriza em C) não diz nada sobre isso. Contar
   diz. */
static long g_draws;
long hostgfx_draws(void) { return g_draws; }
void hostgfx_draws_reset(void) { g_draws = 0; }

/* ---------- cor ---------- */
/* vita2d: RGBA8 = a<<24 | b<<16 | g<<8 | r  (ABGR) */
static void unpack(unsigned int c, int *r, int *g, int *b, int *a)
{
    *r = (int)( c        & 0xFF);
    *g = (int)((c >>  8) & 0xFF);
    *b = (int)((c >> 16) & 0xFF);
    *a = (int)((c >> 24) & 0xFF);
}

static void blend_px(int x, int y, int r, int g, int b, int a)
{
    if (x < 0 || y < 0 || x >= SCRW || y >= SCRH || a <= 0) return;
    unsigned char *p = fb[y][x];
    if (a >= 255) { p[0] = (unsigned char)r; p[1] = (unsigned char)g; p[2] = (unsigned char)b; return; }
    p[0] = (unsigned char)((r * a + p[0] * (255 - a)) / 255);
    p[1] = (unsigned char)((g * a + p[1] * (255 - a)) / 255);
    p[2] = (unsigned char)((b * a + p[2] * (255 - a)) / 255);
}

/* ---------- ciclo de desenho ---------- */
int  vita2d_init(void) { return 0; }
void vita2d_fini(void) { }
void vita2d_start_drawing(void) { }
void vita2d_end_drawing(void) { }
void vita2d_swap_buffers(void) { }
void vita2d_clear_screen(void) { memset(fb, 0, sizeof(fb)); }

/* ---------- primitivas ---------- */
void vita2d_draw_pixel(float x, float y, unsigned int color)
{
    g_draws++;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    blend_px((int)x, (int)y, r, g, b, a);
}

void vita2d_draw_rectangle(float x, float y, float w, float h, unsigned int color)
{
    g_draws++;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    int x0 = (int)floorf(x), y0 = (int)floorf(y);
    int x1 = (int)floorf(x + w), y1 = (int)floorf(y + h);
    for (int yy = y0; yy < y1; yy++)
        for (int xx = x0; xx < x1; xx++)
            blend_px(xx, yy, r, g, b, a);
}

/* o vita2d faz isto na GPU em UMA chamada; aqui rasterizamos, mas contamos
   como uma só — é o número de chamadas que importa para o aparelho */
void vita2d_draw_fill_circle(float cx, float cy, float r, unsigned int color)
{
    g_draws++;
    int cr, cg, cb, ca; unpack(color, &cr, &cg, &cb, &ca);
    int y0 = (int)(cy - r), y1 = (int)(cy + r);
    for (int y = y0; y <= y1; y++) {
        float dy = (float)y - cy;
        float d2 = r * r - dy * dy;
        if (d2 < 0) continue;
        float half = sqrtf(d2);
        for (int x = (int)(cx - half); x <= (int)(cx + half); x++)
            blend_px(x, y, cr, cg, cb, ca);
    }
}

void vita2d_draw_line(float x0, float y0, float x1, float y1, unsigned int color)
{
    g_draws++;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    float dx = x1 - x0, dy = y1 - y0;
    int steps = (int)(fabsf(dx) > fabsf(dy) ? fabsf(dx) : fabsf(dy));
    if (steps <= 0) { blend_px((int)x0, (int)y0, r, g, b, a); return; }
    for (int i = 0; i <= steps; i++) {
        float t = (float)i / (float)steps;
        blend_px((int)(x0 + dx * t), (int)(y0 + dy * t), r, g, b, a);
    }
}

/* ---------- texturas ---------- */
struct vita2d_texture {
    unsigned int w, h;
    unsigned char *rgb;   /* w*h*3 */
};

unsigned int vita2d_texture_get_width(const vita2d_texture *t)  { return t ? t->w : 0; }
unsigned int vita2d_texture_get_height(const vita2d_texture *t) { return t ? t->h : 0; }

void vita2d_free_texture(vita2d_texture *t)
{
    if (!t) return;
    free(t->rgb);
    free(t);
}

void vita2d_draw_texture_scale(const vita2d_texture *t, float x, float y,
                               float x_scale, float y_scale)
{
    if (!t || !t->rgb) return;
    int dw = (int)(t->w * x_scale), dh = (int)(t->h * y_scale);
    if (dw <= 0 || dh <= 0) return;
    for (int j = 0; j < dh; j++) {
        int sy = (int)((float)j / y_scale);
        if (sy < 0 || sy >= (int)t->h) continue;
        for (int i = 0; i < dw; i++) {
            int sx = (int)((float)i / x_scale);
            if (sx < 0 || sx >= (int)t->w) continue;
            const unsigned char *s = &t->rgb[((size_t)sy * t->w + sx) * 3];
            blend_px((int)x + i, (int)y + j, s[0], s[1], s[2], 255);
        }
    }
}

/* Textura TINGIDA: multiplica cada pixel pela cor (e usa o alfa dela). É como
   o ui.c escurece a capa que serve de fundo, e sem isto o preview não
   reproduz a camada certa. */
void vita2d_draw_texture_tint_scale(const vita2d_texture *t, float x, float y,
                                    float x_scale, float y_scale, unsigned int color)
{
    if (!t || !t->rgb) return;
    int tr, tg, tb, ta; unpack(color, &tr, &tg, &tb, &ta);
    int dw = (int)(t->w * x_scale), dh = (int)(t->h * y_scale);
    for (int j = 0; j < dh; j++) {
        int sy = (int)((float)j / y_scale);
        if (sy < 0 || sy >= (int)t->h) continue;
        for (int i = 0; i < dw; i++) {
            int sx = (int)((float)i / x_scale);
            if (sx < 0 || sx >= (int)t->w) continue;
            const unsigned char *s = &t->rgb[((size_t)sy * t->w + sx) * 3];
            blend_px((int)x + i, (int)y + j,
                     s[0] * tr / 255, s[1] * tg / 255, s[2] * tb / 255, ta);
        }
    }
}

/* Desenha um RECORTE da textura. É com isto que o rótulo do vinil vira
   redondo: a UI manda uma tira horizontal por linha da tela, cada uma com a
   largura da corda do círculo naquela altura. */
void vita2d_draw_texture_part_scale(const vita2d_texture *t, float x, float y,
                                    float tex_x, float tex_y,
                                    float tex_w, float tex_h,
                                    float x_scale, float y_scale)
{
    if (!t || !t->rgb) return;
    int dw = (int)(tex_w * x_scale), dh = (int)(tex_h * y_scale);
    if (dw <= 0) dw = 1;
    if (dh <= 0) dh = 1;
    for (int j = 0; j < dh; j++) {
        int sy = (int)(tex_y + (float)j / y_scale);
        if (sy < 0 || sy >= (int)t->h) continue;
        for (int i = 0; i < dw; i++) {
            int sx = (int)(tex_x + (float)i / x_scale);
            if (sx < 0 || sx >= (int)t->w) continue;
            const unsigned char *s = &t->rgb[((size_t)sy * t->w + sx) * 3];
            blend_px((int)x + i, (int)y + j, s[0], s[1], s[2], 255);
        }
    }
}

/* --- JPEG --- */
struct jerr_mgr { struct jpeg_error_mgr pub; jmp_buf jb; };
static void jerr_exit(j_common_ptr ci) { longjmp(((struct jerr_mgr *)ci->err)->jb, 1); }

vita2d_texture *vita2d_load_JPEG_buffer(const void *buffer, unsigned long len)
{
    struct jpeg_decompress_struct ci;
    struct jerr_mgr je;
    vita2d_texture *t = NULL;

    ci.err = jpeg_std_error(&je.pub);
    je.pub.error_exit = jerr_exit;
    if (setjmp(je.jb)) { jpeg_destroy_decompress(&ci); if (t) { free(t->rgb); free(t); } return NULL; }

    jpeg_create_decompress(&ci);
    jpeg_mem_src(&ci, (const unsigned char *)buffer, len);
    if (jpeg_read_header(&ci, TRUE) != JPEG_HEADER_OK) { jpeg_destroy_decompress(&ci); return NULL; }
    ci.out_color_space = JCS_RGB;
    jpeg_start_decompress(&ci);

    t = calloc(1, sizeof(*t));
    if (!t) { jpeg_destroy_decompress(&ci); return NULL; }
    t->w = ci.output_width;
    t->h = ci.output_height;
    t->rgb = malloc((size_t)t->w * t->h * 3);
    if (!t->rgb) { free(t); jpeg_destroy_decompress(&ci); return NULL; }

    while (ci.output_scanline < ci.output_height) {
        unsigned char *row = &t->rgb[(size_t)ci.output_scanline * t->w * 3];
        jpeg_read_scanlines(&ci, &row, 1);
    }
    jpeg_finish_decompress(&ci);
    jpeg_destroy_decompress(&ci);
    return t;
}

/* --- PNG (buffer) --- */
struct png_src { const unsigned char *p; size_t left; };
static void png_read_cb(png_structp ps, png_bytep out, png_size_t n)
{
    struct png_src *s = png_get_io_ptr(ps);
    if (n > s->left) n = s->left;
    memcpy(out, s->p, n);
    s->p += n; s->left -= n;
}

vita2d_texture *vita2d_load_PNG_buffer(const void *buffer)
{
    /* o chamador (ui.c) só passa o ponteiro; assumimos um limite generoso —
       é preview, e as capas do acervo cabem folgado */
    struct png_src src = { (const unsigned char *)buffer, (size_t)32 * 1024 * 1024 };
    png_structp ps = png_create_read_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    if (!ps) return NULL;
    png_infop pi = png_create_info_struct(ps);
    if (!pi) { png_destroy_read_struct(&ps, NULL, NULL); return NULL; }
    if (setjmp(png_jmpbuf(ps))) { png_destroy_read_struct(&ps, &pi, NULL); return NULL; }

    png_set_read_fn(ps, &src, png_read_cb);
    png_read_info(ps, pi);
    png_set_strip_16(ps);
    png_set_palette_to_rgb(ps);
    png_set_expand_gray_1_2_4_to_8(ps);
    png_set_strip_alpha(ps);
    png_set_gray_to_rgb(ps);
    png_read_update_info(ps, pi);

    vita2d_texture *t = calloc(1, sizeof(*t));
    if (!t) { png_destroy_read_struct(&ps, &pi, NULL); return NULL; }
    t->w = png_get_image_width(ps, pi);
    t->h = png_get_image_height(ps, pi);
    t->rgb = malloc((size_t)t->w * t->h * 3);
    if (!t->rgb) { free(t); png_destroy_read_struct(&ps, &pi, NULL); return NULL; }
    for (unsigned int y = 0; y < t->h; y++)
        png_read_row(ps, &t->rgb[(size_t)y * t->w * 3], NULL);
    png_destroy_read_struct(&ps, &pi, NULL);
    return t;
}

/* ---------- texto (FreeType) ---------- */
struct vita2d_pvf { FT_Library lib; FT_Face face; };
static char g_font_path[1024] = "/usr/share/fonts/noto/NotoSans-Regular.ttf";

void hostgfx_set_font_path(const char *ttf)
{
    if (ttf) snprintf(g_font_path, sizeof(g_font_path), "%s", ttf);
}

vita2d_pvf *vita2d_load_default_pvf(void)
{
    vita2d_pvf *f = calloc(1, sizeof(*f));
    if (!f) return NULL;
    if (FT_Init_FreeType(&f->lib)) { free(f); return NULL; }
    if (FT_New_Face(f->lib, g_font_path, 0, &f->face)) {
        fprintf(stderr, "hostgfx: não abriu a fonte %s\n", g_font_path);
        FT_Done_FreeType(f->lib);
        free(f);
        return NULL;
    }
    return f;
}

void vita2d_free_pvf(vita2d_pvf *f)
{
    if (!f) return;
    FT_Done_Face(f->face);
    FT_Done_FreeType(f->lib);
    free(f);
}

/* decodifica UTF-8 (o ui.c tem acento e "·") */
static const char *utf8_next(const char *s, unsigned int *cp)
{
    unsigned char c = (unsigned char)*s;
    if (c < 0x80)              { *cp = c; return s + 1; }
    if ((c & 0xE0) == 0xC0)    { *cp = ((unsigned)(c & 0x1F) << 6) | ((unsigned)s[1] & 0x3F); return s + 2; }
    if ((c & 0xF0) == 0xE0)    { *cp = ((unsigned)(c & 0x0F) << 12) | (((unsigned)s[1] & 0x3F) << 6) | ((unsigned)s[2] & 0x3F); return s + 3; }
    if ((c & 0xF8) == 0xF0)    { *cp = ((unsigned)(c & 0x07) << 18) | (((unsigned)s[1] & 0x3F) << 12) | (((unsigned)s[2] & 0x3F) << 6) | ((unsigned)s[3] & 0x3F); return s + 4; }
    *cp = '?'; return s + 1;
}

static int set_px(vita2d_pvf *f, float scale)
{
    int px = (int)(HOSTGFX_PVF_BASE_PX * scale + 0.5f);
    if (px < 6) px = 6;
    FT_Set_Pixel_Sizes(f->face, 0, (FT_UInt)px);
    return px;
}

int vita2d_pvf_draw_text(vita2d_pvf *f, int x, int y, unsigned int color,
                         float scale, const char *text)
{
    if (!f || !text) return 0;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    set_px(f, scale);

    int pen = x;
    for (const char *s = text; *s; ) {
        unsigned int cp;
        s = utf8_next(s, &cp);
        if (FT_Load_Char(f->face, cp, FT_LOAD_RENDER)) continue;
        FT_GlyphSlot gs = f->face->glyph;
        FT_Bitmap *bm = &gs->bitmap;
        for (unsigned int j = 0; j < bm->rows; j++) {
            for (unsigned int i = 0; i < bm->width; i++) {
                unsigned char cov = bm->buffer[j * (unsigned)bm->pitch + i];
                if (!cov) continue;
                int aa = a * cov / 255;
                blend_px(pen + gs->bitmap_left + (int)i,
                         y - gs->bitmap_top + (int)j, r, g, b, aa);
            }
        }
        pen += (int)(gs->advance.x >> 6);
    }
    return pen - x;
}

int vita2d_pvf_text_width(vita2d_pvf *f, float scale, const char *text)
{
    if (!f || !text) return 0;
    set_px(f, scale);
    int w = 0;
    for (const char *s = text; *s; ) {
        unsigned int cp;
        s = utf8_next(s, &cp);
        if (FT_Load_Char(f->face, cp, FT_LOAD_DEFAULT)) continue;
        w += (int)(f->face->glyph->advance.x >> 6);
    }
    return w;
}

/* ---------- saída ---------- */
int hostgfx_save_png(const char *path)
{
    FILE *fp = fopen(path, "wb");
    if (!fp) return -1;
    png_structp ps = png_create_write_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    if (!ps) { fclose(fp); return -1; }
    png_infop pi = png_create_info_struct(ps);
    if (!pi) { png_destroy_write_struct(&ps, NULL); fclose(fp); return -1; }
    if (setjmp(png_jmpbuf(ps))) { png_destroy_write_struct(&ps, &pi); fclose(fp); return -1; }
    png_init_io(ps, fp);
    png_set_IHDR(ps, pi, SCRW, SCRH, 8, PNG_COLOR_TYPE_RGB,
                 PNG_INTERLACE_NONE, PNG_COMPRESSION_TYPE_DEFAULT, PNG_FILTER_TYPE_DEFAULT);
    png_write_info(ps, pi);
    for (int y = 0; y < SCRH; y++)
        png_write_row(ps, fb[y][0]);
    png_write_end(ps, NULL);
    png_destroy_write_struct(&ps, &pi);
    fclose(fp);
    return 0;
}

/* ---------- relógio / processo ---------- */
int sceKernelPowerTick(int type) { (void)type; return 0; }

/* microssegundos desde o início do processo — é o que o ui.c usa para animar */
uint64_t sceKernelGetProcessTimeWide(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)(ts.tv_nsec / 1000);
}
uint32_t sceKernelGetProcessTimeLow(void)
{
    return (uint32_t)sceKernelGetProcessTimeWide();
}
void sceKernelExitProcess(int res) { exit(res); }

/* ---------- toque ---------- */
/* O painel frontal do Vita reporta numa grade ~2x a da tela. O shim finge o
   mesmo para o mapeamento da UI ser exercitado igual. */
static int g_tap_x = -1, g_tap_y = -1;

void hosttouch_tap(int x, int y) { g_tap_x = x; g_tap_y = y; }

int sceTouchSetSamplingState(uint32_t port, uint32_t state)
{ (void)port; (void)state; return 0; }
int sceTouchEnableTouchForce(uint32_t port) { (void)port; return 0; }

int sceTouchGetPanelInfo(uint32_t port, SceTouchPanelInfo *info)
{
    (void)port;
    if (!info) return -1;
    memset(info, 0, sizeof(*info));
    info->minAaX = 0; info->minAaY = 0;
    info->maxAaX = SCRW * 2 - 1;
    info->maxAaY = SCRH * 2 - 1;
    return 0;
}

int sceTouchPeek(uint32_t port, SceTouchData *data, uint32_t nBufs)
{
    (void)port; (void)nBufs;
    if (!data) return 0;
    memset(data, 0, sizeof(*data));
    if (g_tap_x >= 0) {
        data->reportNum = 1;
        data->report[0].x = (int16_t)(g_tap_x * 2);
        data->report[0].y = (int16_t)(g_tap_y * 2);
        data->report[0].force = 100;
    }
    return 1;
}

/* ---------- controle ---------- */
static uint32_t g_buttons;
void hostctrl_press(uint32_t buttons) { g_buttons = buttons; }
int sceCtrlSetSamplingMode(int mode) { (void)mode; return 0; }
int sceCtrlPeekBufferPositive(int port, SceCtrlData *d, int count)
{
    (void)port; (void)count;
    if (!d) return 0;
    memset(d, 0, sizeof(*d));
    d->buttons = g_buttons;
    return 1;
}
