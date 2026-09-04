#include "decoder.h"

#include <mpg123.h>
#include <FLAC/stream_decoder.h>
#include <FLAC/metadata.h>
#include <vorbis/vorbisfile.h>
#include <opus/opusfile.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

/* ---------------- extensão → formato ---------------- */

static bool ext_is(const char *path, const char *ext)
{
    size_t n = strlen(path), e = strlen(ext);
    if (n <= e) return false;
    return strcasecmp(path + (n - e), ext) == 0;
}

/* TETO DE TAXA DA SAÍDA — e por que ele existe.

   Quem escolhe o TIPO da porta de áudio do Vita não é este app: é o SDL2, e
   ele decide pela taxa de amostragem. Desmontando o SDL_vitaaudio.c.obj do
   vdpm (SDL 2.32.8):

       movw r0, #47999 ; ldr r2,[r4,#4] ; cmp r2,r0
       ite gt ; movgt r0,#0 (MAIN) ; movle r0,#1 (BGM)

   Acima de 47999 Hz ele abre SCE_AUDIO_OUT_PORT_TYPE_MAIN, e porta MAIN o
   plugin de CFW não mantém viva — a música morre ao sair do app. Só a porta
   BGM segura o som dentro de um jogo.

   Isto NÃO é sobre qualidade, é sobre qual porta abre. E como é uma
   propriedade do APARELHO e não do arquivo, mora aqui e vale para todos.

   Só o MP3 é reamostrado (o mpg123 faz por nós, com qualidade). FLAC, Vorbis
   e WAV acima do teto tocam na taxa nativa e PERDEM o áudio de fundo; Opus é
   sempre 48000 e nunca cabe. A tela diz isso em vez de fingir — a tese aqui é
   não mentir sobre o caminho do sinal. */
static long g_max_rate;   /* 0 = sem teto */

/* O teto é uma POLÍTICA (47999, o limiar do SDL2), não um alvo de
   reamostragem. Mirar no próprio teto foi um erro que custou uma medição:
   um MP3 de 48000 virava 47999 Hz — uma taxa que não existe em aparelho
   nenhum, e uma razão de reamostragem patológica (48000/47999) para ganhar
   1 Hz. O Vita trabalha nas taxas padrão; o alvo tem que ser a maior delas
   que caiba no teto. */
static const long TAXAS_PADRAO[] = {
    48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000
};

static long alvo_para(long teto)
{
    for (unsigned i = 0; i < sizeof(TAXAS_PADRAO) / sizeof(TAXAS_PADRAO[0]); i++)
        if (TAXAS_PADRAO[i] <= teto) return TAXAS_PADRAO[i];
    return teto;   /* teto absurdamente baixo: melhor algo que nada */
}

void dec_set_max_rate(long hz) { g_max_rate = hz > 0 ? hz : 0; }
long dec_max_rate(void)        { return g_max_rate; }

DecKind dec_kind_of(const char *path)
{
    if (!path) return DEC_NONE;
    if (ext_is(path, ".mp3") || ext_is(path, ".mp2") ||
        ext_is(path, ".mp1") || ext_is(path, ".mpga")) return DEC_MP3;
    if (ext_is(path, ".flac"))                          return DEC_FLAC;
    if (ext_is(path, ".ogg") || ext_is(path, ".oga"))   return DEC_VORBIS;
    if (ext_is(path, ".opus"))                          return DEC_OPUS;
    if (ext_is(path, ".wav") || ext_is(path, ".wave"))  return DEC_WAV;
    return DEC_NONE;
}

const char *dec_kind_name(DecKind k)
{
    switch (k) {
    case DEC_MP3:    return "MP3";
    case DEC_FLAC:   return "FLAC";
    case DEC_VORBIS: return "Vorbis";
    case DEC_OPUS:   return "Opus";
    case DEC_WAV:    return "WAV";
    default:         return "—";
    }
}

/* ---------------- o objeto ---------------- */

struct Decoder {
    DecKind kind;
    DecFormat fmt;
    long long pos;          /* quadros já entregues */
    long long len;          /* duração em quadros, -1 se desconhecida */

    mpg123_handle *mh;

    OggVorbis_File vf;
    int vf_open;

    OggOpusFile *of;

