#ifndef STYLUS_LASTFM_H
#define STYLUS_LASTFM_H

#include <stdbool.h>

#include "library.h"

/* Scrobble offline do last.fm, STANDALONE e acessível.

   A escuta vai SEMPRE para o banco local (scrobble.c), independente de rede.
   Este módulo é a CAMADA OPCIONAL de last.fm: mantém uma fila
   (`lastfm-queue.tsv`) em disco; quando há credencial E rede, a fila é
   consumida por `track.scrobble`. Sem rede ou sem credencial, a fila fica
   intacta e a escuta não se perde — sai no primeiro sync bem-sucedido. */

#define LASTFM_QUEUE_FILE  "lastfm-queue.tsv"
#define LASTFM_CONFIG_FILE "lastfm.config"

typedef struct {
    char api_key[128];
    char api_secret[64];
    char sk[64];         /* chave de sessão (após login no PC) */
    char username[128];
    bool configured;
} LastfmConfig;

/* Lê a configuração `dir/lastfm.config` (api_key, api_secret, sk).
   Nunca falha: sem arquivo ou incompleta → configured=false. */
void lastfm_config_load(LastfmConfig *cfg, const char *dir);

/* Grava a configuração (para o usuário pôr credenciais via PC). 0 ok. */
int lastfm_config_save(const LastfmConfig *cfg, const char *dir);

/* Enfileira uma escuta (offline-first): sempre grava localmente. 0 ok. */
int lastfm_enqueue(const char *dir, const Track *t, long timestamp, int duration);

/* Quantas escutas esperam upload. */
int lastfm_queue_size(const char *dir);

/* Tenta esvaziar a fila. Sem configuração → só conta (offline). Com
   configuração e rede, consome até a primeira falha (mantendo o resto).
   Devolve quantos subiu. */
int lastfm_sync(const LastfmConfig *cfg, const char *dir);

#endif
