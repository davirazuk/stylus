/* Quantas chamadas de desenho um quadro emite.

   POR QUE ISTO É UM TESTE, e não uma curiosidade: no Vita cada
   vita2d_draw_rectangle vira um sceGxmDraw PRÓPRIO — não há agrupamento,
   conferido desmontando o libvita2d.a. O custo lá é o NÚMERO de chamadas.

   E é a classe de defeito que esta máquina não tem como sentir: o shim do
   preview rasteriza em C, e o tempo que ELE leva não diz nada sobre a GPU do
   aparelho. Contar diz. A estante já emitiu 21.272 chamadas por quadro (1,3
   milhão por segundo a 60 fps) sem nada acusar, porque no PC "funcionava".

   O teto abaixo tem folga sobre o número de hoje. Se um desenho novo o
   estourar, a pergunta certa não é "aumenta o teto" — é "dá para desenhar
   isto com menos chamadas", que foi como se saiu de 21 mil para 5 mil. */

#include <stdio.h>
#include <string.h>

#include <psp2/ctrl.h>
#include <vita2d.h>

#include "library.h"
#include "player.h"
#include "ui.h"

void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

/* Tetos por tela. Não são gosto: 60 fps x 8000 chamadas já são meio milhão
   de sceGxmDraw por segundo, e a partir daí a submissão sozinha come uma
   fatia grande do processador de 444 MHz. */
#define TETO_ESTANTE 9000
#define TETO_DECK    6000

static int falhas = 0;

static void ok(long obtido, long teto, const char *tela)
{
    if (obtido <= teto) {
        printf("  \033[32m✓\033[0m %s: %ld chamadas de desenho (teto %ld)\n",
               tela, obtido, teto);
        return;
    }
    falhas++;
    printf("  \033[31m✗\033[0m %s: %ld chamadas de desenho, teto %ld\n",
           tela, obtido, teto);
    printf("      a 60 fps são %.1f milhões por segundo\n", obtido * 60 / 1e6);
}

int main(int argc, char **argv)
{
    const char *raiz = argc > 1 ? argv[1] : NULL;
    vita2d_init();

    Library lib;
    library_init(&lib);
    if (raiz) library_add_root(&lib, raiz);
    library_scan(&lib);

    Ui *u = ui_create();
    Player *p = player_create();
    if (!u || !p) { printf("nao criei ui/player\n"); return 2; }

    printf("\033[1mchamadas de desenho por quadro\033[0m\n");

    /* aquece: as capas carregam sob demanda e o primeiro quadro não é o que
       a pessoa vê */
    for (int i = 0; i < 30; i++) ui_frame(u, &lib, p);
    hostgfx_draws_reset();
    ui_frame(u, &lib, p);
    ok(hostgfx_draws(), TETO_ESTANTE, "estante");

    /* deck com um disco tocando */
    Album *a = lib.nalbums ? &lib.albums[0] : NULL;
    if (a && a->ntracks) {
        album_load_meta(a);
        hostctrl_press(0);              ui_handle_input(u);
        hostctrl_press(SCE_CTRL_CROSS); ui_handle_input(u);
        hostctrl_press(0);              ui_handle_input(u);
        ui_skip_ritual(u);
        preview_player_set(p, a, &a->tracks[0], PLAYER_PLAYING, 60, 240, 0,
                           a->ntracks, REPEAT_ALL, true, "FLAC", 44100, 16, 44100);
        for (int i = 0; i < 30; i++) ui_frame(u, &lib, p);
        hostgfx_draws_reset();
        ui_frame(u, &lib, p);
        ok(hostgfx_draws(), TETO_DECK, "deck");
    } else {
        printf("  (sem coleção: só a estante foi medida)\n");
    }

    ui_destroy(u);
    library_free(&lib);
    printf(falhas ? "\n\033[31mdesenho acima do teto\033[0m\n"
                  : "\n\033[32mo desenho cabe no orçamento\033[0m\n");
    return falhas ? 1 : 0;
}
