#include "player.h"

#include <mpg123.h>
#include <SDL2/SDL.h>

#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>

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
    const Track **slots;        /* sessão: lista de faixas a tocar (não dono) */
    int nslots;
    int *order;                 /* ordem de execução: slots[order[i]]; sorteio p/ shuffle */
    int cur;                    /* índice atual em order[] (posição na sessão) */
    RepeatMode repeat;
    bool shuffle;

    PlayerCompleteFn complete_cb;
    void *complete_ud;

    PlayerState state;
    /* O relógio conta QUADROS DECODIFICADOS e desconta o que ainda está no
       anel, porque é isso que a pessoa ouve. A conta antiga era
       `done / (canais*2 * taxa)` em inteiros: 8192 / 176400 é ZERO, e a
       posição nunca saía de 00:00 — o tempo parado, a agulha na borda, a
       barra vazia e o ponto de continuação sempre no começo da faixa. */
    long long decoded_frames;
    long long track_frames;     /* duração em quadros, 0 se desconhecida */

    /* quantas faixas seguidas o decodificador recusou: sem isto, uma lista
       inteira de FLAC faz o worker girar para sempre procurando a próxima */
    int skips;
    char last_error[128];
};

static SDL_AudioDeviceID dev;
static Player *g_player;

/* quadros ainda no anel, isto é: decodificados e ainda não ouvidos */
static long long ring_backlog_frames(const Player *p)
{
    if (p->out_enc_need == 0) return 0;
    size_t filled = (p->ring_head - p->ring_tail) & RING_MASK;
    return (long long)(filled / p->out_enc_need);
}

static int position_sec(const Player *p)
{
    if (p->out_rate <= 0) return 0;
    long long f = p->decoded_frames - ring_backlog_frames(p);
    if (f < 0) f = 0;
    return (int)(f / p->out_rate);
}

/* ---------- ring ---------- */
static size_t ring_filled(const Player *p)
{
    return (p->ring_head - p->ring_tail) & RING_MASK;
}

/* faixa na posição i da sessão, respeitando a ordem (de perto do sorteio) */
static const Track *slot_at(const Player *p, int i)
{
    if (!p->slots || p->nslots <= 0) return NULL;
    if (p->shuffle && p->order) {
        if (i < 0 || i >= p->nslots) i = 0;
        i = p->order[i];
    }
    if (i < 0 || i >= p->nslots) return NULL;
    return p->slots[i];
}

/* baralha a ordem (Fisher–Yates) para o modo sorteio */
static void reshuffle(Player *p)
{
    if (!p->order || p->nslots <= 0) return;
    for (int i = p->nslots - 1; i > 0; i--) {
        int j = rand() % (i + 1);
        int t = p->order[i]; p->order[i] = p->order[j]; p->order[j] = t;
    }
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
    if (!t) return -1;
    /* Um .flac chega aqui: o scanner o mostra na estante de propósito, mas o
       decodificador é o mpg123. Recusar pelo nome antes de abrir poupa uma
       abertura de arquivo e dá um recado certo em vez de "erro". */
    if (!t->decodable) {
        snprintf(p->last_error, sizeof(p->last_error),
                 "%.72s: formato que este app não toca", t->title);
        return -1;
    }
    int e = 0;
    p->mh = mpg123_new(NULL, &e);
    if (!p->mh) return -1;
    if (mpg123_open(p->mh, t->path) != MPG123_OK) {
        snprintf(p->last_error, sizeof(p->last_error), "%.90s: não abriu", t->title);
        mpg123_close(p->mh);
        mpg123_delete(p->mh);
        p->mh = NULL;
        return -1;
    }
    int freq, chans, enc;
    long lfreq;
    if (mpg123_getformat(p->mh, &lfreq, &chans, &enc) != MPG123_OK) {
        snprintf(p->last_error, sizeof(p->last_error), "%.90s: formato ilegível", t->title);
        mpg123_close(p->mh);
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
        snprintf(p->last_error, sizeof(p->last_error), "o áudio não abriu");
        mpg123_close(p->mh);
        mpg123_delete(p->mh);
        p->mh = NULL;
        return -1;
    }
    /* faixa nova, anel vazio: sem isto o resto do PCM da anterior toca por
       cima do começo desta, e o relógio já conta a nova */
    p->ring_head = p->ring_tail = 0;
    p->decoded_frames = 0;
    {
        off_t len = mpg123_length(p->mh);
        p->track_frames = len > 0 ? (long long)len : 0;
    }
    p->last_error[0] = '\0';
    SDL_PauseAudioDevice(dev, 0);
    return 0;
}

static void close_stream(Player *p)
{
    if (p->mh) { mpg123_close(p->mh); mpg123_delete(p->mh); p->mh = NULL; }
    if (dev) { SDL_CloseAudioDevice(dev); dev = 0; }
    p->ring_head = p->ring_tail = 0;
}

/* Abre a faixa em p->cur; se ela não abrir, ANDA para a seguinte em vez de
   parar a sessão morta. Uma faixa corrompida no meio de um álbum, ou um
   disco em FLAC, encerravam tudo em silêncio — da poltrona, "o app parou".
   `dir` é +1 ou -1: pular para trás quando quem chamou foi o [esquerda]. */
