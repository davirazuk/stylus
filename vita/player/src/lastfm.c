#include "lastfm.h"
#include "md5.h"
#include "net.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LASTFM_API_URL "https://ws.audioscrobbler.com/2.0/"

/* ---------- config ---------- */

void lastfm_config_load(LastfmConfig *cfg, const char *dir)
{
    memset(cfg, 0, sizeof(*cfg));
    if (!dir) return;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, LASTFM_CONFIG_FILE);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        char *val = eq + 1;
        size_t vl = strlen(val);
        while (vl && (val[vl - 1] == '\n' || val[vl - 1] == '\r')) val[--vl] = '\0';
        if (strcmp(line, "api_key") == 0)   snprintf(cfg->api_key, sizeof(cfg->api_key), "%s", val);
        else if (strcmp(line, "api_secret") == 0) snprintf(cfg->api_secret, sizeof(cfg->api_secret), "%s", val);
        else if (strcmp(line, "sk") == 0)   snprintf(cfg->sk, sizeof(cfg->sk), "%s", val);
        else if (strcmp(line, "username") == 0) snprintf(cfg->username, sizeof(cfg->username), "%s", val);
    }
    fclose(f);
    cfg->configured = cfg->api_key[0] && cfg->api_secret[0] && cfg->sk[0];
}

int lastfm_config_save(const LastfmConfig *cfg, const char *dir)
{
    if (!cfg || !dir) return -1;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, LASTFM_CONFIG_FILE);
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    fprintf(f, "api_key=%s\n", cfg->api_key);
    fprintf(f, "api_secret=%s\n", cfg->api_secret);
    fprintf(f, "sk=%s\n", cfg->sk);
    fprintf(f, "username=%s\n", cfg->username);
    fclose(f);
    return 0;
}

/* ---------- fila ---------- */

int lastfm_enqueue(const char *dir, const Track *t, long timestamp, int duration)
{
    if (!dir || !t || timestamp <= 0) return -1;
    const char *artist = t->owner ? t->owner->artist : "";
    const char *album  = t->owner ? t->owner->album : "";
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, LASTFM_QUEUE_FILE);
    FILE *f = fopen(path, "a");
    if (!f) return -1;
    char a[128], al[128], tl[256];
    snprintf(a, sizeof(a), "%.80s", artist);
    snprintf(al, sizeof(al), "%.80s", album);
    snprintf(tl, sizeof(tl), "%.120s", t->title);
    for (char *p = a; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';
    for (char *p = al; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';
    for (char *p = tl; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';
    fprintf(f, "%ld\t%s\t%s\t%s\t%d\n", timestamp, tl, a, al, duration);
    fclose(f);
    return 0;
}

int lastfm_queue_size(const char *dir)
{
    if (!dir) return 0;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, LASTFM_QUEUE_FILE);
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int n = 0;
    char c;
    while ((c = (char)fgetc(f)) != EOF) if (c == '\n') n++;
    fclose(f);
    return n;
}

/* ---------- URL-encode (form) ---------- */

static void urlenc(const char *in, char *out, size_t cap)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t o = 0;
    for (const unsigned char *p = (const unsigned char *)in; *p && o + 3 < cap; p++) {
        unsigned char c = *p;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') {
            out[o++] = (char)c;
        } else {
            out[o++] = '%';
            out[o++] = hex[c >> 4];
            out[o++] = hex[c & 15];
        }
    }
    out[o] = '\0';
}

/* ---------- sync ---------- */

/* monta corpo + assinatura last.fm para track.scrobble e faz o POST.
   Devolve 0 sucesso, 1 erro de API (descarta a linha), -1 rede. */
