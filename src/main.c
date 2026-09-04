#include <vita2d.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/ctrl.h>
#include <psp2/sysmodule.h>
#include <psp2/appmgr.h>
#include <psp2/power.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "library.h"
#include "paths.h"
#include "fsutil.h"
#include "player.h"
#include "ui.h"
#include "playlist.h"
#include "rec.h"
#include "scrobble.h"
#include "resume.h"
#include "decoder.h"
#include "lastfm.h"
#include "sides.h"

/* recomendações e playlists moram no cartão, junto do app — os caminhos são
   do paths.h, que é o único dono deles */
#define UX0_DATA_DIR        STYLUS_DATA_DIR
#define PLAYLIST_DIR        STYLUS_PLAYLISTS
#define REC_HISTORY_BASE    STYLUS_DATA_DIR

/* módulos de rede são pré-carregados para o futuro (Qobuz); inofensivo agora */
static void load_modules(void)
{
    sceSysmoduleLoadModule(SCE_SYSMODULE_NET);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTP);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTPS);
    sceSysmoduleLoadModule(SCE_SYSMODULE_SSL);
}

/* ÁUDIO EM SEGUNDO PLANO — as DUAS coisas que precisam valer.

   1. O app tem que PEDIR a porta BGM ao sistema. Com o plugin de CFW
      MusicPremium instalado, o Vita então não suspende este processo enquanto
      há som nela, e a música continua dentro de um jogo. Sem o plugin o
      pedido é inofensivo: a porta não vem e seguimos tocando normal.
   2. O SDL2 só ABRE a saída como BGM com taxa <= 47999 Hz (ver a nota grande
      no decoder.c). Sem o teto, um MP3 de 48 kHz cai na porta MAIN e perde o
      segundo plano em silêncio — numa varredura do cartão do usuário, 996 de
      3728 arquivos eram 48 kHz: 27% da coleção.

   Uma sem a outra não funciona, e é por isso que a tela mostra as duas. */
#define BGM_MAX_RATE  47999L
static bool bgm_port_ok;

/* O Vita dá ao homebrew um heap pequeno por padrão, e uma coleção grande não
   cabe: cada Track são ~1,5 KB e um cartão com 5000 faixas já pede 8 MB só de
   estrutura, mais as capas decodificadas. Sem isto o malloc começa a devolver
   NULL no meio da varredura e a estante fica pela metade, em silêncio. */
unsigned int sceLibcHeapSize = 128 * 1024 * 1024;
unsigned int _newlib_heap_size_user = 128 * 1024 * 1024;

/* Fila de faixas terminadas.
   O callback do player roda na THREAD DE ÁUDIO. Escrever o histórico dali
   mexia no mesmo `Rec` que o laço principal estava lendo para montar as
   recomendações — realloc de um lado, leitura do outro. Aqui o callback só
   ENFILEIRA (um produtor, um consumidor, sem trava) e quem escreve em disco é
   o laço principal, que é também quem lê. */
#define DONE_Q 16

