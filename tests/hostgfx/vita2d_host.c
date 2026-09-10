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

/* Altura em px de um texto com scale=1.0. NÃO é mais chute: o vita2d monta a
   PVF padrão com
       scePvfSetResolution(lib, 128.0f, 128.0f);
       scePvfSetCharSize(h, 10.125f, 10.125f);
       scePvfSetEM(lib, 72.0f / (10.125f * 128.0f));
   e px = pt * dpi / 72 = 10,125 * 128 / 72 = 18,0 exatos. O EM confere: 1/18.
   O 10,125 foi escolhido para dar 18 redondo.

   SINTOMA: aqui dizia 25,0 — o preview desenhava toda a tipografia 39%
   MAIOR que o aparelho. A UI foi julgada nestes PNGs, passou, e no Vita o
   usuário não conseguia ler ("text is kind of illegible"). Um preview que
   erra para o lado generoso é pior que preview nenhum: ele aprova. */
#define HOSTGFX_PVF_BASE_PX 18.0f

static unsigned char fb[SCRH][SCRW][3];   /* RGB, já composto */

/* O NÚMERO DO QUADRO. Sobe no clear_screen, que é a primeira coisa de todo
   `ui_frame`. Serve ao detector de textura solta cedo demais lá embaixo —
   declarado aqui em cima porque o clear_screen o usa antes. */
static unsigned long g_quadro;

/* CONTADOR DE CHAMADAS DE DESENHO.
   No Vita cada vita2d_draw_rectangle vira um sceGxmDraw — uma chamada de
   desenho de verdade, não um pixel. O custo lá é o NÚMERO delas, e o tempo
   que este shim leva (que rasteriza em C) não diz nada sobre isso. Contar
   diz. */
static long g_draws;
static long g_linhas, g_ret, g_circ, g_ar, g_px, g_tex;
void vita2d_wait_rendering_done(void) { }

long hostgfx_draws(void) { return g_draws; }
void hostgfx_draws_reset(void) { g_draws = g_linhas = g_ret = g_circ = g_ar = g_px = g_tex = 0; }
long hostgfx_linhas(void){return g_linhas;} long hostgfx_ret(void){return g_ret;}
long hostgfx_circ(void){return g_circ;} long hostgfx_ar(void){return g_ar;}
long hostgfx_px(void){return g_px;} long hostgfx_tex(void){return g_tex;}

/* ---------- cor ---------- */
/* vita2d: RGBA8 = a<<24 | b<<16 | g<<8 | r  (ABGR) */
static void unpack(unsigned int c, int *r, int *g, int *b, int *a)
{
    *r = (int)( c        & 0xFF);
    *g = (int)((c >>  8) & 0xFF);
    *b = (int)((c >> 16) & 0xFF);
    *a = (int)((c >> 24) & 0xFF);
}

unsigned hostgfx_pixel(int x, int y)
{
    if (x < 0 || y < 0 || x >= SCRW || y >= SCRH) return 0;
    return ((unsigned)fb[y][x][0] << 16) | ((unsigned)fb[y][x][1] << 8) |
            (unsigned)fb[y][x][2];
}

/* NÃO PINTAR: o modo da varredura.

   A varredura roda dezenas de milhares de quadros e não olha um pixel — ela
   conta chamada de desenho e mede memória. Misturar cada pixel dos 522 240 da
   tela, em C, para jogar tudo fora depois é 98% do tempo dela: com isto ela
   sai de doze minutos para segundos.

   Não é um atalho sobre o que se mede. Tudo que a varredura procura continua
   acontecendo — a contagem de desenho, a decodificação de JPEG, a alocação e
   a soltura de textura, e o percurso inteiro do ui.c. O que para é o balde de
   tinta no fim do cano. Quem QUER a imagem (o preview) não liga isto.

   ONDE A SAÍDA TEM DE FICAR: no TOPO de cada primitiva, depois de contar o
   desenho. A primeira versão testava dentro do `blend_px` — e assim os laços
   continuavam percorrendo cada pixel de cada retângulo para chamar uma função
   que voltava na hora: 5,6 BILHÕES de chamadas, e a varredura ficou 4%
   mais rápida. Não pintar não é a mesma coisa que não percorrer. */
static int g_sem_pintar;
void hostgfx_sem_pintar(int on) { g_sem_pintar = on; }

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

