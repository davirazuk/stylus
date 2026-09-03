#ifndef STYLUS_RESUME_H
#define STYLUS_RESUME_H

#include <stdbool.h>

/* Ponto de continuação da sessão. Persistido em disco para o app voltar de
   onde estava quando o usuário retorna (o Vita suspende, mas pode ser
   encerrado pelo sistema). Sempre retoma em PAUSA — ninguém quer susto de som. */

#define RESUME_FILE "last_session"

typedef struct {
    char track_path[1024];  /* caminho COMPLETO da faixa (chave de busca) */
    int  position_sec;      /* posição em segundos na faixa */
    int  repeat;            /* 0=off 1=all 2=one */
    bool shuffle;
    bool valid;
} Resume;

/* Escreve o ponto de continuação. Devolve 0 ok, -1 erro. */
int resume_save(const char *dir, const Resume *r);

/* Lê o ponto de continuação; r->valid falso se não há/usável. Nunca falha. */
void resume_load(const char *dir, Resume *r);

#endif
