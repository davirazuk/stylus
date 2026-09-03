#include "ui_layout.h"

void ui_frame_geom(int scrw, int scrh, UiFrameGeom *g)
{
    (void)scrw;
    g->pad_x  = 28.0f;
    g->head_y = 26;
    g->body_y = 58.0f;
    g->foot_y = (float)scrh - 34.0f;
    g->hint_y = (float)scrh - 14.0f;
    g->body_h = (g->foot_y - 22.0f) - g->body_y;
}

void ui_shelf_geom(int scrw, int scrh, UiShelfGeom *g)
{
    UiFrameGeom f;
    ui_frame_geom(scrw, scrh, &f);
    g->gap = 18.0f;
    g->card_w = ((float)scrw - 2 * f.pad_x - (UI_SHELF_COLS - 1) * g->gap) / UI_SHELF_COLS;
    g->card_h = (f.body_h - (UI_SHELF_ROWS - 1) * g->gap) / UI_SHELF_ROWS;
    g->x0 = f.pad_x;
    g->y0 = f.body_y;
    g->cover_pad = 7.0f;
    /* a capa CEDE o que os dois rótulos precisam. Quando dois pisos dividem
       uma medida, quem cede é o DESENHO — a informação não. */
    g->label_dy = g->card_h - 26.0f;
    g->sub_dy   = g->card_h - 8.0f;
    g->cover_side = g->card_h - 46.0f - g->cover_pad;
    if (g->cover_side > g->card_w - 2 * g->cover_pad)
        g->cover_side = g->card_w - 2 * g->cover_pad;
    if (g->cover_side < 0) g->cover_side = 0;
}

void ui_deck_geom(int scrw, int scrh, UiDeckGeom *g)
{
    UiFrameGeom f;
    ui_frame_geom(scrw, scrh, &f);
    /* O disco sai do MENOR lado disponível: fixá-lo em 144 numa tela mais
       baixa o faria sair por baixo, e numa mais larga deixaria a coluna de
       texto com metade da tela vazia ao lado. */
    float avail_h = f.foot_y - f.body_y - 24.0f;
    float r = avail_h / 2.0f;
    if (r > (float)scrw * 0.16f) r = (float)scrw * 0.16f;
    if (r < 40.0f) r = 40.0f;
    g->r  = r;
    g->cx = f.pad_x + r * 1.55f;
    g->cy = f.body_y + avail_h / 2.0f + 12.0f;
    g->text_x = g->cx + r + 42.0f;
    g->text_w = (float)scrw - f.pad_x - g->text_x;
    g->bar_y = 262.0f;
    g->bar_h = 4.0f;
    if (g->bar_y > f.foot_y - 120.0f) g->bar_y = f.foot_y - 120.0f;
    g->list_y = g->bar_y + 34.0f;
    g->list_step = 22.0f;
    g->list_rows = (int)((f.foot_y - 26.0f - g->list_y) / g->list_step);
    if (g->list_rows > 6) g->list_rows = 6;
    if (g->list_rows < 0) g->list_rows = 0;
}

void ui_list_geom(int scrw, int scrh, UiListGeom *g)
{
    UiFrameGeom f;
    ui_frame_geom(scrw, scrh, &f);
    g->x = f.pad_x;
    g->w = (float)scrw - 2 * f.pad_x;
    g->y0 = f.body_y;
    g->row_h = 38.0f;
    g->rows = (int)((f.foot_y - 12.0f - g->y0) / g->row_h);
    if (g->rows < 1) g->rows = 1;
}