    FLAC__StreamDecoder *fd;
    unsigned char *fbuf;    /* PCM já convertido, esperando ser lido */
    size_t fbuf_cap, fbuf_len, fbuf_pos;
    int f_eof, f_err;

    FILE *wf;
    long wav_data;          /* offset do primeiro byte de PCM */
    int wav_bits, wav_float;
};

static int mpg_inited;

void dec_global_init(void)
{
    if (!mpg_inited) { mpg123_init(); mpg_inited = 1; }
}

void dec_global_exit(void)
{
    if (mpg_inited) { mpg123_exit(); mpg_inited = 0; }
}

/* ---------------- FLAC ---------------- */

/* O libFLAC entrega por callback e em int32 por canal, não intercalado nem em
   16 bits: converter aqui é o preço de o resto do programa não saber disso. */
static FLAC__StreamDecoderWriteStatus flac_write(
        const FLAC__StreamDecoder *dec, const FLAC__Frame *frame,
        const FLAC__int32 *const buffer[], void *client)
{
    (void)dec;
    Decoder *d = client;
    unsigned n = frame->header.blocksize;
    unsigned ch = frame->header.channels;
    unsigned bps = frame->header.bits_per_sample;
    if (ch > 2) ch = 2;                  /* o Vita sai em estéreo */

    size_t need = (size_t)n * ch * 2;
    if (d->fbuf_len - d->fbuf_pos + need > d->fbuf_cap) {
        /* compacta antes de crescer: sem isto o buffer só cresce */
        if (d->fbuf_pos) {
            memmove(d->fbuf, d->fbuf + d->fbuf_pos, d->fbuf_len - d->fbuf_pos);
            d->fbuf_len -= d->fbuf_pos;
            d->fbuf_pos = 0;
        }
        while (d->fbuf_len + need > d->fbuf_cap) {
            size_t nc = d->fbuf_cap ? d->fbuf_cap * 2 : 65536;
            unsigned char *nb = realloc(d->fbuf, nc);
            if (!nb) { d->f_err = 1; return FLAC__STREAM_DECODER_WRITE_STATUS_ABORT; }
            d->fbuf = nb;
            d->fbuf_cap = nc;
        }
    }

    /* 24 e 32 bits DESCEM para 16. Não é escolha: o sceAudioOut do Vita aceita
       16 bits com sinal e nada mais. A tela diz a profundidade original. */
    int shift = (int)bps - 16;
    short *out = (short *)(d->fbuf + d->fbuf_len);
    for (unsigned i = 0; i < n; i++) {
        for (unsigned c = 0; c < ch; c++) {
            FLAC__int32 v = buffer[c][i];
            if (shift > 0) v >>= shift;
            else if (shift < 0) v <<= -shift;
            if (v > 32767) v = 32767;
            if (v < -32768) v = -32768;
            *out++ = (short)v;
        }
    }
    d->fbuf_len += need;
    return FLAC__STREAM_DECODER_WRITE_STATUS_CONTINUE;
}

static void flac_meta(const FLAC__StreamDecoder *dec,
                      const FLAC__StreamMetadata *m, void *client)
{
    (void)dec;
    Decoder *d = client;
    if (m->type != FLAC__METADATA_TYPE_STREAMINFO) return;
    d->fmt.rate = (long)m->data.stream_info.sample_rate;
    d->fmt.rate_native = d->fmt.rate;
    d->fmt.channels = (int)m->data.stream_info.channels;
    if (d->fmt.channels > 2) d->fmt.channels = 2;
    d->fmt.bits_native = (int)m->data.stream_info.bits_per_sample;
    d->len = (long long)m->data.stream_info.total_samples;
    if (d->len == 0) d->len = -1;
}

static void flac_err(const FLAC__StreamDecoder *dec,
                     FLAC__StreamDecoderErrorStatus status, void *client)
{
    (void)dec; (void)status;
    /* Um erro de sincronia no meio de um arquivo NÃO é o fim dele: o libFLAC
       segue no quadro seguinte. Tratar isto como fatal cortava a faixa. */
    (void)client;
}

/* ---------------- WAV ---------------- */

static unsigned rd32(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8) |
           ((unsigned)p[2] << 16) | ((unsigned)p[3] << 24);
}
static unsigned rd16(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8);
}

