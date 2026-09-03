#ifndef STYLUS_SCROBBLE_H
#define STYLUS_SCROBBLE_H

#include "library.h"

/* Registro de escuta em disco, no MESMO formato do aplicativo Android do
   Stylus (`stylus-scrobbles.tsv`) e do `stylus-phone`:
   uma linha por disco posto — `timestamp\tartista\tálbum\tpasta`.

   O computador junta esses arquivos com `stylus phone scrobbles`, então o
   Vita participa da memória da coleção (diário, "posto há", desgaste) sem
   precisar de chave de API do last.fm para nada. */

#define SCROBBLE_FILE "stylus-scrobbles.tsv"

/* Acrescenta a escuta de uma faixa ao registro local. Não scrobla a MESMA
   faixa duas vezes seguidas (mesma política do PC). timestamp é o relógio
   da Vita (epoch). Devolve 0 em sucesso, -1 em erro. */
int scrobble_log(const char *dir, const Track *t, long timestamp);

#endif
