#include "rec.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

void rec_load(Rec *r, const char *dir)
{
    memset(r, 0, sizeof(*r));
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, REC_HISTORY_FILE);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char line[1400];
    while (fgets(line, sizeof(line), f)) {
        char *tab = strchr(line, '\t');
        if (!tab) continue;
        *tab = '\0';
        int c = atoi(tab + 1);
        if (c <= 0) continue;
        if (r->n >= r->cap) {
            int nc = r->cap ? r->cap * 2 : 64;
            char **np = realloc(r->paths, (size_t)nc * sizeof(char *));
            int *nc2 = realloc(r->counts, (size_t)nc * sizeof(int));
            if (!np || !nc2) { free(np); free(nc2); break; }
            r->paths = np;
            r->counts = nc2;
            r->cap = nc;
        }
        char *p = strdup(line);
        if (!p) break;
        /* métricas */
        r->paths[r->n] = p;
        r->counts[r->n] = c;
        r->n++;
    }
    fclose(f);
}

static int find_path(const Rec *r, const char *path)
{
    for (int i = 0; i < r->n; i++)
        if (strcmp(r->paths[i], path) == 0) return i;
    return -1;
}

void rec_play(Rec *r, const char *path, const char *dir)
{
    if (!r || !path) return;
    int idx = find_path(r, path);
    if (idx >= 0) {
        r->counts[idx]++;
    } else {
        if (r->n >= r->cap) {
            int nc = r->cap ? r->cap * 2 : 64;
            char **np = realloc(r->paths, (size_t)nc * sizeof(char *));
            int *nc2 = realloc(r->counts, (size_t)nc * sizeof(int));
            if (!np || !nc2) { free(np); free(nc2); return; }
            r->paths = np;
            r->counts = nc2;
            r->cap = nc;
        }
        char *p = strdup(path);
        if (!p) return;
        r->paths[r->n] = p;
        r->counts[r->n] = 1;
        r->n++;
    }

    char fpath[1024];
    snprintf(fpath, sizeof(fpath), "%s/%s", dir, REC_HISTORY_FILE);
    FILE *f = fopen(fpath, "w");
    if (!f) return;
    for (int i = 0; i < r->n; i++)
        fprintf(f, "%s\t%d\n", r->paths[i], r->counts[i]);
    fclose(f);
}

int rec_count(const Rec *r, const Track *t)
{
    if (!r || !t) return 0;
    int idx = find_path(r, t->path);
    return idx >= 0 ? r->counts[idx] : 0;
}

int rec_album_unheard(const Rec *r, const Album *a)
{
    if (!r || !a) return 1;
    for (int i = 0; i < a->ntracks; i++)
        if (rec_count(r, &a->tracks[i]) > 0) return 0;
    return 1;
}

int rec_album_affinity(const Rec *r, const Album *a)
{
    if (!r || !a) return 0;
    int sum = 0;
    for (int i = 0; i < a->ntracks; i++)
        sum += rec_count(r, &a->tracks[i]);
    return sum;
}

static int artist_aff(const ArtistAff *aa, int naa, const char *artist)
{
    for (int j = 0; j < naa; j++)
        if (strcasecmp(aa[j].artist, artist) == 0) return aa[j].aff;
    return 0;
}

void rec_build_list(const Rec *r, Library *lib, const Track **out, int *n, int max)
{
    *n = 0;
    if (!r || !lib || !out || max <= 0) return;

    int N = lib->nalbums;
    if (N <= 0) return;

    /* 1) afinidade por artista (soma das afinidades dos álbuns) */
    ArtistAff *aa = calloc((size_t)(N > 0 ? N : 1), sizeof(ArtistAff));
    int naa = 0;
    if (aa) {
        for (int i = 0; i < N; i++) {
            Album *a = &lib->albums[i];
            int aff = rec_album_affinity(r, a);
            if (aff == 0) continue;
            int j = 0;
            for (; j < naa; j++)
                if (strcasecmp(aa[j].artist, a->artist) == 0) break;
            if (j < naa) {
                aa[j].aff += aff;
            } else if (naa < N) {
                snprintf(aa[j = naa].artist, sizeof(aa[j].artist), "%s", a->artist);
                aa[naa].aff = aff;
                naa++;
            }
        }
    }

    /* 2) separa álbuns em nunca ouvidos e ouvidos */
    int *unheard = malloc((size_t)N * sizeof(int));
    int *heard = malloc((size_t)N * sizeof(int));
    int un = 0, he = 0;
    if (!unheard || !heard) {
        free(unheard); free(heard); free(aa);
        return;
    }
    for (int i = 0; i < N; i++) {
        if (rec_album_unheard(r, &lib->albums[i]))
            unheard[un++] = i;
        else
            heard[he++] = i;
    }

    /* 3) ordena nunca-ouvidos: maior afinidade do artista primeiro */
    for (int i = 1; i < un; i++) {
        int k = unheard[i];
        int j = i - 1;
        while (j >= 0) {
            Album *a1 = &lib->albums[unheard[j]];
            Album *a2 = &lib->albums[k];
            int aff1 = artist_aff(aa, naa, a1->artist);
            int aff2 = artist_aff(aa, naa, a2->artist);
            int before = (aff2 > aff1) ||
                         (aff2 == aff1 && strcasecmp(a1->album, a2->album) > 0);
            if (!before) break;
            unheard[j + 1] = unheard[j];
            j--;
        }
        unheard[j + 1] = k;
    }

    /* 4) empilha faixas: principais desconhecidos, depois ouvidos (shuffle leve) */
    int cap = 0;
    for (int i = 0; i < un && cap < max; i++) {
        Album *a = &lib->albums[unheard[i]];
        for (int t = 0; t < a->ntracks && cap < max; t++)
            out[cap++] = &a->tracks[t];
    }
    /* depois, álbuns já ouvidos mas com faixas ainda não ouvidas */
    for (int i = 0; i < he && cap < max; i++) {
        Album *a = &lib->albums[heard[i]];
        for (int t = 0; t < a->ntracks && cap < max; t++)
            if (rec_count(r, &a->tracks[t]) == 0)
                out[cap++] = &a->tracks[t];
    }
    /* por fim completa com o resto (evita estourar) */
    for (int i = 0; i < he && cap < max; i++) {
        Album *a = &lib->albums[heard[i]];
        for (int t = 0; t < a->ntracks && cap < max; t++)
            out[cap++] = &a->tracks[t];
    }

    *n = cap;
    free(unheard); free(heard); free(aa);
}

void rec_free(Rec *r)
{
    if (!r) return;
    for (int i = 0; i < r->n; i++)
        free(r->paths[i]);
    free(r->paths);
    free(r->counts);
    memset(r, 0, sizeof(*r));
}
