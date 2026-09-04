/* Player de mentira para o preview. O player.c de verdade puxa SDL2, o
   decoder e uma thread, e o preview não quer tocar nada — quer um estado
   plausível para a UI desenhar. Cobre a player.h inteira; o que a UI lê é
   canned e o preview ajusta por preview_player_set(). */

#include "player.h"

#include <stdlib.h>
#include <string.h>
#include <math.h>

struct Player {
    const Album *album;
    const Track *track;
    PlayerState state;
    int position_sec, duration_sec;
    int track_idx, track_count;
    RepeatMode repeat;
    bool shuffle;
    long rate_file, rate_out;
    int bits_file;
    const char *kind;
    int sleep_mode;
    float fase;             /* anima o espectro entre um frame e outro */
};

Player *player_create(void)
{
    Player *p = calloc(1, sizeof(*p));
    if (p) { p->kind = "—"; p->rate_file = p->rate_out = 44100; p->bits_file = 16; }
    return p;
}
void player_destroy(Player *p) { free(p); }

/* --- o que o preview usa para montar a cena --- */
void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out)
{
    if (!p) return;
    p->album = a; p->track = t; p->state = st;
    p->position_sec = pos; p->duration_sec = dur;
    p->track_idx = idx; p->track_count = count;
    p->repeat = rep; p->shuffle = shuf;
    p->kind = kind ? kind : "—";
    p->rate_file = rate_file; p->bits_file = bits_file; p->rate_out = rate_out;
}

/* --- leitura --- */
PlayerState player_state(Player *p)                { return p ? p->state : PLAYER_STOPPED; }
int player_track_idx(Player *p)                    { return p ? p->track_idx : 0; }
const Album *player_current_album(const Player *p) { return p ? p->album : NULL; }
int player_track_seconds(const Player *p)          { return p ? p->position_sec : 0; }
int player_track_duration(const Player *p)         { return p ? p->duration_sec : -1; }
const char *player_last_error(const Player *p)     { (void)p; return ""; }
int player_skipped(const Player *p)                { (void)p; return 0; }
RepeatMode player_repeat(Player *p)                { return p ? p->repeat : REPEAT_OFF; }
bool player_shuffle(Player *p)                     { return p ? p->shuffle : false; }
const Track *player_current_track(const Player *p) { return p ? p->track : NULL; }
int player_track_count(const Player *p)            { return p ? p->track_count : 0; }
int player_sleep_mode(const Player *p)             { return p ? p->sleep_mode : 0; }

void player_signal(const Player *p, PlayerSignal *out)
{
    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!p || p->state == PLAYER_STOPPED) { out->kind = "—"; return; }
    out->kind = p->kind;
    out->rate_file = p->rate_file;
    out->bits_file = p->bits_file;
    out->rate_out = p->rate_out;
    out->bits_out = 16;
    out->channels = 2;
    out->resampled = (p->rate_out != p->rate_file);
    out->requantized = (p->bits_file > 16);
    out->bgm_port = (p->rate_out > 0 && p->rate_out <= 47999);
}

/* Espectro canned: uma curva com queda nos agudos, que é a forma de música
   de verdade. Não é medida — no preview não há som — e por isso o número
   nunca é usado para afirmar nada, só para a barra existir na imagem. */
void player_spectrum(Player *p, float *out, int nbands)
{
    if (!out || nbands <= 0) return;
    if (!p || p->state != PLAYER_PLAYING) {
        for (int i = 0; i < nbands; i++) out[i] = 0.0f;
        return;
    }
    p->fase += 0.21f;
    for (int i = 0; i < nbands; i++) {
        float t = (float)i / (float)(nbands > 1 ? nbands - 1 : 1);
        float queda = 1.0f - 0.72f * t;                   /* agudos mais baixos */
        float ondula = 0.72f + 0.28f * sinf(p->fase + t * 5.3f);
        float v = queda * ondula;
        out[i] = v < 0 ? 0 : (v > 1 ? 1 : v);
    }
}

/* --- comandos: no preview não fazem nada --- */
void player_set_complete_cb(Player *p, PlayerCompleteFn fn, void *ud) { (void)p; (void)fn; (void)ud; }
int  player_load_album(Player *p, Library *lib, int a, int s) { (void)p; (void)lib; (void)a; (void)s; return 0; }
int  player_load_list(Player *p, Library *lib, const Track *const *t, int n, int s)
{ (void)p; (void)lib; (void)t; (void)n; (void)s; return 0; }
void player_stop(Player *p)                     { (void)p; }
void player_play(Player *p)                     { (void)p; }
void player_pause(Player *p)                    { (void)p; }
void player_toggle(Player *p)                   { (void)p; }
void player_next(Player *p)                     { (void)p; }
void player_prev(Player *p)                     { (void)p; }
int  player_seek(Player *p, int s)              { (void)p; (void)s; return 0; }
void player_set_repeat(Player *p, RepeatMode m) { if (p) p->repeat = m; }
void player_set_shuffle(Player *p, bool on)     { if (p) p->shuffle = on; }
void player_set_sleep(Player *p, int mode, int last) { (void)last; if (p) p->sleep_mode = mode; }
int  player_session_tracks(Player *p, const Track **out, int max)
{ (void)p; (void)out; (void)max; return 0; }
