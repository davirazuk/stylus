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
enum { V_ESTANTE = 0, V_DECK, V_RECS, V_PLAYLISTS, V_JOGANDO, V_CONTA,
       V_QOBUZ, V_AJUSTES, V_CONTROLES, V_ARTISTAS, V_HOME };
static const char *NOME[] = { "estante", "deck", "recs", "playlists",
                              "jogando", "conta", "qobuz", "ajustes",
                              "controles", "artistas", "home" };

static int falhas = 0;

static void ok(int cond, const char *o_que, int obtido, int esperado)
{
    if (cond) { printf("  \033[32m✓\033[0m %s\n", o_que); return; }
    falhas++;
    printf("  \033[31m✗\033[0m %s\n", o_que);
    printf("      terminou em \"%s\", esperava \"%s\"\n",
           NOME[obtido % 11], NOME[esperado % 11]);
}

/* aperta e solta um botão */
static void toca(Ui *u, unsigned int b)
{
    hostctrl_press(0);  ui_handle_input(u);
    hostctrl_press(b);  ui_handle_input(u);
    hostctrl_press(0);  ui_handle_input(u);
}

/* segura `mod`, toca `b`, solta tudo — a combinação de verdade.
   Devolve a AÇÃO do momento da combinação: nem todo atalho troca de tela
   (a soneca e o apagar a tela não trocam), e para esses a ação é a única
   prova de que o combo chegou a acontecer. */
