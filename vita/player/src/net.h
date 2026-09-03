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

#endif
