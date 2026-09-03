#include "fsutil.h"

#include <dirent.h>
#include <string.h>
#include <sys/stat.h>

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
    if (!path || !path[0]) return 0;
    DIR *d = opendir(path);
    if (!d) return 0;
    closedir(d);
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
