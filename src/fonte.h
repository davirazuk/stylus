#ifndef STYLUS_FONTE_H
#define STYLUS_FONTE_H

#include <stdbool.h>
#include <stddef.h>

/* De onde os bytes vêm.
 *
 * O decodificador abria por CAMINHO, e por isso só sabia tocar arquivo. Para
 * tocar direto do Qobuz seria preciso ou baixar tudo antes (que é o que já
 * existe) ou escrever um segundo decodificador que fala HTTP — e um segundo
 * decodificador ao lado do primeiro é exatamente como as duas metades passam
 * a discordar.
 *
 * Então a mudança é embaixo: o decodificador passa a ler de uma FONTE, e a
 * fonte é um arquivo ou é a rede. Os cinco formatos continuam com um dono só.
 *
 * A fonte de rede tem um pedaço que a de arquivo não tem: ela BUSCA ADIANTE
 * numa thread, para dentro de um anel. Sem isso, cada leitura do
 * decodificador viraria uma espera de rede no meio do áudio — e o áudio do
 * Vita não espera: o que não chega a tempo sai como estalo. */

typedef struct Fonte Fonte;

Fonte *fonte_arquivo(const char *path);

/* `tam_dica` é o Content-Length quando já se sabe (o Qobuz manda), 0 quando
   não. Ajuda o decodificador a calcular a duração antes de ler tudo. */
Fonte *fonte_rede(const char *url);

void fonte_fecha(Fonte *f);

/* Lê até `n` bytes. Bloqueia enquanto a rede não trouxer, devolve 0 no fim e
   -1 em erro. */
long fonte_le(Fonte *f, void *buf, size_t n);

/* Posiciona. `whence` é SEEK_SET/CUR/END. Devolve a posição ou -1.
   Na rede, um salto para fora do que já está no anel REABRE a conexão com
   Range — caro, mas é o que permite procurar dentro de uma faixa. */
long long fonte_procura(Fonte *f, long long off, int whence);
long long fonte_posicao(const Fonte *f);

/* Tamanho total em bytes, ou -1 quando não se sabe. */
long long fonte_tamanho(const Fonte *f);

/* Chegou ao fim? */
bool fonte_fim(const Fonte *f);

/* É rede? A tela usa para dizer que aquilo depende do Wi-Fi. */
bool fonte_e_rede(const Fonte *f);

/* Quantos bytes já esperam no anel — a tela desenha isto como o "colchão".
   Um colchão que encolhe é a rede não dando conta, e é a única coisa que
   explica um estalo antes de ele acontecer. */
long fonte_colchao(const Fonte *f);

/* O tamanho do anel — o teto do colchão. A tela desenha a PROPORÇÃO, e sem
   este número ela teria de repetir a constante aqui de dentro. */
long fonte_colchao_max(const Fonte *f);

/* O que deu errado, "" quando nada. */
const char *fonte_erro(const Fonte *f);

#endif
