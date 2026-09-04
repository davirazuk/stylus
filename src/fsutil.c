#include "fsutil.h"

#include <dirent.h>
#include <string.h>
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>

size_t path_join(char *out, size_t cap, const char *parent, const char *child)
{
    if (!out || cap == 0) return 0;
    out[0] = '\0';
    if (!parent) parent = "";
    if (!child) child = "";
    size_t pl = strlen(parent);
    while (pl > 0 && parent[pl - 1] == '/') pl--;      /* pai sem barra final */
    while (*child == '/') child++;                     /* filho sem barra inicial */

    size_t n = 0;
    if (pl) {
        if (pl >= cap) pl = cap - 1;
        memcpy(out, parent, pl);
        n = pl;
    }
    if (child[0]) {
        if (n && n + 1 < cap) out[n++] = '/';
        size_t cl = strlen(child);
        if (n + cl >= cap) cl = cap - n - 1;
        memcpy(out + n, child, cl);
        n += cl;
    }
    out[n] = '\0';
    return n;
}

void path_trim_slash(char *s)
{
    if (!s) return;
    size_t n = strlen(s);
    /* "ux0:/" é um caminho inteiro: tirar a barra deixaria só o dispositivo */
    while (n > 0 && s[n - 1] == '/' && !(n >= 2 && s[n - 2] == ':'))
        s[--n] = '\0';
}

int dir_exists(const char *path)
{
    /* pelo dir_open, e não pelo opendir: senão a estante diria que a raiz
       não existe justamente onde a varredura consegue entrar (e vice-versa).
       Duas metades respondendo a mesma pergunta discordariam. */
    if (!path || !path[0]) return 0;
    DirIter *it = dir_open(path);
    if (!it) return 0;
    dir_close(it);
    return 1;
}

int mkdir_p(const char *path)
{
    if (!path || !path[0]) return -1;
    char buf[1024];
    size_t n = strlen(path);
    if (n >= sizeof(buf)) return -1;
    memcpy(buf, path, n + 1);
    path_trim_slash(buf);

    /* pula o prefixo do dispositivo ("ux0:", "uma0:/") — não se cria device */
    char *p = buf;
    char *colon = strchr(buf, ':');
    if (colon) p = colon + 1;
    if (*p == '/') p++;

    for (; *p; p++) {
        if (*p != '/') continue;
        *p = '\0';
        mkdir(buf, 0777);   /* "já existe" é sucesso para o nosso propósito */
        *p = '/';
    }
    mkdir(buf, 0777);
    return dir_exists(buf) ? 0 : -1;
}

/* ---- percorrer uma pasta (ver a nota grande no fsutil.h) ---- */

#ifdef __vita__

#include <psp2/io/dirent.h>
#include <psp2/io/stat.h>

struct DirIter {
    SceUID fd;
    SceIoDirent ent;
};

DirIter *dir_open(const char *path)
{
    if (!path || !*path) return NULL;
    SceUID fd = sceIoDopen(path);
    if (fd < 0) return NULL;
    DirIter *it = calloc(1, sizeof(*it));
    if (!it) { sceIoDclose(fd); return NULL; }
    it->fd = fd;
    return it;
}

int dir_next(DirIter *it, const char **name, int *isdir)
{
    if (!it) return 0;
    memset(&it->ent, 0, sizeof(it->ent));
    if (sceIoDread(it->fd, &it->ent) <= 0) return 0;
    if (name)  *name  = it->ent.d_name;
    /* o próprio dread traz o stat: sem uma segunda ida ao cartão, e sem o
       caminho montado à mão que era onde a barra dupla mordia */
    if (isdir) *isdir = SCE_S_ISDIR(it->ent.d_stat.st_mode) ? 1 : 0;
    return 1;
}

void dir_close(DirIter *it)
{
    if (!it) return;
    sceIoDclose(it->fd);
    free(it);
}

#else   /* PC */

struct DirIter {
    DIR *d;
    char base[1024];
};

DirIter *dir_open(const char *path)
{
    if (!path || !*path) return NULL;
    DIR *d = opendir(path);
    if (!d) return NULL;
    DirIter *it = calloc(1, sizeof(*it));
    if (!it) { closedir(d); return NULL; }
    it->d = d;
    snprintf(it->base, sizeof(it->base), "%s", path);
    return it;
}

int dir_next(DirIter *it, const char **name, int *isdir)
{
    if (!it) return 0;
    struct dirent *e;
    while ((e = readdir(it->d)) != NULL) {
        if (name) *name = e->d_name;
        int d = -1;
#ifdef DT_DIR
        if (e->d_type == DT_DIR) d = 1;
        else if (e->d_type == DT_REG) d = 0;
#endif
        if (d < 0) {
            char full[2048];
            path_join(full, sizeof(full), it->base, e->d_name);
            struct stat st;
            if (stat(full, &st) != 0) continue;
            d = S_ISDIR(st.st_mode) ? 1 : (S_ISREG(st.st_mode) ? 0 : -1);
        }
        if (d < 0) continue;
        if (isdir) *isdir = d;
        return 1;
    }
    return 0;
}

void dir_close(DirIter *it)
{
    if (!it) return;
    closedir(it->d);
    free(it);
}

#endif
