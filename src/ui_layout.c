#include "ui_layout.h"

void ui_frame_geom(int scrw, int scrh, UiFrameGeom *g)
{
    (void)scrw;
    g->pad_x  = UI_PAD_X;
    g->head_y = UI_HEAD_Y;
    g->body_y = UI_BODY_Y;
    /* O RODAPÉ DESCEU 16 px, e o motivo é que a FILA DE ATALHOS MORREU.

       Havia duas linhas embaixo: o rodapé (estado, contagens) em `foot_y` e a
       fila de teclas em `hint_y`, encostada na borda. A fila virou a tela de
       Controls, e ninguém reclamou o espaço que ela deixou — as listas
       continuaram apertadas contra um rodapé que estava alto para dar lugar a
       uma linha que não existe mais.

       O `hint_y` saiu junto: um campo que ninguém lê é uma promessa de que
       ainda há uma fila ali embaixo. */
    g->foot_y = (float)scrh - UI_FOOT_DY;
    g->body_h = (g->foot_y - 22.0f) - g->body_y;
}

void ui_shelf_geom(int scrw, int scrh, UiShelfGeom *g)
{
    UiFrameGeom f;
    ui_frame_geom(scrw, scrh, &f);
    /* 14 e não 18: com seis colunas o vão aparece seis vezes na largura, e
       cada pixel dele sai da capa, que é o que se olha. */
    g->gap = 14.0f;
    g->card_w = ((float)scrw - 2 * f.pad_x - (UI_SHELF_COLS - 1) * g->gap) / UI_SHELF_COLS;
    g->card_h = (f.body_h - (UI_SHELF_ROWS - 1) * g->gap) / UI_SHELF_ROWS;
    g->x0 = f.pad_x;
    g->y0 = f.body_y;
    g->cover_pad = 0.0f;      /* sem moldura, não há borda de onde afastar */

    /* DUAS linhas de rótulo, não três. O nome do disco em uma só, cortado no
       fim, e o artista embaixo. A terceira linha existia porque o card era
       largo o bastante para o nome quebrar em duas; num de 139 px, quebrar em
       duas dá dois pedaços igualmente ilegíveis em vez de um começo legível.
       A capa CEDE o que os rótulos precisam — quem cede é o desenho. */
    g->label_dy = g->card_h - 20.0f;    /* o nome do disco */
    g->sub_dy   = g->card_h - 3.0f;     /* o artista */
    g->cover_side = g->card_h - 42.0f;
    if (g->cover_side > g->card_w) g->cover_side = g->card_w;
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
    /* A barra é onde o dedo busca, e a 4 px ela lia como um sublinhado do
       tempo em vez de um controle. A 6 px ela vira alvo — e continua fina o
       bastante para não competir com o disco, que é o assunto da tela. */
    g->bar_y = 264.0f;
    g->bar_h = 6.0f;
    if (g->bar_y > f.foot_y - 120.0f) g->bar_y = f.foot_y - 120.0f;
    /* Estes quatro afastamentos são função do TAMANHO DA LETRA, e a letra
       cresceu: o corpo da tela saiu de ~10 px para 15–17 (ver a nota da
       tipografia no ui.c). Com os valores de antes — +20, +44, +18, passo 22 —
       o caminho do sinal subia em cima da barra de progresso, que tem 6 px de
       altura e é onde o dedo busca. Encostar texto no único controle da tela
       é pior que apertado: some o alvo.

       A regra para mexer nisto: o afastamento tem de passar da ALTURA da
       linha, não do que sobra no desenho. 26 px para uma linha de 15 e 24 de
       passo para uma de 17 é o mínimo que ainda respira. */
    g->sig_y  = g->bar_y + 26.0f;
    g->note_y = g->bar_y + 50.0f;
    g->list_y = g->note_y + 22.0f;
    g->list_step = 24.0f;
    g->list_rows = (int)((f.foot_y - 26.0f - g->list_y) / g->list_step);
    if (g->list_rows > 6) g->list_rows = 6;
    if (g->list_rows < 0) g->list_rows = 0;

    /* Os botões vão SOB O DISCO, não sob a coluna de texto: ali sobra a faixa
       entre a borda do prato e o rodapé, e é onde a mão já está — a mesma
       metade da tela em que se toca no disco para pausar. */
    g->tr_r = 16.0f;
    g->tr_gap = 54.0f;
    g->tr_toque = 26.0f;
    g->tr_y = g->cy + g->r + 30.0f;
    if (g->tr_y > f.foot_y - 24.0f) g->tr_y = f.foot_y - 24.0f;
}

void ui_list_geom(int scrw, int scrh, UiListGeom *g)
{
    UiFrameGeom f;
    ui_frame_geom(scrw, scrh, &f);
    g->x = f.pad_x;
    g->w = (float)scrw - 2 * f.pad_x;
    g->y0 = f.body_y;
    /* 48 e nao 38: a linha e um ALVO DE DEDO numa tela de 5 polegadas a
       220 ppi, onde 38 px sao 4,4 mm — abaixo do que uma ponta de dedo
       acerta sem mirar. 48 dao ~5,6 mm e ainda cabem as duas linhas de texto
       (17 px em cima, 15 embaixo) sem se encostarem. */
    g->row_h = 48.0f;
    g->rows = (int)((f.foot_y - 12.0f - g->y0) / g->row_h);
    if (g->rows < 1) g->rows = 1;
}
