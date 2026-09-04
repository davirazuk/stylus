/* O TOQUE, nos DOIS painéis.

   Duas coisas que só o dedo pega e que passaram despercebidas lendo o código:

   1. ARRASTAR A BARRA DO DECK NÃO BUSCAVA NADA. A barra se movia sob o dedo
      — o desenho usa o mesmo valor —, então parecia funcionar; ao soltar, a
      música continuava de onde estava. O deck limpava `scrubbing` no MESMO
      quadro em que emitia a ação, e o ui_scrub, que só respondia enquanto
      alguém arrastava, devolvia -1 justamente quando o main perguntava.

   2. A ALMOFADA DE TRÁS não existia para o app. E ela não se resolve com o
      "divide por 2" do painel da frente: a área ativa dela é menor que a
      tela e não começa em zero. Com a conversão errada, um arrasto vertical
      precisa de 40% mais dedo — o gesto fica meio morto, sem erro nenhum.
      É por isso que o shim de host finge as áreas ativas DIFERENTES.        */

#include <stdio.h>
#include <string.h>

#include <psp2/ctrl.h>
#include <psp2/touch.h>
#include <vita2d.h>

#include "ui.h"
#include "ui_layout.h"
#include "library.h"
#include "player.h"

/* do player de mentira do host */
void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

enum { V_ESTANTE = 0, V_DECK };

static int falhas = 0;

static void ok(int cond, const char *o_que)
{
    if (cond) { printf("  \033[32m✓\033[0m %s\n", o_que); return; }
    falhas++;
    printf("  \033[31m✗\033[0m %s\n", o_que);
}

/* nenhum dedo em painel nenhum, um quadro */
static int nada(Ui *u)
{
    hosttouch_tap(-1, -1);
    hosttouch_back(-1, -1);
    hostctrl_press(0);
    return ui_handle_input(u);
}

/* arrasta um dedo de (x0,y0) a (x1,y1) no painel escolhido e SOLTA.
   Devolve a ação do quadro da soltura, que é onde o gesto se completa. */
static int arrasta(Ui *u, int tras, int x0, int y0, int x1, int y1)
{
    void (*poe)(int, int) = tras ? hosttouch_back : hosttouch_tap;
    nada(u);
    for (int i = 0; i <= 8; i++) {
        poe(x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8);
        ui_handle_input(u);
    }
    poe(-1, -1);
    return ui_handle_input(u);
}

int main(void)
{
    vita2d_init();
    Ui *u = ui_create();
    if (!u) { printf("não criei a UI\n"); return 2; }

    printf("\033[1mo toque nos dois painéis\033[0m\n");

    /* ---- a estante ---- */
    ui_set_sel(u, 0);
    nada(u);
    arrasta(u, 1, 400, 270, 200, 272);          /* trás, para a esquerda */
    ok(ui_selected(u) == UI_SHELF_PAGE,
       "estante: arrastar de lado na almofada de trás vira a página");

    arrasta(u, 1, 200, 272, 400, 270);          /* e de volta */
    ok(ui_selected(u) == 0, "estante: e para o outro lado, volta");

    /* 62 px de TELA. O número é escolhido: ele passa do limiar de 50 quando a
       conversão do painel de trás está certa, e NÃO passa (vira 44) se
       alguém copiar o "divide por 2" do painel da frente. É a única forma de
       o teste distinguir as duas — o gesto meio morto não dá erro nenhum. */
    arrasta(u, 1, 300, 150, 302, 212);
    ok(ui_selected(u) == UI_SHELF_COLS,
       "estante: 62 px para baixo andam uma fileira (a escala do painel de trás)");

    ui_set_sel(u, 0);
    nada(u);
    /* um encosto parado atrás é a MÃO segurando o aparelho, não um comando */
    hosttouch_back(300, 200);
    for (int i = 0; i < 6; i++) ui_handle_input(u);
    hosttouch_back(-1, -1);
    ui_handle_input(u);
    ok(ui_selected(u) == 0 && ui_view_dbg(u) == V_ESTANTE,
       "estante: um encosto parado atrás não faz nada (é a mão segurando)");

    /* ---- o deck ---- */
    hostctrl_press(0); ui_handle_input(u);
    hostctrl_press(SCE_CTRL_CROSS); ui_handle_input(u);
    hostctrl_press(0); ui_handle_input(u);
    ui_skip_ritual(u);
    ok(ui_view_dbg(u) == V_DECK, "deck: entrei no deck para os testes da barra");

    /* a barra: o player de mentira do host diz 200 s de faixa, e o deck
       precisa ter DESENHADO um quadro para o cue saber de onde parte */
    UiDeckGeom g;
    ui_deck_geom(960, 544, &g);
    {
        Library lib; memset(&lib, 0, sizeof(lib));
        static Album a;
        static Track t;
        memset(&a, 0, sizeof(a));
        memset(&t, 0, sizeof(t));
        snprintf(a.artist, sizeof(a.artist), "Um Artista");
        snprintf(a.album,  sizeof(a.album),  "Um Disco");
        snprintf(t.title,  sizeof(t.title),  "Uma Faixa");
        t.seconds = 200; t.number = 1; t.decodable = true; t.owner = &a;
        a.tracks = &t; a.ntracks = 1; a.ndecodable = 1; a.seconds_total = 200;
        a.meta_loaded = true; a.cover_loaded = true;

        Player *p = player_create();
        preview_player_set(p, &a, &t, PLAYER_PLAYING, 0, 200, 0, 1,
                           REPEAT_OFF, false, "FLAC", 44100, 16, 44100);
        ui_frame(u, &lib, p);

        int ac = arrasta(u, 0, (int)g.text_x + 5, (int)g.bar_y,
                        (int)(g.text_x + g.text_w * 0.75f), (int)g.bar_y);
        float f = ui_scrub(u);
        ok(ac == 18, "deck: soltar a barra pede a busca");
        ok(f > 0.70f && f < 0.80f,
           "deck: e o ui_scrub AINDA responde onde o dedo largou (era -1)");

        /* o cue de trás: relativo, não absoluto */
        ui_frame(u, &lib, p);
        int a2 = arrasta(u, 1, 480, 270, 480 + 96, 272);   /* 96 px = 1/10 da tela */
        float f2 = ui_scrub(u);
        ok(a2 == 18, "deck: soltar o cue da almofada de trás pede a busca");
        /* 1/10 de tela × 90 s = 9 s; a faixa do stub tem 200 s */
        ok(f2 > 0.02f && f2 < 0.08f,
           "deck: e ele anda 9 s numa faixa de 200 s (ou seja: é fino)");
        player_destroy(p);
    }

    ui_destroy(u);
    if (falhas) { printf("\n\033[31m%d falha(s)\033[0m\n", falhas); return 1; }
    printf("\n\033[32mos dois painéis fazem o que a tela promete\033[0m\n");
    return 0;
}
