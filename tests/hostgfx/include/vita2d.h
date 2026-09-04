/* Shim do vita2d para o PC. Existe para RENDERIZAR a UI de verdade fora do
   Vita: o ui.c é compilado sem nenhuma alteração contra este header, e o
   vita2d_host.c desenha num framebuffer que vira PNG.

   ATENÇÃO: isto é aproximação, não emulação. Ver a lista de diferenças
   honestas no topo de vita2d_host.c antes de "consertar" layout com base
   numa imagem daqui.

   RGBA8 é copiado VERBATIM do vita2d.h do SDK — é justamente a ordem de
   canal (ABGR) que o preview precisa reproduzir pra cor sair fiel. */
#ifndef VITA2D_HOST_SHIM_H
#define VITA2D_HOST_SHIM_H

#include <stddef.h>

#define RGBA8(r,g,b,a) ((((a)&0xFF)<<24) | (((b)&0xFF)<<16) | (((g)&0xFF)<<8) | (((r)&0xFF)<<0))

typedef struct vita2d_texture vita2d_texture;
typedef struct vita2d_pvf vita2d_pvf;

int  vita2d_init(void);
void vita2d_fini(void);
void vita2d_clear_screen(void);
void vita2d_swap_buffers(void);
void vita2d_start_drawing(void);
void vita2d_end_drawing(void);

void vita2d_draw_pixel(float x, float y, unsigned int color);
void vita2d_draw_line(float x0, float y0, float x1, float y1, unsigned int color);
void vita2d_draw_rectangle(float x, float y, float w, float h, unsigned int color);

vita2d_texture *vita2d_load_PNG_buffer(const void *buffer);
vita2d_texture *vita2d_load_JPEG_buffer(const void *buffer, unsigned long buffer_size);
void vita2d_free_texture(vita2d_texture *texture);
unsigned int vita2d_texture_get_width(const vita2d_texture *texture);
unsigned int vita2d_texture_get_height(const vita2d_texture *texture);
void vita2d_draw_texture_scale(const vita2d_texture *texture, float x, float y,
                               float x_scale, float y_scale);
void vita2d_draw_texture_tint_scale(const vita2d_texture *texture, float x, float y,
                                    float x_scale, float y_scale, unsigned int color);
void vita2d_draw_texture_part_scale(const vita2d_texture *texture, float x, float y,
                                    float tex_x, float tex_y, float tex_w, float tex_h,
                                    float x_scale, float y_scale);

vita2d_pvf *vita2d_load_default_pvf(void);
void vita2d_free_pvf(vita2d_pvf *font);
int vita2d_pvf_draw_text(vita2d_pvf *font, int x, int y, unsigned int color,
                         float scale, const char *text);
int vita2d_pvf_text_width(vita2d_pvf *font, float scale, const char *text);

/* --- extras SÓ do host (não existem no vita2d de verdade) --- */
int  hostgfx_save_png(const char *path);
void hostgfx_set_font_path(const char *ttf);

#endif
