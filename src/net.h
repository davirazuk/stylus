#ifndef STYLUS_NET_H
#define STYLUS_NET_H

#include <stddef.h>

/* HTTP pequenino e transportável:
   - no Vita usa sceNetHttp (módulos NET/HTTP/HTTPS/SSL já carregados em main);
   - no PC (build de teste, sem VitaSDK) usa libcurl, pra dar pra validar o
     caminho de rede aqui mesmo na máquina.

   Quem usa: a fila offline do last.fm (quando houver rede + credencial). */

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
