#ifndef STYLUS_SOUNDCLOUD_H
#define STYLUS_SOUNDCLOUD_H

#include <stdbool.h>

/* SoundCloud como FONTE DE STREAMING do aparelho.
 *
 * POR QUE ELE, E NÃO OS OUTROS PRIMEIRO
 * -------------------------------------
 * O que o `player.c` precisa de uma faixa da rede é uma coisa só: uma URL
 * HTTPS comum para um arquivo que o `decoder.c` saiba decodificar. O
 * `fonte.c` faz o resto — anel, curl, decodificação, reamostragem — e já faz
 * isso pelo Qobuz há semanas.
 *
 * Medido nas extensões do SpotiFLAC, uma a uma:
 *
 *   SoundCloud  MP3 128 progressivo em cf-media.sndcdn.com   <- arquivo comum
 *   YouTube     o Cobalt devolve .opus/.m4a/.mp3             <- arquivo comum
 *   Tidal       manifesto BTS dá FLAC direto; ou DASH+XML    <- metade
 *   Deezer      cifrado em Blowfish                          <- precisa cifra
 *   Amazon      MP4 cifrado (CENC/AES-CTR), eac3/ac4/flac    <- cifra + demux
 *
 * O SoundCloud é o único que não precisa de NADA novo no aparelho: nem cifra,
 * nem demultiplexador, nem servidor de terceiro. 44,1 kHz passa no teto de
 * 47999 Hz da porta BGM e o MP3 já toca. É a fonte que se acrescenta sem
 * arriscar nada — e as outras entram depois, nos mesmos trilhos.
 *
 * O CLIENT_ID VEM DO CARTÃO, e isso é deliberado.
 * Ele está publicado nos bundles JavaScript do soundcloud.com, e raspá-lo
 * exige baixar ~1,2 MB e varrer com expressão regular. Isso é código escrito
 * às cegas num aparelho sem depurador, para uma coisa que o PC faz em dois
 * segundos — o mesmo raciocínio que fez as chaves do Qobuz virarem
 * `qobuz.config`. O `tools/soundcloud-chaves.py` escreve
 * `soundcloud.config` a cada `pro-cartao.sh`.
 */

typedef struct {
    char client_id[64];
    int  ok;                  /* há client_id utilizável */
} ScConfig;

/* Lê `<dir>/soundcloud.config`. Devolve 1 se achou um client_id. */
int  sc_config_load(ScConfig *c, const char *dir);

/* Uma faixa achada na busca. `id` vai sem o prefixo `sc:` — quem grava numa
   Track é que o põe (ver o `resolve_remote` do main.c). */
typedef struct {
    char id[24];
    char artista[96];
    char titulo[160];
    int  segundos;
} ScTrack;

/* BUSCA. Devolve quantas faixas escreveu em `out`, ou -1 (o motivo fica no
   `sc_motivo`). Sem isto o resto deste arquivo era encanamento sem torneira:
   o app sabia TOCAR uma faixa `sc:`, e não havia como uma chegar até ele.
   Chamada de uma thread de rede — ver o qobuz.c, mesma dança. */
int  sc_busca(const ScConfig *c, const char *termo, ScTrack *out, int max);

/* A leitura de UMA leva de resultados, exposta para o teste — pelo mesmo
   motivo do `sc_acha_progressiva_dbg`: o que ela tem de acertar (descartar a
   prévia) não aparece na tela, aparece no silêncio de trinta segundos. */
int  sc_le_busca_dbg(const char *json, ScTrack *out, int max);

#define SC_MAX_RES 20

/* A BUSCA SEM SEGURAR O DESENHO. Mesma dança do `qobuz_busca_async`: sobe uma
   thread com a PILHA_REDE e a PRIO_REDE do net.h (os dois números carregam o
   defeito 0x80028023 que já parou toda a rede deste app — ver a nota lá).

   Devolve 0 quando a busca FOI DISPARADA. Todo -1 grava o motivo no
   `sc_motivo()`: um retorno ignorado aqui é como a busca do Qobuz passou
   semanas "não achando nada" sem que nada dissesse por quê. */
int  sc_busca_async(const ScConfig *c, const char *termo);

/* O que a thread já produziu. `ativo` diz se ela ainda está correndo; `n` vem
   negativo quando a busca falhou — a tela distingue "nada achado" de "não deu
   para perguntar", que são coisas diferentes para quem está olhando. */
void sc_busca_estado(ScTrack *out, int max, int *n, bool *ativo);

/* A URL tocável de uma faixa, resolvida na hora (vale poucos minutos).
   0 = deu certo. `out` recebe a URL do CDN. */
int  sc_url(const ScConfig *c, const char *track_id, char *out, int cap);

/* Por que a última resolução falhou, em inglês, para a tela. */
const char *sc_motivo(void);

/* A ESCOLHA DA TRANSCODIFICAÇÃO, exposta para o teste.
 *
 * Exposta pelo mesmo motivo do `ui_view_dbg`: é uma varredura escrita à mão
 * sobre JSON de verdade, e o que ela tem de acertar não aparece na tela. A
 * resposta REAL de uma faixa traz quatro transcodificações — TRÊS delas HLS,
 * e UMA DAS HLS é `audio/mpeg`. Quem procurasse "audio/mpeg" pegaria uma
 * playlist e entregaria texto ao decodificador de MP3.
 *
 * Devolve 1 e escreve a URL em `out` quando acha uma progressiva que não seja
 * prévia. */
int sc_acha_progressiva_dbg(const char *json, char *out, int cap);

#endif
