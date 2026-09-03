#ifndef STYLUS_PLAYER_H
#define STYLUS_PLAYER_H

#include <stdbool.h>
#include <stddef.h>

#include "library.h"

typedef enum {
    PLAYER_STOPPED = 0,
    PLAYER_PLAYING,
    PLAYER_PAUSED
} PlayerState;

typedef enum {
    REPEAT_OFF = 0,
    REPEAT_ALL,
    REPEAT_ONE
} RepeatMode;

typedef struct Player Player;

/* chamado ao término (natural) de uma faixa, com o caminho; para histórico */
typedef void (*PlayerCompleteFn)(const Track *t, void *ud);
void player_set_complete_cb(Player *p, PlayerCompleteFn fn, void *ud);

Player *player_create(void);
void player_destroy(Player *p);

/* carrega uma lista de faixas (não copia tracks; o chamador mantém vivas)
   e começa na 'start'. player_load_list aceita qualquer lista (álbum/playlist/recomendada). */
int player_load_album(Player *p, Library *lib, int album_idx, int start_track);
int player_load_list(Player *p, Library *lib, const Track *const *tracks, int n, int start);
void player_stop(Player *p);

void player_play(Player *p);
void player_pause(Player *p);
void player_toggle(Player *p);
void player_next(Player *p);   /* avança uma faixa dentro do álbum */
void player_prev(Player *p);
int player_seek(Player *p, int seconds);

/* repetição e sorteio (modo do que toca na sessão atual) */
void player_set_repeat(Player *p, RepeatMode m);
RepeatMode player_repeat(Player *p);
void player_set_shuffle(Player *p, bool on);
bool player_shuffle(Player *p);

PlayerState player_state(Player *p);
int player_track_idx(Player *p);
const Album *player_current_album(const Player *p); /* owner do track atual (p/ deck) */
int  player_track_seconds(const Player *p); /* posição atual segundos */
const Track *player_current_track(const Player *p);
int player_track_count(const Player *p);
int player_session_tracks(Player *p, const Track **out, int max);

#endif
