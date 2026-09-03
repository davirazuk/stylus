#include "playlist.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <dirent.h>
#include <sys/stat.h>

/* M3U8: uma linha por caminho absoluto; `#...` = metadado, ignorado.
   Lê também `#EXTINF` mas não o usa (o player pega a duração da tag). */

static char *trim_copy(const char *s)
{
    while (*s == ' ' || *s == '\t') s++;
    size_t len = strlen(s);
    while (len > 0 && (s[len - 1] == ' ' || s[len - 1] == '\t' ||
                       s[len - 1] == '\r' || s[len - 1] == '\n'))
        len--;
    char *o = malloc(len + 1);
    if (!o) return NULL;
    memcpy(o, s, len);
    o[len] = '\0';
    return o;
}

static int is_meta_line(const char *s)
{
    return *s == '#' || *s == '\0';
}

int playlist_add(Playlist *pl, const char *path)
{
    if (!pl || !path || !path[0]) return -1;
    /* ignora duplicado */
    for (int i = 0; i < pl->n; i++)
        if (strcmp(pl->files[i], path) == 0) return 0;
    if (pl->n >= pl->cap) {
        int nc = pl->cap ? pl->cap * 2 : 16;
        char **nf = realloc(pl->files, (size_t)nc * sizeof(char *));
        if (!nf) return -1;
        pl->files = nf;
        pl->cap = nc;
    }
    char *c = strdup(path);
    if (!c) return -1;
    pl->files[pl->n++] = c;
    return 0;
}

int playlist_remove(Playlist *pl, int idx)
{
    if (!pl || idx < 0 || idx >= pl->n) return -1;
    free(pl->files[idx]);
    for (int i = idx; i + 1 < pl->n; i++)
        pl->files[i] = pl->files[i + 1];
    pl->n--;
    return 0;
}

void playlist_sanitize_name(char *name)
{
    if (!name) return;
    for (char *p = name; *p; p++) {
        unsigned char c = (unsigned char)*p;
        if (c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' ||
            c == '"' || c == '<' || c == '>' || c == '|' || c < 0x20)
            *p = '_';
    }
}

int playlist_new(Playlist **array, int *count, const char *name_prefix,
                 const Track *const *tracks, int n)
{
    if (!array || !count || n <= 0) return -1;
    Playlist *np = realloc(*array, (size_t)(*count + 1) * sizeof(Playlist));
    if (!np) return -1;
    *array = np;
    Playlist *pl = &(*array)[*count];
    memset(pl, 0, sizeof(*pl));

    /* nome único: prefixo + número que ainda não colide com os existentes */
    for (int k = 1;; k++) {
        snprintf(pl->name, sizeof(pl->name), "%s %d", name_prefix, k);
        int clash = 0;
        for (int i = 0; i < *count; i++)
            if (strcmp((*array)[i].name, pl->name) == 0) { clash = 1; break; }
        if (!clash) break;
    }

    for (int i = 0; i < n; i++)
        if (tracks[i])
            playlist_add(pl, tracks[i]->path);
    (*count)++;
    return 0;
}

/* carrega um arquivo .m3u (sem a extensão) num Playlist. Devolve 0 ok, -1 erro. */
static int playlist_load_one(Playlist *pl, const char *dir, const char *base_m3u)
{
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, base_m3u);
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    /* nome = base sem ".m3u" */
    size_t bl = strlen(base_m3u);
    char namebuf[PLAYLIST_NAME_MAX];
    if (bl > 4 && strcasecmp(base_m3u + bl - 4, ".m3u") == 0) bl -= 4;
    size_t nl = bl < PLAYLIST_NAME_MAX - 1 ? bl : PLAYLIST_NAME_MAX - 1;
    memcpy(namebuf, base_m3u, nl);
    namebuf[nl] = '\0';
    snprintf(pl->name, sizeof(pl->name), "%s", namebuf);

    char line[1024];
    while (fgets(line, sizeof(line), f)) {
        char *t = trim_copy(line);
        if (!t) { fclose(f); return -1; }
        if (!is_meta_line(t)) {
            char *p = t;
            while (*p == ' ') p++;
            if (p[0]) playlist_add(pl, p);
        }
        free(t);
    }
    fclose(f);
    return 0;
}

int playlist_load_dir(Playlist **out, int *count, const char *dir)
{
    *out = NULL;
    *count = 0;
    DIR *d = opendir(dir);
    if (!d) return -1;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        size_t l = strlen(e->d_name);
        if (l <= 4 || strcasecmp(e->d_name + l - 4, ".m3u") != 0) continue;
        Playlist *np = realloc(*out, (size_t)(*count + 1) * sizeof(Playlist));
        if (!np) { closedir(d); return -1; }
        *out = np;
        Playlist *pl = &(*out)[*count];
        memset(pl, 0, sizeof(*pl));
        if (playlist_load_one(pl, dir, e->d_name) != 0) {
            free(pl->files);
            pl->files = NULL;
            pl->n = pl->cap = 0;
            /* mantém o slot vazio; contabiliza mesmo assim */
        }
        (*count)++;
    }
    closedir(d);
    return *count == 0 ? -2 : 0;
}

int playlist_save(const Playlist *pl, const char *dir)
{
    if (!pl || !pl->name[0]) return -1;
    /* garante que o diretório existe */
    mkdir(dir, 0777); /* erro se já existe é ok */
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s.m3u", dir, pl->name);
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    fputs("#EXTM3U\n", f);
    for (int i = 0; i < pl->n; i++) {
        fputs("#EXTINF:*,\n", f);
        fprintf(f, "%s\n", pl->files[i]);
    }
    fclose(f);
    return 0;
}

void playlist_free(Playlist *pl, int count)
{
    if (!pl) return;
    for (int i = 0; i < count; i++) {
        for (int j = 0; j < pl[i].n; j++)
            free(pl[i].files[j]);
        free(pl[i].files);
    }
    free(pl);
}
