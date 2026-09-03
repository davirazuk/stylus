#include "scrobble.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

/* Protege a leitura/escrita do arquivo do diário: a thread do player apende
   enquanto a thread da UI re-agrega — sem lock, o top/histórico podem ver a
   linha pela metade. */
static pthread_mutex_t s_file_mtx = PTHREAD_MUTEX_INITIALIZER;

#define RECENT_DEFAULT_MAX 200

static int track_by_path(const Scrob *s, const char *path)
{
    for (int i = 0; i < s->ntracks; i++)
        if (strcmp(s->tracks[i].path, path) == 0) return i;
    return -1;
}

static ScrobAlbum *album_for(Scrob *s, Album *a)
{
    for (int i = 0; i < s->nalbums; i++)
        if (s->albums[i].album == a) return &s->albums[i];
    if (s->nalbums >= s->cap_albums) {
        int nc = s->cap_albums ? s->cap_albums * 2 : 64;
        ScrobAlbum *na = realloc(s->albums, (size_t)nc * sizeof(*na));
        if (!na) return NULL;
        s->albums = na;
        s->cap_albums = nc;
    }
    ScrobAlbum *sa = &s->albums[s->nalbums++];
    memset(sa, 0, sizeof(*sa));
    sa->album = a;
    return sa;
}

static void recent_push(Scrob *s, const char *path, long ts)
{
    if (s->nrecent >= s->cap_recent) {
        int nc = s->cap_recent ? s->cap_recent * 2 : 64;
        ScrobRecent *nr = realloc(s->recent, (size_t)nc * sizeof(*nr));
        if (!nr) return;
        s->recent = nr;
        s->cap_recent = nc;
    }
    if (s->nrecent >= s->recent_max) {
        memmove(s->recent + 1, s->recent,
                (size_t)(s->recent_max - 1) * sizeof(*s->recent));
        s->nrecent = s->recent_max;
    } else {
        memmove(s->recent + 1, s->recent, (size_t)s->nrecent * sizeof(*s->recent));
        s->nrecent++;
    }
    snprintf(s->recent[0].path, sizeof(s->recent[0].path), "%s", path);
    s->recent[0].ts = ts;
}

/* Carrega o diário e agrega tudo em memória. Usa o Library só para resolver
   os ponteiros de álbum (paths órfãs/removidas contam no recente). */
void scrob_load(Scrob *s, Library *lib, const char *dir)
{
    memset(s, 0, sizeof(*s));
    s->recent_max = RECENT_DEFAULT_MAX;
    if (!dir) return;

    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, SCROBBLE_FILE);

    pthread_mutex_lock(&s_file_mtx);
    FILE *f = fopen(path, "r");
    if (!f) {
        pthread_mutex_unlock(&s_file_mtx);
        return;
    }

    char line[4096];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        if (n && line[n - 1] == '\n') line[--n] = '\0';
        if (!line[0]) continue;
        char *tab1 = strchr(line, '\t');
        if (!tab1) continue;
        *tab1 = '\0';
        long ts = atol(line);
        char *pathv = tab1 + 1;
        if (!pathv[0]) continue;
        char *tab2 = strchr(pathv, '\t');
        if (tab2) *tab2 = '\0';

        int ti = track_by_path(s, pathv);
        if (ti < 0) {
            if (s->ntracks >= s->cap_tracks) {
                int nc = s->cap_tracks ? s->cap_tracks * 2 : 128;
                ScrobTrack *na = realloc(s->tracks, (size_t)nc * sizeof(*na));
                if (!na) break;
                s->tracks = na;
                s->cap_tracks = nc;
            }
            ScrobTrack *st = &s->tracks[s->ntracks++];
            memset(st, 0, sizeof(*st));
            st->path = strdup(pathv);
            st->count = 1;
            st->last_ts = ts;
            ti = s->ntracks - 1;
        } else {
            s->tracks[ti].count++;
            if (ts > s->tracks[ti].last_ts) s->tracks[ti].last_ts = ts;
        }
        /* resolve o álbum dono para as métricas por álbum */
        if (lib) {
            Album *alb = NULL;
            if (library_find_track_by_path(lib, &alb, pathv) >= 0 && alb) {
                ScrobAlbum *sa = album_for(s, alb);
                if (sa) {
                    sa->count++;
                    if (ts > sa->last_ts) sa->last_ts = ts;
                }
            }
        }
        recent_push(s, pathv, ts);
    }
    fclose(f);
    pthread_mutex_unlock(&s_file_mtx);
}

