#include "library.h"
#include "tags.h"

#include <dirent.h>
#include <sys/stat.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdio.h>

static int ends_with_ext(const char *name, const char *ext)
{
    size_t n = strlen(name), e = strlen(ext);
    if (n < e) return 0;
    return strcasecmp(name + (n - e), ext) == 0;
}

/* extrai artista/álbum de um caminho relativo ao root:
   Artist/Album/xx.mp3  -> artist, album
   Album/xx.mp3         -> album vira o nome do álbum, artist vazio
*/
/* Seta artista/álbum a partir do caminho do diretório do álbum (relativo ao root).
   Esperado:  Artist/Album   -> artist=Artist, album=Album
              Album          -> album=Album, artist vazio
              (vazio)        -> album="?", artist vazio                        */
static void set_artist_album(const char *rel_dir, char *artist, size_t artist_cap,
                             char *album, size_t album_cap)
{
    if (artist && artist_cap) artist[0] = '\0';
    if (album && album_cap) album[0] = '\0';
    if (!rel_dir || !rel_dir[0]) {
        if (album && album_cap) snprintf(album, album_cap, "?");
        return;
    }
    const char *last = strrchr(rel_dir, '/');
    if (!last) {
        /* um único nível: é o álbum, sem artista definido */
        size_t l = strlen(rel_dir);
        if (l >= album_cap) l = album_cap - 1;
        memcpy(album, rel_dir, l);
        album[l] = '\0';
        return;
    }
    /* artista = tudo antes do último '/'; álbum = depois do último '/' */
    size_t alen = (size_t)(last - rel_dir);
    if (alen >= artist_cap) alen = artist_cap - 1;
    memcpy(artist, rel_dir, alen);
    artist[alen] = '\0';
    size_t blen = strlen(last + 1);
    if (blen >= album_cap) blen = album_cap - 1;
    memcpy(album, last + 1, blen);
    album[blen] = '\0';
}

static Album *find_album(Library *lib, const char *key)
{
    for (int i = 0; i < lib->nalbums; i++)
        if (lib->albums[i].key[0] && strcmp(lib->albums[i].key, key) == 0)
            return &lib->albums[i];
    return NULL;
}

static Album *ensure_album(Library *lib)
{
    if (lib->nalbums >= lib->cap) {
        int n = lib->cap ? lib->cap * 2 : 64;
        Album *a = realloc(lib->albums, (size_t)n * sizeof(Album));
        if (!a) return NULL;
        lib->albums = a;
        lib->cap = n;
    }
    Album *a = &lib->albums[lib->nalbums];
    memset(a, 0, sizeof(*a));
    lib->nalbums++;
    return a;
}

static int add_track(Album *a, const char *full, const char *base)
{
    if (a->ntracks >= a->cap) {
        int n = a->cap ? a->cap * 2 : 16;
        Track *t = realloc(a->tracks, (size_t)n * sizeof(Track));
        if (!t) return -1;
        a->tracks = t;
        a->cap = n;
    }
    Track *t = &a->tracks[a->ntracks];
    memset(t, 0, sizeof(*t));
    snprintf(t->path, MAX_PATH_LEN, "%s", full);
    snprintf(t->title, MAX_TITLE_LEN, "%s", base);
    t->number = -1;
    t->seconds = -1;
    a->ntracks++;
    return 0;
}

/* varre recursivamente; album_key = caminho do diretório pai relativo ao root */
static void scan_dir(Library *lib, const char *abs, const char *rel)
{
    DIR *d = opendir(abs);
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        char child_abs[MAX_PATH_LEN], child_rel[MAX_PATH_LEN];
        snprintf(child_abs, MAX_PATH_LEN, "%s/%s", abs, e->d_name);
        if (rel[0])
            snprintf(child_rel, MAX_PATH_LEN, "%s/%s", rel, e->d_name);
        else
            snprintf(child_rel, MAX_PATH_LEN, "%s", e->d_name);

        struct stat st;
        if (stat(child_abs, &st) != 0) continue;

        if (S_ISDIR(st.st_mode)) {
            scan_dir(lib, child_abs, child_rel);
        } else if (S_ISREG(st.st_mode) &&
                   (ends_with_ext(e->d_name, ".mp3") ||
                    ends_with_ext(e->d_name, ".flac") ||
                    ends_with_ext(e->d_name, ".ogg"))) {
            const char *slash = strrchr(child_rel, '/');
            char rel_dir[MAX_PATH_LEN];
            if (slash) {
                size_t l = (size_t)(slash - child_rel);
                if (l >= MAX_PATH_LEN) l = MAX_PATH_LEN - 1;
                memcpy(rel_dir, child_rel, l);
                rel_dir[l] = '\0';
            } else {
                snprintf(rel_dir, MAX_PATH_LEN, "%s", "");
            }

            Album *a = find_album(lib, rel_dir);
            if (!a) {
                a = ensure_album(lib);
                if (!a) { closedir(d); return; }
                snprintf(a->key, MAX_PATH_LEN, "%s", rel_dir);
                set_artist_album(rel_dir, a->artist, MAX_NAME_LEN,
                                 a->album, MAX_NAME_LEN);
                if (!a->album[0] || !strcmp(a->album, "?"))
                    snprintf(a->album, MAX_NAME_LEN, "%s", "?");
            }
            add_track(a, child_abs, e->d_name);
        }
    }
    closedir(d);
}

