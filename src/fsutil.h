#ifndef STYLUS_FSUTIL_H
#define STYLUS_FSUTIL_H

#include <stddef.h>

/* Junta pai + filho SEM produzir "//". O Vita não é o Linux aqui: o
   sceIoGetstat recusa caminho com barra dupla, e um root escrito
   "ux0:music/" (com a barra, que é como a constante nasceu) montava
   "ux0:music//Artista" para TODA pasta — a varredura inteira via zero
   arquivo e nada explicava. Devolve o comprimento escrito. */
size_t path_join(char *out, size_t cap, const char *parent, const char *child);

/* Tira barras do fim (menos a que faz parte de "ux0:/"), no lugar. */
void path_trim_slash(char *s);

/* mkdir -p. O `mkdir` cru não cria pai: "ux0:data/vitastylus/playlists"
   falhava inteiro porque "ux0:data/vitastylus" não existia, e com ele
   falhavam em silêncio o histórico, o scrobble e o ponto de continuação.
   Devolve 0 se o diretório existe ao final. */
int mkdir_p(const char *path);

/* 1 se o caminho abre como diretório. */
int dir_exists(const char *path);

/* ---- percorrer uma pasta ----

   POR QUE ISTO NÃO USA opendir() NO VITA

   O app rodou no aparelho e deixou um diagnóstico no cartão:

       root=ux0:music
       opendir(ux0:music)=NULL
       opendir(ux0:music/)=NULL
       opendir(ux0:/music)=NULL
       opendir(data)=OK
       nalbums=0 ntracks=0

   As TRÊS formas com prefixo de dispositivo falharam; a relativa abriu. E
   no mesmo arranque o `mkdir("ux0:data/vitastylus")` e o `fopen` daquele
   próprio arquivo funcionaram — ou seja, o prefixo `ux0:` não é o problema
   para o resto da libc, só para o opendir. Seja qual for a causa exata na
   tradução de caminho do newlib, ela é evitável: o `sceIoDopen` é a API do
   sistema, aceita `ux0:music` sem ambiguidade, e o `sceIoDread` já devolve
   o stat de cada entrada — o que de quebra dispensa a chamada de `stat`
   separada, que era onde a barra dupla mordia.

   No PC continua sendo opendir/readdir, que é o que existe lá. */
typedef struct DirIter DirIter;

DirIter *dir_open(const char *path);
/* Próxima entrada. Devolve 0 quando acaba. `*isdir` diz o que é.
   `name` aponta para memória do iterador: vale até a próxima chamada. */
int      dir_next(DirIter *it, const char **name, int *isdir);
void     dir_close(DirIter *it);

#endif
