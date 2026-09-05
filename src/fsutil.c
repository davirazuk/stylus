#include "fsutil.h"

#include <dirent.h>
#include <string.h>
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>

#ifdef __vita__
/* Aqui em cima, e não junto do DirIter lá embaixo: o dir_mtime também usa o
   SceIoStat, e ele vem antes no arquivo. */
#include <psp2/io/dirent.h>
#include <psp2/io/stat.h>
#endif

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

void path_normalize(char *s)
{
    /* Alguns firmwares/SD2VITA precisam da barra depois dos dois-pontos:
       "ux0:music" não abre, mas "ux0:/music" abre. Se o caminho tem
       "algo:" seguido de algo que NÃO é barra, insere a barra. */
    if (!s) return;
    char *colon = NULL;
    for (char *p = s; *p; p++)
        if (*p == ':') { colon = p; break; }
    if (!colon) return;
    char *after = colon + 1;
    if (*after == '/' || *after == '\0') return;   /* já tem barra ou é só o device */
    size_t len = strlen(after);
    memmove(after + 1, after, len + 1);
    *after = '/';
}

int path_outra_forma(char *out, size_t cap, const char *path)
{
    if (!out || !cap || !path) return 0;
    const char *colon = strchr(path, ':');
    if (!colon) return 0;                    /* sem "dev:" não há outra forma */
    const char *after = colon + 1;
    if (!*after) return 0;                   /* "ux0:" é só o dispositivo */

    size_t n = strlen(path);
    if (*after == '/') {
        /* "ux0:/music" -> "ux0:music". Só se sobrar caminho depois da barra:
           "ux0:/" inteiro é um caminho, e tirar a barra deixaria o device. */
        if (!after[1]) return 0;
        if (n >= cap) return 0;
        size_t pre = (size_t)(after - path);  /* inclui os dois-pontos */
        memcpy(out, path, pre);
        memcpy(out + pre, after + 1, n - pre - 1 + 1);
        return 1;
    }
    /* "ux0:music" -> "ux0:/music" */
    if (n + 2 > cap) return 0;
    memcpy(out, path, n + 1);
    path_normalize(out);
    return 1;
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

long long dir_mtime(const char *path)
{
    if (!path || !path[0]) return -1;
#ifdef __vita__
    SceIoStat st;
    memset(&st, 0, sizeof(st));
    if (sceIoGetstat(path, &st) < 0) {
        /* a mesma dúvida de grafia do dir_open_err vale aqui */
        char alt[1024];
        if (!path_outra_forma(alt, sizeof(alt), path)) return -1;
        if (sceIoGetstat(alt, &st) < 0) return -1;
    }
    /* SceDateTime não é epoch; o que importa é COMPARAR com o valor guardado
       antes, então qualquer codificação estável serve. */
    return ((long long)st.st_mtime.year   << 40) |
           ((long long)st.st_mtime.month  << 36) |
           ((long long)st.st_mtime.day    << 31) |
           ((long long)st.st_mtime.hour   << 26) |
           ((long long)st.st_mtime.minute << 20) |
           ((long long)st.st_mtime.second << 14) |
           ((long long)st.st_mtime.microsecond / 1000);
#else
    struct stat st;
    if (stat(path, &st) != 0) return -1;
    return (long long)st.st_mtime;
#endif
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

DirIter *dir_open(const char *path) { return dir_open_err(path, NULL); }


#ifdef __vita__

struct DirIter {
    SceUID fd;
    SceIoDirent ent;
};

DirIter *dir_open_err(const char *path, int *err)
{
    if (err) *err = 0;
    if (!path || !*path) return NULL;

    /* AS DUAS FORMAS, e não uma aposta.

       SINTOMA: o relatório que o app deixou no cartão dizia que "ux0:music"
       não abria — e no MESMO arranque "ux0:/data" abria. As cinco raízes
       palpitadas eram todas sem a barra depois dos dois-pontos; a única que
       abriu foi a que a descoberta montou COM a barra. Resultado: a estante
       adotava a pasta de assets de um jogo e a coleção inteira (3.728
       arquivos em ux0:music) ficava invisível.

       Aqui não se decide qual forma este firmware prefere: tenta-se a que
       veio e, se falhar, a outra. Fica no dir_open porque assim vale para
       TODA pasta — as subpastas da varredura e a sondagem da descoberta
       também — e não só para as raízes. Normalizar na entrada consertaria
       menos e ainda mudaria o caminho que a tela mostra. */
    SceUID fd = sceIoDopen(path);
    if (fd < 0) {
        char alt[1024];
        if (path_outra_forma(alt, sizeof(alt), path)) {
            SceUID f2 = sceIoDopen(alt);
            if (f2 >= 0) fd = f2;
        }
    }
    if (fd < 0) { if (err) *err = (int)fd; return NULL; }
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

DirIter *dir_open_err(const char *path, int *err)
{
    if (err) *err = 0;
    if (!path || !*path) return NULL;
    DIR *d = opendir(path);
    if (!d) { if (err) *err = errno; return NULL; }
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