static int wav_open(Decoder *d, const char *path)
{
    d->wf = fopen(path, "rb");
    if (!d->wf) return -1;
    unsigned char h[12];
    if (fread(h, 1, 12, d->wf) != 12 ||
        memcmp(h, "RIFF", 4) || memcmp(h + 8, "WAVE", 4)) return -1;

    int have_fmt = 0;
    for (;;) {
        unsigned char ck[8];
        if (fread(ck, 1, 8, d->wf) != 8) break;
        unsigned size = rd32(ck + 4);
        if (!memcmp(ck, "fmt ", 4)) {
            unsigned char f[40];
            unsigned want = size < sizeof(f) ? size : sizeof(f);
            if (fread(f, 1, want, d->wf) != want) return -1;
            unsigned tag = rd16(f);
            d->fmt.channels = (int)rd16(f + 2);
            d->fmt.rate = (long)rd32(f + 4);
            d->wav_bits = (int)rd16(f + 14);
            /* 0xFFFE é WAVE_FORMAT_EXTENSIBLE: o formato real está no GUID,
               e o primeiro short dele é a mesma tag de sempre. */
            if (tag == 0xFFFE && want >= 26) tag = rd16(f + 24);
            d->wav_float = (tag == 3);
            if (tag != 1 && tag != 3) return -1;   /* nada de ADPCM/lei-mu */
            if (d->fmt.channels < 1 || d->fmt.channels > 2) {
                if (d->fmt.channels < 1) return -1;
                d->fmt.channels = 2;
            }
            if (size > want) fseek(d->wf, (long)(size - want), SEEK_CUR);
            have_fmt = 1;
        } else if (!memcmp(ck, "data", 4)) {
            if (!have_fmt) return -1;
            d->wav_data = ftell(d->wf);
            int bytes_per = d->wav_bits / 8 * d->fmt.channels;
            d->len = bytes_per > 0 ? (long long)size / bytes_per : -1;
            d->fmt.bits_native = d->wav_bits;
            d->fmt.rate_native = d->fmt.rate;
            return 0;
        } else {
            /* pedaço ímpar leva um byte de enchimento — pular sem ele
               desalinha tudo que vem depois */
            fseek(d->wf, (long)(size + (size & 1)), SEEK_CUR);
        }
    }
    return -1;
}

static long wav_read(Decoder *d, void *buf, size_t bytes)
{
    int ch = d->fmt.channels;
    int bps = d->wav_bits / 8;
    size_t want_frames = bytes / (size_t)(ch * 2);
    if (!want_frames) return 0;

    unsigned char raw[8192];
    size_t max_frames = sizeof(raw) / (size_t)(ch * bps);
    if (want_frames > max_frames) want_frames = max_frames;

    size_t got = fread(raw, (size_t)(ch * bps), want_frames, d->wf);
    if (got == 0) return 0;

    short *out = buf;
    for (size_t i = 0; i < got * (size_t)ch; i++) {
        const unsigned char *p = raw + i * (size_t)bps;
        int v = 0;
        if (d->wav_float && bps == 4) {
            float f;
            memcpy(&f, p, 4);
            v = (int)(f * 32767.0f);
        } else if (bps == 1) {
            v = ((int)p[0] - 128) << 8;          /* 8 bits em WAV é SEM sinal */
        } else if (bps == 2) {
            v = (short)(p[0] | (p[1] << 8));
        } else if (bps == 3) {
            int s = (int)(p[0] | (p[1] << 8) | (p[2] << 16));
            if (s & 0x800000) s -= 0x1000000;
            v = s >> 8;
        } else if (bps == 4) {
            int s = (int)rd32(p);
            v = s >> 16;
        }
        if (v > 32767) v = 32767;
        if (v < -32768) v = -32768;
        out[i] = (short)v;
    }
    d->pos += (long long)got;
    return (long)(got * (size_t)ch * 2);
}

/* ---------------- abrir ---------------- */