void library_init(Library *lib, const char *root)
{
    memset(lib, 0, sizeof(*lib));
    snprintf(lib->root, MAX_PATH_LEN, "%s", root ? root : MUSIC_ROOT_DEFAULT);
}

int library_scan(Library *lib)
{
    scan_dir(lib, lib->root, "");
    /* ordena faixas dentro de cada álbum pelo número (ou nome) */
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        /* insertion sort por number, depois por título */
        for (int k = 1; k < a->ntracks; k++) {
            Track t = a->tracks[k];
            int j = k - 1;
            while (j >= 0) {
                int an = a->tracks[j].number;
                if (an < 0) an = 0;
                if (an > t.number && t.number >= 0) break;
                if (an == t.number &&
                    strcasecmp(a->tracks[j].title, t.title) <= 0) break;
                a->tracks[j + 1] = a->tracks[j];
                j--;
            }
            a->tracks[j + 1] = t;
        }
    }
    library_sort(lib);
    return lib->nalbums ? 0 : 0; /* mesmo vazio retorna ok; UI mostra vazio */
}

static int album_cmp(const Album *a, const Album *b)
{
    int r = strcasecmp(a->artist, b->artist);
    if (r) return r;
    r = strcasecmp(a->album, b->album);
    if (r) return r;
    return 0;
}

void library_sort(Library *lib)
{
    for (int i = 1; i < lib->nalbums; i++) {
        Album t = lib->albums[i];
        int j = i - 1;
        while (j >= 0 && album_cmp(&lib->albums[j], &t) > 0) {
            lib->albums[j + 1] = lib->albums[j];
            j--;
        }
        lib->albums[j + 1] = t;
    }
}

void library_free(Library *lib)
{
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        free(a->tracks);
        free(a->cover);
    }
    free(lib->albums);
    lib->albums = NULL;
    lib->nalbums = lib->cap = 0;
    tags_exit();
}

Album *library_album(Library *lib, int i)
{
    if (i < 0 || i >= lib->nalbums) return NULL;
    return &lib->albums[i];
}

int album_load_cover(Album *alb)
{
    if (alb->cover_loaded) return alb->cover ? 0 : 1;
    alb->cover_loaded = true;
    if (!alb->tracks || alb->ntracks == 0) return 1;

    /* tenta até 8 faixas até achar uma com capa front cover */
    for (int i = 0; i < alb->ntracks && i < 8; i++) {
        char t[MAX_TITLE_LEN], a[MAX_NAME_LEN], al[MAX_NAME_LEN];
        int num, sec;
        /* primeiro só para saber o tamanho */
        size_t need = 0;
        if (tags_read(alb->tracks[i].path, t, sizeof(t), a, sizeof(a), al, sizeof(al),
                      &num, &sec, NULL, 0, &need, 1) != 0)
            continue;
        if (need == 0) continue;
        unsigned char *buf = malloc(need);
        if (!buf) return -1;
        size_t got = 0;
        if (tags_read(alb->tracks[i].path, t, sizeof(t), a, sizeof(a), al, sizeof(al),
                      &num, &sec, buf, need, &got, 1) != 0 || got == 0 || got > need) {
            free(buf);
            continue;
        }
        /* preenche metadados de artista/álbum do álbum a partir da tag */
        if (!alb->album[0] && al[0]) snprintf(alb->album, MAX_NAME_LEN, "%s", al);
        if (!alb->artist[0] && a[0]) snprintf(alb->artist, MAX_NAME_LEN, "%s", a);
        alb->cover = buf;
        alb->cover_len = got;
        return 0;
    }
    return 1;
}

void album_free_cover(Album *alb)
{
    free(alb->cover);
    alb->cover = NULL;
    alb->cover_len = 0;
    alb->cover_loaded = false;
}
