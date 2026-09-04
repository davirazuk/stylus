/* Renderiza cada tela da UI num PNG, no PC.
   Não emula o Vita: monta uma cena plausível com a coleção REAL (capas de
   verdade), roda o ui_frame() de verdade e grava a imagem. Serve para julgar
   cor, hierarquia e se algo estoura a caixa — as ressalvas honestas estão no
   topo de vita2d_host.c.

   uso: preview <raiz-de-musica> <dir-de-saida> */

#include <vita2d.h>
#include <psp2/ctrl.h>
#include <psp2/touch.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#include "library.h"
#include "player.h"
#include "ui.h"
#include "playlist.h"

void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

static char outdir[1024];

/* Um frame só não basta: a UI acumula fase e algumas telas recalculam
   buffers. Roda alguns e grava o último. */
static void shot(Ui *ui, Library *lib, Player *p, const char *name)
{
    /* As capas carregam sob demanda, algumas por quadro: com poucos quadros a
       imagem pega o estado "ainda carregando" e não o que a pessoa vê. */
    for (int i = 0; i < 24; i++)
        ui_frame(ui, lib, p);
    char path[1200];
    snprintf(path, sizeof(path), "%s/%s.png", outdir, name);
    printf(hostgfx_save_png(path) == 0 ? "  %s\n" : "  !! falhou: %s\n", path);
}

/* o ui_handle_input lê a BORDA: precisa soltar antes de apertar */
static void tap(Ui *ui, unsigned int botao)
{
    hostctrl_press(0);  ui_handle_input(ui);
    hostctrl_press(botao); ui_handle_input(ui);
    hostctrl_press(0);  ui_handle_input(ui);
}

/* combinação: um botão SEGURADO e outro tocado. A tela de ouvir enquanto
   joga só se alcança assim (R1 + triângulo), e sem isto ela ficava de fora
   do preview — justamente a tela que mais importa com o plugin instalado. */
static void tap_com(Ui *ui, unsigned int segurado, unsigned int botao)
{
    hostctrl_press(0);                    ui_handle_input(ui);
    hostctrl_press(segurado);             ui_handle_input(ui);
    hostctrl_press(segurado | botao);     ui_handle_input(ui);
    hostctrl_press(segurado);             ui_handle_input(ui);
    hostctrl_press(0);                    ui_handle_input(ui);
}

