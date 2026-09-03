#include <vita2d.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/ctrl.h>
#include <psp2/sysmodule.h>
#include <psp2/appmgr.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "library.h"
#include "player.h"
#include "ui.h"
#include "playlist.h"
#include "rec.h"
#include "scrobble.h"

#define MUSIC_ROOT "ux0:music"

/* recomendações e playlists moram no cartão, junto do app */
#define UX0_DATA_DIR        "ux0:data/vitastylus"
#define PLAYLIST_DIR        UX0_DATA_DIR "/playlists"
#define REC_HISTORY_BASE    UX0_DATA_DIR

/* módulos de rede são pré-carregados para o futuro (Qobuz); inofensivo agora */
static void load_modules(void)
{
    sceSysmoduleLoadModule(SCE_SYSMODULE_NET);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTP);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTPS);
    sceSysmoduleLoadModule(SCE_SYSMODULE_SSL);
}

/* estado persistente que sobrevive o loop e alimenta a UI a cada frame */
typedef struct {
    Playlist *plists;
    int nplists;
    Rec rec;
    const Track **recs; /* ponteiros dentro de lib; dono é main (rebuild) */
    int nrecs;
    int recs_cap;
    bool dirty_plists;
    bool dirty_recs;
} Session;

#define RECS_MAX 200

static void session_free(Session *s)
{
    if (!s) return;
    if (s->plists) playlist_free(s->plists, s->nplists);
    free(s->recs);
    rec_free(&s->rec);
    memset(s, 0, sizeof(*s));
}

/* ao terminar uma faixa (>=50% tocada já aconteceu no player), marca no histórico */
static void on_track_done(const Track *t, void *ud)
{
    Session *s = ud;
    if (!t || !s) return;
    rec_play(&s->rec, t->path, REC_HISTORY_BASE);
    scrobble_log(REC_HISTORY_BASE, t, (long)time(NULL));
    s->dirty_recs = true;
}

/* reconstrói a lista recomendada (chamado quando o histórico muda) */
static void recs_rebuild(Session *s, Library *lib)
{
    if (s->recs_cap == 0) {
        s->recs_cap = RECS_MAX;
        s->recs = malloc((size_t)s->recs_cap * sizeof(*s->recs));
    }
    s->nrecs = 0;
    if (s->recs)
        rec_build_list(&s->rec, lib, s->recs, &s->nrecs, RECS_MAX);
    s->dirty_recs = false;
}

/* resolve uma lista de caminhos (playlist) em bubbles para o player */
static const Track *track_by_path(Library *lib, const char *path)
{
    for (int a = 0; a < lib->nalbums; a++) {
        Album *alb = &lib->albums[a];
        for (int t = 0; t < alb->ntracks; t++)
            if (strcmp(alb->tracks[t].path, path) == 0)
                return &alb->tracks[t];
    }
    return NULL;
}

static int playlist_to_tracks(Library *lib, const Playlist *pl,
                              const Track **out, int max)
{
    int n = 0;
    for (int i = 0; i < pl->n && n < max; i++) {
        const Track *t = track_by_path(lib, pl->files[i]);
        if (t) out[n++] = t;
    }
    return n;
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    sceCtrlSetSamplingMode(SCE_CTRL_MODE_DIGITAL);
    load_modules();

    if (vita2d_init() < 0) {
        sceAppMgrLoadExec("app0:eboot.bin", NULL, NULL);
        return 1;
    }

    Library lib;
    library_init(&lib, MUSIC_ROOT);
    library_scan(&lib);

    Session ses;
    memset(&ses, 0, sizeof(ses));
    playlist_load_dir(&ses.plists, &ses.nplists, PLAYLIST_DIR);
    rec_load(&ses.rec, REC_HISTORY_BASE);
    recs_rebuild(&ses, &lib);

    Ui *ui = ui_create();
    Player *player = player_create();
    if (!ui || !player) {
        if (ui) ui_destroy(ui);
        if (player) player_destroy(player);
        session_free(&ses);
        vita2d_fini();
        sceKernelExitProcess(1);
    }
    player_set_complete_cb(player, on_track_done, &ses);

    ui_set_data(ui, ses.plists, ses.nplists, ses.recs, ses.nrecs);

    int running = 1;
    while (running) {
        int act = ui_handle_input(ui);
        switch (act) {
        case -1:
            running = 0;
            break;
        case 2: {
            int idx = ui_selected(ui);
            if (idx >= 0 && idx < lib.nalbums)
                player_load_album(player, &lib, idx, 0);
            break;
        }
        case 4:
            player_toggle(player);
            break;
        case 5:
            player_next(player);
            break;
        case 6:
            player_prev(player);
            break;
        case 7:
            player_seek(player, player_track_seconds(player) - 10);
            break;
        case 11: /* tocar recomendações */
            if (ses.nrecs > 0)
                player_load_list(player, &lib, ses.recs, ses.nrecs, 0);
            break;
        case 12: { /* tocar playlist selecionada */
            int pi = ui_playlist_idx(ui);
            if (ses.plists && pi >= 0 && pi < ses.nplists && ses.plists[pi].n > 0) {
                const Track *tracks[1600];
                int n = playlist_to_tracks(&lib, &ses.plists[pi],
                                           tracks, 1600);
                if (n > 0)
                    player_load_list(player, &lib, tracks, n, 0);
            }
            break;
        }
        case 13: { /* criar playlist nova com o que está tocando */
            const Track *sess[1600];
            int n = player_session_tracks(player, sess, 1600);
            if (n > 0) {
                if (playlist_new(&ses.plists, &ses.nplists, PLAYLIST_NAME_PREFIX,
                                 sess, n) == 0) {
                    const Playlist *pl = &ses.plists[ses.nplists - 1];
                    playlist_save(pl, PLAYLIST_DIR);
                }
            }
            break;
        }
        case 14: { /* cicla repetição: ALL → ONE → OFF */
            RepeatMode r = player_repeat(player);
            r = (RepeatMode)(((int)r + 1) % 3);
            player_set_repeat(player, r);
            break;
        }
        case 15: /* alterna o sorteio */
            player_set_shuffle(player, !player_shuffle(player));
            break;
        case 16: /* avança +10s */
            player_seek(player, player_track_seconds(player) + 10);
            break;
        default:
            break;
        }
        /* se uma faixa terminou, a lista recomendada muda: inline no frame */
        if (ses.dirty_recs)
            recs_rebuild(&ses, &lib);
        ui_set_data(ui, ses.plists, ses.nplists, ses.recs, ses.nrecs);
        ui_frame(ui, &lib, player);
    }

    player_destroy(player);
    ui_destroy(ui);
    session_free(&ses);
    library_free(&lib);
    vita2d_fini();
    sceKernelExitProcess(0);
    return 0;
}