static void load_next_ready_dir(Player *p, int dir)
{
    p->state = PLAYER_STOPPED;
    if (dev) SDL_PauseAudioDevice(dev, 1);
    if (p->nslots <= 0) return;

    /* no máximo uma volta: com a lista inteira ilegível isto TERMINA */
    for (int tries = 0; tries < p->nslots; tries++) {
        const Track *t = slot_at(p, p->cur);
        if (t && open_track(p, t) == 0) {
            p->state = PLAYER_PLAYING;
            p->first_push = true;
            p->skips = tries;
            return;
        }
        p->cur += dir;
        if (p->cur >= p->nslots) p->cur = 0;
        if (p->cur < 0) p->cur = p->nslots - 1;
    }
    /* nenhuma abriu: para, e o last_error já diz por quê */
    p->cur = 0;
    p->skips = p->nslots;
}

static void load_next_ready(Player *p) { load_next_ready_dir(p, 1); }

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
                if (p->out_enc_need)
                    p->decoded_frames += (long long)(done / p->out_enc_need);
            }
            if (rc == MPG123_DONE) {
                /* fim da faixa: registra e decide o que vem (repetição/sorteio) */
                PlayerCompleteFn cb = p->complete_cb;
                void *ud = p->complete_ud;
                pthread_mutex_lock(&p->mtx);
                const Track *done_t = slot_at(p, p->cur);
                int at_end = (p->cur + 1 >= p->nslots);
                if (p->repeat == REPEAT_ONE) {
                    /* repete a mesma faixa */
                } else if (at_end) {
                    if (p->repeat == REPEAT_ALL) {
                        if (p->shuffle) reshuffle(p);
                        p->cur = 0;
                    } else {
                        p->cur = 0; /* fim da sessão: para aqui */
                        p->state = PLAYER_STOPPED;
                        if (dev) SDL_PauseAudioDevice(dev, 1);
                        pthread_mutex_unlock(&p->mtx);
                        if (cb) cb(done_t, ud);
                        break;
                    }
                } else {
                    p->cur++;
                }
                load_next_ready(p);
                if (p->state == PLAYER_PLAYING)
                    pthread_cond_broadcast(&p->cond); /* self */
                pthread_mutex_unlock(&p->mtx);
                if (cb) cb(done_t, ud);
                break;
            }
            if (rc == MPG123_NEW_FORMAT) {
                mpg123_getformat(p->mh, &p->out_rate, &p->out_channels, NULL);
            }
        }
    }
    return NULL;
}

void player_set_complete_cb(Player *p, PlayerCompleteFn fn, void *ud)
{
    if (!p) return;
    pthread_mutex_lock(&p->mtx);
    p->complete_cb = fn;
    p->complete_ud = ud;
    pthread_mutex_unlock(&p->mtx);
}

Player *player_create(void)
{
    Player *p = calloc(1, sizeof(*p));
    if (!p) return NULL;
    pthread_mutex_init(&p->mtx, NULL);
    pthread_cond_init(&p->cond, NULL);
    p->thread_run = true;
    p->state = PLAYER_STOPPED;
    p->cur = -1;
    p->nslots = 0;
    p->repeat = REPEAT_ALL;
    srand((unsigned)time(NULL));
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
    free(p->slots);
    free(p->order);
    close_stream(p);
    pthread_mutex_destroy(&p->mtx);
    pthread_cond_destroy(&p->cond);
    SDL_QuitSubSystem(SDL_INIT_AUDIO);
    free(p);
    g_player = NULL;
}

/* monta a sessão a partir de um array (não copia os tracks; copia o array) */
static int set_session(Player *p, Library *lib, const Track *const *tracks, int n, int start)
{
    if (n <= 0) return -1;
    pthread_mutex_lock(&p->mtx);
    if (p->slots) free(p->slots);
    if (p->order) free(p->order);
    p->slots = malloc((size_t)(n > 0 ? n : 1) * sizeof(const Track *));
    p->order = malloc((size_t)(n > 0 ? n : 1) * sizeof(int));
    if (!p->slots || !p->order) {
        free(p->slots); free(p->order);
        p->slots = NULL; p->order = NULL;
        p->nslots = 0;
        pthread_mutex_unlock(&p->mtx);
        return -1;
    }
    for (int i = 0; i < n; i++) {
        p->slots[i] = tracks[i];
        p->order[i] = i;
    }
    p->nslots = n;
    p->lib = lib;
    if (p->shuffle) reshuffle(p);
    p->cur = (start >= 0 && start < n) ? start : 0;
    /* em shuffle, 'start' vira o primeiro da ordem sorteada só se ainda couber */
    if (p->shuffle && start >= 0 && start < n) {
        for (int i = 0; i < n; i++)
            if (p->order[i] == start) { p->cur = i; break; }
    }
    close_stream(p);
    load_next_ready(p);
    pthread_cond_broadcast(&p->cond);
    pthread_mutex_unlock(&p->mtx);
    return 0;
}

