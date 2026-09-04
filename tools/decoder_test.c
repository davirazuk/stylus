/* Exercita o decoder.c contra ÁUDIO DE VERDADE, na máquina de quem mexe.
 *
 * O sinal é conhecido (uma senoide por canal, frequências diferentes nos dois
 * lados), então dá para exigir muito mais que "não estourou":
 *
 *   - o FLAC e o WAV são SEM PERDAS: as amostras têm que sair IDÊNTICAS às
 *     do WAV de origem, uma a uma. Um decodificador que troque os canais,
 *     erre o intercalado, escale errado ou perca um bloco reprova aqui e
 *     passaria em qualquer teste que só olhasse "tocou alguma coisa";
 *   - depois de um seek, a amostra em que a agulha cai tem que ser a amostra
 *     daquele ponto — não a de antes do salto, que é o defeito clássico de
 *     quem procura sem esvaziar o buffer;
 *   - o Vorbis, o Opus e o MP3 têm perdas, então a exigência é sobre a FORMA:
 *     duração, taxa, canais, e a energia por canal batendo com a do original
 *     (o canal esquerdo é mais alto que o direito de propósito — se saírem
 *     trocados, isto acusa).
 */

#include "decoder.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fails = 0, checks = 0;

static void okf(int cond, const char *what, const char *fmt, ...)
{
    checks++;
    if (cond) { printf("  \033[32m✓\033[0m %s\n", what); return; }
    fails++;
    printf("  \033[31m✗\033[0m %s\n", what);
    if (fmt) {
        char b[512];
        va_list ap; va_start(ap, fmt);
        vsnprintf(b, sizeof(b), fmt, ap);
        va_end(ap);
        printf("      %s\n", b);
    }
}

static char FX[512];
static char *fx(const char *name)
{
    static char b[1024];
    snprintf(b, sizeof(b), "%s/%s", FX, name);
    return b;
}

/* lê a faixa toda para memória */
static short *slurp(const char *path, long *out_frames, int *out_ch, long *out_rate)
{
    Decoder *d = dec_open(path);
    if (!d) return NULL;
    DecFormat f;
    dec_format(d, &f);
    *out_ch = f.channels;
    *out_rate = f.rate;

    size_t cap = 1 << 20, len = 0;
    short *buf = malloc(cap);
    for (;;) {
        if (len + 8192 > cap) {
            cap *= 2;
            short *nb = realloc(buf, cap);
            if (!nb) { free(buf); dec_close(d); return NULL; }
            buf = nb;
        }
        long got = dec_read(d, (unsigned char *)buf + len, 8192);
        if (got <= 0) break;
        len += (size_t)got;
    }
    dec_close(d);
    *out_frames = (long)(len / (size_t)(*out_ch * 2));
    return buf;
}

/* energia RMS por canal — o que sobrevive a um codec com perdas */
static void rms(const short *pcm, long frames, int ch, double *out)
{
    for (int c = 0; c < ch; c++) {
        double s = 0;
        for (long i = 0; i < frames; i++) {
            double v = pcm[i * ch + c];
            s += v * v;
        }
        out[c] = frames ? sqrt(s / (double)frames) : 0;
    }
}

static short *REF;
static long REF_FRAMES;