/* ═══ TEXTURA CRIADA OU SOLTA COM A CENA ABERTA ═══════════════════════════

   Criar uma textura no vita2d é `sceGxmMapMemory`; soltá-la é
   `sceGxmUnmapMemory`. Fazer qualquer um dos dois entre o `start_drawing` e o
   `end_drawing` é mexer no mapa de memória da GPU enquanto a lista de display
   está sendo gravada — e no Vita isso trava a GPU, que derruba o sistema.

   O app fez exatamente isso por meses sem consequência, porque a coleção não
   tem arte embutida e o caminho de decodificar capa quase nunca rodava. No
   dia em que ele passou a ler os 324 `cover.jpg` do cartão, o problema
   apareceu em minutos.

   No PC nada disso dói — não há GPU nenhuma aqui. Então a regra do aparelho
   vira uma conferência: quem chamar dentro da cena é reprovado, com a pilha
   do ASAN apontando o arquivo e a linha. */
static int  g_cena;
static int  g_na_cena;
static char g_na_cena_onde[160] = "";

int  hostgfx_tex_na_cena(void) { return g_na_cena; }
const char *hostgfx_tex_na_cena_onde(void) { return g_na_cena_onde; }

static void acusa_cena(const char *o_que, unsigned w, unsigned h)
{
    if (!g_cena) return;
    g_na_cena++;
    if (!g_na_cena_onde[0])
        snprintf(g_na_cena_onde, sizeof(g_na_cena_onde),
                 "textura %ux%u %s com a cena aberta "
                 "(no Vita isso é sceGxmMap/Unmap no meio da lista de display)",
                 w, h, o_que);
}

void vita2d_start_drawing(void) { g_cena = 1; vita2d_pool_reset(); }
void vita2d_end_drawing(void)   { g_cena = 0; }
void vita2d_swap_buffers(void) { }
void vita2d_clear_screen(void) { g_quadro++; memset(fb, 0, sizeof(fb)); }

/* ---------- primitivas ---------- */
/* COORDENADA SUJA CHEGANDO NA GPU.

   No PC um NaN vira um laço que não roda e ninguém percebe. No Vita ele entra
   no sceGxm, que não devolve erro: a GPU TRAVA e derruba o sistema. Era este
   o GPUCRASH que sobrava depois de tudo — o espectro do áudio ia cru para o
   `vita2d_draw_line`. Aqui a regra do aparelho vira conferência. */
static int g_suja;
static char g_suja_onde[256];
static int limpo(float v) { return v > -100000.0f && v < 100000.0f; }

/* O DETECTOR TEM DE DIZER QUEM.

   Ele contava, e um contador que só conta manda procurar em 6.700 linhas de
   ui.c. Guarda a PRIMEIRA suja por extenso — primitiva e números — que é a
   única que interessa: as seguintes são quase sempre a mesma conta escapando
   no mesmo quadro. */
static void suja(const char *quem, float a, float b, float c, float d)
{
    g_suja++;
    if (g_suja_onde[0]) return;
    snprintf(g_suja_onde, sizeof(g_suja_onde),
             "%s(%g, %g, %g, %g)", quem, (double)a, (double)b, (double)c, (double)d);
}

void vita2d_draw_pixel(float x, float y, unsigned int color)
{
    if (!limpo(x) || !limpo(y)) suja("draw_pixel", x, y, 0, 0);
    g_draws++; g_px++;
    if (g_sem_pintar) return;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    blend_px((int)x, (int)y, r, g, b, a);
}

/* CONTADOR DE CHAMADAS DE DESENHO.

   No Vita CADA primitiva do vita2d é um sceGxmDraw próprio — não há
   agrupamento. Conferido desmontando o `libvita2d.a` deste SDK: as 19
   funções de `vita2d_texture.o` e as 5 de `vita2d_draw.o` chamam
   `sceGxmDraw` exatamente uma vez cada. A lista de display tem limite, e
   estourá-la trava a GPU; a trava derruba o sistema inteiro e o cartão fica
   cheio de psp2core-*-GPUCRASH.

   ── O QUE ESTE CONTADOR NÃO VIA, E ERA A METADE QUE IMPORTAVA ──────────

   Ele contava retângulo, linha, círculo e pixel. Não contava TEXTURA nem
   TEXTO — e o `vita2d_pvf.o` desenha um `vita2d_draw_texture_tint_part_scale`
   POR GLIFO, o que faz de cada CARACTERE na tela um sceGxmDraw.

   Uma tela do deck tem centenas de caracteres. O número que a varredura
   anunciava — "3145, teto 8000, tudo bem" — media talvez metade do custo
   real, e a varredura passava verde enquanto o aparelho enchia o cartão de
   GPUCRASH no mesmo dia. Um contador que mede a metade fácil é pior que
   contador nenhum: ele APROVA.

   Agora conta as três coisas do jeito que o aparelho conta. */
