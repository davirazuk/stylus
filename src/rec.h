#ifndef STYLUS_REC_H
#define STYLUS_REC_H

#include "library.h"

#define REC_HISTORY_DIR_DEFAULT "ux0:data/vitastylus"
#define REC_HISTORY_FILE "history.txt"

/* Recomendação baseada em conteúdo (sem colaboração).
   Guarda, por caminho de faixa, quantas vezes ela foi COMPLETADA (>=50%).
   Persistido em texto: uma linha "path<TAB>count" por faixa. Sobrevive a
   re-varreduras da biblioteca (chave é o caminho, não o endereço). */

typedef struct {
    char **paths;   /* donos */
    int  *counts;
    int n;
    int cap;
} Rec;

typedef struct {
    char artist[256];
    int aff;
} ArtistAff;

/* Carrega `dir/history.txt`. Nunca falha: sem arquivo = histórico vazio. */
void rec_load(Rec *r, const char *dir);

/* Marca `path` como completado mais uma vez e persiste em `dir/history.txt`. */
void rec_play(Rec *r, const char *path, const char *dir);

/* completações de um track; 0 = nunca ouvido */
int rec_count(const Rec *r, const Track *t);

/* 1 se o álbum não teve nenhuma faixa completada */
int rec_album_unheard(const Rec *r, const Album *a);

/* afinidade de um álbum = soma de completações de suas faixas
   (ponderadas pelo rank de recência p/ quem quiser refinar depois) */
int rec_album_affinity(const Rec *r, const Album *a);

/* Monta uma lista de faixas "recomendada" (nunca-ouvido primeiro, ponderado
   pela afinidade dos artistas que a pessoa mais ouviu). Preenche `out` (vec
   de até `max` faixas) e ajusta *n. Não copia os tracks. */
void rec_build_list(const Rec *r, Library *lib, const Track **out, int *n, int max);

void rec_free(Rec *r);

#endif
