#ifndef STYLUS_UI_LAYOUT_H
#define STYLUS_UI_LAYOUT_H

/* A GEOMETRIA das telas, separada do desenho — e pura, para o teste de host
   poder MEDIR sem abrir janela nenhuma.
 *
 * Isto existe porque "número fixo de largura no desenho é sempre a tela de
 * quem escreveu". A estante nasceu com cards de 296x330 numa tela de 960x544:
 * três fileiras somavam 1042 px de altura, as duas de baixo eram desenhadas
 * FORA do monitor, e a paginação contava com nove visíveis — a seleção podia
 * parar numa fileira que não existia na tela. Nada disso estoura, e ler o
 * código não pega: os números parecem razoáveis. Só medir pega. */

#define UI_SHELF_COLS 4
#define UI_SHELF_ROWS 2
#define UI_SHELF_PAGE (UI_SHELF_COLS * UI_SHELF_ROWS)

typedef struct {
    float pad_x;
    float body_y, body_h;    /* a faixa entre o cabeçalho e o rodapé */
    float foot_y, hint_y;
    int   head_y;
} UiFrameGeom;

typedef struct {
    float card_w, card_h, gap, x0, y0;
    float cover_side, cover_pad;
    float label_dy, sub_dy;  /* linha de base dos rótulos, do topo do card */
} UiShelfGeom;

typedef struct {
    float cx, cy, r;         /* o disco */
    float text_x, text_w;    /* a coluna à direita dele */
    float list_y, list_step;
    int   list_rows;
} UiDeckGeom;

typedef struct {
    float x, w, y0, row_h;
    int   rows;
} UiListGeom;

void ui_frame_geom(int scrw, int scrh, UiFrameGeom *g);
void ui_shelf_geom(int scrw, int scrh, UiShelfGeom *g);
void ui_deck_geom(int scrw, int scrh, UiDeckGeom *g);
void ui_list_geom(int scrw, int scrh, UiListGeom *g);

#endif
