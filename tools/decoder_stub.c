/* O library.c pergunta ao decoder.c o que é tocável e lê tags por ele. O
   teste de host mede a VARREDURA — pastas, nomes, ordem — e para isso não
   precisa de decodificador nenhum; quem exercita os de verdade é o
   decoder_test.c, contra áudio de verdade. Este stub existe para o
   host_test.c linkar sem as bibliotecas de áudio, que nem toda máquina tem. */
#include "decoder.h"
#include <string.h>
#include <strings.h>

static int ext_is(const char *p, const char *e)
{
    size_t n = strlen(p), m = strlen(e);
    return n > m && strcasecmp(p + n - m, e) == 0;
}

DecKind dec_kind_of(const char *path)
{
    if (!path) return DEC_NONE;
    if (ext_is(path, ".mp3") || ext_is(path, ".mp2") ||
        ext_is(path, ".mp1") || ext_is(path, ".mpga")) return DEC_MP3;
    if (ext_is(path, ".flac"))                        return DEC_FLAC;
    if (ext_is(path, ".ogg") || ext_is(path, ".oga"))  return DEC_VORBIS;
    if (ext_is(path, ".opus"))                        return DEC_OPUS;
    if (ext_is(path, ".wav") || ext_is(path, ".wave")) return DEC_WAV;
    return DEC_NONE;
}

const char *dec_kind_name(DecKind k) { (void)k; return "—"; }
void dec_global_init(void) {}
void dec_global_exit(void) {}
void dec_tags_free(DecTags *t) { (void)t; }

int dec_probe(const char *path, DecTags *t, int want_cover)
{
    (void)path; (void)want_cover;
    if (t) { memset(t, 0, sizeof(*t)); t->number = -1; t->seconds = -1; }
    return -1;
}
