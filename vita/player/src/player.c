#include "player.h"

#include "decoder.h"
#include <SDL2/SDL.h>

#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include <math.h>

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
    Decoder *dec;
    DecFormat dfmt;
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
    int hw_rate, hw_channels;   /* o que o APARELHO aceitou, não o que se pediu */

    /* A SONECA. Um `pause` seco no meio da faixa é o contrário do que este
       sistema faz — ele é sobre discos, e um disco acaba no fim do LADO.
       Duas formas: esmaecer em vinte segundos, ou parar no fim do lado.
       O ganho digital desses vinte segundos é exceção consciente à tese do
       bit-perfect, e está escrita aqui ao lado por isso. */
    int sleep_mode;             /* 0 desligada, 1 esmaecendo, 2 no fim do lado */
    float sleep_gain;           /* 1.0 → 0.0 durante o esmaecer */
    int sleep_at_track;         /* fim do lado: última faixa a tocar, -1 n/d */
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

    /* O esmaecer da soneca, aplicado AQUI e em nenhum outro lugar: é o único
       ponto por onde todo o som passa. Em POTÊNCIA (o quadrado do ganho), que
       é como o ouvido ouve — linear, os últimos dez segundos somem de uma vez
       e os dez primeiros não mudam nada. */
    if (p->sleep_mode == 1) {
        short *s16 = (short *)stream;
        size_t n = need / 2;
        float g = p->sleep_gain;
        for (size_t i = 0; i < n; i++) {
            float gg = g * g;
            s16[i] = (short)((float)s16[i] * gg);
        }
        /* desce proporcional ao TEMPO deste buffer, não por chamada: o
           tamanho do buffer varia e um passo fixo daria fades diferentes */
        if (p->out_rate > 0 && p->out_enc_need > 0) {
            float secs = (float)(need / p->out_enc_need) / (float)p->out_rate;
            p->sleep_gain -= secs / 20.0f;
            if (p->sleep_gain <= 0.0f) {
                p->sleep_gain = 0.0f;
                p->state = PLAYER_PAUSED;
            }
        }
    }
}

static int open_track(Player *p, const Track *t)
{
    if (p->dec) { dec_close(p->dec); p->dec = NULL; }
    if (!t) return -1;
    /* A pergunta "eu sei tocar isto?" tem UM dono, o decoder.c. Perguntá-la
       aqui por extensão criaria a segunda metade que discorda da primeira. */
    if (dec_kind_of(t->path) == DEC_NONE) {
        snprintf(p->last_error, sizeof(p->last_error),
                 "%.72s: formato que este app não toca", t->title);
        return -1;
    }
    p->dec = dec_open(t->path);
    if (!p->dec) {
        snprintf(p->last_error, sizeof(p->last_error), "%.90s: não abriu", t->title);
        return -1;
    }
    dec_format(p->dec, &p->dfmt);
    if (p->dfmt.rate <= 0 || p->dfmt.channels <= 0) {
        snprintf(p->last_error, sizeof(p->last_error), "%.90s: formato ilegível", t->title);
        dec_close(p->dec);
        p->dec = NULL;
        return -1;
    }
    p->out_rate = p->dfmt.rate;
    p->out_channels = p->dfmt.channels;
    p->out_enc_need = (size_t)p->dfmt.channels * 2; /* int16 sempre */

    /* reconfigura o device SDL se o formato mudou */
    SDL_CloseAudioDevice(dev);
    SDL_AudioSpec want, have;
    SDL_zero(want);
    want.freq = (int)p->dfmt.rate;
    want.format = AUDIO_S16;
    want.channels = (Uint8)p->dfmt.channels;
    want.samples = 1024;
    want.callback = sdl_cb;
    want.userdata = p;
    dev = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (dev == 0) {
        snprintf(p->last_error, sizeof(p->last_error), "o áudio não abriu");
        dec_close(p->dec);
        p->dec = NULL;
        return -1;
    }
    /* O que o APARELHO recebeu, que não é sempre o que se pediu: o Vita sai
       em 16 bits e num punhado de taxas, e um FLAC de 96k/24 é reamostrado e
       reduzido antes de virar som. A tela diz isso — a tese do projeto é não
       mentir sobre o caminho do sinal. */
    p->hw_rate = have.freq;
    p->hw_channels = have.channels;

    /* faixa nova, anel vazio: sem isto o resto do PCM da anterior toca por
       cima do começo desta, e o relógio já conta a nova */
    p->ring_head = p->ring_tail = 0;
    p->decoded_frames = 0;
    {
        long long len = dec_length(p->dec);
        p->track_frames = len > 0 ? len : 0;
    }
    p->last_error[0] = '\0';
    SDL_PauseAudioDevice(dev, 0);
    return 0;
}