int scrob_append_file(const char *dir, const Track *t, long timestamp)
{
    if (!dir || !t || timestamp <= 0 || !t->path[0]) return -1;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, SCROBBLE_FILE);

    pthread_mutex_lock(&s_file_mtx);

    /* dedupe: não regista a mesma trecho do player duas vezes (mesma faixa,
       mesmo timestamp que a última linha do arquivo). */
    long last_ts = 0;
    char last_path[1024] = "";
    FILE *r = fopen(path, "r");
    if (r) {
        char buf[4096] = "";
        while (fgets(buf, sizeof(buf), r)) {
            if (buf[0] == '\n' || buf[0] == '\0') continue;
            char *t1 = strchr(buf, '\t');
            char *p1 = t1 ? t1 + 1 : NULL;
            char *t2 = p1 ? strchr(p1, '\t') : NULL;
            if (t2) *t2 = '\0';
            last_ts = atol(buf);
            if (p1) snprintf(last_path, sizeof(last_path), "%s", p1);
        }
        fclose(r);
    }
    if (last_ts == timestamp && strcmp(last_path, t->path) == 0) {
        pthread_mutex_unlock(&s_file_mtx);
        return 0;
    }

    const char *artist = t->owner ? t->owner->artist : "";
    const char *album  = t->owner ? t->owner->album : "";
    char a[128], al[128];
    snprintf(a, sizeof(a), "%.60s", artist);
    snprintf(al, sizeof(al), "%.60s", album);
    for (char *p = a; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';
    for (char *p = al; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';

    FILE *f = fopen(path, "a");
    if (f) {
        fprintf(f, "%ld\t%s\t%s\t%s\n", timestamp, t->path, a, al);
        fclose(f);
    }

    pthread_mutex_unlock(&s_file_mtx);
    return f ? 0 : -1;
}

int scrob_log(Scrob *s, const char *dir, const Track *t, long timestamp)
{
    if (!s || !dir || !t || timestamp <= 0) return -1;
    if (!t->path[0]) return -1;

    /* dedupe em memória: mesma faixa imediatamente à frente */
    int ti = track_by_path(s, t->path);
    if (ti >= 0 && s->tracks[ti].last_ts == timestamp)
        return 0;

    scrob_append_file(dir, t, timestamp);

    /* atualiza métricas em memória */
    if (ti < 0) {
        if (s->ntracks >= s->cap_tracks) {
            int nc = s->cap_tracks ? s->cap_tracks * 2 : 128;
            ScrobTrack *na = realloc(s->tracks, (size_t)nc * sizeof(*na));
            if (na) { s->tracks = na; s->cap_tracks = nc; }
        }
        if (s->ntracks < s->cap_tracks) {
            ScrobTrack *st = &s->tracks[s->ntracks++];
            memset(st, 0, sizeof(*st));
            st->path = strdup(t->path);
            st->count = 1;
            st->last_ts = timestamp;
            ti = s->ntracks - 1;
        }
    } else {
        s->tracks[ti].count++;
        if (timestamp > s->tracks[ti].last_ts) s->tracks[ti].last_ts = timestamp;
    }
    if (t->owner) {
        ScrobAlbum *sa = album_for(s, t->owner);
        if (sa) {
            sa->count++;
            if (timestamp > sa->last_ts) sa->last_ts = timestamp;
        }
    }
    recent_push(s, t->path, timestamp);
    return 0;
}

int scrob_track_count(const Scrob *s, const Track *t)
{
    if (!s || !t) return 0;
    int ti = track_by_path(s, t->path);
    return ti >= 0 ? s->tracks[ti].count : 0;
}

int scrob_album_count(const Scrob *s, Album *a)
{
    if (!s || !a) return 0;
    for (int i = 0; i < s->nalbums; i++)
        if (s->albums[i].album == a) return s->albums[i].count;
    return 0;
}

long scrob_album_last(const Scrob *s, Album *a)
{
    if (!s || !a) return 0;
    for (int i = 0; i < s->nalbums; i++)
        if (s->albums[i].album == a) return s->albums[i].last_ts;
    return 0;
}

/* ordena o top por contagem (igualdade: mais recente primeiro) */
static int album_better(const Scrob *s, int a, int b)
{
    const ScrobAlbum *x = &s->albums[a];
    const ScrobAlbum *y = &s->albums[b];
    if (x->count != y->count) return x->count > y->count;
    if (x->last_ts != y->last_ts) return x->last_ts > y->last_ts;
    return 0;
}

int scrob_top_albums(const Scrob *s, Album **out, int max)
{
    if (!s || !out || max <= 0) return 0;
    if (s->nalbums <= 0) return 0;
    int *idx = malloc((size_t)s->nalbums * sizeof(int));
    if (!idx) return 0;
    for (int i = 0; i < s->nalbums; i++) idx[i] = i;
    /* ordenação por inserção (lista pequena; portátil sem qsort_r) */
    for (int i = 1; i < s->nalbums; i++) {
        int key = idx[i], j = i - 1;
        while (j >= 0 && album_better(s, key, idx[j])) {
            idx[j + 1] = idx[j];
            j--;
        }
        idx[j + 1] = key;
    }
    int k = s->nalbums < max ? s->nalbums : max;
    for (int i = 0; i < k; i++)
        out[i] = s->albums[idx[i]].album;
    free(idx);
    return k;
}

int scrob_recent(const Scrob *s, const char **paths, long *ts, int max)
{
    if (!s || !paths || max <= 0) return 0;
    int k = s->nrecent < max ? s->nrecent : max;
    for (int i = 0; i < k; i++) {
        paths[i] = s->recent[i].path;
        if (ts) ts[i] = s->recent[i].ts;
    }
    return k;
}

void scrob_free(Scrob *s)
{
    if (!s) return;
    for (int i = 0; i < s->ntracks; i++) free(s->tracks[i].path);
    free(s->tracks);
    free(s->albums);
    free(s->recent);
    memset(s, 0, sizeof(*s));
}