static int scrobble_one(const LastfmConfig *cfg, long ts,
                        const char *artist, const char *track,
                        const char *album, int duration)
{
    /* pares (chave, valor cru) — a assinatura usa o VALOR CRU (como o
       stylus-scrobble do PC); o corpo urlencodeia cada valor e mantém a
       estrutura key=value&... */
    struct KV { const char *k; const char *v; } kv[16];
    int kn = 0;
    char dur[16] = "", tstr[20];
    snprintf(tstr, sizeof(tstr), "%ld", ts);
    if (duration > 0) snprintf(dur, sizeof(dur), "%d", duration);
    if (album && album[0]) kv[kn].k = "album", kv[kn].v = album, kn++;
    kv[kn].k = "api_key"; kv[kn].v = cfg->api_key; kn++;
    kv[kn].k = "artist";  kv[kn].v = artist; kn++;
    if (duration > 0)     kv[kn].k = "duration", kv[kn].v = dur, kn++;
    kv[kn].k = "format";  kv[kn].v = "json"; kn++;
    kv[kn].k = "method";  kv[kn].v = "track.scrobble"; kn++;
    kv[kn].k = "sk";      kv[kn].v = cfg->sk; kn++;
    kv[kn].k = "timestamp"; kv[kn].v = tstr; kn++;
    kv[kn].k = "track";   kv[kn].v = track; kn++;

    /* assinatura: chaves ordenadas + valores crus + secret → MD5 */
    for (int i = 1; i < kn; i++) {
        struct KV t = kv[i];
        int j = i - 1;
        while (j >= 0 && strcmp(kv[j].k, t.k) > 0) { kv[j + 1] = kv[j]; j--; }
        kv[j + 1] = t;
    }
    char sig[4096];
    int sp = 0;
    for (int i = 0; i < kn; i++)
        sp += sprintf(sig + sp, "%s%s", kv[i].k, kv[i].v);
    sp += sprintf(sig + sp, "%s", cfg->api_secret);
    char md5[33];
    md5_hex(sig, (size_t)sp, md5);

    /* corpo: key=urlencode(valor) separado por & */
    char body[8192];
    int bp = 0;
    for (int i = 0; i < kn; i++) {
        if (i) body[bp++] = '&';
        bp += sprintf(body + bp, "%s=", kv[i].k);
        char enc[1024];
        urlenc(kv[i].v, enc, sizeof(enc));
        bp += sprintf(body + bp, "%s", enc);
    }
    bp += sprintf(body + bp, "&api_sig=%s", md5);
    (void)bp;

    char resp[2048];
    if (net_post(LASTFM_API_URL, body, resp, (int)sizeof(resp)) != 0)
        return -1;
    if (strstr(resp, "\"error\""))
        return 1; /* erro permanente de API: descarta a linha */
    return 0;
}

int lastfm_sync(const LastfmConfig *cfg, const char *dir)
{
    if (!cfg || !dir) return 0;
    if (!cfg->configured) return 0; /* offline / sem credencial */

    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, LASTFM_QUEUE_FILE);
    FILE *f = fopen(path, "r");
    if (!f) return 0;

    enum { MAXQ = 2048 };
    char *lines[MAXQ];
    int n = 0;
    char buf[1024];
    while (n < MAXQ && fgets(buf, sizeof(buf), f)) {
        size_t l = strlen(buf);
        if (l && buf[l - 1] == '\n') buf[l - 1] = '\0';
        if (buf[0]) {
            lines[n] = strdup(buf);
            if (lines[n]) n++;
        }
    }
    fclose(f);

    /* esvazia da frente; para na primeira falha de rede */
    int kept = 0, sent = 0, i;
    for (i = 0; i < n; i++) {
        /* ts\t(track)\tartist\talbum\tduration — cuidado com tabs dentro de
           valores não há (sanitizado no enqueue), então split é estável */
        long ts = atol(lines[i]);
        char *p = strchr(lines[i], '\t'); if (!p) { free(lines[i]); continue; }
        char *track = p + 1; char *t2 = strchr(track, '\t'); if (!t2) { free(lines[i]); continue; }
        *t2 = '\0'; char *artist = t2 + 1; char *t3 = strchr(artist, '\t');
        char *album = ""; int duration = 0;
        if (t3) { *t3 = '\0'; album = t3 + 1; char *t4 = strchr(album, '\t'); if (t4) { *t4 = '\0'; duration = atoi(t4 + 1); } }
        int r = scrobble_one(cfg, ts, artist, track, album, duration);
        if (r == 0) { sent++; free(lines[i]); }
        else if (r == 1) { free(lines[i]); } /* erro permanente: descarta */
        else { lines[kept++] = lines[i]; break; } /* rede: para, guarda o resto */
    }
    for (; i < n; i++) lines[kept++] = lines[i];

    /* reescreve a fila com o que sobrou */
    FILE *w = fopen(path, "w");
    if (w) {
        for (int k = 0; k < kept; k++)
            fprintf(w, "%s\n", lines[k]);
        fclose(w);
    }
    for (int k = 0; k < kept; k++) free(lines[k]);
    return sent;
}
