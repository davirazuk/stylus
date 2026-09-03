/* O leitor de tags de verdade é o mpg123, e um MP3 de mentira não prova nada
   sobre ele. O teste de host mede a VARREDURA; este stub existe só para o
   library.c linkar sem a biblioteca. */
#include "tags.h"
#include <string.h>

void tags_init(void) {}
void tags_exit(void) {}

int tags_read(const char *path,
              char *title, size_t title_cap,
              char *artist, size_t artist_cap,
              char *album, size_t album_cap,
              int *number, int *seconds,
              unsigned char *cover, size_t cover_cap, size_t *cover_len,
              int want_cover)
{
    (void)path; (void)cover; (void)cover_cap; (void)want_cover;
    if (title && title_cap) title[0] = '\0';
    if (artist && artist_cap) artist[0] = '\0';
    if (album && album_cap) album[0] = '\0';
    if (number) *number = -1;
    if (seconds) *seconds = -1;
    if (cover_len) *cover_len = 0;
    return -1;
}
