/* O filtro da estante: 388 discos em 49 páginas viram os que interessam.
 *
 * O que se mede aqui é a parte que não se vê olhando a tela: o `u->sel` passa
 * a ser a posição DENTRO da lista filtrada, e o `ui_selected` tem de traduzir
 * de volta para o índice REAL da biblioteca. Errar essa tradução não desenha
 * nada de estranho — só toca o disco errado, que é o pior tipo de defeito
 * visual: aquele que não é visual.
 */
#include <stdio.h>
#include <string.h>

#include <psp2/ctrl.h>
#include <psp2/touch.h>
#include <vita2d.h>

#include "ui.h"
#include "library.h"
#include "player.h"

void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

static int falhas = 0;
static void ok(int cond, const char *o_que)
{
    printf("  %s %s\n", cond ? "\033[32m✓\033[0m" : "\033[31m✗\033[0m", o_que);
    if (!cond) falhas++;
}

int main(int argc, char **argv)
{
    const char *raiz = argc > 1 ? argv[1] : NULL;
    if (!raiz) { printf("uso: filtro_test <raiz>\n"); return 2; }

    vita2d_init();
    Library lib;
    library_init(&lib);
    library_add_root(&lib, raiz);
    library_scan(&lib);
    if (lib.nalbums < 4) { printf("  (colecao pequena demais: pulei)\n"); return 0; }

    Ui *u = ui_create();
    Player *p = player_create();
    printf("\033[1mo filtro da estante (%d discos)\033[0m\n", lib.nalbums);

    /* sem filtro: a estante inteira, e o indice e ele mesmo */
    ui_frame(u, &lib, p);
    ui_set_sel(u, 3);
    ui_frame(u, &lib, p);
    ok(ui_selected(u) == 3, "sem filtro, o indice marcado e o da biblioteca");

    /* com filtro: escolhe um termo que existe */
    const char *termo = NULL;
    static char buf[64];
    for (int i = 0; i < lib.nalbums && !termo; i++) {
        const char *nm = lib.albums[i].artist[0] ? lib.albums[i].artist
                                                 : lib.albums[i].album;
        if (strlen(nm) >= 4) {
            snprintf(buf, sizeof(buf), "%.4s", nm);
            termo = buf;
        }
    }
    ok(termo != NULL, "achei um termo para procurar");
    if (!termo) return 1;

    ui_set_busca(u, termo);
    ui_frame(u, &lib, p);
    int n = ui_shelf_count_dbg(u);
    printf("    termo \"%s\" -> %d disco(s)\n", termo, n);
    ok(n > 0 && n <= lib.nalbums, "o filtro devolve algo, e nao mais que tudo");

    /* TODO disco que passou tem mesmo o termo, e o indice traduzido bate */
    int erros = 0;
    for (int i = 0; i < n; i++) {
        ui_set_sel(u, i);
        ui_frame(u, &lib, p);
        int real = ui_selected(u);
        if (real < 0 || real >= lib.nalbums) { erros++; continue; }
        const Album *a = &lib.albums[real];
        char lo[512], t[64];
        snprintf(lo, sizeof(lo), "%s %s", a->artist, a->album);
        snprintf(t, sizeof(t), "%s", termo);
        for (char *q = lo; *q; q++) if (*q >= 'A' && *q <= 'Z') *q += 32;
        for (char *q = t;  *q; q++) if (*q >= 'A' && *q <= 'Z') *q += 32;
        if (!strstr(lo, t)) erros++;
    }
    ok(erros == 0, "cada posicao filtrada aponta para um disco que CASA o termo");

    /* limpar devolve a estante inteira */
    ui_set_busca(u, "");
    ui_frame(u, &lib, p);
    ok(ui_shelf_count_dbg(u) == lib.nalbums, "limpar o filtro devolve tudo");

    /* termo impossivel: zero, e sem estourar */
    ui_set_busca(u, "zzzqqqxxx-nao-existe");
    ui_frame(u, &lib, p);
    ok(ui_shelf_count_dbg(u) == 0, "termo impossivel da zero, e a tela nao quebra");
    ui_set_busca(u, "");

    player_destroy(p);
    ui_destroy(u);
    library_free(&lib);
    if (falhas) { printf("\n\033[31m%d falha(s)\033[0m\n", falhas); return 1; }
    printf("\n\033[32mo filtro corta a estante e o indice continua honesto\033[0m\n");
    return 0;
}