void vita2d_draw_rectangle(float x, float y, float w, float h, unsigned int color)
{
    /* O RETÂNGULO É 127 DOS ~150 DESENHOS DESTE APP, E ERA O QUE NÃO SE
       CONFERIA. O detector nasceu olhando linha e lote — as duas primitivas
       de onde o espectro saía —, e ficou verde a semana inteira enquanto o
       cartão enchia de GPUCRASH, porque o desenho que o aparelho mais faz
       passava por fora dele. Conferir a primitiva rara e não a comum é o
       mesmo erro do contador que não contava glifo. */
    if (!limpo(x) || !limpo(y) || !limpo(w) || !limpo(h))
        suja("draw_rectangle", x, y, w, h);
    g_draws++; g_ret++;
    if (g_sem_pintar) return;
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
    if (!limpo(cx) || !limpo(cy) || !limpo(r)) suja("fill_circle", cx, cy, r, 0);
    g_draws++; g_circ++;
    if (g_sem_pintar) return;
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
    if (!limpo(x0) || !limpo(y0) || !limpo(x1) || !limpo(y1))
        suja("draw_line", x0, y0, x1, y1);
    g_draws++;
    if (g_sem_pintar) return;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    float dx = x1 - x0, dy = y1 - y0;
    int steps = (int)(fabsf(dx) > fabsf(dy) ? fabsf(dx) : fabsf(dy));
    if (steps <= 0) { blend_px((int)x0, (int)y0, r, g, b, a); return; }
    for (int i = 0; i <= steps; i++) {
        float t = (float)i / (float)steps;
        blend_px((int)(x0 + dx * t), (int)(y0 + dy * t), r, g, b, a);
    }
}

/* O LOTE: UM sceGxmDraw para o vetor INTEIRO (é isso que o aparelho faz; o
   `draw_line` por segmento era o que estourava a lista de display com o deck
   aberto). Rasterizamos par a par para o preview continuar honesto, mas a
   contagem é UMA chamada só. */
void vita2d_draw_array(int mode, const vita2d_color_vertex *vertices, size_t count)
{
    g_draws++; g_ar++;
    if (g_sem_pintar) return;
    for (size_t i = 0; i + 1 < count; i += 2) {
        if (!limpo(vertices[i].x) || !limpo(vertices[i].y) ||
            !limpo(vertices[i + 1].x) || !limpo(vertices[i + 1].y))
            suja("draw_array", vertices[i].x, vertices[i].y,
                 vertices[i + 1].x, vertices[i + 1].y);
        int r, g, b, a; unpack(vertices[i].color, &r, &g, &b, &a);
        float x0 = vertices[i].x, y0 = vertices[i].y;
        float x1 = vertices[i + 1].x, y1 = vertices[i + 1].y;
        float dx = x1 - x0, dy = y1 - y0;
        int steps = (int)(fabsf(dx) > fabsf(dy) ? fabsf(dx) : fabsf(dy));
        if (steps <= 0) { blend_px((int)x0, (int)y0, r, g, b, a); continue; }
        for (int j = 0; j <= steps; j++) {
            float t = (float)j / (float)steps;
            blend_px((int)(x0 + dx * t), (int)(y0 + dy * t), r, g, b, a);
        }
    }
}

/* Pool: no Vita reinicia a cada quadro e os vértices vivem até o fim da
   cena. No PC o vértice é consumido na hora, então um espelhinho basta para o
   ui.c compilar e a varredura medir. NUNCA libera — é o comportamento do
   pool de verdade: a RAM volta TODA de uma vez no reset. */
/* O TAMANHO É O DO APARELHO, E ISSO CUSTOU UMA MUDANÇA INTEIRA.

   Era 64 KB. O `vita2d_init` do SDK pede **16 MB** (`.word 0x01000000`,
   desmontado do `vita2d.o`) — 256 vezes mais. Todo quadro cujos vértices
   passavam de 64 KB tinha o resto dos desenhos DESCARTADO aqui, em silêncio:
   o `arco` e o `ring_segmentos` checam o NULL e voltam sem desenhar.

   SINTOMA: subir os arcos de irisação do CD de 34 para 96 não mudou NADA no
   preview — nem a imagem, nem a contagem de desenho, byte por byte. A
   mudança estava no código e o shim a jogava fora.

   É a terceira vez que uma foto aprova o que o aparelho reprova (as outras:
   a coleção sem capa e o tamanho da letra). Aqui era pior que aprovar: era
   ESCONDER a mudança de quem a fez. */
