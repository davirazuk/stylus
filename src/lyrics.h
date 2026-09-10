#ifndef STYLUS_LYRICS_H
#define STYLUS_LYRICS_H

#include <stdbool.h>
#include <stddef.h>

/* A LETRA, no tempo. Um .lrc ao lado do arquivo de áudio.
 *
 * O desktop já lia isto; o Vita não. Um acervo grande costuma ter milhares
 * de .lrc que aqui não serviam para nada. */

#define LRC_MAX_LINES 400
#define LRC_TEXT_MAX 200

typedef struct {
    int  ms;                     /* momento, em milissegundos */
    char text[LRC_TEXT_MAX];
} LrcLine;

typedef struct {
    LrcLine lines[LRC_MAX_LINES];
    int  n;
    int  offset_ms;              /* o `[offset:±ms]` que quem sincronizou pôs */
    bool loaded;
    char for_path[1024];         /* de qual faixa esta letra é */
} Lyrics;

/* Procura o .lrc da faixa (mesmo nome, extensão trocada) e lê. Se não achar,
   tenta o lrclib.net com os metadados fornecidos e grava o resultado no
   cartão para offline. Sempre marca `loaded`: sem letra é uma resposta, não
   uma tentativa a repetir a cada quadro. artist/album/track podem ser NULL
   (a busca online fica desabilitada); duration_s <= 0 é omitido do pedido. */
void lyrics_load(Lyrics *l, const char *audio_path,
                 const char *artist, const char *album,
                 const char *track, int duration_s);

/* Qual linha está sendo cantada em `ms`. -1 antes da primeira.
   Busca binária: devolve a linha ATUAL, não a seguinte — o desktop errava
   isso e a letra ia uma linha adiantada, sempre. */
int lyrics_at(const Lyrics *l, int ms);

#endif