/* estado persistente que sobrevive o loop e alimenta a UI a cada frame */
typedef struct {
    Playlist *plists;
    int nplists;
    Rec rec;
    const Track *done_q[DONE_Q];
    volatile int done_head;   /* escrito pela thread de áudio */
    volatile int done_tail;   /* lido pelo laço principal */
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

/* thread de áudio: só enfileira. Fila cheia perde a mais nova, que é melhor
   que sobrescrever uma que o laço ainda não leu. */
static void on_track_done(const Track *t, void *ud)
{
    Session *s = ud;
    if (!t || !s) return;
    int head = s->done_head;
    int next = (head + 1) % DONE_Q;
    if (next == s->done_tail) return;
    s->done_q[head] = t;
    s->done_head = next;
}

/* laço principal: escreve o histórico e o scrobble */
static void drain_done(Session *s)
{
    while (s->done_tail != s->done_head) {
        const Track *t = s->done_q[s->done_tail];
        s->done_tail = (s->done_tail + 1) % DONE_Q;
        if (!t) continue;
        rec_play(&s->rec, t->path, REC_HISTORY_BASE);
        long agora = (long)time(NULL);
        scrobble_log(REC_HISTORY_BASE, t, agora);
        /* Camada last.fm. A ordem importa: ENFILEIRA primeiro, sempre, e só
           depois tenta subir. A escuta fica no cartão antes de qualquer coisa
           poder dar errado — sem rede, sem conta, ou com a bateria acabando
           no meio do envio, ela continua lá e sai na próxima vez. */
        lastfm_enqueue(REC_HISTORY_BASE, t, agora,
                       t->seconds > 0 ? t->seconds : 0);
        lastfm_sync_async(REC_HISTORY_BASE);
        s->dirty_recs = true;
    }
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

/* retoma onde o app foi encerrado/suspenso, sempre em pausa */
static void try_resume(Library *lib, Player *player)
{
    Resume r;
    resume_load(UX0_DATA_DIR, &r);
    if (!r.valid) return;
    Album *alb = NULL;
    int ti = library_find_track_by_path(lib, &alb, r.track_path);
    if (ti < 0 || !alb) return;
    for (int i = 0; i < lib->nalbums; i++)
        if (&lib->albums[i] == alb) {
            player_set_repeat(player, (RepeatMode)r.repeat);
            player_set_shuffle(player, r.shuffle);
            player_load_album(player, lib, i, ti);
            if (r.position_sec > 0)
                player_seek(player, r.position_sec);
            player_pause(player);
            break;
        }
}

/* grava o ponto de continuação (chamado periodicamente e a cada faixa) */
static void write_resume(Player *player)
{
    const Track *t = player_current_track(player);
    if (!t || !t->path[0]) return;
    Resume r;
    memset(&r, 0, sizeof(r));
    snprintf(r.track_path, sizeof(r.track_path), "%s", t->path);
    r.position_sec = player_track_seconds(player);
    r.repeat = (int)player_repeat(player);
    r.shuffle = player_shuffle(player);
    if (r.track_path[0]) {
        r.valid = true;
        resume_save(UX0_DATA_DIR, &r);
    }
}

/* desenhada durante a varredura, a cada punhado de pastas */
static void scan_progress(void *ud, const char *where, int files)
{
    ui_draw_scanning((Ui *)ud, where, files);
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    sceCtrlSetSamplingMode(SCE_CTRL_MODE_DIGITAL);
    load_modules();
    dec_global_init();
    dec_set_max_rate(BGM_MAX_RATE);
    bgm_port_ok = (sceAppMgrAcquireBgmPort() >= 0);

    if (vita2d_init() < 0) {
        sceAppMgrLoadExec("app0:eboot.bin", NULL, NULL);
        return 1;
    }

    /* ANTES de qualquer escrita. O `mkdir` cru não cria pai, e ninguém criava
       este: o histórico, o scrobble e o ponto de continuação abriam o arquivo
       para escrita numa pasta inexistente, o fopen devolvia NULL, cada função
       voltava em silêncio e NADA do que a pessoa ouviu era guardado — entre
       sessões o app esquecia tudo, sem uma linha de erro em lugar nenhum. */
    mkdir_p(UX0_DATA_DIR);
    mkdir_p(PLAYLIST_DIR);

    Ui *boot = ui_create();

    Library lib;
    library_init(&lib);
    library_roots_from(&lib, UX0_DATA_DIR);
    /* varrer um cartão cheio leva segundos; sem esta tela é preto e parado,
       que da poltrona é indistinguível de travado */
    library_set_progress(&lib, scan_progress, boot);
    library_scan(&lib);
    /* Deixa o que a varredura viu escrito no cartão. Quem conserta o app
       quase nunca é quem está com o aparelho na mão, e a tela some quando se
       muda de tela — foi um arquivo assim que revelou o opendir devolvendo
       NULL. Custa uma escrita pequena por arranque. */
    library_report(&lib, STYLUS_DATA_DIR "/varredura.txt");

    Session ses;
    memset(&ses, 0, sizeof(ses));
    playlist_load_dir(&ses.plists, &ses.nplists, PLAYLIST_DIR);
    rec_load(&ses.rec, REC_HISTORY_BASE);

    /* A fila que sobrou de quando não havia rede sai agora, atrás do
       arranque. Não trava nada: volta na hora se estiver vazia. */
    lastfm_sync_async(REC_HISTORY_BASE);
    recs_rebuild(&ses, &lib);

    Ui *ui = boot;
    Player *player = player_create();
    if (!ui || !player) {
        if (ui) ui_destroy(ui);
        if (player) player_destroy(player);
        library_free(&lib);
        session_free(&ses);
        vita2d_fini();
        sceKernelExitProcess(1);
    }
    player_set_complete_cb(player, on_track_done, &ses);

    ui_set_data(ui, ses.plists, ses.nplists, ses.recs, ses.nrecs);
    ui_set_bgm(ui, bgm_port_ok);

    /* Abrir com música já tocando NÃO encena a cerimônia: o disco não foi
       posto agora, foi encontrado no meio. */
    try_resume(&lib, player);
    ui_skip_ritual(ui);

    int running = 1;
    int frame = 0;
    while (running) {
        int act = ui_handle_input(ui);
        switch (act) {
        case -1:
            running = 0;
            break;
        case 2: {
            int idx = ui_selected(ui);
            if (idx >= 0 && idx < lib.nalbums &&
                player_load_album(player, &lib, idx, 0) == 0)
                ui_begin_ritual(ui);   /* a pessoa PÔS um disco: encena */
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
        case 11: { /* tocar recomendações, a partir da que está MARCADA */
            int ri = ui_rec_idx(ui);
            if (ses.nrecs > 0) {
                if (ri < 0 || ri >= ses.nrecs) ri = 0;
                if (player_load_list(player, &lib, ses.recs, ses.nrecs, ri) == 0)
                    ui_begin_ritual(ui);
            }
            break;
        }
        case 12: { /* tocar playlist selecionada */
            int pi = ui_playlist_idx(ui);
            if (ses.plists && pi >= 0 && pi < ses.nplists && ses.plists[pi].n > 0) {
                const Track *tracks[1600];
                int n = playlist_to_tracks(&lib, &ses.plists[pi],
                                           tracks, 1600);
                if (n > 0 && player_load_list(player, &lib, tracks, n, 0) == 0)
                    ui_begin_ritual(ui);
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
        case 19: { /* a régua: pula para o primeiro disco daquela letra */
            int want = ui_jump_letter(ui);
            for (int i = 0; i < lib.nalbums; i++) {
                const char *nm = lib.albums[i].artist[0] ? lib.albums[i].artist
                                                         : lib.albums[i].album;
                char c0 = nm[0];
                if (c0 >= 'a' && c0 <= 'z') c0 -= 32;
                int letra = (c0 >= 'A' && c0 <= 'Z') ? c0 - 'A' : 26;
                if (letra == want) { ui_set_sel(ui, i); break; }
            }
            break;
        }
        case 21: {
            /* Revarrer, sem sair do app.

               Existe por causa do download do Qobuz: um disco que acabou de
               cair no cartão não aparecia na estante até a próxima abertura
               do app. "Baixei e não está lá" é indistinguível de "o download
               falhou", e as duas coisas pedem reações opostas.

               O que TOCA não é interrompido: o player segura ponteiros para
               dentro da biblioteca antiga, então a varredura só substitui a
               estante quando não há nada tocando. Com música no ar, a tela
               diz para voltar depois — mentir que revarreu seria pior. */
            if (player_state(player) != PLAYER_STOPPED) {
                break;
            }
            ui_set_data(ui, NULL, 0, NULL, 0);   /* solta as recomendações */
            library_free(&lib);
            library_init(&lib);
            library_roots_from(&lib, UX0_DATA_DIR);
            library_set_progress(&lib, scan_progress, ui);
            library_scan(&lib);
            library_report(&lib, STYLUS_DATA_DIR "/varredura.txt");
            recs_rebuild(&ses, &lib);
            ui_set_sel(ui, 0);
            break;
        }
        case 20: { /* a soneca: desligada → esmaece → fim do lado → desligada */
            int m2 = (player_sleep_mode(player) + 1) % 3;
            int last = -1;
            if (m2 == 2) {
                /* o fim do LADO, não um relógio: é o disco que decide */
                const Album *a = player_current_album(player);
                if (a && a->lados.n > 0) {
                    int l = sides_of_track(&a->lados, player_track_idx(player));
                    if (l >= 0) last = a->lados.sides[l].last;
                }
                if (last < 0) m2 = 0;   /* sem lados, não prometa o que não sabe */
            }
            player_set_sleep(player, m2, last);
            break;
        }
        case 18: { /* o dedo largou a barra: busca para onde ele apontou */
            float f = ui_scrub(ui);
            int dur = player_track_duration(player);
            if (f >= 0 && dur > 0) player_seek(player, (int)(f * (float)dur));
            break;
        }
        case 17: { /* apagar playlist (confirmado em 2 toques via R2) */
            int pi = ui_playlist_idx(ui);
            if (ses.plists && pi >= 0 && pi < ses.nplists)
                playlist_remove_file(ses.plists, &ses.nplists, pi, PLAYLIST_DIR);
            break;
        }
        default:
            break;
        }
        /* O Vita SUSPENDE sozinho depois de alguns minutos sem toque, e
           suspenso o áudio para: um álbum inteiro nunca chegava ao fim se a
           pessoa não encostasse no aparelho. Cancelar o timer de suspensão é
           uma linha, e nada no app a tinha.

           A tela, ao contrário, DEIXAMOS apagar: é um tocador de música, e o
           OLED aceso é o que come a bateria. Por isso só o timer de suspensão
           é cancelado, e não o da tela. */
        if (player_state(player) == PLAYER_PLAYING)
            sceKernelPowerTick(SCE_KERNEL_POWER_TICK_DISABLE_AUTO_SUSPEND);

        drain_done(&ses);
        /* No repouso a tela está apagada e ninguém está olhando: remontar a
           lista recomendada varre a coleção inteira, e fazer isso a cada
           faixa com a tela preta é gastar bateria para desenhar nada. Fica
           marcado como sujo e é refeito quando a pessoa voltar. */
        if (ses.dirty_recs && !ui_resting(ui))
            recs_rebuild(&ses, &lib);
        ui_set_data(ui, ses.plists, ses.nplists, ses.recs, ses.nrecs);
        ui_frame(ui, &lib, player);
        /* Persiste o ponto de continuação a cada ~2 s, e SÓ quando ele mudou:
           robusto se o app for suspenso sem saída limpa, sem escrever no
           cartão duas vezes por segundo a noite inteira. */
        if ((++frame & 127) == 0 && player_state(player) != PLAYER_STOPPED) {
            static int last_written = -1;
            int now_sec = player_track_seconds(player);
            if (now_sec != last_written) {
                write_resume(player);
                last_written = now_sec;
            }
        }
    }

    if (player_state(player) != PLAYER_STOPPED) write_resume(player);
    player_destroy(player);
    drain_done(&ses);
    ui_destroy(ui);
    session_free(&ses);
    library_free(&lib);
    /* devolve a porta BGM: presa, a próxima abertura leva
       SCE_APPMGR_ERROR_BGM_PORT_BUSY e o áudio de fundo some sem explicação */
    if (bgm_port_ok) sceAppMgrReleaseBgmPort();
    vita2d_fini();
    sceKernelExitProcess(0);
    return 0;
}