static char g_pool[16 * 1024 * 1024];
static unsigned int g_pool_u;
static long g_pool_faltou;
long hostgfx_pool_faltou(void) { return g_pool_faltou; }
void *vita2d_pool_memalign(unsigned int size, unsigned int alignment)
{
    if (alignment == 0) alignment = 1;
    unsigned int base = (g_pool_u + alignment - 1) & ~(alignment - 1);
    if (base + size > sizeof(g_pool)) { g_pool_faltou++; return NULL; }
    void *p = g_pool + base;
    g_pool_u = base + size;
    return p;
}
unsigned int vita2d_pool_free_space(void) { return (unsigned int)(sizeof(g_pool) - g_pool_u); }
void vita2d_pool_reset(void) { g_pool_u = 0; }

/* ---------- texturas ---------- */
struct vita2d_texture {
    unsigned int w, h;
    unsigned char *rgb;   /* w*h*3 */
    unsigned long ultimo_uso;   /* em que quadro a GPU a leu por último */
    int linear;           /* o desenho INTERPOLA — ver vita2d_texture_set_filters */
};

unsigned int vita2d_texture_get_width(const vita2d_texture *t)  { return t ? t->w : 0; }
unsigned int vita2d_texture_get_height(const vita2d_texture *t) { return t ? t->h : 0; }

/* contabiliza a textura nova; definida mais abaixo, junto do contador */
static vita2d_texture *tex_nasceu(vita2d_texture *t);

/* ---------- acesso cru, para o ui.c poder encolher a capa ----------
   O shim guarda RGB de três bytes e ASSUME isso: o get_format diz qual é, e o
   ui.c trata os dois formatos. Não mentir aqui é o que faz o preview
   desenhar o mesmo fundo que o aparelho. */
unsigned int vita2d_texture_get_stride(const vita2d_texture *t) { return t ? t->w * 3 : 0; }
SceGxmTextureFormat vita2d_texture_get_format(const vita2d_texture *t)
{
    /* três bytes R,G,B — o mesmo que o carregador de JPEG do vita2d entrega
       no aparelho, e é por isso que o ui.c não precisa de #ifdef */
    (void)t; return SCE_GXM_TEXTURE_FORMAT_U8U8U8_BGR;
}
void *vita2d_texture_get_datap(const vita2d_texture *t) { return t ? t->rgb : NULL; }

/* NO APARELHO ISTO É O QUE FAZ O BORRÃO EXISTIR: ampliar 64 px para a tela
   inteira só vira borrão se o hardware interpolar. O shim não tem hardware,
   então interpola na mão no desenho — ver `amostra`. Um preview que
   desenhasse o mosaico e o aparelho o borrão seria mais uma imagem que
   mente, e este projeto já pagou por uma dessas. */
void vita2d_texture_set_filters(vita2d_texture *t,
                                SceGxmTextureFilter min_filter,
                                SceGxmTextureFilter mag_filter)
{
    (void)min_filter;
    if (t) t->linear = (mag_filter == SCE_GXM_TEXTURE_FILTER_LINEAR);
}

/* Lê a textura em (u,v) NORMALIZADO por pixel de destino. Com `linear`,
   interpola os quatro vizinhos; sem, é o vizinho mais próximo — que é
   exatamente o que o SGX faz nos dois modos. */
static void amostra(const vita2d_texture *t, float sx, float sy,
                    int *r, int *g, int *b)
{
    int w = (int)t->w, h = (int)t->h;
    if (!t->linear) {
        int x = (int)sx, y = (int)sy;
        if (x < 0) x = 0; if (x >= w) x = w - 1;
        if (y < 0) y = 0; if (y >= h) y = h - 1;
        const unsigned char *s = &t->rgb[((size_t)y * w + x) * 3];
        *r = s[0]; *g = s[1]; *b = s[2];
        return;
    }
    float fx = sx - 0.5f, fy = sy - 0.5f;
    int x0 = (int)floorf(fx), y0 = (int)floorf(fy);
    float tx = fx - x0, ty = fy - y0;
    int x1 = x0 + 1, y1 = y0 + 1;
    if (x0 < 0) x0 = 0; if (x0 >= w) x0 = w - 1;
    if (x1 < 0) x1 = 0; if (x1 >= w) x1 = w - 1;
    if (y0 < 0) y0 = 0; if (y0 >= h) y0 = h - 1;
    if (y1 < 0) y1 = 0; if (y1 >= h) y1 = h - 1;
    const unsigned char *a = &t->rgb[((size_t)y0 * w + x0) * 3];
    const unsigned char *b2 = &t->rgb[((size_t)y0 * w + x1) * 3];
    const unsigned char *c = &t->rgb[((size_t)y1 * w + x0) * 3];
    const unsigned char *d = &t->rgb[((size_t)y1 * w + x1) * 3];
    for (int k = 0; k < 3; k++) {
        float top = a[k] + (b2[k] - a[k]) * tx;
        float bot = c[k] + (d[k] - c[k]) * tx;
        float v = top + (bot - top) * ty;
        int iv = (int)(v + 0.5f);
        if (iv < 0) iv = 0; if (iv > 255) iv = 255;
        if (k == 0) *r = iv; else if (k == 1) *g = iv; else *b = iv;
    }
}

