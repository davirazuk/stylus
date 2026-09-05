/* Toca pela REDE e exige o mesmo som que pelo cartao.
 *
 * Um servidor de mentira (o proprio teste sobe um) serve as mesmas fixtures
 * que o teste do decodificador usa. Entao:
 *
 *   - o FLAC pela rede tem que sair IDENTICO ao FLAC do disco, amostra por
 *     amostra. E sem perdas dos dois lados; qualquer diferenca e defeito do
 *     caminho, nao do formato;
 *   - o MP3 e o Ogg tem que dar a mesma duracao e a mesma energia por canal;
 *   - uma conexao que CAI no meio nao pode virar "fim da faixa". A diferenca
 *     importa: fim faz o player passar para a proxima, erro faz a tela dizer
 *     que a rede caiu. Confundir os dois faz um disco "terminar" sozinho
 *     quando o Wi-Fi pisca — que e o jeito mais confuso possivel de falhar.
 */

#include "decoder.h"
#include "fonte.h"

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

static char BASE[256];
static char FX[256];

static short *tudo(Decoder *d, long *frames, int *ch, long *rate)
{
    if (!d) return NULL;
    DecFormat f;
    dec_format(d, &f);
    *ch = f.channels;
    *rate = f.rate;
    size_t cap = 1 << 20, len = 0;
    short *buf = malloc(cap);
    for (;;) {
        if (len + 16384 > cap) {
            cap *= 2;
            short *nb = realloc(buf, cap);
            if (!nb) { free(buf); return NULL; }
            buf = nb;
        }
        long got = dec_read(d, (unsigned char *)buf + len, 16384);
        if (got <= 0) break;
        len += (size_t)got;
    }
    *frames = (long)(len / (size_t)(*ch * 2));
    return buf;
}

static void rms(const short *p, long n, int ch, double *out)
{
    for (int c = 0; c < ch; c++) {
        double s = 0;
        for (long i = 0; i < n; i++) { double v = p[i * ch + c]; s += v * v; }
        out[c] = n ? sqrt(s / (double)n) : 0;
    }
}

