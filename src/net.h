#ifndef STYLUS_NET_H
#define STYLUS_NET_H

#include <stddef.h>

/* HTTP pequenino e transportável:
   - no Vita usa sceNetHttp (módulos NET/HTTP/HTTPS/SSL já carregados em main);
   - no PC (build de teste, sem VitaSDK) usa libcurl, pra dar pra validar o
     caminho de rede aqui mesmo na máquina.

   Quem usa: a fila offline do last.fm (quando houver rede + credencial). */

/* ---------- POR QUE A FALHA TEM NÚMERO PRÓPRIO ----------

   Todo caminho de erro devolvia -1: pilha de rede que não subiu, Wi-Fi
   desligado, conexão recusada, handshake de TLS reprovado, status ilegível.
   A tela do Qobuz escrevia "the network call failed (net_get -1)" para as
   cinco — e -1 não distingue nada. O comentário do qobuz.c já dizia que o
   número ia junto porque é "a diferença entre consertar e adivinhar de
   novo"; só que o número era sempre o mesmo, e portanto adivinhava-se
   sempre. Estes separam "liga o Wi-Fi" de "o TLS deste servidor é novo
   demais para a pilha do aparelho", que têm consertos opostos. */
#define NET_E_GERAL    -1   /* argumento inválido ou causa não classificada */
#define NET_E_MODULO   -2   /* a pilha de rede não subiu (sysmodule/http)   */
#define NET_E_SEMLINK  -3   /* não há Wi-Fi associado AGORA                 */
#define NET_E_CONN     -4   /* não abriu a conexão: URL, DNS, rota          */
#define NET_E_REQ      -5   /* não montou o pedido                          */
#define NET_E_ENVIO    -6   /* não saiu — é AQUI que mora o handshake TLS   */
#define NET_E_STATUS   -7   /* respondeu, mas sem status legível            */
#define NET_E_HTTP     -8   /* status fora da faixa aceita (5xx)            */

/* Frase curta sobre a ÚLTIMA falha, em inglês (vai para a tela), mais o
   código cru do sistema — no Vita o sceHttp* devolve 0x8043xxxx, e é esse
   número que se procura quando a frase não basta. Valem até a chamada
   seguinte; `net_erro_sistema` devolve 0 quando não há código cru. */
const char *net_motivo(void);
int         net_erro_sistema(void);
int         net_http_ultimo(void);

/* ═══ AS THREADS QUE FALAM COM A REDE ═════════════════════════════════════

   A PILHA. 256 KB bastavam quando quem fazia o handshake era o sceHttp: o
   trabalho pesado — cadeia de certificados, verificação, cifras — acontecia
   DENTRO do módulo do sistema, não na nossa pilha. Com o curl+OpenSSL esse
   trabalho passou a rodar AQUI, e OpenSSL é guloso de pilha. Uma thread que
   estoura a pilha no Vita não devolve erro: ela morre, e leva junto o rastro
   que ia explicar o que houve — foi por isso que o `rede.txt` não apareceu em
   três versões seguidas, mesmo com a busca falhando.

   1 MB é folgado de propósito: são threads que existem uma de cada vez e
   vivem segundos.

   A PRIORIDADE — e por que não é +32. Era `0x10000100 + 32`, e o aparelho
   respondia **0x80028023** (SCE_KERNEL_ERROR_ILLEGAL_PRIORITY) em TODA
   criação de thread. O 0x10000100 é a prioridade padrão do usuário numa forma
   RELATIVA, e o deslocamento aceito vai só até ±31: 0x100 + 32 cai um passo
   fora da faixa. A chamada falhava, o `qobuz_busca_async` voltava -1 em
   silêncio, e a tela escrevia "nothing found".

   Foi ESSE o motivo de a busca do Qobuz nunca ter funcionado — não a API, não
   o TLS, não o parser, não o teclado — e valia para as quatro threads. +16
   mantém a intenção (um degrau ABAIXO do padrão, para não disputar com o
   áudio e a tela) com folga dentro da faixa.

   Moram AQUI, e não no qobuz.c, porque agora há mais de uma fonte de rede: um
   segundo módulo que redescobrisse estes números redescobriria o defeito. */
#define PILHA_REDE (1024 * 1024)
#define PRIO_REDE  (0x10000100 + 16)

/* Percent-encoding de um termo para pôr numa query string. Mora aqui porque
   é de REDE e porque tem mais de um usuário: o Qobuz e o SoundCloud montam a
   mesma busca com a mesma regra, e a segunda cópia de uma regra é por onde
   elas começam a divergir. */
void net_urlenc(const char *s, char *out, size_t cap);

/* Faz um POST urlencoded em `url` com corpo `body`. Em sucesso (HTTP 2xx)
   devolve 0 e copia o corpo da resposta para `resp` (limitado a `resplen-1`);
   em erro de rede/HTTP devolve -1. */
int net_post(const char *url, const char *body, char *resp, int resplen);

/* Um GET. `headers` é uma lista terminada em NULL de linhas "Nome: valor"
   (pode ser NULL). O corpo da resposta vai para `resp`, cortado em
   `resplen-1`. 0 em sucesso, -1 em erro de rede/HTTP.

   Existe separado do POST porque a API do Qobuz é GET com token em cabeçalho
   — e enfiar cabeçalho e método no net_post transformaria a função que o
   last.fm usa numa navalha suíça que ninguém lê. */
int net_get(const char *url, const char *const *headers, char *resp, int resplen);

/* Baixa `url` para o arquivo `path`. Chama `prog` de vez em quando com os
   bytes já gravados e o total (ou -1 quando o servidor não diz) — sem isso a
   tela fica parada por minutos num arquivo FLAC e parece travada.

   Grava num ".parcial" e só renomeia no fim: um download interrompido não
   pode virar um arquivo meio escrito que a estante depois tenta tocar.
   0 em sucesso, -1 em erro. */
int net_download(const char *url, const char *const *headers, const char *path,
                 void (*prog)(void *ud, long feitos, long total), void *ud);

/* ---------- ler um GET AOS POUCOS ----------

   O `net_download` baixa até o fim antes de devolver, e é o que serve para
   guardar um disco no cartão. Não serve para TOCAR pela rede: aí os bytes têm
   de chegar ao decodificador enquanto o resto ainda vem.

   POR QUE ISTO MORA AQUI, e não num HTTP próprio da fonte de rede: porque já
   existe um dono de HTTP neste app, e é este arquivo. A primeira versão da
   fonte trouxe libcurl junto e apontou o `CAINFO` para um `app0:cacert.pem`
   que não está no VPK — no aparelho todo HTTPS falharia na verificação, e o
   app passaria a ter duas pilhas de rede para inicializar e depurar. O
   sceHttp daqui já está de pé, já fala com o Qobuz e já resolve o problema
   dos certificados de 2011 (ver a nota lá em cima).

   `de` é o primeiro byte desejado (vira `Range: bytes=de-`), 0 para o começo.
   Em `*total` vai o tamanho do RECURSO INTEIRO — não o do pedaço —, ou -1
   quando o servidor não diz. `erro` recebe uma frase curta quando falha. */
typedef struct NetStream NetStream;

NetStream *net_stream_open(const char *url, const char *const *headers,
                           long long de, long long *total,
                           char *erro, int erolen);

/* Lê até `n` bytes. Devolve quantos, 0 no fim, -1 em erro de rede. */
long net_stream_read(NetStream *s, void *buf, size_t n);

void net_stream_close(NetStream *s);

#endif