Decoder *dec_open(const char *path)
{
    DecKind k = dec_kind_of(path);
    if (k == DEC_NONE) return NULL;
    Decoder *d = calloc(1, sizeof(*d));
    if (!d) return NULL;
    d->kind = k;
    d->len = -1;
    d->fmt.channels = 2;
    d->fmt.rate = 44100;

    if (k == DEC_MP3) {
        dec_global_init();
        int e = 0;
        d->mh = mpg123_new(NULL, &e);
        if (!d->mh) goto fail;
        mpg123_param(d->mh, MPG123_ADD_FLAGS, MPG123_QUIET, 0.0);
        if (mpg123_open(d->mh, path) != MPG123_OK) goto fail;
        long rate = 0; int ch = 0, enc = 0;
        if (mpg123_getformat(d->mh, &rate, &ch, &enc) != MPG123_OK || rate <= 0) goto fail;
        /* trava o formato: sem isto uma faixa VBR com mudança de layout
           reabre o device no meio e o áudio some */
        long saida = rate;
        /* acima do teto, pede a reamostragem ao mpg123 e reabre: é preciso
           reabrir porque o FORCE_RATE só vale a partir da próxima abertura */
        if (g_max_rate > 0 && rate > g_max_rate) {
            long alvo = alvo_para(g_max_rate);
            mpg123_close(d->mh);
            if (mpg123_param(d->mh, MPG123_FORCE_RATE, alvo, 0.0) == MPG123_OK &&
                mpg123_open(d->mh, path) == MPG123_OK &&
                mpg123_getformat(d->mh, &saida, &ch, &enc) == MPG123_OK &&
                saida > 0) {
                /* reamostrado: `rate` continua sendo a do ARQUIVO */
            } else {
                /* não deu: melhor tocar sem BGM do que não tocar. Desfaz o
                   FORCE_RATE, senão a "volta ao normal" continuaria forçando
                   e o comentário acima seria mentira. */
                mpg123_close(d->mh);
                mpg123_param(d->mh, MPG123_FORCE_RATE, 0, 0.0);
                if (mpg123_open(d->mh, path) != MPG123_OK) goto fail;
                if (mpg123_getformat(d->mh, &saida, &ch, &enc) != MPG123_OK) goto fail;
            }
        }
        mpg123_format_none(d->mh);
        mpg123_format(d->mh, saida, ch, MPG123_ENC_SIGNED_16);
        d->fmt.rate = saida;
        d->fmt.rate_native = rate;
        d->fmt.channels = ch > 2 ? 2 : ch;
        d->fmt.bits_native = 16;
        {
            off_t l = mpg123_length(d->mh);
            d->len = l > 0 ? (long long)l : -1;
        }
        return d;
    }

    if (k == DEC_FLAC) {
        d->fd = FLAC__stream_decoder_new();
        if (!d->fd) goto fail;
        FLAC__stream_decoder_set_md5_checking(d->fd, false);
        if (FLAC__stream_decoder_init_file(d->fd, path, flac_write, flac_meta,
                                           flac_err, d) != FLAC__STREAM_DECODER_INIT_STATUS_OK)
            goto fail;
        /* o STREAMINFO vem antes do primeiro áudio: sem isto a taxa e a
           duração ainda não existem quando o player pergunta */
        if (!FLAC__stream_decoder_process_until_end_of_metadata(d->fd)) goto fail;
        if (d->fmt.rate <= 0) goto fail;
        return d;
    }

    if (k == DEC_VORBIS) {
        FILE *f = fopen(path, "rb");
        if (!f) goto fail;
        if (ov_open_callbacks(f, &d->vf, NULL, 0, OV_CALLBACKS_DEFAULT) < 0) {
            fclose(f);
            goto fail;
        }
        d->vf_open = 1;
        vorbis_info *vi = ov_info(&d->vf, -1);
        if (!vi) goto fail;
        d->fmt.rate = d->fmt.rate_native = vi->rate;
        d->fmt.channels = vi->channels > 2 ? 2 : vi->channels;
        d->fmt.bits_native = 16;   /* Vorbis é com perdas: não tem "bits" */
        {
            ogg_int64_t l = ov_pcm_total(&d->vf, -1);
            d->len = l > 0 ? (long long)l : -1;
        }
        return d;
    }

    if (k == DEC_OPUS) {
        int e = 0;
        d->of = op_open_file(path, &e);
        if (!d->of) goto fail;
        /* Opus é SEMPRE 48 kHz por definição do formato — não há taxa nativa
           diferente para reamostrar, e dizer "reamostrado" seria mentira. */
        d->fmt.rate = d->fmt.rate_native = 48000;
        d->fmt.channels = op_channel_count(d->of, -1) > 2 ? 2 : op_channel_count(d->of, -1);
        if (d->fmt.channels < 1) d->fmt.channels = 2;
        d->fmt.bits_native = 16;
        {
            ogg_int64_t l = op_pcm_total(d->of, -1);
            d->len = l > 0 ? (long long)l : -1;
        }
        return d;
    }

    if (k == DEC_WAV) {
        if (wav_open(d, path) != 0) goto fail;
        return d;
    }

fail:
    dec_close(d);
    return NULL;
}

