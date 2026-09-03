#ifndef STYLUS_PLAYER_H
#define STYLUS_PLAYER_H

#include <stdbool.h>
#include <stddef.h>

#include "library.h"

typedef enum {
    PLAYER_STOPPED = 0,
    PLAYER_PLAYING,
    PLAYER_PAUSED,
} PlayerState;

typedef struct Player Player;

Player *player_create(void);
void player_destroy(Player *p);

/* carrega uma lista de faixas (não copia; o chamador mantém vivas) e começa na 'start' */
int player_load(Player *p, Library *lib, int album_idx, int start_track);
void player_stop(Player *p);

void player_play(Player *p);
void player_pause(Player *p);
void player_toggle(Player *p);
void player_next(Player *p);   /* avança uma faixa dentro do álbum */
void player_prev(Player *p);
int  player_seek(Player *p, int seconds);

PlayerState player_state(Player *p);
int player_album_idx(Player *p);
int player_track_idx(Player *p);
int  player_track_seconds(const Player *p); /* posição atual segundos */
const Track *player_current_track(const Player *p);
int player_track_count(const Player *p);

#endif
