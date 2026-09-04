#ifndef STYLUS_DECODER_H
#define STYLUS_DECODER_H

#include <stdbool.h>
#include <stddef.h>

/* UM decodificador, cinco formatos.
 *
 * Antes o player era o mpg123 escrito por dentro dele: abrir, ler, procurar e
 * medir a duração eram chamadas de mpg123 espalhadas pelo player.c, e a
 * pergunta "eu sei tocar isto?" era uma lista de extensões noutro arquivo.
 * Acrescentar FLAC assim seria escrever um segundo player ao lado do
 * primeiro, e é exatamente assim que duas metades passam a discordar.
 *
 * A saída é SEMPRE int16 intercalado, porque a saída do Vita é: o
 * sceAudioOut aceita 16 bits com sinal e mais nada. Um FLAC de 24 bits é
 * reduzido aqui, e a tela DIZ isso — a tese do projeto é não mentir sobre o
 * caminho do sinal, não fingir que o aparelho faz o que não faz. */

typedef enum {
    DEC_NONE = 0,
    DEC_MP3,
    DEC_FLAC,
    DEC_VORBIS,
    DEC_OPUS,
    DEC_WAV
} DecKind;

typedef struct Decoder Decoder;

typedef struct {
    long rate;          /* taxa da SAÍDA */
    int  channels;
    int  bits_native;   /* profundidade do ARQUIVO (16, 24, 32...), 0 se n/d */
    long rate_native;   /* taxa do ARQUIVO — diferente da saída = reamostrado */
} DecFormat;

/* Metadados sem montar um decodificador inteiro. Campos vazios = ausentes. */
typedef struct {
    char title[256];
    char artist[256];
    char album[256];
    int  number;         /* -1 se ausente */
    int  seconds;        /* -1 se desconhecida */
    unsigned char *cover; /* malloc do chamador liberar; NULL se não houver */
    size_t cover_len;
} DecTags;

/* Este arquivo tem decodificador? Olha a EXTENSÃO — a pergunta é barata e é
   feita uma vez por arquivo na varredura. */
DecKind dec_kind_of(const char *path);
const char *dec_kind_name(DecKind k);

Decoder *dec_open(const char *path);
void     dec_close(Decoder *d);
void     dec_format(const Decoder *d, DecFormat *f);
DecKind  dec_kind(const Decoder *d);

/* Lê até `bytes` de PCM int16 intercalado. Devolve bytes escritos,
   0 no fim da faixa, -1 em erro. */
long dec_read(Decoder *d, void *buf, size_t bytes);

/* Posição e duração em QUADROS (amostras por canal). -1 = desconhecida. */
long long dec_tell(const Decoder *d);
long long dec_length(const Decoder *d);
long long dec_seek(Decoder *d, long long frame);  /* devolve onde parou, -1 erro */

/* Tags + capa embutida. `want_cover` != 0 preenche tags->cover. 0 ok, -1 erro. */
int  dec_probe(const char *path, DecTags *tags, int want_cover);
void dec_tags_free(DecTags *tags);

/* Teto da taxa de SAÍDA, em Hz (0 = sem teto). É propriedade do aparelho, não
   do arquivo: o SDL2 do Vita só abre a porta BGM — a que segura o som dentro
   de um jogo — com taxa <= 47999. Ver a nota grande no decoder.c. */
void dec_set_max_rate(long hz);
long dec_max_rate(void);

void dec_global_init(void);
void dec_global_exit(void);

#endif