void dec_close(Decoder *d)
{
    if (!d) return;
    if (d->mh) { mpg123_close(d->mh); mpg123_delete(d->mh); }
    if (d->fd) {
        FLAC__stream_decoder_finish(d->fd);
        FLAC__stream_decoder_delete(d->fd);
    }
    if (d->vf_open) ov_clear(&d->vf);   /* fecha o FILE também */
    if (d->of) op_free(d->of);
    if (d->wf) fclose(d->wf);
    free(d->fbuf);
    free(d);
}

void dec_format(const Decoder *d, DecFormat *f)
{
    if (!f) return;
    if (!d) { memset(f, 0, sizeof(*f)); return; }
    *f = d->fmt;
}

DecKind dec_kind(const Decoder *d) { return d ? d->kind : DEC_NONE; }
long long dec_tell(const Decoder *d) { return d ? d->pos : 0; }
long long dec_length(const Decoder *d) { return d ? d->len : -1; }

/* ---------------- ler ---------------- */

long dec_read(Decoder *d, void *buf, size_t bytes)
{
    if (!d || !buf || bytes < 4) return -1;
    size_t frame_bytes = (size_t)d->fmt.channels * 2;
    bytes -= bytes % frame_bytes;          /* nunca devolve meio quadro */
    if (!bytes) return 0;

    switch (d->kind) {
    case DEC_MP3: {
        size_t done = 0;
        int rc = mpg123_read(d->mh, buf, bytes, &done);
        if (done) d->pos += (long long)(done / frame_bytes);
        if (done) return (long)done;
        if (rc == MPG123_DONE) return 0;
        return rc == MPG123_OK ? 0 : -1;
    }
    case DEC_FLAC: {
        while (d->fbuf_len - d->fbuf_pos == 0) {
            if (d->f_err) return -1;
            FLAC__StreamDecoderState st = FLAC__stream_decoder_get_state(d->fd);
            if (st == FLAC__STREAM_DECODER_END_OF_STREAM) return 0;
            if (st == FLAC__STREAM_DECODER_ABORTED ||
                st == FLAC__STREAM_DECODER_MEMORY_ALLOCATION_ERROR) return -1;
            if (!FLAC__stream_decoder_process_single(d->fd)) return -1;
            if (FLAC__stream_decoder_get_state(d->fd) ==
                FLAC__STREAM_DECODER_END_OF_STREAM &&
                d->fbuf_len - d->fbuf_pos == 0) return 0;
        }
        size_t have = d->fbuf_len - d->fbuf_pos;
        size_t take = have < bytes ? have : bytes;
        take -= take % frame_bytes;
        if (!take) return 0;
        memcpy(buf, d->fbuf + d->fbuf_pos, take);
        d->fbuf_pos += take;
        if (d->fbuf_pos >= d->fbuf_len) d->fbuf_pos = d->fbuf_len = 0;
        d->pos += (long long)(take / frame_bytes);
        return (long)take;
    }
    case DEC_VORBIS: {
        int bs = 0;
        /* o ov_read devolve UM pacote por vez e pode devolver menos que o
           pedido sem que isso seja fim de faixa */
        long r = ov_read(&d->vf, buf, (int)bytes, 0, 2, 1, &bs);
        if (r == OV_HOLE) return dec_read(d, buf, bytes);   /* buraco: segue */
        if (r <= 0) return r == 0 ? 0 : -1;
        d->pos += (long long)((size_t)r / frame_bytes);
        return r;
    }
    case DEC_OPUS: {
        int n = op_read(d->of, buf, (int)(bytes / 2), NULL);
        if (n == OP_HOLE) return dec_read(d, buf, bytes);
        if (n < 0) return -1;
        if (n == 0) return 0;
        d->pos += n;
        return (long)((size_t)n * frame_bytes);
    }
    case DEC_WAV:
        return wav_read(d, buf, bytes);
    default:
        return -1;
    }
}