vita2d_texture *vita2d_create_empty_texture_format(unsigned int w, unsigned int h,
                                                   SceGxmTextureFormat format)
{
    (void)format;
    if (!w || !h) return NULL;
    vita2d_texture *t = calloc(1, sizeof(*t));
    if (!t) return NULL;
    t->w = w; t->h = h;
    t->rgb = calloc((size_t)w * h, 3);
    if (!t->rgb) { free(t); return NULL; }
    return tex_nasceu(t);
}

/* QUANTA TEXTURA ESTÁ VIVA.

   No PC isto não custa nada e por isso não se nota; no Vita a VRAM é o que
   acaba primeiro, e uma capa que se carrega e não se solta some do orçamento
   sem aparecer em lugar nenhum — até a lista de display estourar e o cartão
   encher de GPUCRASH. A varredura pergunta este número ANTES e DEPOIS de
   passear pelas telas: se ele subiu e não voltou, há capa vazando.

   Conta o BYTE e não só o objeto: uma capa de 500x500 e um ícone de 24 são a
   mesma unidade numa contagem de objetos e duzentas vezes um do outro aqui. */
static long g_tex_vivas, g_tex_bytes;
long hostgfx_tex_vivas(void) { return g_tex_vivas; }
long hostgfx_tex_bytes(void) { return g_tex_bytes; }

/* ═══ SOLTA CEDO DEMAIS: o detector de GPUCRASH ═══════════════════════════

   No PC, soltar uma textura logo depois de desenhá-la não dói: nada leu
   aquela memória de verdade. No Vita dói, e o preço é o sistema inteiro —
   o vita2d é TRIPLO-bufferizado (o `displayBufferData` do libvita2d.a tem
   três ponteiros), então a GPU pode estar LENDO uma textura entregue dois
   quadros atrás enquanto a CPU já desenha o de agora. Soltar ali é ler
   memória liberada, e o sintoma é `psp2core-*-GPUCRASH` no cartão.

   Foi assim que este projeto perdeu duas semanas: o defeito só existe no
   aparelho, o teste do PC passava verde, e o único sinal era um arquivo de
   dump que não diz qual tela o causou.

   Isto põe a regra do aparelho DENTRO do shim: toda textura lembra em que
   quadro foi desenhada pela última vez, e soltá-la a menos de
   VITA_BUFFERS quadros disso é reprovado, com o nome do arquivo e a linha
   pela pilha do ASAN. O host não precisa de GPU nenhuma para conferir uma
   REGRA. */
#define VITA_BUFFERS 3          /* medido no libvita2d.a, não chutado */

static int  g_solta_cedo;
static char g_solta_onde[160] = "";

void hostgfx_frame_mark(void) { g_quadro++; }
int  hostgfx_solta_cedo(void) { return g_solta_cedo; }
const char *hostgfx_solta_cedo_onde(void) { return g_solta_onde; }

static vita2d_texture *tex_nasceu(vita2d_texture *t)
{
    if (t) {
        g_tex_vivas++;
        g_tex_bytes += (long)t->w * t->h * 3;
        acusa_cena("CRIADA", t->w, t->h);
    }
    return t;
}

void vita2d_free_texture(vita2d_texture *t)
{
    if (!t) return;
    /* A REGRA DO APARELHO, conferida aqui. `ultimo_uso` 0 quer dizer
       "nunca desenhada" — soltar essa é sempre seguro. */
    if (t->ultimo_uso && g_quadro - t->ultimo_uso < VITA_BUFFERS) {
        g_solta_cedo++;
        if (!g_solta_onde[0])
            snprintf(g_solta_onde, sizeof(g_solta_onde),
                     "textura %ux%u desenhada no quadro %lu e solta no %lu "
                     "(a GPU do Vita ainda pode estar lendo até %d quadros depois)",
                     t->w, t->h, t->ultimo_uso, g_quadro, VITA_BUFFERS);
    }
    acusa_cena("SOLTA", t->w, t->h);
    g_tex_vivas--;
    g_tex_bytes -= (long)t->w * t->h * 3;
    free(t->rgb);
    free(t);
}

