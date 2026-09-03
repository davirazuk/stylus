#ifndef STYLUS_PLAYLIST_H
#define STYLUS_PLAYLIST_H

#include <stddef.h>

#include "library.h"

#define PLAYLIST_NAME_MAX 128
#define PLAYLIST_DIR_DEFAULT "ux0:data/vitastylus/playlists"
#define PLAYLIST_NAME_PREFIX "Mix"

/* Uma playlist = lista ordenada de caminhos (M3U8). Cada linha é o caminho
   absoluto de uma faixa; caminhos relativos/`#` são ignorados na leitura. */
typedef struct {
    char name[PLAYLIST_NAME_MAX]; /* nome sem extensão, usado como base do arquivo */
    char **files;                 /* ponteiros para strings (donas) */
    int n;
    int cap;
} Playlist;

/* Carrega todas as playlists *.m3u do diretório. Devolve 0 em sucesso.
   Cria um array de Playlist (cada uma com seu nome e lista). */
int playlist_load_dir(Playlist **out, int *count, const char *dir);

/* Salva a playlist sob o nome `pl->name` em `dir` (arquivo <name>.m3u). */
int playlist_save(const Playlist *pl, const char *dir);

/* Compacta (remove linhas vazias/duplicadas contíguas? só vazias/`#`) */
void playlist_free(Playlist *pl, int count);

/* add / remove por índice. Devolve 0 ok, -1 erro. */
int playlist_add(Playlist *pl, const char *path);
int playlist_remove(Playlist *pl, int idx);

/* cria uma nova playlist com nome único (prefixo + N) a partir de uma lista
   de tracks e a anexa ao array (o caller é dono do array expandido).
   Devolve 0 ok, -1 erro. */
int playlist_new(Playlist **array, int *count, const char *name_prefix,
                 const Track *const *tracks, int n);

/* sanitiza um nome para uso como nome de arquivo (sem '/' etc.). Mutável. */
void playlist_sanitize_name(char *name);

/* apaga a playlist no índice `idx`: libera a entrada, desloca o resto do
   array e remove o .m3u em `dir`. Devolve 0 ok, -1 erro (sem/nada). */
int playlist_remove_file(Playlist *array, int *count, int idx, const char *dir);

#endif
