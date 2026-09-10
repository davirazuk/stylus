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

/* A MOLDURA, COM UM DONO SÓ.

   Estes quatro números estavam escritos DUAS vezes: aqui, no ui_frame_geom,
   e como `#define` no topo do ui.c. Enquanto ninguém mexeu, as duas cópias
   concordaram; na primeira vez que o rodapé desceu (quando a fila de atalhos
   morreu e liberou 16 px), só uma das cópias soube — e o sintoma foi a nona
   linha da lista continuar cortada, com a geometria "certa" e a tela errada.

   É a mesma doença que o comentário lá embaixo descreve sobre a estante. Um
   dono só, e as duas metades leem daqui. */
#define UI_PAD_X   28.0f
#define UI_HEAD_Y  26
#define UI_BODY_Y  58.0f
#define UI_FOOT_DY 18.0f    /* distância do rodapé até o fim da tela */

/* SEIS POR TRÊS, e não quatro por dois.

   Oito discos de 388 são quarenta e nove páginas. A grade era pequena porque
   o card era GRANDE — moldura, sombra em três camadas, borda de seleção e
   três linhas de texto —, e o card era grande porque não havia capa: um
   quadrado vazio precisa de decoração para parecer alguma coisa.

   Agora há arte em 339 dos 388, e a lição do Sonara vale: A ARTE É O CARD.
   Sem moldura e sem sombra, a capa de 100 px se reconhece de relance, cabem
   dezoito por tela (22 páginas em vez de 49) e some o "muro de caixas" que
   dezoito molduras teriam feito.

   De quebra saem oito retângulos por card — sombra, fundo e as quatro bordas
   — que no aparelho são oito sceGxmDraw cada. */
#define UI_SHELF_COLS 6
#define UI_SHELF_ROWS 3
#define UI_SHELF_PAGE (UI_SHELF_COLS * UI_SHELF_ROWS)

typedef struct {
    float pad_x;
    float body_y, body_h;    /* a faixa entre o cabeçalho e o rodapé */
    float foot_y;
    int   head_y;
} UiFrameGeom;

typedef struct {
    float card_w, card_h, gap, x0, y0;
    float cover_side, cover_pad;
    /* Linhas de base dos rótulos, do topo do card. São DUAS: o nome do disco
       numa, o artista na outra.

       Eram TRÊS — o nome quebrava em duas linhas — porque o card tinha 212 px
       de largura e cabiam quatro por tela. Com dezoito por tela a coluna tem
       139: quebrar o nome em duas dá dois pedaços igualmente ilegíveis, em
       vez de um começo legível seguido de reticências. */
    float label_dy, sub_dy;
} UiShelfGeom;

typedef struct {
    float cx, cy, r;         /* o disco */
    float text_x, text_w;    /* a coluna à direita dele */
    float bar_y, bar_h;      /* a barra de progresso — o toque a usa para
                                buscar, então a geometria dela é pública */
    /* As duas linhas que moram SOB a barra. Estavam escritas à mão no ui.c
       como `bar_y + 20` e `bar_y + 44`, enquanto o list_y era calculado aqui:
       duas metades decidindo a mesma coisa, e elas discordaram — a primeira
       faixa da lista caía em cima do aviso. Um dono só. */
    float sig_y;             /* o caminho do sinal */
    float note_y;            /* "vira em X min" / o gesto do lado */
    float list_y, list_step;
    int   list_rows;
    /* Os TRÊS BOTÕES embaixo do disco: anterior, tocar/pausar, próxima.
       Existem porque o aparelho tem tela sensível ao toque e o deck só
       respondia a GESTO — tocar no disco pausa, arrastar de lado troca de
       faixa —, e gesto não se descobre olhando. Um botão desenhado é a única
       forma de a tela dizer que ela responde ao dedo.
       `tr_toque` é maior que `tr_r` de propósito: o alvo do dedo não é o
       tamanho do desenho, é o tamanho da ponta do dedo. */
    float tr_y, tr_gap, tr_r, tr_toque;
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
