/* Os atalhos que o rodapé ANUNCIA levam mesmo aonde prometem?

   Esta pergunta parece boba e não é. O deck anuncia três combinações com
   [R1] segurado — ouvir jogando, soneca, apagar a tela — e as três eram
   IMPOSSÍVEIS: [R1] agia na apertada, então no instante em que se segurava
   para fazer a combinação a tela já tinha pulado para as playlists. Três
   recursos inteiros escritos, desenhados no rodapé e mortos.

   Ler o código não pega isso: cada linha, sozinha, está certa. Só apertar
   pega — e apertar, aqui, é isto. */

#include <stdio.h>
#include <string.h>

#include <psp2/ctrl.h>
#include <vita2d.h>

#include "ui.h"
#include "library.h"
#include "player.h"

/* os números de View, na ordem do enum do ui.c */
enum { V_ESTANTE = 0, V_DECK, V_RECS, V_PLAYLISTS, V_JOGANDO };
static const char *NOME[] = { "estante", "deck", "recs", "playlists", "jogando" };

static int falhas = 0;

static void ok(int cond, const char *o_que, int obtido, int esperado)
{
    if (cond) { printf("  \033[32m✓\033[0m %s\n", o_que); return; }
    falhas++;
    printf("  \033[31m✗\033[0m %s\n", o_que);
    printf("      terminou em \"%s\", esperava \"%s\"\n",
           NOME[obtido & 7], NOME[esperado & 7]);
}

/* aperta e solta um botão */
static void toca(Ui *u, unsigned int b)
{
    hostctrl_press(0);  ui_handle_input(u);
    hostctrl_press(b);  ui_handle_input(u);
    hostctrl_press(0);  ui_handle_input(u);
}

/* segura `mod`, toca `b`, solta tudo — a combinação de verdade */
static void toca_com(Ui *u, unsigned int mod, unsigned int b)
{
    hostctrl_press(0);        ui_handle_input(u);
    hostctrl_press(mod);      ui_handle_input(u);
    hostctrl_press(mod | b);  ui_handle_input(u);
    hostctrl_press(mod);      ui_handle_input(u);
    hostctrl_press(0);        ui_handle_input(u);
}

/* leva ao deck a partir de onde estiver */
static void ao_deck(Ui *u)
{
    while (ui_view_dbg(u) != V_DECK) {
        if (ui_view_dbg(u) == V_ESTANTE) { toca(u, SCE_CTRL_CROSS); ui_skip_ritual(u); }
        else toca(u, SCE_CTRL_TRIANGLE);
    }
    ui_skip_ritual(u);
}

int main(void)
{
    vita2d_init();
    Ui *u = ui_create();
    if (!u) { printf("não criei a UI\n"); return 2; }

    printf("\033[1mos atalhos anunciados no rodapé\033[0m\n");

    ao_deck(u);
    toca_com(u, SCE_CTRL_R1, SCE_CTRL_TRIANGLE);
    ok(ui_view_dbg(u) == V_JOGANDO, "deck: [R1]+triângulo abre ouvir enquanto joga",
       ui_view_dbg(u), V_JOGANDO);

    ao_deck(u);
    /* SEGURAR o modificador não pode, sozinho, trocar de tela: era isso que
       matava as três combinações */
    hostctrl_press(0);            ui_handle_input(u);
    hostctrl_press(SCE_CTRL_R1);  ui_handle_input(u);
    ok(ui_view_dbg(u) == V_DECK, "deck: segurar [R1] NÃO troca de tela sozinho",
       ui_view_dbg(u), V_DECK);
    hostctrl_press(0);            ui_handle_input(u);
    ok(ui_view_dbg(u) == V_PLAYLISTS, "deck: e soltar [R1] sem combinar abre playlists",
       ui_view_dbg(u), V_PLAYLISTS);

    ao_deck(u);
    toca(u, SCE_CTRL_L1);
    ok(ui_view_dbg(u) == V_RECS, "deck: [L1] abre as recomendações",
       ui_view_dbg(u), V_RECS);

    ao_deck(u);
    toca(u, SCE_CTRL_TRIANGLE);
    ok(ui_view_dbg(u) == V_ESTANTE, "deck: triângulo volta à estante",
       ui_view_dbg(u), V_ESTANTE);

    toca(u, SCE_CTRL_L1);
    ok(ui_view_dbg(u) == V_RECS, "estante: [L1] abre as recomendações",
       ui_view_dbg(u), V_RECS);
    toca(u, SCE_CTRL_TRIANGLE);
    toca(u, SCE_CTRL_R1);
    ok(ui_view_dbg(u) == V_PLAYLISTS, "estante: [R1] abre as playlists",
       ui_view_dbg(u), V_PLAYLISTS);
    toca(u, SCE_CTRL_TRIANGLE);
    ok(ui_view_dbg(u) == V_ESTANTE, "playlists: triângulo volta à estante",
       ui_view_dbg(u), V_ESTANTE);

    ui_destroy(u);
    printf(falhas ? "\n\033[31m%d atalho(s) não levam aonde prometem\033[0m\n"
                  : "\n\033[32mtodos os atalhos levam aonde prometem\033[0m\n", falhas);
    return falhas ? 1 : 0;
}
