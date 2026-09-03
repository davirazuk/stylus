#include "player.h"

#include <mpg123.h>
#include <SDL2/SDL.h>

#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define RING_SIZE (1 << 20)   /* 1 MiB de PCM por canal intercalado */
#define RING_MASK (RING_SIZE - 1)

struct Player {
    pthread_t thread;
    bool thread_run;
    pthread_mutex_t mtx;
    pthread_cond_t cond;        /* avisa o worker de comandos */

    /* ring buffer PCM (int16 stereo intercalado) */
    unsigned char ring[RING_SIZE];
    volatile size_t ring_head;  /* escrita */
    volatile size_t ring_tail;  /* leitura (callback) */
    bool first_push;

    /* estado do stream */
    mpg123_handle *mh;
    long out_rate;
    int out_channels;
    size_t out_enc_need;        /* bytes por frame (channels*bytesPerSample) */

    Library *lib;
    int album_idx;
    int track_idx;

    PlayerState state;
    int position_sec;
};

static SDL_AudioDeviceID dev;
static Player *g_player;

/* ---------- ring ---------- */
static size_t ring_filled(const Player *p)
{
    return (p->ring_head - p->ring_tail) & RING_MASK;
}

static void sdl_cb(void *udata, Uint8 *stream, int len)
{
    Player *p = udata;
    size_t need = (size_t)len;
    if (p->state != PLAYER_PLAYING) {
        memset(stream, 0, (size_t)len);
        return;
    }
    size_t avail = ring_filled(p);
    size_t take = need < avail ? need : avail;
    size_t tail = p->ring_tail;
    if (take) {
        size_t first = RING_SIZE - tail;
        if (first > take) first = take;
        memcpy(stream, p->ring + tail, first);
        if (take > first)
            memcpy(stream + first, p->ring, take - first);
        p->ring_tail = (tail + take) & RING_MASK;
    }
    if (take < need)
        memset(stream + take, 0, (size_t)(need - take));
}

static int open_track(Player *p, const Track *t)
{
    if (p->mh) { mpg123_close(p->mh); mpg123_delete(p->mh); p->mh = NULL; }
    int e = 0;
    p->mh = mpg123_new(NULL, &e);
    if (!p->mh) return -1;
    if (mpg123_open(p->mh, t->path) != MPG123_OK) {
        mpg123_delete(p->mh);
        p->mh = NULL;
        return -1;
    }
    int freq, chans, enc;
    long lfreq;
    if (mpg123_getformat(p->mh, &lfreq, &chans, &enc) != MPG123_OK) {
        mpg123_delete(p->mh);
        p->mh = NULL;
        return -1;
    }
    freq = (int)lfreq;
    p->out_rate = lfreq;
    p->out_channels = chans;
    p->out_enc_need = (size_t)chans * 2; /* 16-bit */

    /* reconfigura o device SDL se o formato mudou */
    SDL_CloseAudioDevice(dev);
    SDL_AudioSpec want, have;
    SDL_zero(want);
    want.freq = freq;
    want.format = AUDIO_S16;
    want.channels = (Uint8)chans;
    want.samples = 1024;
    want.callback = sdl_cb;
    want.userdata = p;
    dev = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (dev == 0) {
        mpg123_delete(p->mh);
        p->mh = NULL;
        return -1;
    }
    SDL_PauseAudioDevice(dev, 0);
    return 0;
}

static void close_stream(Player *p)
{
    if (p->mh) { mpg123_close(p->mh); mpg123_delete(p->mh); p->mh = NULL; }
    if (dev) { SDL_CloseAudioDevice(dev); dev = 0; }
    p->ring_head = p->ring_tail = 0;
}

static void load_next_ready(Player *p)
{
    p->state = PLAYER_STOPPED;
    if (dev) SDL_PauseAudioDevice(dev, 1);
    /* decide próxima faixa */
    int idx = p->track_idx;
    if (p->lib && p->album_idx >= 0 && p->album_idx < p->lib->nalbums) {
        Album *a = &p->lib->albums[p->album_idx];
        if (a->ntracks > 0) {
            if (idx < 0) idx = 0;
            if (idx >= a->ntracks) idx = 0; /* loopa o álbum */
            p->track_idx = idx;
            if (open_track(p, &a->tracks[idx]) == 0) {
                p->state = PLAYER_PLAYING;
                p->position_sec = 0;
                p->first_push = true;
                return;
            }
        }
    }
}

static void *player_thread(void *arg)
{
    Player *p = arg;
    unsigned char buf[8192];
    while (p->thread_run) {
        pthread_mutex_lock(&p->mtx);
        /* espera um comando: abrir nova faixa em PLAYING */
        while (p->thread_run && p->state != PLAYER_PLAYING)
            pthread_cond_wait(&p->cond, &p->mtx);
        if (!p->thread_run) { pthread_mutex_unlock(&p->mtx); break; }

        if (!p->mh) {
            pthread_mutex_unlock(&p->mtx);
            continue;
        }
        pthread_mutex_unlock(&p->mtx);

        /* decodifica em pedaços, respeitando o espaço do ring */
        while (p->thread_run && p->state == PLAYER_PLAYING) {
            size_t avail = RING_SIZE - ring_filled(p);
            if (avail < sizeof(buf)) {
                SDL_Delay(1);
                continue;
            }
            size_t done = 0;
            int rc = mpg123_read(p->mh, buf, sizeof(buf), &done);
            if (done > 0) {
                size_t whead = p->ring_head, w = done;
                size_t first = RING_SIZE - whead;
                if (first > w) first = w;
                memcpy(p->ring + whead, buf, first);
                if (w > first) memcpy(p->ring, buf + first, w - first);
                p->ring_head = (whead + w) & RING_MASK;
                p->position_sec += (int)(done / (p->out_enc_need * p->out_rate));
            }
            if (rc == MPG123_DONE) {
                /* fim da faixa: avança */
                pthread_mutex_lock(&p->mtx);
                p->track_idx++;
                load_next_ready(p);
                if (p->state == PLAYER_PLAYING)
                    pthread_cond_broadcast(&p->cond); /* self */
                pthread_mutex_unlock(&p->mtx);
                break;
            }
            if (rc == MPG123_NEW_FORMAT) {
                mpg123_getformat(p->mh, &p->out_rate, &p->out_channels, NULL);
            }
        }
    }
    return NULL;
}