void vita2d_draw_texture_scale(const vita2d_texture *t, float x, float y,
                               float x_scale, float y_scale)
{
    if (t) ((vita2d_texture *)t)->ultimo_uso = g_quadro;
    g_draws++; g_tex++;
    if (g_sem_pintar) return;
    if (!t || !t->rgb) return;
    int dw = (int)(t->w * x_scale), dh = (int)(t->h * y_scale);
    if (dw <= 0 || dh <= 0) return;
    for (int j = 0; j < dh; j++) {
        float sy = ((float)j + 0.5f) / y_scale;
        if (sy < 0 || sy >= (float)t->h) continue;
        for (int i = 0; i < dw; i++) {
            float sx = ((float)i + 0.5f) / x_scale;
            if (sx < 0 || sx >= (float)t->w) continue;
            int r, g, b;
            amostra(t, sx, sy, &r, &g, &b);
            blend_px((int)x + i, (int)y + j, r, g, b, 255);
        }
    }
}

/* Textura TINGIDA: multiplica cada pixel pela cor (e usa o alfa dela). É como
   o ui.c escurece a capa que serve de fundo, e sem isto o preview não
   reproduz a camada certa. */
void vita2d_draw_texture_tint_scale(const vita2d_texture *t, float x, float y,
                                    float x_scale, float y_scale, unsigned int color)
{
    if (t) ((vita2d_texture *)t)->ultimo_uso = g_quadro;
    g_draws++; g_tex++;
    if (g_sem_pintar) return;
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
    if (t) ((vita2d_texture *)t)->ultimo_uso = g_quadro;
    g_draws++; g_tex++;
    if (g_sem_pintar) return;
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
    return tex_nasceu(t);
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

vita2d_texture *vita2d_load_JPEG_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0) { fclose(f); return NULL; }
    void *buf = malloc((size_t)n);
    if (!buf) { fclose(f); return NULL; }
    size_t lidos = fread(buf, 1, (size_t)n, f);
    fclose(f);
    vita2d_texture *t = vita2d_load_JPEG_buffer(buf, (unsigned long)lidos);
    free(buf);
    return t;
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
    return tex_nasceu(t);
}

/* ---------- texto (FreeType) ---------- */
struct vita2d_pvf { FT_Library lib; FT_Face face; int px; };
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