static void test_wav(void)
{
    printf("\n\033[1mWAV (escrito à mão, é onde o erro mora)\033[0m\n");
    int ch; long rate;
    REF = slurp(fx("tone16.wav"), &REF_FRAMES, &ch, &rate);
    okf(REF && ch == 2 && rate == 44100 && REF_FRAMES == 44100 * 4,
        "WAV 16 bits: 4 s, estéreo, 44100",
        "ch=%d rate=%ld frames=%ld", ch, rate, REF_FRAMES);
    if (!REF) return;

    /* o sinal é conhecido: o esquerdo tem que ser MAIS ALTO que o direito.
       Canais trocados é o defeito que "tocou alguma coisa" não pega. */
    double e[2];
    rms(REF, REF_FRAMES, 2, e);
    okf(e[0] > e[1] * 1.1, "os canais não saem trocados (esq mais alto)",
        "esq=%.0f dir=%.0f", e[0], e[1]);

    struct { const char *f; const char *nome; int tol; } casos[] = {
        { "tone24.wav",  "WAV 24 bits desce para 16", 2 },
        { "tone8.wav",   "WAV 8 bits (SEM sinal) sobe para 16", 300 },
        { "tonef32.wav", "WAV float32 vira inteiro", 3 },
    };
    for (unsigned i = 0; i < sizeof(casos) / sizeof(casos[0]); i++) {
        long fr; int c; long r;
        short *p = slurp(fx(casos[i].f), &fr, &c, &r);
        if (!p) { okf(0, casos[i].nome, "não abriu"); continue; }
        long n = fr < REF_FRAMES ? fr : REF_FRAMES;
        long worst = 0;
        for (long k = 0; k < n * 2; k++) {
            long d = labs((long)p[k] - (long)REF[k]);
            if (d > worst) worst = d;
        }
        okf(fr == REF_FRAMES && worst <= casos[i].tol, casos[i].nome,
            "frames=%ld (esperado %ld), maior diferença=%ld (tolerância %d)",
            fr, REF_FRAMES, worst, casos[i].tol);
        free(p);
    }
}

static void test_lossless(void)
{
    printf("\n\033[1mFLAC — sem perdas quer dizer IDÊNTICO\033[0m\n");
    if (!REF) { okf(0, "sem referência", NULL); return; }

    long fr; int ch; long rate;
    short *p = slurp(fx("tone.flac"), &fr, &ch, &rate);
    if (!p) { okf(0, "o FLAC não abriu", NULL); return; }
    okf(fr == REF_FRAMES && ch == 2 && rate == 44100,
        "FLAC: mesma duração, canais e taxa do original",
        "frames=%ld ch=%d rate=%ld", fr, ch, rate);

    long diffs = 0, worst = 0, first = -1;
    long n = fr < REF_FRAMES ? fr : REF_FRAMES;
    for (long k = 0; k < n * 2; k++) {
        if (p[k] != REF[k]) {
            diffs++;
            long d = labs((long)p[k] - (long)REF[k]);
            if (d > worst) worst = d;
            if (first < 0) first = k;
        }
    }
    okf(diffs == 0, "FLAC: TODA amostra idêntica ao WAV de origem",
        "%ld amostras diferentes de %ld, maior desvio %ld, a 1ª em %ld",
        diffs, n * 2, worst, first);
    free(p);

    /* 24 bits: o Vita só sai em 16, então o esperado é o original >> 8 */
    long fr2; int ch2; long rate2;
    short *q = slurp(fx("tone24.flac"), &fr2, &ch2, &rate2);
    if (q) {
        long bad = 0;
        long m = fr2 < REF_FRAMES ? fr2 : REF_FRAMES;
        for (long k = 0; k < m * 2; k++)
            if (labs((long)q[k] - (long)REF[k]) > 1) bad++;
        okf(bad == 0, "FLAC de 24 bits desce para 16 sem se deslocar",
            "%ld amostras fora de ±1", bad);
        free(q);
    } else {
        okf(0, "o FLAC de 24 bits não abriu", NULL);
    }
}

