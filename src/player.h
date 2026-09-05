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

/* Resolve o id de uma faixa REMOTA numa URL tocável. Devolve 0 em sucesso e
   preenche `url` e `kind` (um DecKind). Injetado pelo main: o player não
   conhece o Qobuz, e este é o único fio entre os dois. */
typedef int (*PlayerResolve)(void *ud, const char *remote_id,
                             char *url, int cap, int *kind);
void player_set_resolver(PlayerResolve fn, void *ud);

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
int  player_track_duration(const Player *p); /* duração, -1 se desconhecida */
const char *player_last_error(const Player *p); /* "" quando não houve nada */
int  player_skipped(const Player *p);        /* faixas puladas por não abrir */

/* o caminho do sinal, MEDIDO */
typedef struct {
    const char *kind;    /* "FLAC", "MP3"… "—" quando não há nada tocando */
    long rate_file;      /* taxa do arquivo */
    int  bits_file;      /* profundidade do arquivo */
    long rate_out;       /* taxa que o aparelho aceitou */
    int  bits_out;       /* 16: o Vita não tem outra */
    int  channels;
    bool resampled;      /* a taxa mudou no caminho */
    bool requantized;    /* a profundidade desceu */
    bool bgm_port;       /* a taxa deixa o SDL2 abrir a porta BGM (2º plano) */

    /* O COLCHÃO, quando a faixa vem pela rede.

       Fica AQUI, e não num acessório à parte, porque é a mesma pergunta que o
       resto desta struct responde: o que o caminho do sinal está de fato
       fazendo. E porque um colchão que encolhe é a única coisa que explica um
       estalo ANTES de ele acontecer — sem isto a tela só teria como dizer que
       a rede caiu depois de já ter falhado. */
    bool remoto;         /* a faixa vem da rede, e não do cartão */
    long colchao;        /* bytes já esperando à frente; 0 quando local */
    long colchao_max;    /* o tamanho do anel, para desenhar a proporção */
} PlayerSignal;
void player_signal(const Player *p, PlayerSignal *out);

/* Espectro do que está prestes a soar, `nbands` valores em 0..1.
   Zerado quando não há som — o anel é a única fonte, e ausência de dado não
   pode virar afirmação de silêncio nem de nível. */
void player_spectrum(Player *p, float *out, int nbands);

/* A SONECA. 0 desliga, 1 esmaece em 20 s, 2 para quando a faixa
   `last_track` (a última do lado) terminar. */
void player_set_sleep(Player *p, int mode, int last_track);
int  player_sleep_mode(const Player *p);
const Track *player_current_track(const Player *p);
int player_track_count(const Player *p);
int player_session_tracks(Player *p, const Track **out, int max);

#endif
