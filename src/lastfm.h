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

/* Entra na conta a partir do APARELHO: troca usuário+senha por uma chave de
   sessão (auth.getMobileSession) e preenche cfg->sk e cfg->username. A senha
   não é guardada. Chame lastfm_config_save depois para persistir.

    0  entrou
   -1  argumento vazio
   -2  falta api_key/api_secret (a pessoa ainda não pôs as chaves da API)
   -3  não falou com o servidor (sem Wi-Fi, ou a rede não subiu)
   -4  o last.fm recusou usuário ou senha                                  */
int lastfm_login(LastfmConfig *cfg, const char *user, const char *pass);

/* Enfileira uma escuta (offline-first): sempre grava localmente. 0 ok. */
int lastfm_enqueue(const char *dir, const Track *t, long timestamp, int duration);

/* Quantas escutas esperam upload. */
int lastfm_queue_size(const char *dir);

/* Tenta esvaziar a fila. Sem configuração → só conta (offline). Com
   configuração e rede, consome até a primeira falha (mantendo o resto).
   Devolve quantos subiu. */
int lastfm_sync(const LastfmConfig *cfg, const char *dir);

/* Manda a fila subir SEM esperar: volta na hora, o envio acontece atrás.
   É isto que o app chama ao fim de cada faixa — `lastfm_sync` direto
   seguraria o desenho pelo tempo do timeout de rede. Não faz nada quando a
   fila está vazia ou não há credencial, e portanto não acorda a rede à toa. */
void lastfm_sync_async(const char *dir);

#endif