static void test_lossy(void)
{
    printf("\n\033[1mVorbis, Opus e MP3 — a forma tem que bater\033[0m\n");
    if (!REF) return;
    double ref_e[2];
    rms(REF, REF_FRAMES, 2, ref_e);

    struct { const char *f, *nome; long rate; double dur_tol; } casos[] = {
        { "tone.ogg",  "Vorbis", 44100, 0.10 },
        { "tone.opus", "Opus",   48000, 0.10 },
        { "tone.mp3",  "MP3",    44100, 0.15 },
    };
    for (unsigned i = 0; i < sizeof(casos) / sizeof(casos[0]); i++) {
        long fr; int ch; long rate;
        short *p = slurp(fx(casos[i].f), &fr, &ch, &rate);
        char what[128];
        if (!p) {
            snprintf(what, sizeof(what), "%s: abre e decodifica", casos[i].nome);
            okf(0, what, "não abriu");
            continue;
        }
        double secs = rate > 0 ? (double)fr / (double)rate : 0;
        snprintf(what, sizeof(what), "%s: 4 s, estéreo, %ld Hz",
                 casos[i].nome, casos[i].rate);
        okf(ch == 2 && rate == casos[i].rate &&
            fabs(secs - 4.0) < casos[i].dur_tol, what,
            "%.3f s, ch=%d, rate=%ld", secs, ch, rate);

        double e[2];
        rms(p, fr, ch, e);
        snprintf(what, sizeof(what),
                 "%s: a energia dos dois canais bate com o original",
                 casos[i].nome);
        okf(ref_e[0] > 0 && ref_e[1] > 0 &&
            fabs(e[0] - ref_e[0]) / ref_e[0] < 0.10 &&
            fabs(e[1] - ref_e[1]) / ref_e[1] < 0.10, what,
            "esq %.0f vs %.0f, dir %.0f vs %.0f", e[0], ref_e[0], e[1], ref_e[1]);
        free(p);
    }
}

/* O TETO DE TAXA — o que decide o áudio em segundo plano.

   Quem escolhe o TIPO da porta de saída do Vita é o SDL2, e ele decide pela
   taxa: <=47999 Hz abre a porta BGM, acima abre MAIN. Só a BGM segura o som
   dentro de um jogo. Numa varredura do cartão, 996 de 3728 arquivos eram de
   48 kHz — 27% da coleção perdia o segundo plano em silêncio.

   Isto NÃO é um teste de qualidade de reamostragem: é um teste de que o teto
   é obedecido, e de que a taxa NATIVA continua sendo dita (a tela promete não
   mentir sobre o caminho do sinal, então precisa das duas). */
static void test_teto_bgm(void)
{
    printf("\n\033[1mo teto de taxa (áudio em segundo plano)\033[0m\n");
    const long TETO = 47999;

    /* sem teto: sai na taxa do arquivo */
    dec_set_max_rate(0);
    Decoder *d = dec_open(fx("tone48k.mp3"));
    if (!d) { okf(0, "o MP3 de 48 kHz abre", "não abriu"); return; }
    DecFormat f;
    dec_format(d, &f);
    okf(f.rate == 48000 && f.rate_native == 48000,
        "sem teto, o MP3 de 48 kHz sai em 48 kHz",
        "saída %ld, arquivo %ld", f.rate, f.rate_native);
    dec_close(d);

    /* com teto: a SAÍDA desce, o NATIVO não muda */
    dec_set_max_rate(TETO);
    d = dec_open(fx("tone48k.mp3"));
    if (!d) { okf(0, "com teto, o MP3 de 48 kHz ainda abre", "não abriu"); return; }
    dec_format(d, &f);
    okf(f.rate > 0 && f.rate <= TETO, "com teto, a saída cabe na porta BGM",
        "saída %ld, teto %ld", f.rate, TETO);
    okf(f.rate_native == 48000,
        "e a taxa do ARQUIVO continua sendo dita (a tela não mente)",
        "nativo %ld", f.rate_native);
    /* e continua entregando áudio: um teto que muda a taxa e para de
       decodificar seria pior que não ter teto */
    {
        unsigned char buf[8192];
        long got = dec_read(d, buf, sizeof(buf));
        okf(got > 0, "e continua entregando PCM depois de reamostrar",
            "dec_read devolveu %ld", got);
    }
    dec_close(d);

    /* quem JÁ cabe não é tocado: reamostrar 44,1k à toa é perda de qualidade
       e de CPU do aparelho por nada */
    d = dec_open(fx("tone.mp3"));
    if (d) {
        dec_format(d, &f);
        okf(f.rate == 44100 && f.rate_native == 44100,
            "quem já cabe no teto passa intacto",
            "saída %ld, arquivo %ld", f.rate, f.rate_native);
        dec_close(d);
    }
    dec_set_max_rate(0);
}