long long dec_seek(Decoder *d, long long frame)
{
    if (!d) return -1;
    if (frame < 0) frame = 0;
    if (d->len > 0 && frame >= d->len) frame = d->len - 1;

    switch (d->kind) {
    case DEC_MP3: {
        off_t got = mpg123_seek(d->mh, (off_t)frame, SEEK_SET);
        if (got < 0) return -1;
        d->pos = (long long)got;
        return d->pos;
    }
    case DEC_FLAC:
        /* o buffer guarda PCM da posição VELHA: procurar sem esvaziá-lo faz o
           som de antes do salto tocar depois dele */
        d->fbuf_len = d->fbuf_pos = 0;
        if (!FLAC__stream_decoder_seek_absolute(d->fd, (FLAC__uint64)frame)) {
            /* um seek falho deixa o decodificador em SEEK_ERROR e ele não
               volta a ler nada até ser reiniciado */
            FLAC__stream_decoder_flush(d->fd);
            return -1;
        }
        d->pos = frame;
        return frame;
    case DEC_VORBIS:
        if (ov_pcm_seek(&d->vf, (ogg_int64_t)frame) != 0) return -1;
        d->pos = frame;
        return frame;
    case DEC_OPUS:
        if (op_pcm_seek(d->of, (ogg_int64_t)frame) != 0) return -1;
        d->pos = frame;
        return frame;
    case DEC_WAV: {
        long off = d->wav_data + (long)(frame * (d->wav_bits / 8) * d->fmt.channels);
        if (fseek(d->wf, off, SEEK_SET) != 0) return -1;
        d->pos = frame;
        return frame;
    }
    default:
        return -1;
    }
}

/* ---------------- tags e capa ---------------- */

