#include "lyrics.h"
#include "decoder.h"
#ifdef __vita__
#include "net.h"
#endif

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

/* --- lrclib.net: busca online, fallback quando não há .lrc local --- */
#ifdef __vita__

static void urlenc(const char *s, char *out, size_t cap)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t o = 0;
    for (; s && *s && o + 4 < cap; s++) {
        unsigned char c = (unsigned char)*s;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~')
            out[o++] = (char)c;
        else {
            out[o++] = '%';
            out[o++] = hex[c >> 4];
            out[o++] = hex[c & 15];
        }
    }
    out[o] = '\0';
}

/* Extrai uma string JSON simples (sem nesting). Devolve 1 se achou. */
static int jstr(const char *json, const char *key, char *out, int cap)
{
    char agulha[128];
    snprintf(agulha, sizeof(agulha), "\"%s\"", key);
    const char *p = strstr(json, agulha);
    if (!p) return 0;
    p += strlen(agulha);
    while (*p == ' ' || *p == ':') p++;
    if (*p != '"') return 0;
    p++;
    /* AS ESCAPAS DO JSON, DE VERDADE.

       Antes isto era `if (*p == '\\') { p++; out[i++] = *p; }`: jogava a
       barra fora e copiava a LETRA seguinte. Ou seja, `\n` virava a letra
       `n`. O lrclib devolve a letra inteira num único campo com `\n`
       separando os versos, então o .lrc gravado no cartão saía SEM UMA
       QUEBRA DE LINHA e com um `n` grudado no fim de cada verso
       ("...at men[00:29.83]..."). O parse_lrc corta por '\n', não achava
       nenhuma, e a letra inteira virava uma linha só — na tela, nada.
       Os dois .lrc que o aparelho baixou em 05/09 estão assim; apagar para
       rebaixar. */
    int i = 0;
    while (*p && *p != '"' && i < cap - 1) {
        if (*p != '\\') { out[i++] = *p++; continue; }
        p++;
        switch (*p) {
        case 'n':  out[i++] = '\n'; p++; break;
        case 'r':  out[i++] = '\r'; p++; break;
        case 't':  out[i++] = '\t'; p++; break;
        case 'b':  out[i++] = '\b'; p++; break;
        case 'f':  out[i++] = '\f'; p++; break;
        case '"':
        case '\\':
        case '/':  out[i++] = *p++; break;
        case 'u': {
            /* \uXXXX -> UTF-8. Letra sem acento não é letra: o lrclib
               escapa caracteres fora do ASCII, e sem isto "coração" chegava
               como "u00e7" no meio da palavra. */
            unsigned cp = 0;
            int ok = 1;
            for (int k = 1; k <= 4; k++) {
                char c = p[k];
                cp <<= 4;
                if      (c >= '0' && c <= '9') cp |= (unsigned)(c - '0');
                else if (c >= 'a' && c <= 'f') cp |= (unsigned)(c - 'a' + 10);
                else if (c >= 'A' && c <= 'F') cp |= (unsigned)(c - 'A' + 10);
                else { ok = 0; break; }
            }
            if (!ok) { out[i++] = *p++; break; }
            p += 5;
            if (cp < 0x80) {
                out[i++] = (char)cp;
            } else if (cp < 0x800) {
                if (i + 2 > cap - 1) { i = cap - 1; break; }
                out[i++] = (char)(0xC0 | (cp >> 6));
                out[i++] = (char)(0x80 | (cp & 0x3F));
            } else {
                if (i + 3 > cap - 1) { i = cap - 1; break; }
                out[i++] = (char)(0xE0 | (cp >> 12));
                out[i++] = (char)(0x80 | ((cp >> 6) & 0x3F));
                out[i++] = (char)(0x80 | (cp & 0x3F));
            }
            break;
        }
        case '\0': break;
        default:   out[i++] = *p++; break;
        }
    }
    out[i] = '\0';
    return 1;
}

/* Lê conteúdo LRC em `lrc` e adiciona linhas em `l`. */
static void parse_lrc(Lyrics *l, const char *lrc)
{
    const char *p = lrc;
    while (*p && l->n < LRC_MAX_LINES) {
        const char *eol = p;
        while (*eol && *eol != '\n') eol++;

        const char *q = p;
        int stamps[16], ns = 0;
        for (;;) {
            const char *r = q;
            int ms = read_stamp(&r);
            if (ms < 0) break;
            if (ns < 16) stamps[ns++] = ms;
            q = r;
        }
        if (ns) {
            while (*q == ' ') q++;
            size_t len = (size_t)(eol - q);
            char text[LRC_TEXT_MAX];
            if (len >= sizeof(text)) len = sizeof(text) - 1;
            memcpy(text, q, len);
            text[len] = '\0';
            size_t tl = strlen(text);
            while (tl && (text[tl - 1] == ' ' || text[tl - 1] == '\r'))
                text[--tl] = '\0';
            for (int i = 0; i < ns; i++)
                add_line(l, stamps[i], text);
        }

        if (*eol == '\n') p = eol + 1;
        else break;
    }
    if (l->n > 1)
        qsort(l->lines, (size_t)l->n, sizeof(LrcLine), cmp_line);
}

