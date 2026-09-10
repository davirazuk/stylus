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
#include "qobuz.h"
#include "rec.h"

void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

/* os números de View, na ordem do enum do ui.c */
enum { V_ESTANTE = 0, V_DECK, V_RECS, V_PLAYLISTS, V_JOGANDO, V_CONTA,
       V_QOBUZ, V_AJUSTES, V_CONTROLES, V_ARTISTAS, V_HOME };

static char outdir[1024];

/* Um frame só não basta: a UI acumula fase e algumas telas recalculam
   buffers. Roda alguns e grava o último. */
static void shot(Ui *ui, Library *lib, Player *p, const char *name)
{
    /* As capas carregam sob demanda, algumas por quadro: com poucos quadros a
       imagem pega o estado "ainda carregando" e não o que a pessoa vê. */
    for (int i = 0; i < 24; i++)
        ui_frame(ui, lib, p);
    /* O CUSTO DA TELA, medido no ÚLTIMO quadro (os anteriores carregam capa e
       não representam o estado de regime). Cada unidade é um sceGxmDraw no
       aparelho. Acima de ~8000 por quadro a lista de display começa a ficar
       perigosa; foi estourá-la que encheu o cartão de GPUCRASH. */
    hostgfx_draws_reset();
    ui_frame(ui, lib, p);
    unsigned long custo = (unsigned long)hostgfx_draws();

    char path[1200];
    snprintf(path, sizeof(path), "%s/%s.png", outdir, name);
    printf(hostgfx_save_png(path) == 0 ? "  %-34s %7lu draws\n"
                                       : "  !! falhou: %s (%lu)\n", name, custo);
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
/* Vai até a tela pedida andando na fila de abas.

   Antes daqui saíam [L1]/[R1] contados à mão — "L1 abre recs, R1 abre
   playlists" —, e quando a navegação virou uma fila só, cada foto passou a
   sair da tela errada COM O NOME CERTO: o arquivo "8c-qobuz.png" mostrava as
   recomendações. Uma foto que mente é pior que foto nenhuma. Agora se diz o
   DESTINO e o caminho que ele toma é problema dele. */
static void va_para(Ui *ui, int view)
{
    for (int i = 0; i < 12 && ui_view_dbg(ui) != view; i++)
        tap(ui, SCE_CTRL_R1);
}

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

    /* UMA CONTA DO QOBUZ DE MENTIRA.

       Metade das telas muda de forma quando há conta: a loja sai do
       formulário e vai para a busca, e o deck ganha a pílula que troca a
       faixa do cartão pela versão lossless. Sem isto o preview fotografa
       para sempre o estado de quem nunca entrou — e a lição do desktop é
       exatamente essa: tela medida vazia não é tela medida.

       Nada sai daqui para lugar nenhum: o preview só DESENHA, e a rede só é
       tocada por ação de botão, que este arquivo não dá para estas telas. */
    {
        QobuzConfig *qc = ui_qobuz_cfg(ui);
        snprintf(qc->app_id, sizeof(qc->app_id), "%s", "preview");
        snprintf(qc->app_secret, sizeof(qc->app_secret), "%s", "preview");
        snprintf(qc->token, sizeof(qc->token), "%s", "preview");
        qc->configured = true;
        ui_qobuz_finge_conta(ui);
    }

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

    /* uma parada em cada aba — nenhuma tela do anel fica sem foto */
    va_para(ui, V_RECS);       shot(ui, &lib, p, "7-recomendados");
    va_para(ui, V_PLAYLISTS);  shot(ui, &lib, p, "8-playlists");
    va_para(ui, V_CONTA);      shot(ui, &lib, p, "8b-conta");
    va_para(ui, V_QOBUZ);      shot(ui, &lib, p, "8c-qobuz");
    /* A MESMA ABA, A OUTRA FONTE. Sem esta foto, a tela do SoundCloud é a
       única do app que ninguém olha antes de instalar — e foi olhando as
       fotos que as duas últimas falhas visuais apareceram. */
    ui_set_fonte(ui, 1);       shot(ui, &lib, p, "8g-soundcloud");
    ui_set_fonte(ui, 0);
    va_para(ui, V_ARTISTAS);   shot(ui, &lib, p, "8f-artistas");
    /* A home lê o histórico para montar "mais tocados" e "nunca tocados".
       Sem ele as duas seções saem vazias e a foto não mostra a tela que a
       pessoa vê — então o preview carrega um Rec de verdade. */
    {
        static Rec rec;
        rec_load(&rec, "/tmp");
        ui_set_rec(ui, &rec);
    }
    va_para(ui, V_HOME);       shot(ui, &lib, p, "0-home");
    /* Os ajustes e a lista de controles: é para cá que foram as opções que
       antes eram atalho escondido, então elas precisam ser vistas. */
    va_para(ui, V_AJUSTES);    shot(ui, &lib, p, "8d-ajustes");
    /* CINCO descidas, não duas: `controls` é a ÚLTIMA linha dos ajustes
       (AJ_CONTROLES = 5) e a lista cresceu desde que isto foi escrito. Com
       duas, o [X] caía em "rear touch pad" — a foto chamada "8e-controles"
       mostrava os AJUSTES, e de quebra o preview LIGAVA um ajuste a cada
       execução. Uma foto que mente é pior que foto nenhuma; já tinha
       acontecido aqui com as abas.

       Contado a partir do topo porque entrar na tela marca a primeira linha:
       se um dia a ordem mudar, o certo é este laço falhar em VOLTAR e a foto
       sair visivelmente errada — não sair certa por acidente. */
    for (int i = 0; i < 5; i++) tap(ui, SCE_CTRL_DOWN);
    tap(ui, SCE_CTRL_CROSS);
    shot(ui, &lib, p, "8e-controles");
    tap(ui, SCE_CTRL_TRIANGLE);
    va_para(ui, V_ESTANTE);

    /* O OUTRO TEMA. Não adianta conferir a paleta só na conta de contraste:
       o que decide se um tema presta é ver a tela inteira nele. */
    ui_set_tema(ui, 1);
    shot(ui, &lib, p, "9a-tema-vita-estante");
    va_para(ui, V_DECK);       shot(ui, &lib, p, "9b-tema-vita-deck");
    va_para(ui, V_ESTANTE);
    ui_set_tema(ui, 0);

    /* O CD. A outra mídia do prato tem desenho próprio — corpo prateado,
       irisação, furo no meio e a leitura ao contrário — e nada disso se
       julga sem ver. */
    ui_set_midia(ui, 1);
    va_para(ui, V_DECK);       shot(ui, &lib, p, "9c-cd");
    ui_set_tema(ui, 1);        shot(ui, &lib, p, "9d-cd-tema-vita");
    ui_set_tema(ui, 0);
    ui_set_midia(ui, 0);
    va_para(ui, V_ESTANTE);

    /* A RÉGUA e a ESTANTE FILTRADA. Elas são a forma de achar um disco entre
       388, e sem elas aqui a única maneira de julgar como ficaram seria
       instalar no aparelho — que é justamente o que este arquivo evita. */
    tap(ui, SCE_CTRL_SQUARE);
    shot(ui, &lib, p, "1b-regua");
    tap(ui, SCE_CTRL_TRIANGLE);
    {
        /* um termo que exista de fato nesta coleção */
        char termo[32] = "";
        for (int i = 0; i < lib.nalbums && !termo[0]; i++) {
            const char *nm = lib.albums[i].artist[0] ? lib.albums[i].artist
                                                     : lib.albums[i].album;
            if (strlen(nm) >= 4) snprintf(termo, sizeof(termo), "%.4s", nm);
        }
        if (termo[0]) {
            ui_set_busca(ui, termo);
            shot(ui, &lib, p, "1c-estante-filtrada");
        }
        ui_set_busca(ui, "zzqqxx");
        shot(ui, &lib, p, "1d-filtro-sem-resultado");
        ui_set_busca(ui, "");
    }

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