static void set_str(char *dst, size_t cap, const char *src, size_t n)
{
    if (!dst || !cap) return;
    if (!src) { dst[0] = '\0'; return; }
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

/* "TRACKNUMBER=3/12" → 3. Para no primeiro não-dígito depois do primeiro
   dígito: a barra do "3/12" é a forma mais comum e vira faixa 312 sem isto. */
static int parse_num(const char *s, size_t n)
{
    int v = 0, any = 0;
    for (size_t i = 0; i < n && s[i]; i++) {
        if (s[i] >= '0' && s[i] <= '9') { v = v * 10 + (s[i] - '0'); any = 1; }
        else if (any) break;
    }
    return any ? v : -1;
}

/* Um comentário Vorbis é "CHAVE=valor". A mesma estrutura serve FLAC, Vorbis
   e Opus — três formatos, um leitor. */
static void take_vorbis_comment(DecTags *t, const char *c, size_t len)
{
    const char *eq = memchr(c, '=', len);
    if (!eq) return;
    size_t klen = (size_t)(eq - c);
    const char *v = eq + 1;
    size_t vlen = len - klen - 1;
    if (klen == 5 && !strncasecmp(c, "TITLE", 5) && !t->title[0])
        set_str(t->title, sizeof(t->title), v, vlen);
    else if (klen == 6 && !strncasecmp(c, "ARTIST", 6) && !t->artist[0])
        set_str(t->artist, sizeof(t->artist), v, vlen);
    else if (klen == 5 && !strncasecmp(c, "ALBUM", 5) && !t->album[0])
        set_str(t->album, sizeof(t->album), v, vlen);
    else if (klen == 11 && !strncasecmp(c, "TRACKNUMBER", 11) && t->number < 0)
        t->number = parse_num(v, vlen);
    /* ALBUMARTIST ganha do ARTIST quando existe: numa coletânea, agrupar pelo
       artista da FAIXA espalha o disco em doze artistas de uma faixa cada. */
    else if (klen == 11 && !strncasecmp(c, "ALBUMARTIST", 11))
        set_str(t->artist, sizeof(t->artist), v, vlen);
    else if (klen == 12 && !strncasecmp(c, "ALBUM ARTIST", 12))
        set_str(t->artist, sizeof(t->artist), v, vlen);
}

/* A capa em Vorbis e Opus é um bloco PICTURE do FLAC em base64, dentro do
   comentário METADATA_BLOCK_PICTURE. O opusfile já sabe desfazer isso, e
   serve para os dois — o formato é o mesmo. */
static void take_picture_comment(DecTags *t, const char *c, size_t len)
{
    if (t->cover) return;
    static const char KEY[] = "METADATA_BLOCK_PICTURE=";
    size_t klen = sizeof(KEY) - 1;
    if (len <= klen || strncasecmp(c, KEY, klen) != 0) return;

    char *z = malloc(len + 1);
    if (!z) return;
    memcpy(z, c, len);
    z[len] = '\0';

    OpusPictureTag pic;
    opus_picture_tag_init(&pic);
    if (opus_picture_tag_parse(&pic, z) == 0 &&
        pic.data && pic.data_length > 0 &&
        (pic.type == 3 || pic.type == 0)) {   /* 3 = front cover */
        t->cover = malloc((size_t)pic.data_length);
        if (t->cover) {
            memcpy(t->cover, pic.data, (size_t)pic.data_length);
            t->cover_len = (size_t)pic.data_length;
        }
    }
    opus_picture_tag_clear(&pic);
    free(z);
}

static int probe_mp3(const char *path, DecTags *t, int want_cover)
{
    dec_global_init();
    int e = 0;
    mpg123_handle *mh = mpg123_new(NULL, &e);
    if (!mh) return -1;
    mpg123_param(mh, MPG123_ADD_FLAGS, MPG123_QUIET, 0.0);
    if (want_cover) mpg123_param(mh, MPG123_ADD_FLAGS, MPG123_PICTURE, 0.0);
    if (mpg123_open(mh, path) != MPG123_OK) { mpg123_delete(mh); return -1; }

    /* o scan de ID3 acontece na abertura; o mpg123_scan fecha a duração de um
       VBR sem Xing, que senão sai errada por minutos */
    long rate = 0; int ch = 0, enc = 0;
    if (mpg123_getformat(mh, &rate, &ch, &enc) == MPG123_OK && rate > 0) {
        off_t len = mpg123_length(mh);
        if (len > 0) t->seconds = (int)(len / rate);
    }

    mpg123_id3v1 *v1 = NULL;
    mpg123_id3v2 *v2 = NULL;
    if (mpg123_id3(mh, &v1, &v2) == MPG123_OK) {
        if (v2) {
            if (v2->title  && v2->title->p)  set_str(t->title,  sizeof(t->title),  v2->title->p,  strlen(v2->title->p));
            if (v2->artist && v2->artist->p) set_str(t->artist, sizeof(t->artist), v2->artist->p, strlen(v2->artist->p));
            if (v2->album  && v2->album->p)  set_str(t->album,  sizeof(t->album),  v2->album->p,  strlen(v2->album->p));
            for (size_t i = 0; v2->text && i < v2->texts; i++) {
                if (!memcmp(v2->text[i].id, "TRCK", 4) && v2->text[i].text.p)
                    t->number = parse_num(v2->text[i].text.p, strlen(v2->text[i].text.p));
                /* TPE2 é o artista do ÁLBUM: sem ele uma coletânea vira um
                   artista por faixa na estante */
                if (!memcmp(v2->text[i].id, "TPE2", 4) && v2->text[i].text.p &&
                    v2->text[i].text.p[0])
                    set_str(t->artist, sizeof(t->artist), v2->text[i].text.p,
                            strlen(v2->text[i].text.p));
            }
            if (want_cover && v2->picture) {
                for (size_t i = 0; i < v2->pictures; i++) {
                    mpg123_picture *p = &v2->picture[i];
                    if (p->type != mpg123_id3_pic_front_cover &&
                        p->type != mpg123_id3_pic_other) continue;
                    if (!p->data || p->size == 0) continue;
                    t->cover = malloc(p->size);
                    if (t->cover) { memcpy(t->cover, p->data, p->size); t->cover_len = p->size; }
                    break;
                }
            }
        }
        if (v1) {
            if (!t->title[0])  set_str(t->title,  sizeof(t->title),  v1->title,  strnlen(v1->title, 30));
            if (!t->artist[0]) set_str(t->artist, sizeof(t->artist), v1->artist, strnlen(v1->artist, 30));
            if (!t->album[0])  set_str(t->album,  sizeof(t->album),  v1->album,  strnlen(v1->album, 30));
        }
    }
    mpg123_close(mh);
    mpg123_delete(mh);
    return 0;
}

static int probe_flac(const char *path, DecTags *t, int want_cover)
{
    FLAC__StreamMetadata si;
    if (FLAC__metadata_get_streaminfo(path, &si)) {
        if (si.data.stream_info.sample_rate > 0 && si.data.stream_info.total_samples > 0)
            t->seconds = (int)(si.data.stream_info.total_samples /
                               si.data.stream_info.sample_rate);
    }
    FLAC__StreamMetadata *tags = NULL;
    if (FLAC__metadata_get_tags(path, &tags) && tags) {
        for (unsigned i = 0; i < tags->data.vorbis_comment.num_comments; i++) {
            const FLAC__StreamMetadata_VorbisComment_Entry *e =
                &tags->data.vorbis_comment.comments[i];
            take_vorbis_comment(t, (const char *)e->entry, e->length);
        }
        FLAC__metadata_object_delete(tags);
    }
    if (want_cover) {
        FLAC__StreamMetadata *pic = NULL;
        if (FLAC__metadata_get_picture(path, &pic,
                FLAC__STREAM_METADATA_PICTURE_TYPE_FRONT_COVER,
                NULL, NULL, (unsigned)-1, (unsigned)-1, (unsigned)-1, (unsigned)-1) && pic) {
            if (pic->data.picture.data && pic->data.picture.data_length > 0) {
                t->cover = malloc(pic->data.picture.data_length);
                if (t->cover) {
                    memcpy(t->cover, pic->data.picture.data, pic->data.picture.data_length);
                    t->cover_len = pic->data.picture.data_length;
                }
            }
            FLAC__metadata_object_delete(pic);
        }
    }
    return 0;
}

static int probe_vorbis(const char *path, DecTags *t, int want_cover)
{
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    OggVorbis_File vf;
    if (ov_open_callbacks(f, &vf, NULL, 0, OV_CALLBACKS_DEFAULT) < 0) {
        fclose(f);
        return -1;
    }
    double secs = ov_time_total(&vf, -1);
    if (secs > 0) t->seconds = (int)secs;
    vorbis_comment *vc = ov_comment(&vf, -1);
    if (vc) {
        for (int i = 0; i < vc->comments; i++) {
            take_vorbis_comment(t, vc->user_comments[i], (size_t)vc->comment_lengths[i]);
            if (want_cover)
                take_picture_comment(t, vc->user_comments[i], (size_t)vc->comment_lengths[i]);
        }
    }
    ov_clear(&vf);
    return 0;
}

static int probe_opus(const char *path, DecTags *t, int want_cover)
{
    int e = 0;
    OggOpusFile *of = op_open_file(path, &e);
    if (!of) return -1;
    ogg_int64_t total = op_pcm_total(of, -1);
    if (total > 0) t->seconds = (int)(total / 48000);   /* Opus é sempre 48k */
    const OpusTags *ot = op_tags(of, -1);
    if (ot) {
        for (int i = 0; i < ot->comments; i++) {
            take_vorbis_comment(t, ot->user_comments[i], (size_t)ot->comment_lengths[i]);
            if (want_cover)
                take_picture_comment(t, ot->user_comments[i], (size_t)ot->comment_lengths[i]);
        }
    }
    op_free(of);
    return 0;
}

int dec_probe(const char *path, DecTags *t, int want_cover)
{
    if (!path || !t) return -1;
    memset(t, 0, sizeof(*t));
    t->number = -1;
    t->seconds = -1;

    switch (dec_kind_of(path)) {
    case DEC_MP3:    return probe_mp3(path, t, want_cover);
    case DEC_FLAC:   return probe_flac(path, t, want_cover);
    case DEC_VORBIS: return probe_vorbis(path, t, want_cover);
    case DEC_OPUS:   return probe_opus(path, t, want_cover);
    case DEC_WAV: {
        /* WAV não tem tags que valha a pena ler, mas TEM duração — e sem ela
           o lado não fecha e a agulha aponta para o sulco errado. */
        Decoder *d = dec_open(path);
        if (!d) return -1;
        if (d->len > 0 && d->fmt.rate > 0) t->seconds = (int)(d->len / d->fmt.rate);
        dec_close(d);
        return 0;
    }
    default: return -1;
    }
}

void dec_tags_free(DecTags *t)
{
    if (!t) return;
    free(t->cover);
    t->cover = NULL;
    t->cover_len = 0;
}