static void test_seek(void)
{
    printf("\n\033[1mprocurar cai onde disse que caiu\033[0m\n");
    if (!REF) return;
    const char *sem_perdas[] = { "tone16.wav", "tone.flac", NULL };
    for (int i = 0; sem_perdas[i]; i++) {
        Decoder *d = dec_open(fx(sem_perdas[i]));
        char what[160];
        if (!d) {
            snprintf(what, sizeof(what), "%s: seek", sem_perdas[i]);
            okf(0, what, "não abriu");
            continue;
        }
        /* LÊ ANTES de procurar, e para numa leitura PEQUENA.
           Sem ler antes, o buffer interno está vazio e o teste não pode pegar
           o defeito que existe para pegar: PCM de antes do salto tocando
           depois dele. E não basta ler: seis leituras do mesmo tamanho
           esvaziavam o buffer exatamente na última, e o teste passava verde
           mesmo com o esvaziamento removido do decodificador. A leitura curta
           no fim garante que sobre PCM velho lá dentro. */
        short warm[4096];
        for (int w = 0; w < 5; w++)
            if (dec_read(d, warm, sizeof(warm)) <= 0) break;
        dec_read(d, warm, 64);

        long long target = 44100 * 2;             /* metade da faixa */
        long long got = dec_seek(d, target);
        short buf[512];
        long n = dec_read(d, buf, sizeof(buf));

        /* a amostra em que a agulha cai TEM que ser a daquele ponto: é aqui
           que se pega o buffer velho tocando depois do salto */
        int match = 0;
        if (n > 0 && got >= 0) {
            long off = (long)got * 2;
            long cmp = n / 2 < 200 ? n / 2 : 200;
            match = 1;
            for (long k = 0; k < cmp; k++)
                if (labs((long)buf[k] - (long)REF[off + k]) > 1) { match = 0; break; }
        }
        snprintf(what, sizeof(what), "%s: depois do seek vem o áudio DAQUELE ponto",
                 sem_perdas[i]);
        okf(match, what, "seek devolveu %lld, leu %ld bytes", got, n);

        snprintf(what, sizeof(what), "%s: dec_tell concorda com o seek",
                 sem_perdas[i]);
        okf(dec_tell(d) >= got, what, "tell=%lld got=%lld", dec_tell(d), got);
        dec_close(d);
    }

    /* com perdas: não dá para comparar amostra, mas dá para exigir que o
       tempo ande e que a leitura continue funcionando depois do salto */
    const char *com_perdas[] = { "tone.ogg", "tone.opus", "tone.mp3", NULL };
    for (int i = 0; com_perdas[i]; i++) {
        Decoder *d = dec_open(fx(com_perdas[i]));
        char what[160];
        if (!d) continue;
        DecFormat f; dec_format(d, &f);
        short warm[4096];
        for (int w = 0; w < 5; w++)
            if (dec_read(d, warm, sizeof(warm)) <= 0) break;
        dec_read(d, warm, 64);
        long long got = dec_seek(d, f.rate * 2);
        short buf[512];
        long n = dec_read(d, buf, sizeof(buf));
        snprintf(what, sizeof(what), "%s: procura e continua lendo", com_perdas[i]);
        okf(got > 0 && n > 0, what, "seek=%lld, leu %ld", got, n);
        dec_close(d);
    }
}