static void caso(const char *nome, const char *arquivo, DecKind k, int exato)
{
    char url[512], path[512];
    snprintf(url, sizeof(url), "%s/%s", BASE, arquivo);
    snprintf(path, sizeof(path), "%s/%s", FX, arquivo);

    long fl = 0, fr = 0, rl = 0, rr = 0;
    int cl = 0, cr = 0;
    Decoder *dl = dec_open(path);
    short *loc = tudo(dl, &fl, &cl, &rl);
    dec_close(dl);

    Decoder *dr = dec_open_url(url, k);
    char what[160];
    if (!dr) {
        snprintf(what, sizeof(what), "%s: abre pela rede", nome);
        okf(0, what, "dec_open_url devolveu NULL para %s", url);
        free(loc);
        return;
    }
    snprintf(what, sizeof(what), "%s: a fonte se declara REDE", nome);
    okf(dec_e_remoto(dr), what, NULL);

    short *rem = tudo(dr, &fr, &cr, &rr);
    const char *erro = dec_erro_rede(dr);
    dec_close(dr);

    snprintf(what, sizeof(what), "%s: mesma duracao, canais e taxa que o arquivo", nome);
    okf(loc && rem && fl == fr && cl == cr && rl == rr, what,
        "cartao %ld quadros %dch %ldHz; rede %ld %dch %ldHz; erro \"%s\"",
        fl, cl, rl, fr, cr, rr, erro);

    if (loc && rem && fl == fr && cl == cr) {
        if (exato) {
            long dif = 0, pior = 0;
            for (long i = 0; i < fl * cl; i++) {
                long dd = labs((long)loc[i] - (long)rem[i]);
                if (dd) { dif++; if (dd > pior) pior = dd; }
            }
            snprintf(what, sizeof(what),
                     "%s: TODA amostra igual a do cartao (sem perdas dos dois lados)", nome);
            okf(dif == 0, what, "%ld amostras diferentes, pior desvio %ld", dif, pior);
        } else {
            double a[2], b[2];
            rms(loc, fl, cl, a);
            rms(rem, fr, cr, b);
            snprintf(what, sizeof(what), "%s: a energia dos dois canais bate", nome);
            okf(a[0] > 0 && b[0] > 0 &&
                fabs(a[0] - b[0]) / a[0] < 0.02 &&
                fabs(a[1] - b[1]) / a[1] < 0.02, what,
                "esq %.0f vs %.0f, dir %.0f vs %.0f", a[0], b[0], a[1], b[1]);
        }
    }
    free(loc);
    free(rem);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "uso: fluxo_test <base-url> <pasta-fixtures>\n");
        return 2;
    }
    snprintf(BASE, sizeof(BASE), "%s", argv[1]);
    snprintf(FX, sizeof(FX), "%s", argv[2]);

    printf("\033[1mvitastylus — tocar pela rede\033[0m\n");
    printf("servidor %s\n", BASE);
    dec_global_init();

    caso("FLAC",   "tone.flac", DEC_FLAC,   1);
    caso("MP3",    "tone.mp3",  DEC_MP3,    0);
    caso("Vorbis", "tone.ogg",  DEC_VORBIS, 0);
    caso("Opus",   "tone.opus", DEC_OPUS,   0);

    /* a fonte de rede diz o tamanho quando o servidor manda Content-Length */
    {
        char url[512];
        snprintf(url, sizeof(url), "%s/tone.flac", BASE);
        Fonte *f = fonte_rede(url);
        unsigned char b[64];
        long r = f ? fonte_le(f, b, sizeof(b)) : -1;
        okf(f && r == (long)sizeof(b) && fonte_tamanho(f) > 1000,
            "a fonte de rede sabe o tamanho pelo Content-Length",
            "leu %ld, tamanho %lld", r, f ? fonte_tamanho(f) : -1);
        /* os quatro primeiros bytes de um FLAC sao "fLaC" */
        okf(f && r >= 4 && !memcmp(b, "fLaC", 4),
            "e os primeiros bytes sao mesmo os do arquivo", NULL);
        fonte_fecha(f);
    }

    /* A rede CAI no meio. O servidor de teste promete o Content-Length
       inteiro e fecha depois de um terco. Isto tem que virar ERRO, e nao
       "acabou": o fim faz o player passar para a proxima faixa, o erro faz a
       tela dizer que a rede caiu. Confundir os dois faz um disco terminar
       sozinho quando o Wi-Fi pisca. */
    {
        char url[512];
        snprintf(url, sizeof(url), "%s/cai/tone.flac", BASE);
        Fonte *f = fonte_rede(url);
        long total = 0;
        unsigned char b[8192];
        for (;;) {
            long r = fonte_le(f, b, sizeof(b));
            if (r <= 0) {
                okf(r < 0, "conexao que cai no meio devolve ERRO, nao fim de faixa",
                    "fonte_le devolveu %ld depois de %ld bytes", r, total);
                break;
            }
            total += r;
            if (total > 4 * 1024 * 1024) { okf(0, "a fonte parou de crescer", NULL); break; }
        }
        okf(fonte_erro(f)[0] != '\0', "e a fonte DIZ o que a rede fez",
            "erro ficou vazio");
        okf(total > 0 && total < 128023,
            "e o que chegou antes da queda nao foi jogado fora",
            "chegaram %ld de 128023 bytes", total);
        fonte_fecha(f);
    }

    /* 404: nao existe. Tem que dar ERRO, e nao uma faixa vazia que o player
       trataria como "acabou" e passaria adiante calado. */
    {
        char url[512];
        snprintf(url, sizeof(url), "%s/nao-existe.flac", BASE);
        Decoder *d = dec_open_url(url, DEC_FLAC);
        okf(d == NULL, "uma URL que da 404 NAO abre (nem vira faixa muda)",
            "dec_open_url devolveu %p", (void *)d);
        dec_close(d);
    }

    /* servidor que nao existe: mesma exigencia, sem travar para sempre */
    {
        Decoder *d = dec_open_url("http://127.0.0.1:1/x.flac", DEC_FLAC);
        okf(d == NULL, "servidor inalcancavel NAO abre", NULL);
        dec_close(d);
    }

    dec_global_exit();
    printf("\n%d conferencias, %d \033[31mfalha%s\033[0m\n",
           checks, fails, fails == 1 ? "" : "s");
    return fails ? 1 : 0;
}