static void close_stream(Player *p)
{
    if (p->dec) { dec_close(p->dec); p->dec = NULL; }
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

        if (!p->dec) {
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
            long got = dec_read(p->dec, buf, sizeof(buf));
            size_t done = got > 0 ? (size_t)got : 0;
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
            if (got <= 0) {
                /* fim da faixa: registra e decide o que vem (repetição/sorteio) */
                PlayerCompleteFn cb = p->complete_cb;
                void *ud = p->complete_ud;
                pthread_mutex_lock(&p->mtx);
                const Track *done_t = slot_at(p, p->cur);
                int at_end = (p->cur + 1 >= p->nslots);
                /* soneca "fim do lado": esta era a última, e é aqui que ela
                   acaba — não num relógio que não sabe onde o lado termina */
                if (p->sleep_mode == 2 && p->sleep_at_track >= 0 &&
                    p->cur >= p->sleep_at_track)
                    at_end = 1, p->repeat = REPEAT_OFF;
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
    if (!p->dec) { pthread_mutex_unlock(&p->mtx); return; }
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
    } else if (p->dec) {
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

/* modo 0 desliga, 1 esmaece agora (20 s), 2 para no fim do lado */
void player_set_sleep(Player *p, int mode, int last_track)
{
    if (!p) return;
    pthread_mutex_lock(&p->mtx);
    p->sleep_mode = mode;
    p->sleep_gain = 1.0f;
    p->sleep_at_track = last_track;
    pthread_mutex_unlock(&p->mtx);
}

int player_sleep_mode(const Player *p) { return p ? p->sleep_mode : 0; }

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
    if (p->dec && p->out_rate > 0) {
        if (seconds < 0) seconds = 0;
        long long target = (long long)seconds * p->out_rate;
        long long got = dec_seek(p->dec, target);
        /* usa o que a API realmente alcançou (clampa no fim da faixa) */
        if (got >= 0) {
            /* ESVAZIA o anel. Sem isto, o decodificador pula mas até seis segundos
               de PCM velho continuam na fila e tocam depois do salto: o
               [cima] mexia no relógio e a música só obedecia meio minuto
               depois, que lê como "o seek não funciona". */
            p->ring_head = p->ring_tail = 0;
            p->decoded_frames = got;
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
    return p && p->dec ? position_sec(p) : 0;
}

/* Duração da faixa em segundos, ou -1 se o decodificador não soube dizer.
   -1 é "não sei" e a tela precisa poder distinguir isso de "dura zero": a
   AGORA dividia por uma duração 1 e desenhava o disco sempre no fim. */
int player_track_duration(const Player *p)
{
    if (!p || !p->dec || p->out_rate <= 0 || p->track_frames <= 0) return -1;
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

/* O CAMINHO DO SINAL, medido e não prometido: o formato do arquivo, a taxa e
   a profundidade dele, e o que o aparelho realmente recebeu. Sem tocador, um
   travessão — acusação tirada da ausência de dado é a doença que a tela SINAL
   do desktop pegou. */
/* O ESPECTRO, medido no PCM que está prestes a ser ouvido.
 *
 * Goertzel, não FFT: são dezesseis frequências fixas, e para dezesseis alvos
 * o Goertzel custa menos que montar uma FFT inteira e jogar fora 90% dela.
 * As bandas são espaçadas em LOG porque é assim que o ouvido divide o
 * espectro — dezesseis bandas lineares dariam quinze de agudo e uma de tudo
 * o que a pessoa reconhece como música.
 *
 * Lê do ring_tail, que é o que o callback vai entregar em seguida: ler do
 * head mostraria o que só vai soar daqui a seis segundos, e o anel adiantado
 * é justamente o que faz um "visualizador" não bater com o som. */
void player_spectrum(Player *p, float *out, int nbands)
{
    if (!out || nbands <= 0) return;
    for (int i = 0; i < nbands; i++) out[i] = 0.0f;
    if (!p || p->state != PLAYER_PLAYING || p->out_rate <= 0) return;

    size_t frame = p->out_enc_need ? p->out_enc_need : 4;
    size_t filled = (p->ring_head - p->ring_tail) & RING_MASK;
    size_t want = 1024 * frame;
    if (filled < want) return;

    /* mono: a soma dos canais. Um espectro por canal seria dois desenhos e a
       tela tem um disco só. */
    static float mono[1024];
    size_t t = p->ring_tail;
    int ch = p->out_channels > 0 ? p->out_channels : 2;
    for (int i = 0; i < 1024; i++) {
        long acc = 0;
        for (int c = 0; c < ch; c++) {
            size_t off = (t + (size_t)(i * ch + c) * 2) & RING_MASK;
            short v;
            memcpy(&v, p->ring + off, 2);
            acc += v;
        }
        /* Hann: sem janela, cada banda vaza nas vizinhas e o anel inteiro
           sobe e desce junto, que lê como pulsar e não como espectro. */
        float w = 0.5f * (1.0f - cosf(6.2831853f * (float)i / 1023.0f));
        mono[i] = (float)acc / (float)(ch * 32768) * w;
    }

    for (int b = 0; b < nbands; b++) {
        /* 40 Hz a 12 kHz, em log */
        float f = 40.0f * powf(12000.0f / 40.0f, (float)b / (float)(nbands - 1 > 0 ? nbands - 1 : 1));
        float k = f * 1024.0f / (float)p->out_rate;
        float w = 6.2831853f * k / 1024.0f;
        float coeff = 2.0f * cosf(w);
        float s0 = 0, s1 = 0, s2 = 0;
        for (int i = 0; i < 1024; i++) {
            s0 = mono[i] + coeff * s1 - s2;
            s2 = s1;
            s1 = s0;
        }
        float mag = sqrtf(s1 * s1 + s2 * s2 - coeff * s1 * s2) / 512.0f;
        /* em dB: linear, o grave come a tela inteira e o resto é uma linha */
        float db = 20.0f * log10f(mag + 1e-6f);
        float v = (db + 60.0f) / 60.0f;
        if (v < 0) v = 0;
        if (v > 1) v = 1;
        out[b] = v;
    }
}

void player_signal(const Player *p, PlayerSignal *out)
{
    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!p || !p->dec) { out->kind = "—"; return; }
    out->kind = dec_kind_name(dec_kind(p->dec));
    out->rate_file = p->dfmt.rate_native;
    out->bits_file = p->dfmt.bits_native;
    out->rate_out = p->hw_rate;
    out->channels = p->hw_channels;
    /* 16 bits não é escolha nossa: o sceAudioOut do Vita não tem outra. */
    out->bits_out = 16;
    out->resampled = (p->hw_rate > 0 && p->dfmt.rate_native > 0 &&
                      p->hw_rate != p->dfmt.rate_native);
    out->requantized = (p->dfmt.bits_native > 16);
}
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