static void test_tags(void)
{
    printf("\n\033[1mtags e capa embutida\033[0m\n");
    struct { const char *f, *nome; int quer_capa; int quer_num; } casos[] = {
        { "tone.flac", "FLAC",   1, 1 },
        { "tone.ogg",  "Vorbis", 0, 1 },
        { "tone.opus", "Opus",   1, 1 },
        { "tone.mp3",  "MP3",    1, 1 },
    };
    for (unsigned i = 0; i < sizeof(casos) / sizeof(casos[0]); i++) {
        DecTags t;
        char what[160];
        if (dec_probe(fx(casos[i].f), &t, 1) != 0) {
            snprintf(what, sizeof(what), "%s: lê as tags", casos[i].nome);
            okf(0, what, "dec_probe falhou");
            continue;
        }
        snprintf(what, sizeof(what), "%s: título, artista e álbum", casos[i].nome);
        okf(!strcmp(t.title, "Faixa de Teste") &&
            !strcmp(t.artist, "Artista Teste") &&
            !strcmp(t.album, "Album Teste"), what,
            "título=\"%s\" artista=\"%s\" álbum=\"%s\"", t.title, t.artist, t.album);

        if (casos[i].quer_num) {
            /* "7/12" é a forma mais comum de TRACKNUMBER e vira 712 sem cuidado */
            snprintf(what, sizeof(what), "%s: faixa 7 (e não 712, de \"7/12\")",
                     casos[i].nome);
            okf(t.number == 7, what, "deu %d", t.number);
        }

        snprintf(what, sizeof(what), "%s: duração ≈ 4 s", casos[i].nome);
        okf(t.seconds >= 3 && t.seconds <= 5, what, "deu %d", t.seconds);

        if (casos[i].quer_capa) {
            snprintf(what, sizeof(what), "%s: a capa embutida sai como PNG",
                     casos[i].nome);
            okf(t.cover && t.cover_len >= 8 &&
                t.cover[0] == 0x89 && t.cover[1] == 'P' &&
                t.cover[2] == 'N' && t.cover[3] == 'G', what,
                "cover=%p len=%zu", (void *)t.cover, t.cover_len);
        }
        dec_tags_free(&t);
    }
}

static void test_kinds(void)
{
    printf("\n\033[1mquem sabe tocar o quê\033[0m\n");
    okf(dec_kind_of("a.flac") == DEC_FLAC && dec_kind_of("A.FLAC") == DEC_FLAC,
        "FLAC, com e sem maiúscula", NULL);
    okf(dec_kind_of("a.ogg") == DEC_VORBIS && dec_kind_of("a.oga") == DEC_VORBIS,
        ".ogg e .oga são Vorbis", NULL);
    okf(dec_kind_of("a.opus") == DEC_OPUS, ".opus é Opus", NULL);
    okf(dec_kind_of("a.mp3") == DEC_MP3 && dec_kind_of("a.mp2") == DEC_MP3,
        ".mp3 e .mp2 são MPEG", NULL);
    okf(dec_kind_of("a.wav") == DEC_WAV, ".wav é WAV", NULL);
    okf(dec_kind_of("a.m4a") == DEC_NONE && dec_kind_of("capa.jpg") == DEC_NONE,
        "m4a e jpg continuam sem decodificador (e a estante os marca)", NULL);
    okf(dec_open("/nao/existe/x.flac") == NULL,
        "arquivo que não existe devolve NULL e não estoura", NULL);
}

int main(int argc, char **argv)
{
    snprintf(FX, sizeof(FX), "%s", argc > 1 ? argv[1] : "/tmp/fx");
    printf("\033[1mvitastylus — decodificadores, contra áudio de verdade\033[0m\n");
    printf("fixtures em %s\n", FX);
    dec_global_init();
    test_kinds();
    test_wav();
    test_lossless();
    test_lossy();
    test_teto_bgm();
    test_seek();
    test_tags();
    free(REF);
    dec_global_exit();
    printf("\n%d conferências, %d \033[31mfalha%s\033[0m\n",
           checks, fails, fails == 1 ? "" : "s");
    return fails ? 1 : 0;
}
