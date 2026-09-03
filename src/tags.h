#ifndef STYLUS_TAGS_H
#define STYLUS_TAGS_H

#include <stddef.h>

/* Extrai tags + capa embutida de um mp3 com mpg123. Buffers:
   title/artist/album: preenchidos se encontrados (senão ficam "").
   number: -1 se ausente. seconds: -1 se desconhecida.
   Se *cover não for NULL e cover_cap > 0, copia a capa (front cover APIC)
   e ajusta *cover_len. Devolve 0 em sucesso, -1 em erro.
*/
void tags_init(void);  /* chama uma vez (mpg123 global) */
void tags_exit(void);

int tags_read(const char *path,
              char *title, size_t title_cap,
              char *artist, size_t artist_cap,
              char *album, size_t album_cap,
              int *number, int *seconds,
              unsigned char *cover, size_t cover_cap, size_t *cover_len,
              int want_cover);

#endif