vita2d_pvf *vita2d_load_system_pvf(int numFonts, const vita2d_system_pvf_config *cfg)
{
    (void)numFonts; (void)cfg;
    return vita2d_load_default_pvf();
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

/* ═══ O TEXTO AQUI TEM DE MENTIR IGUAL AO APARELHO ════════════════════════

   Esta função rasterizava no tamanho FINAL: pedia 13 px ao FreeType e saía
   um 13 px perfeito. O Vita não faz isso.

   Lá o `scePvfSetCharSize` é chamado UMA vez, no load — 18 px exatos —, os
   glifos vão para um atlas nesse tamanho, e o `vita2d_pvf_draw_text` só
   ESCALA a textura. Então todo texto do app é um bitmap de 18 px reamostrado,
   e os três tamanhos mais usados (13, 15, 17) são REDUÇÕES.

   Um preview que rasteriza no tamanho final não pode ver isso — e não viu:
   o dono leu a tela de verdade e disse "low res and you cant read properly"
   enquanto todo PNG daqui saía limpo. É a terceira vez hoje que uma foto
   aprova o que o aparelho reprova.

   Agora o shim rasteriza SEMPRE em 18 e escala o bitmap, com a mesma
   filtragem bilinear que o atlas usa depois do conserto do `pvf_filtro_linear`
   no ui.c. A imagem fica um pouco mole — e é para ficar: é assim que está no
   aparelho, e é isso que se veio julgar.

   O AVANÇO também muda de dono: o Vita mede em 18 px e multiplica pela
   escala (é o que o `vita2d_pvf_text_width` faz), então medir em 13 px daria
   larguras que o aparelho não tem — e a UI decide o que CORTAR por largura. */
static int set_px(vita2d_pvf *f, float scale)
{
    (void)scale;
    int px = (int)(HOSTGFX_PVF_BASE_PX + 0.5f);
    if (px != f->px) { FT_Set_Pixel_Sizes(f->face, 0, (FT_UInt)px); f->px = px; }
    return px;
}

/* O AVANÇO DE UM GLIFO, LEMBRADO.

   Medir a largura de um texto não precisa do desenho do glifo — precisa só do
   avanço, que para um par (tamanho, caractere) é sempre o mesmo. Sem esta
   tabela, cada `text_width` fazia o FreeType carregar, escalar e ajustar cada
   caractere de novo; e a UI mede MUITO mais do que desenha, porque é por
   largura que ela decide o que cortar e onde alinhar.

   É memória exata, não aproximação: o valor guardado é o que o FreeType
   devolveu. Um cache que devolvesse outro número mudaria o corte do texto e
   com isso o que o preview mostra — que é o contrário do que ele serve. */
#define AV_PX   64        /* corpos possíveis, 6..63 px */
#define AV_CP  512        /* latim, acentuados e a pontuação que a UI usa */
static short g_av[AV_PX][AV_CP];      /* 0 = ainda não perguntei */
static unsigned char g_av_vazio[AV_PX][AV_CP];   /* o glifo não existe */

static int avanco(vita2d_pvf *f, int px, unsigned int cp, FT_GlyphSlot *gs_out)
{
    int cabe = (px >= 0 && px < AV_PX && cp < AV_CP);
    if (cabe && !gs_out) {
        if (g_av_vazio[px][cp]) return -1;
        if (g_av[px][cp]) return g_av[px][cp];
    }
    if (FT_Load_Char(f->face, cp,
                     gs_out ? FT_LOAD_RENDER : FT_LOAD_DEFAULT)) {
        if (cabe) g_av_vazio[px][cp] = 1;
        return -1;
    }
    int a = (int)(f->face->glyph->advance.x >> 6);
    if (cabe && a > 0 && a < 32767) g_av[px][cp] = (short)a;
    if (gs_out) *gs_out = f->face->glyph;
    return a;
}

int vita2d_pvf_draw_text(vita2d_pvf *f, int x, int y, unsigned int color,
                         float scale, const char *text)
{
    if (!f || !text) return 0;
    int r, g, b, a; unpack(color, &r, &g, &b, &a);
    int px = set_px(f, scale);

    int pen = x;
    for (const char *s = text; *s; ) {
        unsigned int cp;
        s = utf8_next(s, &cp);
        /* SEM PINTAR, sem RASTERIZAR: o `FT_LOAD_RENDER` desenha o glifo, e
           a varredura joga esse desenho fora. Só o AVANÇO sobrevive — e ele
           não depende de o glifo ter sido desenhado. */
        FT_GlyphSlot gs = NULL;
        int av = avanco(f, px, cp, g_sem_pintar ? NULL : &gs);
        if (av < 0) continue;
        /* UM POR GLIFO. O vita2d_pvf desenha cada caractere com um
           `vita2d_draw_texture_tint_part_scale` — logo, um sceGxmDraw por
           letra. É o item mais caro de qualquer tela deste app e era o
           único que este contador não enxergava. */
        g_draws++;
        if (gs) {
            /* O BITMAP DE 18 PX, ESCALADO — como o atlas do aparelho.
               Amostragem bilinear, que é o filtro que o `pvf_filtro_linear`
               do ui.c passa a pôr nos dois sentidos. */
            FT_Bitmap *bm = &gs->bitmap;
            int dw = (int)(bm->width * scale + 0.5f);
            int dh = (int)(bm->rows * scale + 0.5f);
            float px0 = (float)pen + gs->bitmap_left * scale;
            float py0 = (float)y - gs->bitmap_top * scale;
            for (int j = 0; j < dh; j++) {
                float sy = ((float)j + 0.5f) / scale - 0.5f;
                int y0 = (int)floorf(sy); float fy = sy - (float)y0;
                for (int i = 0; i < dw; i++) {
                    float sx = ((float)i + 0.5f) / scale - 0.5f;
                    int x0 = (int)floorf(sx); float fx = sx - (float)x0;
                    float acc = 0.0f;
                    for (int dy2 = 0; dy2 < 2; dy2++) {
                        int yy = y0 + dy2;
                        if (yy < 0 || yy >= (int)bm->rows) continue;
                        for (int dx2 = 0; dx2 < 2; dx2++) {
                            int xx = x0 + dx2;
                            if (xx < 0 || xx >= (int)bm->width) continue;
                            float w2 = (dx2 ? fx : 1.0f - fx) * (dy2 ? fy : 1.0f - fy);
                            acc += w2 * (float)bm->buffer[yy * (unsigned)bm->pitch + xx];
                        }
                    }
                    int cov = (int)(acc + 0.5f);
                    if (cov <= 0) continue;
                    if (cov > 255) cov = 255;
                    blend_px((int)(px0 + (float)i), (int)(py0 + (float)j),
                             r, g, b, a * cov / 255);
                }
            }
        }
        pen += (int)(av * scale + 0.5f);
    }
    return pen - x;
}

int vita2d_pvf_text_width(vita2d_pvf *f, float scale, const char *text)
{
    if (!f || !text) return 0;
    /* Mede em 18 e MULTIPLICA — é o que o `vita2d_pvf_text_width` faz no
       aparelho. Medir no corpo final daria larguras que o Vita não tem, e a
       UI decide o que cortar por largura. */
    int px = set_px(f, scale);
    float w = 0.0f;
    for (const char *s = text; *s; ) {
        unsigned int cp;
        s = utf8_next(s, &cp);
        int av = avanco(f, px, cp, NULL);
        if (av > 0) w += (float)av * scale;
    }
    return (int)(w + 0.5f);
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

/* ---------- toque ----------
   Os DOIS painéis, e de propósito com áreas ativas diferentes: o da frente
   reporta numa grade 2x a da tela; o de TRÁS é menor que a tela e a área
   ativa dele não começa em zero. Fingir os dois iguais aqui deixaria passar
   justamente o defeito que o mapeamento existe para evitar — um arrasto de
   trás preso no terço de cima. */
#define AA_FRENTE_X0 0
#define AA_FRENTE_Y0 0
#define AA_FRENTE_X1 (SCRW * 2 - 1)
#define AA_FRENTE_Y1 (SCRH * 2 - 1)
#define AA_TRAS_X0   0
#define AA_TRAS_Y0   108
#define AA_TRAS_X1   (SCRW * 2 - 1)
#define AA_TRAS_Y1   889

static int g_tap_x = -1,  g_tap_y = -1;    /* frente, em coordenadas de TELA */
static int g_back_x = -1, g_back_y = -1;   /* trás, idem */

void hosttouch_tap(int x, int y)  { g_tap_x = x;  g_tap_y = y; }
void hosttouch_back(int x, int y) { g_back_x = x; g_back_y = y; }

int sceTouchSetSamplingState(uint32_t port, uint32_t state)
{ (void)port; (void)state; return 0; }
int sceTouchEnableTouchForce(uint32_t port) { (void)port; return 0; }

int sceTouchGetPanelInfo(uint32_t port, SceTouchPanelInfo *info)
{
    if (!info) return -1;
    memset(info, 0, sizeof(*info));
    if (port == SCE_TOUCH_PORT_BACK) {
        info->minAaX = AA_TRAS_X0; info->minAaY = AA_TRAS_Y0;
        info->maxAaX = AA_TRAS_X1; info->maxAaY = AA_TRAS_Y1;
    } else {
        info->minAaX = AA_FRENTE_X0; info->minAaY = AA_FRENTE_Y0;
        info->maxAaX = AA_FRENTE_X1; info->maxAaY = AA_FRENTE_Y1;
    }
    return 0;
}

int sceTouchPeek(uint32_t port, SceTouchData *data, uint32_t nBufs)
{
    (void)nBufs;
    if (!data) return 0;
    memset(data, 0, sizeof(*data));
    int sx = (port == SCE_TOUCH_PORT_BACK) ? g_back_x : g_tap_x;
    int sy = (port == SCE_TOUCH_PORT_BACK) ? g_back_y : g_tap_y;
    if (sx >= 0) {
        /* o teste fala em coordenadas de TELA; aqui elas voltam para a grade
           do painel, que é o que o aparelho entrega */
        int x0 = (port == SCE_TOUCH_PORT_BACK) ? AA_TRAS_X0 : AA_FRENTE_X0;
        int y0 = (port == SCE_TOUCH_PORT_BACK) ? AA_TRAS_Y0 : AA_FRENTE_Y0;
        int x1 = (port == SCE_TOUCH_PORT_BACK) ? AA_TRAS_X1 : AA_FRENTE_X1;
        int y1 = (port == SCE_TOUCH_PORT_BACK) ? AA_TRAS_Y1 : AA_FRENTE_Y1;
        data->reportNum = 1;
        data->report[0].x = (int16_t)(x0 + (sx * (x1 - x0)) / SCRW);
        data->report[0].y = (int16_t)(y0 + (sy * (y1 - y0)) / SCRH);
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

/* --- a conferência de coordenada suja, para a varredura --- */
int hostgfx_coord_suja(void) { return g_suja; }
const char *hostgfx_coord_suja_onde(void)
{ return g_suja_onde[0] ? g_suja_onde : "(nenhuma)"; }