Player *player_create(void)
{
    Player *p = calloc(1, sizeof(*p));
    if (!p) return NULL;
    pthread_mutex_init(&p->mtx, NULL);
    pthread_cond_init(&p->cond, NULL);
    p->thread_run = true;
    p->state = PLAYER_STOPPED;
    p->album_idx = -1;
    p->track_idx = -1;
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) < 0) {
        free(p);
        return NULL;
    }
    g_player = p;
    pthread_create(&p->thread, NULL, player_thread, p);
    return p;
}

void player_destroy(Player *p)
{
    if (!p) return;
    pthread_mutex_lock(&p->mtx);
    p->thread_run = false;
    p->state = PLAYER_STOPPED;
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
    pthread_join(p->thread, NULL);
    close_stream(p);
    pthread_mutex_destroy(&p->mtx);
    pthread_cond_destroy(&p->cond);
    SDL_QuitSubSystem(SDL_INIT_AUDIO);
    free(p);
    g_player = NULL;
}

int player_load(Player *p, Library *lib, int album_idx, int start_track)
{
    if (!p || album_idx < 0 || album_idx >= lib->nalbums) return -1;
    Album *a = &lib->albums[album_idx];
    if (a->ntracks == 0) return -1;
    if (start_track < 0 || start_track >= a->ntracks) start_track = 0;

    pthread_mutex_lock(&p->mtx);
    p->lib = lib;
    p->album_idx = album_idx;
    p->track_idx = start_track;
    close_stream(p);
    load_next_ready(p);
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
    return 0;
}

void player_stop(Player *p)
{
    if (!p) return;
    pthread_mutex_lock(&p->mtx);
    p->state = PLAYER_STOPPED;
    close_stream(p);
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
}

void player_play(Player *p)
{
    pthread_mutex_lock(&p->mtx);
    if (!p->mh) { pthread_mutex_unlock(&p->mtx); return; }
    p->state = PLAYER_PLAYING;
    SDL_PauseAudioDevice(dev, 0);
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
}

void player_pause(Player *p)
{
    pthread_mutex_lock(&p->mtx);
    if (p->state == PLAYER_PLAYING) {
        p->state = PLAYER_PAUSED;
        SDL_PauseAudioDevice(dev, 1);
    }
    pthread_mutex_unlock(&p->mtx);
}

void player_toggle(Player *p)
{
    pthread_mutex_lock(&p->mtx);
    if (p->state == PLAYER_PLAYING) {
        p->state = PLAYER_PAUSED;
        SDL_PauseAudioDevice(dev, 1);
    } else if (p->mh) {
        p->state = PLAYER_PLAYING;
        SDL_PauseAudioDevice(dev, 0);
        pthread_cond_broadcast(&p->cond);
    }
    pthread_mutex_unlock(&p->mtx);
}

void player_next(Player *p)
{
    pthread_mutex_lock(&p->mtx);
    p->track_idx++;
    if (p->lib && p->album_idx >= 0 && p->album_idx < p->lib->nalbums) {
        Album *a = &p->lib->albums[p->album_idx];
        if (p->track_idx >= a->ntracks) p->track_idx = 0;
    }
    close_stream(p);
    load_next_ready(p);
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
}

void player_prev(Player *p)
{
    pthread_mutex_lock(&p->mtx);
    p->track_idx--;
    if (p->lib && p->album_idx >= 0 && p->album_idx < p->lib->nalbums) {
        Album *a = &p->lib->albums[p->album_idx];
        if (p->track_idx < 0) p->track_idx = a->ntracks - 1;
    }
    close_stream(p);
    load_next_ready(p);
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
}

int player_seek(Player *p, int seconds)
{
    pthread_mutex_lock(&p->mtx);
    int r = -1;
    if (p->mh) {
        off_t target = (off_t)seconds * p->out_rate;
        off_t got = mpg123_seek(p->mh, target, SEEK_SET);
        if (got >= 0) { p->position_sec = seconds; r = 0; }
    }
    pthread_mutex_unlock(&p->mtx);
    return r;
}

PlayerState player_state(Player *p) { return p ? p->state : PLAYER_STOPPED; }
int player_album_idx(Player *p) { return p ? p->album_idx : -1; }
int player_track_idx(Player *p) { return p ? p->track_idx : -1; }
int player_track_seconds(const Player *p)
{
    return p && p->mh ? p->position_sec : 0;
}
int player_track_count(const Player *p)
{
    if (!p || !p->lib || p->album_idx < 0) return 0;
    return p->lib->albums[p->album_idx].ntracks;
}
const Track *player_current_track(const Player *p)
{
    if (!p || !p->lib || p->album_idx < 0 || p->album_idx >= p->lib->nalbums) return NULL;
    Album *a = &p->lib->albums[p->album_idx];
    if (p->track_idx < 0 || p->track_idx >= a->ntracks) return NULL;
    return &a->tracks[p->track_idx];
}
