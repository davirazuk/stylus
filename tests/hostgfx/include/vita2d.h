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
void vita2d_draw_fill_circle(float x, float y, float radius, unsigned int color);
void vita2d_draw_rectangle(float x, float y, float w, float h, unsigned int color);

/* O LOTE. No Vita isto é UM sceGxmDraw para o vetor INTEIRO de vértices, e é
   por isso que replanta o ring_segmentos/arco: milhares de chamadas viram
   dezenas. Aqui no PC rasteriza cada par linha, mas CONTA como uma chamada só
   — é o número de sceGxmDraw que importa para o aparelho. */
typedef struct vita2d_color_vertex {
    float x;
    float y;
    float z;
    unsigned int color;
} vita2d_color_vertex;
#define SCE_GXM_PRIMITIVE_LINES 0x04000000u
void vita2d_draw_array(int mode, const vita2d_color_vertex *vertices, size_t count);

/* O pool de onde os vértices do draw_array têm de vir. No Vita é um pedaço de
   RAM REAL que o vita2d reinicia a cada quadro; no PC o vértice morre ao
   rasterizar, então é só malloc — mas a função existe para o ui.c compilar
   igual nos dois lados. */
void *vita2d_pool_memalign(unsigned int size, unsigned int alignment);
unsigned int vita2d_pool_free_space(void);
void vita2d_pool_reset(void);

/* ---------- textura crua ----------
   O ui.c encolhe a capa para 64x64 para fazer o fundo do deck (ver blur_faz).
   Para isso ele precisa LER e ESCREVER pixel, e o SDK oferece estas cinco
   funções. O shim guarda três bytes por pixel e diz isso pelo get_format —
   é por isso que existe uma constante de formato SÓ do shim: assim o ui.c
   trata os dois casos por dado, sem #ifdef espalhado. */
/* Os DOIS formatos que os carregadores do vita2d realmente produzem, com os
   valores conferidos contra o `psp2/gxm.h` do SDK (e não supostos):

     JPEG colorido -> U8U8U8_BGR   0x98000000   TRÊS bytes, em memória R,G,B
     PNG           -> A8B8G8R8     0x0C000000   QUATRO bytes, R,G,B,A

   O shim guarda três bytes R,G,B, que é exatamente o primeiro — então ele
   diz `U8U8U8_BGR` e o ui.c segue UM caminho só nos dois lados. */
typedef int SceGxmTextureFormat;
#define SCE_GXM_TEXTURE_FORMAT_U8U8U8_BGR 0x98000000
#define SCE_GXM_TEXTURE_FORMAT_A8B8G8R8   0x0C000000
#define SCE_GXM_TEXTURE_FILTER_POINT     0
#define SCE_GXM_TEXTURE_FILTER_LINEAR    1
typedef int SceGxmTextureFilter;

vita2d_texture *vita2d_create_empty_texture_format(unsigned int w, unsigned int h,
                                                   SceGxmTextureFormat format);
unsigned int         vita2d_texture_get_stride(const vita2d_texture *texture);
SceGxmTextureFormat  vita2d_texture_get_format(const vita2d_texture *texture);
void                *vita2d_texture_get_datap(const vita2d_texture *texture);
void vita2d_texture_set_filters(vita2d_texture *texture,
                                SceGxmTextureFilter min_filter,
                                SceGxmTextureFilter mag_filter);

vita2d_texture *vita2d_load_PNG_buffer(const void *buffer);
vita2d_texture *vita2d_load_JPEG_buffer(const void *buffer, unsigned long buffer_size);
/* as capas do Qobuz chegam como ARQUIVO no cartão; o preview lê igual */
vita2d_texture *vita2d_load_JPEG_file(const char *path);
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

/* no PC não há GPU para esperar; existe para o ui.c compilar igual */
void vita2d_wait_rendering_done(void);

vita2d_pvf *vita2d_load_default_pvf(void);

/* O app carrega as fontes do sistema em GRUPO (latim + CJK) para não perder
   os acentos. Aqui no PC existe UMA fonte e ela já tem tudo, então o grupo é
   aceito e ignorado — o que importa é o preview continuar compilando o mesmo
   ui.c, sem #ifdef espalhado no código de verdade. */
typedef struct { int code; int (*in_font_group)(unsigned int c); }
        vita2d_system_pvf_config;
vita2d_pvf *vita2d_load_system_pvf(int numFonts, const vita2d_system_pvf_config *cfg);

#define SCE_PVF_LANGUAGE_LATIN 2
#define SCE_PVF_LANGUAGE_J     1
void vita2d_free_pvf(vita2d_pvf *font);
int vita2d_pvf_draw_text(vita2d_pvf *font, int x, int y, unsigned int color,
                         float scale, const char *text);
int vita2d_pvf_text_width(vita2d_pvf *font, float scale, const char *text);

/* --- extras SÓ do host (não existem no vita2d de verdade) --- */
int  hostgfx_save_png(const char *path);
/* Quantas chamadas de desenho o último quadro emitiu. No Vita cada uma é um
   sceGxmDraw, e é esse número que custa lá — não o tempo deste shim. */
long hostgfx_draws(void);
/* Quantas vezes o pool de vértices acabou e um desenho foi DESCARTADO em
   silêncio. Zero é o estado são: qualquer número acima quer dizer que o
   preview está escondendo desenho de quem o está olhando. */
long hostgfx_pool_faltou(void);
void hostgfx_draws_reset(void);
/* De onde vêm as chamadas: útil para achar o próximo gargalo do deck. */
long hostgfx_linhas(void); long hostgfx_ret(void); long hostgfx_circ(void);
long hostgfx_ar(void); long hostgfx_px(void); long hostgfx_tex(void);
void hostgfx_set_font_path(const char *ttf);

/* Um pixel do quadro composto, 0xRRGGBB. Existe para o teste poder perguntar
   à TELA, e não ao código, para que lado um glifo aponta — foi um ícone
   espelhado (os três botões do transporte) que passou por toda leitura de
   código e só apareceu ao olhar o PNG. */
unsigned hostgfx_pixel(int x, int y);

/* Textura viva agora: quantos objetos e quantos bytes. No Vita é a VRAM, que
   acaba antes de tudo; aqui é só um número — mas é o mesmo número. */
long hostgfx_tex_vivas(void);
long hostgfx_tex_bytes(void);

/* Desliga a mistura de pixel. Para quem CONTA desenho e não olha a imagem —
   é 98% do tempo de uma varredura, e ela não usa um pixel do resultado. */
void hostgfx_sem_pintar(int on);

/* TEXTURA SOLTA CEDO DEMAIS — a regra do Vita, conferida no PC.
   Quantas vezes uma textura foi liberada enquanto a GPU do aparelho ainda
   poderia estar lendo dela, e a primeira delas por extenso. É esta a causa
   dos psp2core-*-GPUCRASH. */
int         hostgfx_solta_cedo(void);
const char *hostgfx_solta_cedo_onde(void);

/* TEXTURA CRIADA OU SOLTA COM A CENA ABERTA. No Vita é sceGxmMap/Unmap no
   meio da lista de display — trava a GPU e derruba o sistema. */
/* Coordenada NaN/absurda entregue à GPU — no Vita isso TRAVA.
   `_onde` traz a PRIMEIRA por extenso: primitiva e números. */
int         hostgfx_coord_suja(void);
const char *hostgfx_coord_suja_onde(void);
int         hostgfx_tex_na_cena(void);
const char *hostgfx_tex_na_cena_onde(void);

#endif