static int toca_com(Ui *u, unsigned int mod, unsigned int b)
{
    hostctrl_press(0);        ui_handle_input(u);
    hostctrl_press(mod);      ui_handle_input(u);
    hostctrl_press(mod | b);
    int acao = ui_handle_input(u);
    hostctrl_press(mod);      ui_handle_input(u);
    hostctrl_press(0);        ui_handle_input(u);
    return acao;
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
    ok(ui_view_dbg(u) == V_QOBUZ, "deck: e soltar [R1] sem combinar anda uma aba",
       ui_view_dbg(u), V_QOBUZ);

    /* Os outros dois combos com [R1] não trocam de tela, então a prova é a
       ação — e eram tão inalcançáveis quanto o primeiro. */
    ao_deck(u);
    {
        int a = toca_com(u, SCE_CTRL_R1, SCE_CTRL_SQUARE);
        ok(a == 20, "deck: [R1]+quadrado cicla a soneca", ui_view_dbg(u), V_DECK);
        if (a != 20) printf("      ação %d, esperava 20\n", a);
    }

    ao_deck(u);
    {
        int antes = ui_resting(u) ? 1 : 0;
        toca_com(u, SCE_CTRL_R1, SCE_CTRL_L1);
        int depois = ui_resting(u) ? 1 : 0;
        ok(!antes && depois, "deck: [R1]+[L1] apaga a tela e segue no deck",
           ui_view_dbg(u), V_DECK);
    }
    /* e sai do repouso sem virar outra coisa */
    toca(u, SCE_CTRL_CIRCLE);

    /* A TRAVA (L1+R1, o L1 primeiro): congela tudo até repetir o gesto.
       R1+L1 (o R1 primeiro) continua apagando a tela — a ordem separa os
       dois, e era por NÍVEL antes: travava e destravava a cada quadro com
       as duas seguradas, e travado nada navega (este teste girava aqui). */
    {
        /* trava: depois do gesto, os ombros sozinhos não andam */
        toca_com(u, SCE_CTRL_L1, SCE_CTRL_R1);
        int v0 = ui_view_dbg(u);
        toca(u, SCE_CTRL_R1);
        toca(u, SCE_CTRL_L1);
        ok(ui_view_dbg(u) == v0, "travado: ombros sozinhos não andam",
           ui_view_dbg(u), v0);
        /* destrava com o mesmo gesto: os ombros voltam a andar */
        toca_com(u, SCE_CTRL_L1, SCE_CTRL_R1);
        toca(u, SCE_CTRL_R1);
        ok(ui_view_dbg(u) != v0, "destrava: [R1] volta a andar",
           ui_view_dbg(u), v0);
        ao_deck(u);
    }

    ao_deck(u);
    toca(u, SCE_CTRL_TRIANGLE);
    ok(ui_view_dbg(u) == V_ESTANTE, "deck: triângulo volta à estante",
       ui_view_dbg(u), V_ESTANTE);

    /* A FILA DE ABAS. O dono do app disse "qobuz simply doesn't exist" — e
       era verdade: chegar lá custava TRÊS R1 às cegas (estante → listas →
       conta → qobuz), sem que nenhuma tela dissesse a palavra antes da
       última. Agora L1/R1 andam numa fila só, desenhada no topo.
       A ordem é SHELF · PLAYING · QOBUZ · LISTS · RECS · ACCOUNT · SETTINGS.
       SETTINGS entrou na fila quando as opções que eram atalho escondido
       viraram tela — uma aba a mais é o preço de não ter combo secreto. */
    const int anel[] = { V_HOME, V_ESTANTE, V_ARTISTAS, V_DECK, V_QOBUZ,
                         V_PLAYLISTS, V_RECS, V_CONTA, V_AJUSTES };
    const int n_anel = (int)(sizeof(anel) / sizeof(anel[0]));

    ao_deck(u);
    toca(u, SCE_CTRL_R1);
    ok(ui_view_dbg(u) == V_QOBUZ, "deck: UM [R1] chega ao Qobuz",
       ui_view_dbg(u), V_QOBUZ);

    /* volta à estante e percorre o anel inteiro para a frente */
    /* começa na CABEÇA do anel, seja ela qual for — o anel ganhou a HOME na
       frente e este laço supunha que a estante era a primeira. */
    while (ui_view_dbg(u) != anel[0]) toca(u, SCE_CTRL_R1);
    for (int i = 1; i <= n_anel; i++) {
        toca(u, SCE_CTRL_R1);
        int esperado = anel[i % n_anel];
        char q[96];
        snprintf(q, sizeof(q), "[R1] %d/%d: chega em \"%s\"", i, n_anel,
                 NOME[esperado % 11]);
        ok(ui_view_dbg(u) == esperado, q, ui_view_dbg(u), esperado);
    }

    /* O OMBRO DE VERDADE. Os testes acima apertam SCE_CTRL_L1/R1, que é o que
       um controle externo manda. O ombro do PRÓPRIO Vita manda outro bit —
       LTRIGGER/RTRIGGER — e por isso o app inteiro ficou com as teclas de
       ombro mortas em aparelho, passando em todo teste. Este aperta o bit do
       aparelho. */
    while (ui_view_dbg(u) != V_ESTANTE) toca(u, SCE_CTRL_R1);
    /* a aba seguinte à estante passou a ser ARTISTS — ver o anel acima */
    toca(u, SCE_CTRL_RTRIGGER);
    ok(ui_view_dbg(u) == V_ARTISTAS, "o ombro DIREITO do Vita (RTRIGGER) anda na fila",
       ui_view_dbg(u), V_ARTISTAS);
    toca(u, SCE_CTRL_LTRIGGER);
    ok(ui_view_dbg(u) == V_ESTANTE, "e o ESQUERDO (LTRIGGER) volta",
       ui_view_dbg(u), V_ESTANTE);

    /* e para trás: [L1] da estante dá a volta e cai na última */
    ok(ui_view_dbg(u) == V_ESTANTE, "o ombro deixou onde se esperava",
       ui_view_dbg(u), V_ESTANTE);
    toca(u, SCE_CTRL_L1);
    ok(ui_view_dbg(u) == V_HOME, "estante: [L1] volta para a home",
       ui_view_dbg(u), V_HOME);
    toca(u, SCE_CTRL_R1);
    ok(ui_view_dbg(u) == V_ESTANTE, "e [R1] desfaz o passo",
       ui_view_dbg(u), V_ESTANTE);

    ui_destroy(u);
    printf(falhas ? "\n\033[31m%d atalho(s) não levam aonde prometem\033[0m\n"
                  : "\n\033[32mtodos os atalhos levam aonde prometem\033[0m\n", falhas);
    return falhas ? 1 : 0;
}
