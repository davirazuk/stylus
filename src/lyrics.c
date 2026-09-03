#include "lyrics.h"
#include "decoder.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static void trim(char *s)
{
    size_t n = strlen(s);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r' ||
                 s[n - 1] == ' '  || s[n - 1] == '\t')) s[--n] = '\0';
}

static int add_line(Lyrics *l, int ms, const char *text)
{
    if (l->n >= LRC_MAX_LINES) return -1;
    l->lines[l->n].ms = ms;
    snprintf(l->lines[l->n].text, LRC_TEXT_MAX, "%s", text);
    l->n++;
    return 0;
}

/* "[01:23.45]" e "[01:23]" — o segundo, sem centésimos, é comum e é o que o
   celular não casava: a linha simplesmente sumia. Devolve os ms e avança `p`. */
static int read_stamp(const char **p)
{
    const char *s = *p;
    if (*s != '[') return -1;
    s++;
    int mm = 0, digits = 0;
    while (*s >= '0' && *s <= '9') { mm = mm * 10 + (*s++ - '0'); digits++; }
    if (!digits || *s != ':') return -1;
    s++;
    int ss = 0;
    digits = 0;
    while (*s >= '0' && *s <= '9') { ss = ss * 10 + (*s++ - '0'); digits++; }
    if (!digits) return -1;
    int cs = 0;
    if (*s == '.' || *s == ':') {
        s++;
        int d = 0;
        int frac = 0;
        while (*s >= '0' && *s <= '9' && d < 3) { frac = frac * 10 + (*s++ - '0'); d++; }
        while (*s >= '0' && *s <= '9') s++;      /* milésimos a mais, ignora */
        if (d == 1) cs = frac * 100;
        else if (d == 2) cs = frac * 10;
        else cs = frac;
    }
    if (*s != ']') return -1;
    s++;
    *p = s;
    return mm * 60000 + ss * 1000 + cs;
}

static int cmp_line(const void *a, const void *b)
{
    const LrcLine *x = a, *y = b;
    return x->ms < y->ms ? -1 : (x->ms > y->ms ? 1 : 0);
}

void lyrics_load(Lyrics *l, const char *audio_path)
{
    if (!l) return;
    if (l->loaded && audio_path && !strcmp(l->for_path, audio_path)) return;

    memset(l, 0, sizeof(*l));
    l->loaded = true;                 /* "não tem" é resposta, não tentativa */
    if (!audio_path || !audio_path[0]) return;
    snprintf(l->for_path, sizeof(l->for_path), "%s", audio_path);

    char path[1024];
    snprintf(path, sizeof(path), "%s", audio_path);
    char *dot = strrchr(path, '.');
    char *slash = strrchr(path, '/');
    if (!dot || (slash && dot < slash)) return;
    snprintf(dot, sizeof(path) - (size_t)(dot - path), "%s", ".lrc");

    FILE *f = fopen(path, "r");
    if (!f) {
        /* .LRC em maiúscula: um acervo passado por Windows guarda assim, e
           comparar com maiúscula descarta meia coleção */
        snprintf(dot, sizeof(path) - (size_t)(dot - path), "%s", ".LRC");
        f = fopen(path, "r");
        if (!f) return;
    }

    char line[1024];
    while (fgets(line, sizeof(line), f)) {
        trim(line);
        const char *p = line;

        /* `[offset:±ms]` é o conserto que quem sincronizou deixou escrito, e
           era ignorado nos dois lados do sistema */
        if (!strncasecmp(p, "[offset:", 8)) {
            l->offset_ms = atoi(p + 8);
            continue;
        }

        /* `[00:42][02:15]refrão` é UMA linha com DOIS momentos, e é como todo
           refrão de .lrc é escrito. Casar só o primeiro fazia o refrão sair
           uma vez, com os outros colchetes impressos na tela. */
        int stamps[16], ns = 0;
        for (;;) {
            const char *q = p;
            int ms = read_stamp(&q);
            if (ms < 0) break;
            if (ns < 16) stamps[ns++] = ms;
            p = q;
        }
        if (!ns) continue;
        while (*p == ' ') p++;
        if (!*p) continue;                /* linha só de carimbo: sem texto */
        for (int i = 0; i < ns; i++)
            if (add_line(l, stamps[i], p) != 0) break;
    }
    fclose(f);

    if (l->n > 1)
        qsort(l->lines, (size_t)l->n, sizeof(LrcLine), cmp_line);
}

int lyrics_at(const Lyrics *l, int ms)
{
    if (!l || l->n <= 0) return -1;
    ms -= l->offset_ms;
    if (ms < l->lines[0].ms) return -1;
    /* Busca binária devolve a linha SEGUINTE, não a atual: quem canta é
       `lo - 1`. O desktop errava isso e a letra ia uma linha adiantada,
       sempre — e o mesmo código no celular estava certo, e ninguém comparou. */
    int lo = 0, hi = l->n;
    while (lo < hi) {
        int mid = (lo + hi) / 2;
        if (l->lines[mid].ms <= ms) lo = mid + 1;
        else hi = mid;
    }
    return lo - 1;
}
