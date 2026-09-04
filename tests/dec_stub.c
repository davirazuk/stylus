/* O decoder de verdade arrasta mpg123, libFLAC, vorbis e opus. Um teste de
 * ESTANTE não precisa de nenhum deles: o que ele mede é achar pasta e
 * ordenar faixa. Estes tocos deixam o teste linkar em segundos em vez de
 * exigir a árvore de codecs inteira na máquina de quem for rodá-lo.
 *
 * dec_kind_of é o único com comportamento, porque a estante o usa para
 * decidir se sabe tocar o arquivo — devolver "não sei" para tudo faria os
 * discos entrarem com ndecodable=0 e mascararia o que se quer medir.
 */
#include <string.h>

#include "decoder.h"

DecKind dec_kind_of(const char *path)
{
    const char *p = path ? strrchr(path, '.') : NULL;
    if (!p) return DEC_NONE;
    if (!strcasecmp(p, ".mp3")) return DEC_MP3;
    if (!strcasecmp(p, ".flac")) return DEC_FLAC;
    if (!strcasecmp(p, ".ogg")) return DEC_VORBIS;
    if (!strcasecmp(p, ".opus")) return DEC_OPUS;
    if (!strcasecmp(p, ".wav")) return DEC_WAV;
    return DEC_NONE;
}

int  dec_probe(const char *path, DecTags *tags, int want_cover)
{
    (void)path; (void)want_cover;
    if (tags) memset(tags, 0, sizeof(*tags));
    return -1;                       /* sem tags: a estante cai no nome do arquivo */
}
void dec_tags_free(DecTags *tags) { (void)tags; }
void dec_global_exit(void) { }