int player_load_album(Player *p, Library *lib, int album_idx, int start_track)
{
    if (!p || !lib || album_idx < 0 || album_idx >= lib->nalbums) return -1;
    Album *a = &lib->albums[album_idx];
    if (a->ntracks == 0) return -1;
    /* as durações vêm daqui; sem elas o disco não tem raio e a barra não anda */
    album_load_meta(a);
    if (start_track < 0 || start_track >= a->ntracks) start_track = 0;
    const Track *ts[256];
    int n = a->ntracks < 256 ? a->ntracks : 256;
    for (int i = 0; i < n; i++) ts[i] = &a->tracks[i];
    return set_session(p, lib, ts, n, start_track);
}

int player_load_list(Player *p, Library *lib, const Track *const *tracks, int n, int start)
{
    if (!p || !tracks || n <= 0) return -1;
    return set_session(p, lib, tracks, n, start);
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
    if (p->nslots > 0) {
        p->cur++;
        if (p->cur >= p->nslots) p->cur = 0;
        close_stream(p);
        load_next_ready(p);
        pthread_cond_broadcast(&p->cond);
    }
    pthread_mutex_unlock(&p->mtx);
}

void player_prev(Player *p)
{
    pthread_mutex_lock(&p->mtx);
    if (p->nslots > 0) {
        p->cur--;
        if (p->cur < 0) p->cur = p->nslots - 1;
        close_stream(p);
        /* para trás: se esta não abrir, a anterior — não a seguinte, senão
           [esquerda] num disco com uma faixa ilegível ANDA para a frente */
        load_next_ready_dir(p, -1);
        pthread_cond_broadcast(&p->cond);
    }
    pthread_mutex_unlock(&p->mtx);
}

void player_set_repeat(Player *p, RepeatMode m)
{
    if (!p) return;
    pthread_mutex_lock(&p->mtx);
    p->repeat = m;
    pthread_mutex_unlock(&p->mtx);
}

RepeatMode player_repeat(Player *p) { return p ? p->repeat : REPEAT_OFF; }

void player_set_shuffle(Player *p, bool on)
{
    if (!p) return;
    pthread_mutex_lock(&p->mtx);
    if (on && !p->shuffle && p->order) reshuffle(p);
    p->shuffle = on;
    pthread_mutex_unlock(&p->mtx);
}

bool player_shuffle(Player *p) { return p ? p->shuffle : false; }

int player_seek(Player *p, int seconds)
{
    if (!p) return -1;
    pthread_mutex_lock(&p->mtx);
    int r = -1;
    if (p->mh && p->out_rate > 0) {
        if (seconds < 0) seconds = 0;
        off_t target = (off_t)seconds * p->out_rate;
        off_t got = mpg123_seek(p->mh, target, SEEK_SET);
        /* usa o que a API realmente alcançou (clampa no fim da faixa) */
        if (got >= 0) {
            /* ESVAZIA o anel. Sem isto, o mpg123 pula mas até seis segundos
               de PCM velho continuam na fila e tocam depois do salto: o
               [cima] mexia no relógio e a música só obedecia meio minuto
               depois, que lê como "o seek não funciona". */
            p->ring_head = p->ring_tail = 0;
            p->decoded_frames = (long long)got;
            r = 0;
        }
    }
    pthread_mutex_unlock(&p->mtx);
    return r;
}

PlayerState player_state(Player *p) { return p ? p->state : PLAYER_STOPPED; }
int player_track_idx(Player *p) { return p ? p->cur : -1; }
const Album *player_current_album(const Player *p)
{
    const Track *t = slot_at(p, p ? p->cur : -1);
    return t ? t->owner : NULL;
}
int player_track_seconds(const Player *p)
{
    return p && p->mh ? position_sec(p) : 0;
}

/* Duração da faixa em segundos, ou -1 se o decodificador não soube dizer.
   -1 é "não sei" e a tela precisa poder distinguir isso de "dura zero": a
   AGORA dividia por uma duração 1 e desenhava o disco sempre no fim. */
int player_track_duration(const Player *p)
{
    if (!p || !p->mh || p->out_rate <= 0 || p->track_frames <= 0) return -1;
    return (int)(p->track_frames / p->out_rate);
}

/* A última coisa que deu errado, para a tela poder DIZER em vez de ficar
   quieta. Vazio quando não houve nada. */
const char *player_last_error(const Player *p)
{
    return p ? p->last_error : "";
}

/* Quantas faixas o decodificador teve de pular para chegar nesta. */
int player_skipped(const Player *p) { return p ? p->skips : 0; }
int player_track_count(const Player *p) { return p ? p->nslots : 0; }
const Track *player_current_track(const Player *p)
{
    return slot_at(p, p ? p->cur : -1);
}
int player_session_tracks(Player *p, const Track **out, int max)
{
    if (!p || !out || max <= 0) return 0;
    pthread_mutex_lock(&p->mtx);
    int n = p->nslots < max ? p->nslots : max;
    for (int i = 0; i < n; i++) out[i] = slot_at(p, i);
    pthread_mutex_unlock(&p->mtx);
    return n;
}