/* Busca letra síncronizada no lrclib.net e grava no cartão para offline.
   Devolve 1 se achou letra sincronizada, 0 se não. */
static int fetch_online(Lyrics *l, const char *audio_path,
                        const char *artist, const char *album,
                        const char *track, int duration_s)
{
    if (!artist && !track) return 0;

    char a[512], b[512], t[512];
    urlenc(artist ? artist : "", a, sizeof(a));
    urlenc(album  ? album  : "", b, sizeof(b));
    urlenc(track  ? track  : "", t, sizeof(t));

    char url[2048];
    if (duration_s > 0)
        snprintf(url, sizeof(url),
                 "https://lrclib.net/api/get?artist_name=%s&album_name=%s"
                 "&track_name=%s&duration=%d",
                 a, b, t, duration_s);
    else
        snprintf(url, sizeof(url),
                 "https://lrclib.net/api/get?artist_name=%s&album_name=%s"
                 "&track_name=%s",
                 a, b, t);

    static char resp[64 * 1024];
    resp[0] = '\0';
    if (net_get(url, NULL, resp, (int)sizeof(resp)) != 0) return 0;
    if (strstr(resp, "\"error\":true")) return 0;

    char lrc[48 * 1024];
    if (jstr(resp, "syncedLyrics", lrc, (int)sizeof(lrc)) && lrc[0]) {
        parse_lrc(l, lrc);
        if (l->n > 0) {
            /* Grava no cartão para offline — só a versão síncrona,
               porque .lrc com timestamps é o que o reader local espera. */
            if (audio_path) {
                char path[1024];
                snprintf(path, sizeof(path), "%s", audio_path);
                char *dot = strrchr(path, '.');
                if (dot) {
                    snprintf(dot, sizeof(path) - (size_t)(dot - path), ".lrc");
                    FILE *f = fopen(path, "w");
                    if (f) { fputs(lrc, f); fclose(f); }
                }
            }
            return 1;
        }
    }

    /* Fallback: plainLyrics (texto sem timestamps). Não é .lrc, então não
       gravamos — o reader local não saberia ler. Mas é melhor que nada:
       a tela mostra o texto completo sem destaque de linha. */
    if (jstr(resp, "plainLyrics", lrc, (int)sizeof(lrc)) && lrc[0]) {
        const char *p = lrc;
        while (*p && l->n < LRC_MAX_LINES) {
            const char *eol = p;
            while (*eol && *eol != '\n') eol++;
            size_t len = (size_t)(eol - p);
            char line[LRC_TEXT_MAX];
            if (len >= sizeof(line)) len = sizeof(line) - 1;
            memcpy(line, p, len);
            line[len] = '\0';
            /* trim\r */
            size_t tl = strlen(line);
            while (tl && line[tl - 1] == '\r') line[--tl] = '\0';
            if (tl > 0) add_line(l, 0, line);
            if (*eol == '\n') p = eol + 1;
            else break;
        }
        return l->n > 0 ? 1 : 0;
    }

    return 0;
}
#endif /* __vita__ */

void lyrics_load(Lyrics *l, const char *audio_path,
                 const char *artist, const char *album,
                 const char *track, int duration_s)
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
    }

    if (f) {
        char line[1024];
        while (fgets(line, sizeof(line), f)) {
            trim(line);
            const char *p = line;

            if (!strncasecmp(p, "[offset:", 8)) {
                l->offset_ms = atoi(p + 8);
                continue;
            }

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
            if (!*p) continue;
            for (int i = 0; i < ns; i++)
                if (add_line(l, stamps[i], p) != 0) break;
        }
        fclose(f);

        if (l->n > 1)
            qsort(l->lines, (size_t)l->n, sizeof(LrcLine), cmp_line);
    } else {
#ifdef __vita__
        /* Sem .lrc local: tenta o lrclib.net */
        if (artist && track)
            fetch_online(l, audio_path, artist, album, track, duration_s);
#else
        (void)artist; (void)album; (void)track; (void)duration_s;
#endif
    }
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
