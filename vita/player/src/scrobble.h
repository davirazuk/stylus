#ifndef STYLUS_SCROBBLE_H
#define STYLUS_SCROBBLE_H

#include "library.h"

/* Banco de escuta STANDALONE do Vita.

   Antes este módulo gravava um TSV pensado para o PC juntar com
   `stylus phone scrobbles` — ou seja, a memória da coleção só virava
   estatística depois do computador processar. Isso acoplava o Vita ao PC.

   Agora o Vita é dono do próprio histórico: cada escuta vira uma linha em
   `stylus-scrobbles.tsv` (`timestamp\tpath\tartista\tálbum`), e a memória é
   agregada AQUI, em memória, e mostrada nas telas Histórico e Mais tocadas
   DENTRO do app. Nada depende de PC nem de rede para funcionar.

   O last.fm (rede) é uma camada separada e opcional: o banco alimenta a fila
   `lastfm-queue.tsv`, e o upload só sai se houver rede + credencial. Sem
   rede, a escuta continua registrada neste banco do mesmo jeito. */

#define SCROBBLE_FILE "stylus-scrobbles.tsv"

typedef struct {
    char *path;        /* caminho da faixa (string dona) */
    int   count;       /* vezes que a faixa foi posta */
    long  last_ts;     /* último toque (epoch) */
} ScrobTrack;

typedef struct {
    Album *album;      /* ponteiro resolvido na biblioteca */
    int    count;      /* toques somados das faixas */
    long   last_ts;    /* toque mais recente do álbum */
} ScrobAlbum;

typedef struct {
    char  path[1024];
    long  ts;
} ScrobRecent;

typedef struct Scrob {
    ScrobTrack *tracks;
    int ntracks, cap_tracks;
    ScrobAlbum *albums;
    int nalbums, cap_albums;
    /* últimos toques (ordem do mais recente para o mais antigo) */
    ScrobRecent *recent;
    int nrecent, cap_recent;
    int recent_max;              /* teto de entradas do histórico recente */
} Scrob;

/* Carrega o diário `dir/stylus-scrobbles.tsv` e agrega em memória (resolve os
   álbuns pela biblioteca; paths órfãs só alimentam o recente).
   Nunca falha: sem arquivo = banco vazio. */
void scrob_load(Scrob *s, Library *lib, const char *dir);

/* Acrescenta uma escuta (uma linha no diário) e atualiza as métricas.
   Não regista a MESMA faixa duas vezes no MESMO segundo. Devolve 0 ok. */
int scrob_log(Scrob *s, const char *dir, const Track *t, long timestamp);

/* Só acrescenta a linha no arquivo, SEM mexer na memória. Seguro para chamar
   da thread do player; a thread da UI re-agrega com scrob_load quando a flag
   de sujeira estiver marcada. Devolve 0 ok. */
int scrob_append_file(const char *dir, const Track *t, long timestamp);

/* métricas */
int  scrob_track_count(const Scrob *s, const Track *t);
int  scrob_album_count(const Scrob *s, Album *a);
long scrob_album_last(const Scrob *s, Album *a);

/* top álbuns por número de toques, preenchendo um vetor ordenado (TÍTULOS)
   de ponteiros para os álbuns do banco. devolve quantos entrou. */
int scrob_top_albums(const Scrob *s, /**/ Album **out, int max);

/* últimas escutas, do mais recente para o mais antigo (caminhos + ts).
   devolve quantos entrou (≤ `max`). */
int scrob_recent(const Scrob *s, const char **paths, long *ts, int max);

void scrob_free(Scrob *s);

#endif
