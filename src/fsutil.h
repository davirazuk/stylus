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

#endif