int main(int argc, char **argv)
{
    const char *root = argc > 1 ? argv[1] : "/run/media/davirazuk/VITASD/music";
    snprintf(outdir, sizeof(outdir), "%s",
             argc > 2 ? argv[2] : "/tmp/vitastylus-preview");
    mkdir(outdir, 0777);

    Library lib;
    library_init(&lib);
    library_add_root(&lib, root);
    library_scan(&lib);
    if (lib.nalbums == 0) {
        fprintf(stderr, "preview: nada varrido em %s\n", root);
        return 1;
    }
    printf("biblioteca: %d álbuns de %s\n", lib.nalbums, root);

    vita2d_init();
    Ui *ui = ui_create();
    Player *p = player_create();
    if (!ui || !p) { fprintf(stderr, "preview: ui/player\n"); return 1; }

    /* recomendações: primeiras faixas de vários álbuns */
    static const Track *recs[64];
    int nrecs = 0;
    for (int a = 0; a < lib.nalbums && nrecs < 40; a++)
        if (lib.albums[a].ntracks > 0) recs[nrecs++] = &lib.albums[a].tracks[0];

    /* playlists de mentira, em memória */
    Playlist *pls = NULL;
    int npls = 0;
    for (int k = 0; k < 4 && k < lib.nalbums; k++) {
        const Track *t[8];
        int n = 0;
        for (int i = 0; i < lib.albums[k].ntracks && n < 8; i++)
            t[n++] = &lib.albums[k].tracks[i];
        if (n) playlist_new(&pls, &npls, "Mix", t, n);
    }

    ui_set_data(ui, pls, npls, recs, nrecs);
    ui_set_bgm(ui, true);

    /* um álbum COM capa: o rótulo do vinil só se julga com arte de verdade */
    Album *alb = &lib.albums[0];
    for (int i = 0; i < lib.nalbums; i++)
        if (album_load_cover(&lib.albums[i]) == 0 && lib.albums[i].cover
            && lib.albums[i].ntracks > 0) { alb = &lib.albums[i]; break; }
    album_load_meta(alb);
    const Track *tr = alb->ntracks ? &alb->tracks[0] : NULL;
    int dur = (tr && tr->seconds > 0) ? tr->seconds : 231;

    printf("gravando em %s:\n", outdir);

    shot(ui, &lib, p, "1-estante");

    for (int i = 0; i < 5; i++) tap(ui, SCE_CTRL_DOWN);
    shot(ui, &lib, p, "2-estante-rolada");
    for (int i = 0; i < 5; i++) tap(ui, SCE_CTRL_UP);

    /* deck tocando, FLAC 44,1 (o caso que segura o 2º plano) */
    tap(ui, SCE_CTRL_CROSS);
    ui_skip_ritual(ui);                 /* pula a cerimônia para ver o deck */
    preview_player_set(p, alb, tr, PLAYER_PLAYING, dur * 38 / 100, dur, 0,
                       alb->ntracks, REPEAT_ALL, true, "FLAC", 44100, 16, 44100);
    shot(ui, &lib, p, "3-deck-tocando");

    /* deck pausado, hi-res: 96k/24 no arquivo, 44,1k/16 no aparelho — o
       caso que a linha do sinal existe para contar sem enfeite */
    preview_player_set(p, alb, tr, PLAYER_PAUSED, dur * 72 / 100, dur, 2,
                       alb->ntracks, REPEAT_ONE, false, "FLAC", 96000, 24, 44100);
    shot(ui, &lib, p, "4-deck-pausado-hires");
    preview_player_set(p, alb, tr, PLAYER_PLAYING, dur * 38 / 100, dur, 0,
                       alb->ntracks, REPEAT_ALL, true, "FLAC", 44100, 16, 44100);

    /* a cerimônia de pôr o disco */
    ui_begin_ritual(ui);
    shot(ui, &lib, p, "5-cerimonia");
    ui_skip_ritual(ui);

    /* ouvir enquanto joga: a tela do 2º plano */
    tap_com(ui, SCE_CTRL_R1, SCE_CTRL_TRIANGLE);
    shot(ui, &lib, p, "6-ouvir-jogando");
    tap(ui, SCE_CTRL_TRIANGLE);

    tap(ui, SCE_CTRL_L1);  shot(ui, &lib, p, "7-recomendados");
    tap(ui, SCE_CTRL_TRIANGLE);
    tap(ui, SCE_CTRL_R1);  shot(ui, &lib, p, "8-playlists");
    tap(ui, SCE_CTRL_TRIANGLE);

    /* tela de varredura e estante vazia */
    ui_draw_scanning(ui, "ux0:music/Radiohead", 1234);
    hostgfx_save_png("/tmp/vitastylus-preview-scan.png");
    {
        char path[1200];
        snprintf(path, sizeof(path), "%s/9-varrendo.png", outdir);
        rename("/tmp/vitastylus-preview-scan.png", path);
        printf("  %s\n", path);
    }
    {
        Library vazia;
        memset(&vazia, 0, sizeof(vazia));
        library_init(&vazia);
        preview_player_set(p, NULL, NULL, PLAYER_STOPPED, 0, -1, 0, 0,
                           REPEAT_OFF, false, "—", 0, 0, 0);
        shot(ui, &vazia, p, "10-estante-vazia");
    }

    playlist_free(pls, npls);
    player_destroy(p);
    ui_destroy(ui);
    library_free(&lib);
    vita2d_fini();
    printf("pronto.\n");
    return 0;
}
