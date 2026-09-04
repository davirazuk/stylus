#ifndef STYLUS_NET_H
#define STYLUS_NET_H

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

#endif
