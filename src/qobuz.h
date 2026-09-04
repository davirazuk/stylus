#ifndef STYLUS_QOBUZ_H
#define STYLUS_QOBUZ_H

#include <stdbool.h>

/* Qobuz, DENTRO do aparelho.

   Antes isto era uma ferramenta de PC (tools/qobuz-vita.py): buscava,
   baixava e copiava para o cartão. Funcionava, e mesmo assim era o oposto do
   que este app quer ser — quem está com o Vita na mão não deveria precisar
   levantar e ligar um computador para pôr um disco novo.

   O que existe aqui: entrar na conta, buscar álbum, e BAIXAR (não tocar
   direto da rede). A escolha de baixar em vez de transmitir não é preguiça:
   o Vita perde o Wi-Fi ao suspender, e um app que só toca com rede é um app
   que para quando a tela apaga — justamente o que o resto deste programa
   passou o tempo todo tentando evitar. Baixado, o disco é um disco: toca
   offline, entra na estante, funciona em avião.

   As chaves (app_id e o segredo) são de quem usa, não deste app, e ficam no
   cartão em qobuz.config. NUNCA vão para o repositório. */

#define QOBUZ_CONFIG_FILE "qobuz.config"

/* Os formatos que o Qobuz entrega, e o que cada um custa em cartão.
   MP3 é o padrão de propósito: num Vita, 1 GB é muito, e a diferença entre
   320 kbps e FLAC num fone de aparelho de mão é bem menor que a diferença
   entre caber e não caber. */
typedef enum {
    QB_MP3  = 5,    /* MP3 320 kbps   ~7 MB por faixa  */
    QB_FLAC = 6,    /* FLAC 16/44,1   ~25 MB por faixa */
    QB_HIRES = 7    /* FLAC 24 bits até 96 kHz — grande, e o Vita reamostra */
} QobuzFormato;

typedef struct {
    char app_id[32];
    /* Uma LISTA separada por vírgula. O Qobuz publica vários segredos por
       app_id e só um assina — qual, muda com o tempo e não há como saber a
       não ser tentando. Guardar um só significa "funcionou no dia em que eu
       configurei". */
    char app_secret[256];
    char email[128];
    char token[128];     /* user_auth_token, depois do login */
    int  formato;        /* QobuzFormato preferido para baixar */
    bool configured;     /* tem app_id, segredo E token */
} QobuzConfig;

typedef struct {
    char id[32];
    char titulo[160];
    char artista[128];
    int  faixas;
    int  ano;
    bool hires;
} QobuzAlbum;

typedef struct {
    char id[32];
    char titulo[160];
    int  numero;
    int  segundos;
} QobuzFaixa;

void qobuz_config_load(QobuzConfig *cfg, const char *dir);
int  qobuz_config_save(const QobuzConfig *cfg, const char *dir);

/* Troca e-mail + senha por um token permanente. A senha não é guardada.
    0 entrou | -1 argumento vazio | -2 falta app_id/segredo
   -3 não falou com o servidor | -4 o Qobuz recusou                        */
int  qobuz_login(QobuzConfig *cfg, const char *email, const char *senha);

/* Busca álbuns. Devolve quantos escreveu em `out`, ou <0 em erro. */
int  qobuz_busca(const QobuzConfig *cfg, const char *termo,
                 QobuzAlbum *out, int max);

/* As faixas de um álbum. Devolve quantas escreveu, ou <0. */
int  qobuz_faixas(const QobuzConfig *cfg, const char *album_id,
                  QobuzFaixa *out, int max);

/* Baixa uma faixa para `destino`. `prog` pode ser NULL.
   0 ok | -1 erro de rede | -2 o Qobuz não deu URL (sem assinatura para este
   formato, ou a faixa não está disponível na região)                      */
int  qobuz_baixa(const QobuzConfig *cfg, const char *faixa_id, int formato,
                 const char *destino,
                 void (*prog)(void *ud, long feitos, long total), void *ud);

/* Quantos MB uma faixa deste formato costuma ocupar. Serve para a tela poder
   dizer "isto vai ocupar 240 MB" ANTES de ocupar. */
int  qobuz_mb_por_faixa(int formato);

/* --- expostos para o teste de host, porque são onde dá para errar --- */

/* A assinatura do track/getFileUrl: md5 dos parâmetros em ordem alfabética,
   concatenados sem separador, mais o segredo. Errar isto devolve "Invalid
   Request Signature" com tudo o mais aparentemente certo. */
void qobuz_assina(const char *secret, const char *faixa_id, int formato,
                  long ts, char out_md5[33]);

/* Tira `"chave":"valor"` de um JSON, procurando a partir de `de`. Devolve 1
   se achou. É um extrator, não um parser: basta para as respostas desta API
   e não carrega uma biblioteca de JSON para dentro de um VPK. */
int  qobuz_json_str(const char *json, const char *chave, char *out, int cap);
int  qobuz_json_int(const char *json, const char *chave, int *out);



/* ---------- baixar um álbum inteiro, em segundo plano ----------

   Um disco em FLAC são uns 400 MB e vários minutos de Wi-Fi. Fazer isso no
   laço de vídeo congelaria o app inteiro pelo tempo do download, com a
   agulha parada — e não há como distinguir isso de um travamento.

   Então: o pedido volta na hora e o trabalho acontece atrás. A tela lê o
   andamento com qobuz_job_estado e desenha; o resto do app continua tocando
   o que já estava tocando. */

typedef struct {
    bool ativo;
    bool ok;              /* terminou e deu certo */
    bool falhou;
    int  faixa;           /* 1..total */
    int  total;
    long bytes;           /* da faixa atual */
    long bytes_total;     /* -1 quando o servidor não diz */
    char titulo[160];     /* a faixa atual */
    char album[160];
    char erro[96];
} QobuzJob;

/* Começa a baixar. `dir` é a pasta de música onde o disco vai virar uma
   subpasta. Devolve 0 se começou, -1 se já havia um em curso ou faltou algo.
   Um de cada vez, de propósito: dois downloads simultâneos num Vita só
   dividem a mesma banda e enchem o cartão em paralelo. */
int  qobuz_baixa_album(const QobuzConfig *cfg, const QobuzAlbum *alb,
                       int formato, const char *dir);

/* Uma foto do andamento. Nunca bloqueia. */
void qobuz_job_estado(QobuzJob *out);

/* Pede para parar no fim da faixa atual. */
void qobuz_job_cancela(void);

/* Esquece o resultado do último download, para a tela poder sair do resumo
   e voltar à busca. Não faz nada enquanto houver um em curso. */
void qobuz_job_limpa(void);

/* ---------- buscar sem travar a tela ----------

   Uma busca leva um ou dois segundos de rede. Feita no laço de vídeo, o app
   fica parado esse tempo — logo depois de a pessoa apertar "buscar", que é
   exatamente o momento em que ela está olhando para ver se funcionou. Dois
   segundos de tela congelada ali não leem como "carregando", leem como
   travou. */
int  qobuz_busca_async(const QobuzConfig *cfg, const char *termo);

/* Copia o resultado (até `max`). `*ativo` diz se ainda está buscando e
   `*n` quantos vieram (-1 se a última busca falhou). */
void qobuz_busca_estado(QobuzAlbum *out, int max, int *n, bool *ativo);

#endif
