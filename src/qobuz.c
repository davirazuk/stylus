#include "qobuz.h"
#include "decoder.h"

#include "md5.h"
#include "net.h"
#include "paths.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define QB_API "https://www.qobuz.com/api.json/0.2/"

/* PILHA_REDE e PRIO_REDE mudaram de casa para o `net.h` quando o SoundCloud
   passou a criar a própria thread de busca. Os dois números carregam um
   defeito que já custou uma sessão inteira (o 0x80028023), e um segundo
   módulo que os redescobrisse por conta redescobriria o defeito junto. */


/* ---------- config ---------- */

void qobuz_config_load(QobuzConfig *cfg, const char *dir)
{
    memset(cfg, 0, sizeof(*cfg));
    cfg->formato = QB_MP3;
    if (!dir) return;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, QOBUZ_CONFIG_FILE);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        char *v = eq + 1;
        size_t vl = strlen(v);
        while (vl && (v[vl - 1] == '\n' || v[vl - 1] == '\r')) v[--vl] = '\0';
        if (!strcmp(line, "app_id"))          snprintf(cfg->app_id, sizeof(cfg->app_id), "%.*s", (int)sizeof(cfg->app_id) - 1, v);
        else if (!strcmp(line, "app_secret")) snprintf(cfg->app_secret, sizeof(cfg->app_secret), "%.*s", (int)sizeof(cfg->app_secret) - 1, v);
        else if (!strcmp(line, "email"))      snprintf(cfg->email, sizeof(cfg->email), "%.*s", (int)sizeof(cfg->email) - 1, v);
        else if (!strcmp(line, "token"))      snprintf(cfg->token, sizeof(cfg->token), "%.*s", (int)sizeof(cfg->token) - 1, v);
        else if (!strcmp(line, "formato"))    cfg->formato = atoi(v);
    }
    fclose(f);
    if (cfg->formato != QB_MP3 && cfg->formato != QB_FLAC && cfg->formato != QB_HIRES)
        cfg->formato = QB_MP3;
    cfg->configured = cfg->app_id[0] && cfg->app_secret[0] && cfg->token[0];
}

int qobuz_config_save(const QobuzConfig *cfg, const char *dir)
{
    if (!cfg || !dir) return -1;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, QOBUZ_CONFIG_FILE);
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    fprintf(f, "app_id=%s\n", cfg->app_id);
    fprintf(f, "app_secret=%s\n", cfg->app_secret);
    fprintf(f, "email=%s\n", cfg->email);
    fprintf(f, "token=%s\n", cfg->token);
    fprintf(f, "formato=%d\n", cfg->formato);
    fclose(f);
    return 0;
}

/* ---------- JSON, o mínimo ----------

   Um parser de JSON de verdade são milhares de linhas e um alocador. O que
   esta API pede é ler campos de um objeto, e isso dá para fazer direito em
   cinquenta linhas — desde que se faça direito.

   A REGRA É: o valor no NÍVEL DE CIMA do objeto. Não "a primeira ocorrência
   da chave", que foi como isto nasceu e que está errado de duas maneiras
   diferentes, as duas descobertas contra a API de verdade:

     - Num item de ÁLBUM, o `"id"` do artista vem antes e é NÚMERO; o do
       álbum vem depois e é STRING. Pegando a primeira, lia-se o do artista.
     - Num item de FAIXA, `performer.id` e `composer.id` vêm antes do `id`
       da faixa, e os três são números. Nem "a primeira do tipo certo"
       resolve: só a profundidade resolve.

   Nenhum JSON inventado por mim pegaria isso, porque eu teria inventado os
   campos na ordem que o meu código esperava. Foi uma chamada de verdade que
   mostrou — e é por isso que o teste agora usa a estrutura real. */

/* Anda pelo objeto que começa em `json` e devolve o começo do valor de
   `chave`, considerando SÓ o nível de cima. NULL se não houver. */
static const char *valor_no_topo(const char *json, const char *chave)
{
    if (!json || !chave) return NULL;
    const char *p = json;
    while (*p && *p != '{') p++;
    if (!*p) return NULL;
    p++;                                   /* entrou no objeto: prof = 1 */

    size_t nc = strlen(chave);
    int prof = 1;
    while (*p) {
        if (*p == '"') {
            /* uma string: ou é uma chave deste nível, ou é um valor */
            const char *ini = ++p;
            while (*p && *p != '"') {
                if (*p == '\\' && p[1]) p++;
                p++;
            }
            if (!*p) return NULL;
            size_t len = (size_t)(p - ini);
            p++;                           /* passa a aspa final */
            const char *q = p;
            while (*q == ' ') q++;
            if (*q == ':' && prof == 1 && len == nc &&
                strncmp(ini, chave, nc) == 0) {
                q++;
                while (*q == ' ') q++;
                return q;
            }
            continue;
        }
        if (*p == '{' || *p == '[') prof++;
        else if (*p == '}' || *p == ']') { if (--prof == 0) return NULL; }
        p++;
    }
    return NULL;
}

/* O valor como TEXTO, seja ele string ou número. É de propósito: o id de
   álbum vem como string ("0634904078164") e o de faixa como número
   (33978480), e quem chama não deveria ter de saber disso. */
int qobuz_json_str(const char *json, const char *chave, char *out, int cap)
{
    if (!json || !out || cap <= 0) return 0;
    out[0] = '\0';
    const char *p = valor_no_topo(json, chave);
    if (!p) return 0;

    if (*p != '"') {
        if (*p != '-' && (*p < '0' || *p > '9')) return 0;
        int o = 0;
        if (*p == '-' && o < cap - 1) out[o++] = *p++;
        while (*p >= '0' && *p <= '9' && o < cap - 1) out[o++] = *p++;
        out[o] = '\0';
        return o > 0;
    }

    p++;
    int o = 0;
    while (*p && *p != '"' && o < cap - 1) {
        if (*p == '\\' && p[1]) {
            p++;
            /* Só as fugas que aparecem de verdade num título de disco. Uma
               \uXXXX vira '?' em vez de virar lixo binário na tela. */
            char c = *p++;
            if (c == 'n') out[o++] = ' ';
            else if (c == 'u') { out[o++] = '?'; for (int k = 0; k < 4 && *p; k++) p++; }
            else out[o++] = c;
            continue;
        }
        out[o++] = *p++;
    }
    out[o] = '\0';
    return 1;
}

int qobuz_json_int(const char *json, const char *chave, int *out)
{
    if (!json || !out) return 0;
    const char *p = valor_no_topo(json, chave);
    if (!p) return 0;
    if (*p == '"') p++;
    if (*p != '-' && (*p < '0' || *p > '9')) return 0;
    *out = atoi(p);
    return 1;
}

/* ---------- utilidades ---------- */

/* Mudou de casa para o `net.c`: a segunda fonte de rede (SoundCloud) precisa
   exatamente disto, e duas cópias de um codificador é como duas delas passam
   a divergir. O nome aqui continua valendo para as três chamadas abaixo. */
#define urlenc net_urlenc

/* MP3 vira DEC_MP3; todo o resto que o Qobuz entrega e FLAC. Sem isto o
   dec_open_url receberia DEC_NONE e nenhuma faixa abriria — e o sintoma,
   "nao toca nada da rede", nao aponta para um enum. */
int qobuz_deckind(int formato)
{
    return (formato == QB_MP3) ? DEC_MP3 : DEC_FLAC;
}

int qobuz_mb_por_faixa(int formato)
{
    /* Medidas grosseiras de faixa de 4 minutos. Servem para AVISAR antes de
       encher o cartão, não para prever byte. */
    if (formato == QB_FLAC)  return 30;   /* medido: 34 MB numa faixa de 4:48 */
    if (formato == QB_HIRES) return 60;
    return 8;                                   /* MP3 320 */
}

void qobuz_assina(const char *secret, const char *faixa_id, int formato,
                  long ts, char out_md5[33])
{
    /* Parâmetros em ordem ALFABÉTICA (format_id, intent, track_id), colados
       sem separador, depois o timestamp, depois o segredo. */
    char buf[512];
    int n = snprintf(buf, sizeof(buf),
                     "trackgetFileUrlformat_id%dintentstreamtrack_id%s%ld%s",
                     formato, faixa_id ? faixa_id : "", ts, secret ? secret : "");
    if (n < 0) { out_md5[0] = '\0'; return; }
    md5_hex(buf, (size_t)n, out_md5);
}

/* ---------- chamadas ---------- */

/* POR QUE GUARDAR O MOTIVO.

   A tela dizia só "could not reach Qobuz — is the Wi-Fi on?" para tudo: sem
   rede, token vencido, app_id recusado, DNS, TLS. São causas com consertos
   diferentes, e "qobuz doesnt work yet" três vezes seguidas é o que acontece
   quando a tela não distingue. O número do net_get vai junto — feio, mas é a
   diferença entre consertar e adivinhar de novo. */
static char g_motivo[160];

const char *qobuz_motivo(void) { return g_motivo; }

static void motivo(const char *o_que, int rc)
{
    snprintf(g_motivo, sizeof(g_motivo), "%s (net_get %d)", o_que, rc);
}

static int pega(const QobuzConfig *cfg, const char *url, char *resp, int cap)
{
    char auth[192];
    snprintf(auth, sizeof(auth), "X-User-Auth-Token: %s", cfg->token);
    char apph[64];
    snprintf(apph, sizeof(apph), "X-App-Id: %s", cfg->app_id);
    const char *hdrs[3];
    int h = 0;
    if (cfg->token[0]) hdrs[h++] = auth;
    if (cfg->app_id[0]) hdrs[h++] = apph;
    hdrs[h] = NULL;
    int rc = net_get(url, hdrs, resp, cap);
    if (rc != 0) {
        /* A frase vem do net.c, que é quem sabe ONDE quebrou — módulo, Wi-Fi,
           DNS, handshake, status. Antes todas viravam "the network call
           failed (net_get -1)", que é o mesmo que não dizer nada. O código
           cru do sistema vai junto: é o número que se procura quando a frase
           não basta. Falta de token continua na frente de tudo — sem ele nem
           vale olhar a rede. */
        const char *onde = net_motivo();
        if (!cfg->token[0])
            snprintf(g_motivo, sizeof(g_motivo), "%s",
                     "no session token — sign in again");
        else if (onde && onde[0]) {
            int sis = net_erro_sistema();
            if (sis)
                snprintf(g_motivo, sizeof(g_motivo), "%s (0x%08X)",
                         onde, (unsigned)sis);
            else
                snprintf(g_motivo, sizeof(g_motivo), "%s", onde);
        } else {
            motivo("the network call failed", rc);
        }
    }
    return rc;
}

int qobuz_login(QobuzConfig *cfg, const char *email, const char *senha)
{
    if (!cfg || !email || !senha || !email[0] || !senha[0]) return -1;
    if (!cfg->app_id[0] || !cfg->app_secret[0]) return -2;

    /* O Qobuz quer o MD5 da senha, não a senha. A senha em claro não sai
       daqui e não é guardada em lugar nenhum. */
    char md5[33];
    md5_hex(senha, strlen(senha), md5);

    char em[512];
    urlenc(email, em, sizeof(em));
    char url[1024];
    snprintf(url, sizeof(url),
             QB_API "user/login?app_id=%s&username=%s&password=%s",
             cfg->app_id, em, md5);

    char resp[8192];
    if (net_get(url, NULL, resp, (int)sizeof(resp)) != 0) return -3;
    char tok[128];
    if (!qobuz_json_str(resp, "user_auth_token", tok, (int)sizeof(tok)) || !tok[0])
        return -4;
    snprintf(cfg->token, sizeof(cfg->token), "%s", tok);
    snprintf(cfg->email, sizeof(cfg->email), "%.*s", (int)sizeof(cfg->email) - 1, email);
    cfg->configured = cfg->app_id[0] && cfg->app_secret[0] && cfg->token[0];
    return cfg->configured ? 0 : -4;
}

/* Anda pelos objetos de uma lista JSON contando chaves. Não é elegante, mas
   é o suficiente: cada item de "items" começa num '{' de primeiro nível
   dentro do vetor, e é daí que se lê o item inteiro. */
static const char *proximo_item(const char *p)
{
    int prof = 0;
    for (; *p; p++) {
        if (*p == '{') { if (prof++ == 0) return p; }
        else if (*p == '}') prof--;
        else if (*p == ']' && prof <= 0) return NULL;
    }
    return NULL;
}

static const char *fim_item(const char *p)
{
    int prof = 0;
    for (; *p; p++) {
        if (*p == '{') prof++;
        else if (*p == '}') { if (--prof == 0) return p + 1; }
    }
    return p;
}

/* Extrai um álbum de um item JSON genérico (serve para album/search e para o
   objeto "album" dentro de track/search). Devolve true se achou id. */
static bool extrai_album(const char *json, QobuzAlbum *a)
{
    memset(a, 0, sizeof(*a));
    if (!qobuz_json_str(json, "id", a->id, (int)sizeof(a->id))) return false;
    qobuz_json_str(json, "title", a->titulo, (int)sizeof(a->titulo));
    const char *art = strstr(json, "\"artist\"");
    if (art) qobuz_json_str(art, "name", a->artista, (int)sizeof(a->artista));
    /* A CAPA. Vem num sub-objeto "image" com três tamanhos; o "small" (230 px)
       é o certo para uma lista — o "large" seria meio megabyte por linha. */
    const char *img = strstr(json, "\"image\"");
    if (img) qobuz_json_str(img, "small", a->capa, (int)sizeof(a->capa));
    qobuz_json_int(json, "tracks_count", &a->faixas);
    /* O ANO, que ninguém lia: o campo saía 0 em TODA busca, e a linha do
       disco mostrava "0" onde devia estar o ano. O Qobuz manda
       "release_date_original":"2007-10-10" — o ano são os quatro primeiros
       dígitos. (Há também release_date_stream e _download; a ORIGINAL é a
       data do disco, não a de quando entrou no catálogo.) */
    char data[32];
    if (qobuz_json_str(json, "release_date_original", data, (int)sizeof(data)) &&
        data[0] >= '0' && data[0] <= '9')
        a->ano = (int)strtol(data, NULL, 10);
    a->hires = strstr(json, "\"hires\":true") != NULL;
    return true;
}

/* Busca o primeiro objeto JSON de nível 1 dentro de um array "items" a partir
   de `p`. Devolve o começo do objeto, ou NULL se não houver mais. */
static const char *itera_items(const char *p)
{
    return proximo_item(p);
}

int qobuz_busca(const QobuzConfig *cfg, const char *termo,
                QobuzAlbum *out, int max)
{
    if (!cfg || !termo || !out || max <= 0) return -1;
    if (!cfg->app_id[0]) return -2;

    char q[512];
    urlenc(termo, q, sizeof(q));
    g_motivo[0] = '\0';

    /* DUAS buscas: album/search e track/search. Alguém busca "Creep" e a
       album/search não acha — mas a track/search acha e traz o álbum de
       origem. As duas respostas têm "items", mas com objetos diferentes:
       na de álbuns, cada item É um álbum; na de faixas, cada item tem um
       sub-objeto "album" com o disco de origem. */
    int n = 0;
    /* Alguma das duas chamadas chegou a RESPONDER?

       Sem esta marca as duas podiam falhar na rede e a função devolvia 0 — e
       0, para quem chama, quer dizer "procurei e não achei nada". A tela
       então escrevia "nothing found" para um Wi-Fi fora do ar ou um handshake
       recusado, e o motivo de verdade ficava parado no qobuz_motivo(), que
       ela só mostra quando o retorno é NEGATIVO. Era exatamente este o
       sintoma relatado: "a busca do Qobuz não traz nada" — sem dizer por quê,
       e sem diferença visível entre "não existe esse disco" e "não houve
       rede". */
    bool respondeu = false;
    static char resp[96 * 1024];
    static char item[16 * 1024];

    /* --- album/search --- */
    {
        char url[1024];
        snprintf(url, sizeof(url),
                 QB_API "album/search?query=%s&limit=%d&app_id=%s",
                 q, max > 30 ? 30 : max, cfg->app_id);
        if (pega(cfg, url, resp, (int)sizeof(resp)) == 0) {
            respondeu = true;
            const char *itens = strstr(resp, "\"items\"");
            if (itens) {
                const char *p = itens;
                while (n < max && (p = itera_items(p)) != NULL) {
                    const char *fim = fim_item(p);
                    size_t len = (size_t)(fim - p);
                    if (len >= sizeof(item)) len = sizeof(item) - 1;
                    memcpy(item, p, len);
                    item[len] = '\0';
                    QobuzAlbum a;
                    if (extrai_album(item, &a)) out[n++] = a;
                    p = fim;
                }
            } else {
                /* Respondeu, mas sem "items". O STATUS separa duas coisas que
                   a mensagem do corpo nem sempre separa: 401/403 é sessão
                   vencida — e essa tem conserto, na aba ACCOUNT — enquanto o
                   resto é o Qobuz recusando o pedido por outro motivo. */
                int http = net_http_ultimo();
                char msg[96] = "";
                if (http == 401 || http == 403)
                    snprintf(g_motivo, sizeof(g_motivo), "%s",
                             "the Qobuz session expired — sign in again on ACCOUNT");
                else if (qobuz_json_str(resp, "message", msg, (int)sizeof(msg)) && msg[0])
                    snprintf(g_motivo, sizeof(g_motivo), "Qobuz said: %.90s", msg);
                else if (strstr(resp, "\"code\"") || strstr(resp, "error"))
                    snprintf(g_motivo, sizeof(g_motivo), "%s", "Qobuz refused the request");
                return -3;
            }
        }
    }

    /* --- track/search: cada faixa traz o álbum de origem em "album" --- */
    {
        char url[1024];
        snprintf(url, sizeof(url),
                 QB_API "track/search?query=%s&limit=%d&app_id=%s",
                 q, 20, cfg->app_id);
        if (pega(cfg, url, resp, (int)sizeof(resp)) == 0) {
            respondeu = true;
            const char *itens = strstr(resp, "\"items\"");
            if (itens) {
                const char *p = itens;
                while (n < max && (p = itera_items(p)) != NULL) {
                    const char *fim = fim_item(p);
                    size_t len = (size_t)(fim - p);
                    if (len >= sizeof(item)) len = sizeof(item) - 1;
                    memcpy(item, p, len);
                    item[len] = '\0';

                    /* O objeto "album" dentro da faixa — começa onde diz
                       "album" e vai até o fechamento correspondente. */
                    const char *alb = strstr(item, "\"album\"");
                    if (!alb) { p = fim; continue; }
                    while (*alb && *alb != '{') alb++;
                    if (!*alb) { p = fim; continue; }

                    QobuzAlbum a;
                    if (!extrai_album(alb, &a)) { p = fim; continue; }

                    /* Deduplicar: este álbum já veio da album/search? */
                    bool dup = false;
                    for (int i = 0; i < n; i++)
                        if (!strcmp(out[i].id, a.id)) { dup = true; break; }
                    if (!dup) out[n++] = a;
                    p = fim;
                }
            }
        }
    }

    /* Nenhuma das duas respondeu: isto é erro de REDE, não estante vazia. */
    if (!respondeu) {
        if (!g_motivo[0])
            snprintf(g_motivo, sizeof(g_motivo), "%s", "could not reach Qobuz");
        return -3;
    }
    return n;
}

int qobuz_faixas(const QobuzConfig *cfg, const char *album_id,
                 QobuzFaixa *out, int max)
{
    if (!cfg || !album_id || !out || max <= 0) return -1;
    char url[512];
    snprintf(url, sizeof(url), QB_API "album/get?album_id=%s&app_id=%s",
             album_id, cfg->app_id);

    static char resp[128 * 1024];
    if (pega(cfg, url, resp, (int)sizeof(resp)) != 0) return -3;

    /* As faixas vêm em "tracks":{"items":[...]} — começar a busca DEPOIS do
       "tracks" é o que impede de pegar a lista de álbuns do artista, que
       aparece antes na mesma resposta. */
    const char *tr = strstr(resp, "\"tracks\"");
    const char *itens = tr ? strstr(tr, "\"items\"") : NULL;
    if (!itens) return 0;

    int n = 0;
    const char *p = itens;
    while (n < max && (p = proximo_item(p)) != NULL) {
        const char *fim = fim_item(p);
        size_t len = (size_t)(fim - p);
        static char item[8192];
        if (len >= sizeof(item)) len = sizeof(item) - 1;
        memcpy(item, p, len);
        item[len] = '\0';

        QobuzFaixa *t = &out[n];
        memset(t, 0, sizeof(*t));
        if (!qobuz_json_str(item, "id", t->id, (int)sizeof(t->id))) { p = fim; continue; }
        qobuz_json_str(item, "title", t->titulo, (int)sizeof(t->titulo));
        qobuz_json_int(item, "track_number", &t->numero);
        qobuz_json_int(item, "duration", &t->segundos);
        n++;
        p = fim;
    }
    return n;
}

/* Pede a URL assinada de uma faixa, tentando cada segredo da lista.

   POR QUE TENTAR VÁRIOS: o Qobuz tem mais de um segredo válido por app_id, e
   só um deles assina num dado momento. Não há chamada que diga qual — o
   jeito é assinar e ver se volta URL. Guardar um só é guardar "o que
   funcionava no dia em que configurei", e o sintoma da escolha errada é um
   "não deu para baixar" idêntico ao de estar sem rede. */
static int url_da_faixa(const QobuzConfig *cfg, const char *faixa_id, int formato,
                        char *out, int cap)
{
    char lista[sizeof(cfg->app_secret)];
    snprintf(lista, sizeof(lista), "%s", cfg->app_secret);

    int viu_rede = 0;
    char *save = NULL;
    for (char *seg = strtok_r(lista, ",", &save); seg;
         seg = strtok_r(NULL, ",", &save)) {
        while (*seg == ' ') seg++;
        if (!*seg) continue;

        long ts = (long)time(NULL);
        char sig[33];
        qobuz_assina(seg, faixa_id, formato, ts, sig);

        char url[1024];
        snprintf(url, sizeof(url),
                 QB_API "track/getFileUrl?request_ts=%ld&request_sig=%s"
                 "&track_id=%s&format_id=%d&intent=stream&app_id=%s",
                 ts, sig, faixa_id, formato, cfg->app_id);

        static char resp[16 * 1024];
        if (pega(cfg, url, resp, (int)sizeof(resp)) != 0) continue;
        viu_rede = 1;
        if (qobuz_json_str(resp, "url", out, cap) && out[0]) return 0;
    }
    return viu_rede ? -2 : -1;
}

/* A mesma URL assinada que o download usa — so que para TOCAR direto. Vale
   cerca de uma hora, o que e muito mais do que uma faixa dura; nao ha o que
   renovar no meio. */
int qobuz_url(const QobuzConfig *cfg, const char *faixa_id, int formato,
              char *out, int cap)
{
    if (!cfg || !faixa_id || !out || cap <= 0) return -1;
    if (!cfg->configured) return -1;
    out[0] = '\0';
    return url_da_faixa(cfg, faixa_id, formato, out, cap);
}

int qobuz_baixa(const QobuzConfig *cfg, const char *faixa_id, int formato,
                const char *destino,
                void (*prog)(void *ud, long feitos, long total), void *ud)
{
    if (!cfg || !faixa_id || !destino) return -1;
    if (!cfg->configured) return -1;

    /* A URL vem assinada e vale cerca de uma hora — baixar é imediato, então
       não há o que guardar. O segredo assina o PEDIDO; ele não decifra áudio
       nenhum, e o arquivo que chega já é tocável. */
    static char durl[4096];
    int r = url_da_faixa(cfg, faixa_id, formato, durl, (int)sizeof(durl));
    if (r != 0) return r;

    return net_download(durl, NULL, destino, prog, ud);
}

/* ---------- baixar um álbum inteiro, em segundo plano ---------- */

#include "fsutil.h"

/* O estado é lido pela thread de vídeo enquanto a de rede escreve. Não há
   trava: os campos são escalares, a tela só LÊ, e o pior caso de uma leitura
   no meio de uma escrita é um número de faixa desenhado um quadro fora de
   hora. Um mutex aqui custaria mais em complexidade do que o defeito que
   evitaria. `ativo` é escrito por último ao terminar, e é o único campo de
   que a lógica da tela depende. */
static QobuzJob    g_job;
static QobuzConfig g_job_cfg;
static QobuzAlbum  g_job_alb;
static int         g_job_fmt;
static char        g_job_dir[512];
static volatile int g_job_parar;

/* Um nome de pasta que o FAT do cartão aceite. Barra, dois-pontos e
   companhia viram '-': um álbum chamado "AC/DC: Live" criaria uma subpasta
   fantasma e o resto do disco cairia no lugar errado. */
static void nome_seguro(const char *in, char *out, size_t cap)
{
    size_t o = 0;
    for (; in && *in && o + 1 < cap; in++) {
        unsigned char c = (unsigned char)*in;
        if (c < 0x20 || strchr("\\/:*?\"<>|", c)) {
            if (o && out[o - 1] == '-') continue;
            out[o++] = '-';
        } else {
            out[o++] = (char)c;
        }
    }
    while (o > 0 && (out[o - 1] == ' ' || out[o - 1] == '.' || out[o - 1] == '-')) o--;
    out[o] = '\0';
    if (!out[0]) snprintf(out, cap, "disco");
}

static void job_prog(void *ud, long feitos, long total)
{
    (void)ud;
    g_job.bytes = feitos;
    g_job.bytes_total = total;
}

static void job_corpo(void)
{
    QobuzFaixa faixas[64];
    int n = qobuz_faixas(&g_job_cfg, g_job_alb.id, faixas,
                         (int)(sizeof(faixas) / sizeof(faixas[0])));
    if (n <= 0) {
        snprintf(g_job.erro, sizeof(g_job.erro),
                 n == 0 ? "the record returned no tracks" : "could not reach Qobuz");
        g_job.falhou = true;
        g_job.ativo = false;
        return;
    }
    g_job.total = n;

    char art[128], tit[160], pasta[512];
    nome_seguro(g_job_alb.artista[0] ? g_job_alb.artista : "Qobuz", art, sizeof(art));
    nome_seguro(g_job_alb.titulo[0] ? g_job_alb.titulo : g_job_alb.id, tit, sizeof(tit));
    /* Os cortes explícitos não são enfeite: pasta[512] com um diretório de
       até 511 e um título de 159 pode estourar, e um snprintf que trunca no
       meio de um caminho cria a pasta no lugar errado em silêncio. */
    snprintf(pasta, sizeof(pasta), "%.300s/%.100s - %.100s", g_job_dir, art, tit);
    if (mkdir_p(pasta) != 0) {
        snprintf(g_job.erro, sizeof(g_job.erro), "could not create the folder");
        g_job.falhou = true;
        g_job.ativo = false;
        return;
    }

    const char *ext = (g_job_fmt == QB_MP3) ? "mp3" : "flac";
    int erros = 0;
    for (int i = 0; i < n && !g_job_parar; i++) {
        g_job.faixa = i + 1;
        g_job.bytes = 0;
        g_job.bytes_total = -1;
        snprintf(g_job.titulo, sizeof(g_job.titulo), "%s", faixas[i].titulo);

        char nome[192], destino[768];
        nome_seguro(faixas[i].titulo[0] ? faixas[i].titulo : faixas[i].id,
                    nome, sizeof(nome));
        /* O número na frente é o que dá a ORDEM: a estante ordena pelo nome
           do arquivo, e sem ele um disco toca em ordem alfabética. */
        snprintf(destino, sizeof(destino), "%s/%02d - %.150s.%s",
                 pasta, faixas[i].numero > 0 ? faixas[i].numero : i + 1, nome, ext);

        if (qobuz_baixa(&g_job_cfg, faixas[i].id, g_job_fmt, destino,
                        job_prog, NULL) != 0)
            erros++;
    }

    if (erros >= n) {
        snprintf(g_job.erro, sizeof(g_job.erro), "no track downloaded");
        g_job.falhou = true;
    } else {
        if (erros > 0)
            snprintf(g_job.erro, sizeof(g_job.erro),
                     "%d track%s did not arrive", erros, erros == 1 ? "" : "s");
        g_job.ok = true;
    }
    g_job.ativo = false;      /* por último: ver a nota lá em cima */
}

#ifdef __vita__
#include <psp2/kernel/threadmgr.h>

static int job_thread(SceSize args, void *argp)
{
    (void)args; (void)argp;
    job_corpo();
    return sceKernelExitDeleteThread(0);
}
#endif

int qobuz_baixa_album(const QobuzConfig *cfg, const QobuzAlbum *alb,
                      int formato, const char *dir)
{
    if (!cfg || !alb || !dir || g_job.ativo) return -1;
    if (!cfg->configured) return -1;

    g_job_cfg = *cfg;
    g_job_alb = *alb;
    g_job_fmt = formato;
    snprintf(g_job_dir, sizeof(g_job_dir), "%s", dir);
    g_job_parar = 0;

    memset(&g_job, 0, sizeof(g_job));
    g_job.ativo = true;
    g_job.bytes_total = -1;
    snprintf(g_job.album, sizeof(g_job.album), "%s", alb->titulo);

#ifdef __vita__
    /* Prioridade abaixo da principal: entre alimentar o áudio e baixar um
       disco, a escolha certa é óbvia. */
    SceUID th = sceKernelCreateThread("stylus_qobuz", job_thread,
                                      PRIO_REDE, PILHA_REDE, 0, 0, NULL);
    if (th < 0) { g_job.ativo = false; return -1; }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_job.ativo = false;
        return -1;
    }
#else
    /* No host não há thread a economizar e o teste quer o efeito agora. */
    job_corpo();
#endif
    return 0;
}

void qobuz_job_estado(QobuzJob *out) { if (out) *out = g_job; }

void qobuz_job_limpa(void)
{
    /* Enquanto estiver baixando, zerar isto faria a tela achar que acabou e
       largar o download rodando invisível. */
    if (g_job.ativo) return;
    memset(&g_job, 0, sizeof(g_job));
}
void qobuz_job_cancela(void) { g_job_parar = 1; }


/* ---------- buscar sem travar a tela ---------- */

#define QB_MAX_RES 12

static QobuzAlbum  g_res[QB_MAX_RES];
static int         g_nres;
static volatile int g_buscando;
static QobuzConfig g_bus_cfg;
static char        g_bus_termo[128];

/* O RASTRO DA FALHA, NO CARTÃO.

   A tela já diz o motivo, mas a tela SOME quando se muda de tela — e quem
   conserta o app quase nunca é quem está com o aparelho na mão. Foi um
   arquivo assim, o varredura.txt, que resolveu o "as músicas não aparecem"
   depois de duas teorias erradas e duas viagens ao aparelho.

   Só escreve quando FALHA: não existe relatório para ler quando está tudo
   bem, e ninguém precisa de mais uma tela de diagnóstico. */
static void rede_escreve(const char *linha)
{
    const char *caminho = STYLUS_DATA_DIR "/rede.txt";
    long tam = 0;
    FILE *g = fopen(caminho, "rb");
    if (g) { fseek(g, 0, SEEK_END); tam = ftell(g); fclose(g); }
    FILE *f = fopen(caminho, tam > 4096 ? "w" : "a");
    if (!f) return;
    fputs(linha, f);
    fputc('\n', f);
    fclose(f);
}

/* A BUSCA RECUSADA ANTES DE COMEÇAR.

   O `qobuz_busca_async` tem CINCO saídas -1 (termo vazio, busca já em curso,
   sem app_id, thread não criada, thread não iniciada) e ninguém olhava o
   retorno: `qobuz_busca_async(c, u->qb_termo);` e pronto. Com isso o
   `g_nres` ficava 0, a tela escrevia "nothing found", e o `busca_corpo` — que
   é quem grava o rede.txt — nunca rodava. Era exatamente essa a assinatura no
   aparelho: nenhum rede.txt, nem a linha START, e "nothing found" na tela.

   Agora cada recusa escreve o motivo E põe `g_nres` em -3, que é o que faz a
   tela mostrar a tela de erro com a frase em vez de "nada encontrado". */
static void recusa(const char *porque)
{
    snprintf(g_motivo, sizeof(g_motivo), "%s", porque);
    g_nres = -3;
    char linha[192];
    snprintf(linha, sizeof(linha), "search REFUSED  %s", porque);
    rede_escreve(linha);
}

static void anota_busca(const char *fase, const char *termo, int rc)
{
    const char *caminho = STYLUS_DATA_DIR "/rede.txt";
    /* Não vira arquivo de log de verdade: passou de 4 KB, recomeça. O que
       interessa são as últimas tentativas, não o histórico do ano. */
    long tam = 0;
    FILE *g = fopen(caminho, "rb");
    if (g) { fseek(g, 0, SEEK_END); tam = ftell(g); fclose(g); }

    FILE *f = fopen(caminho, tam > 4096 ? "w" : "a");
    if (!f) return;
    if (!strcmp(fase, "start"))
        fprintf(f, "search START \"%.40s\"\n", termo ? termo : "");
    else
        fprintf(f, "search END   rc=%d  http=%d  sys=0x%08X  %s\n",
                rc, net_http_ultimo(), (unsigned)net_erro_sistema(),
                qobuz_motivo()[0] ? qobuz_motivo() : "(no reason: it worked)");
    fclose(f);   /* fecha SEMPRE: o valor da linha "START" é existir mesmo
                    quando o que vem depois dela mata o app */
}

static void busca_corpo(void)
{
    /* ANTES da chamada, e não só quando ela falha.

       O rede.txt só era escrito no fracasso, e por isso não existia em três
       versões seguidas: uma thread que morre (pilha estourada num handshake,
       por exemplo) não chega a escrever nada, e a ausência do arquivo era
       lida como "a busca nunca rodou". Com a linha START gravada e fechada
       antes, um arquivo com START e sem END diz exatamente isto: ela rodou e
       não voltou. */
    anota_busca("start", g_bus_termo, 0);
    int n = qobuz_busca(&g_bus_cfg, g_bus_termo, g_res, QB_MAX_RES);
    g_nres = n;                 /* <0 fica <0: a tela distingue "nada achado"
                                   de "não deu para perguntar" */
    anota_busca("end", g_bus_termo, n);
    g_buscando = 0;
}

#ifdef __vita__
static int busca_thread(SceSize args, void *argp)
{
    (void)args; (void)argp;
    busca_corpo();
    return sceKernelExitDeleteThread(0);
}
#endif

int qobuz_busca_async(const QobuzConfig *cfg, const char *termo)
{
    if (!cfg || !termo || !termo[0]) { recusa("no search term typed"); return -1; }
    if (g_buscando) { recusa("a search is still running"); return -1; }
    if (!cfg->app_id[0]) { recusa("no app_id in qobuz.config"); return -1; }
    g_bus_cfg = *cfg;
    snprintf(g_bus_termo, sizeof(g_bus_termo), "%.*s",
             (int)sizeof(g_bus_termo) - 1, termo);
    g_nres = 0;
    g_buscando = 1;
#ifdef __vita__
    SceUID th = sceKernelCreateThread("stylus_qbusca", busca_thread,
                                      PRIO_REDE, PILHA_REDE, 0, 0, NULL);
    if (th < 0) {
        g_buscando = 0;
        char m[96];
        snprintf(m, sizeof(m), "search thread refused (0x%08X)", (unsigned)th);
        recusa(m);
        return -1;
    }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_buscando = 0;
        recusa("the search thread would not start");
        return -1;
    }
#else
    busca_corpo();
#endif
    return 0;
}

/* ---------- as capas dos resultados ---------- */

static QobuzAlbum   g_cap_lista[QB_MAX_RES];
static int          g_cap_n;
static volatile int g_cap_ativo;
static char         g_cap_dir[256];

void qobuz_capa_arquivo(const char *dir, const char *id, char *out, int cap)
{
    snprintf(out, (size_t)cap, "%s/capas-qobuz/%s.jpg",
             dir ? dir : ".", id ? id : "unknown");
}

static void capas_corpo(void)
{
    char pasta[300];
    snprintf(pasta, sizeof(pasta), "%s/capas-qobuz", g_cap_dir);
    mkdir_p(pasta);

    for (int i = 0; i < g_cap_n; i++) {
        if (!g_cap_lista[i].capa[0] || !g_cap_lista[i].id[0]) continue;
        char dest[512];
        qobuz_capa_arquivo(g_cap_dir, g_cap_lista[i].id, dest, (int)sizeof(dest));
        /* já está no cartão de uma busca anterior: não baixa de novo */
        FILE *f = fopen(dest, "rb");
        if (f) { fclose(f); continue; }

        /* Não precisa de nome provisório aqui: o `net_download` já baixa
           para `<nome>.parcial` e só renomeia no fim. Isso importa porque
           quem DESENHA é outra thread e ela pergunta a cada quadro "a capa já
           existe?" — se o arquivo aparecesse com o primeiro byte, o desenho
           abriria um JPEG pela metade e guardaria o fracasso no cache com
           `cheio = true`, deixando aquela capa em branco para sempre. */
        net_download(g_cap_lista[i].capa, NULL, dest, NULL, NULL);
    }
    g_cap_ativo = 0;
}

#ifdef __vita__
static int capas_thread(SceSize args, void *argp)
{
    (void)args; (void)argp;
    capas_corpo();
    return sceKernelExitDeleteThread(0);
}
#endif

int qobuz_capas_async(const QobuzAlbum *lista, int n, const char *dir)
{
    if (!lista || n <= 0 || !dir || g_cap_ativo) return -1;
    if (n > QB_MAX_RES) n = QB_MAX_RES;
    for (int i = 0; i < n; i++) g_cap_lista[i] = lista[i];
    g_cap_n = n;
    snprintf(g_cap_dir, sizeof(g_cap_dir), "%s", dir);
    g_cap_ativo = 1;
#ifdef __vita__
    SceUID th = sceKernelCreateThread("stylus_qcapas", capas_thread,
                                      PRIO_REDE, PILHA_REDE, 0, 0, NULL);
    if (th < 0) { g_cap_ativo = 0; return -1; }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_cap_ativo = 0;
        return -1;
    }
#else
    capas_corpo();
#endif
    return 0;
}

void qobuz_busca_estado(QobuzAlbum *out, int max, int *n, bool *ativo)
{
    if (ativo) *ativo = g_buscando != 0;
    if (n) *n = g_nres;
    if (out && max > 0) {
        int q = g_nres < max ? g_nres : max;
        for (int i = 0; i < q; i++) out[i] = g_res[i];
    }
}

/* ---------- abrir um disco para TOCAR pela rede ----------

   Pedir as faixas é uma chamada de rede de um ou dois segundos. Feita no laço
   de vídeo, ela congela a tela logo depois de a pessoa apertar "tocar" — que
   é exatamente o instante em que ela está olhando para ver se funcionou, e
   dois segundos parados ali não leem como "carregando", leem como travou.
   Mesmo motivo, mesma forma que a busca. */

#define QB_MAX_FAIXAS 64

static QobuzFaixa   g_fx[QB_MAX_FAIXAS];
static int          g_nfx;
static volatile int g_abrindo;
static QobuzConfig  g_ab_cfg;
static char         g_ab_id[32];
static QobuzAlbum   g_ab_alb;

static void abre_corpo(void)
{
    int n = qobuz_faixas(&g_ab_cfg, g_ab_id, g_fx, QB_MAX_FAIXAS);
    g_nfx = n;
    g_abrindo = 0;
}

#ifdef __vita__
static int abre_thread(SceSize args, void *argp)
{
    (void)args; (void)argp;
    abre_corpo();
    return sceKernelExitDeleteThread(0);
}
#endif

int qobuz_abre_async(const QobuzConfig *cfg, const QobuzAlbum *alb)
{
    if (!cfg || !alb || !alb->id[0] || g_abrindo) return -1;
    if (!cfg->configured) return -1;
    g_ab_cfg = *cfg;
    g_ab_alb = *alb;
    snprintf(g_ab_id, sizeof(g_ab_id), "%s", alb->id);
    g_nfx = 0;
    g_abrindo = 1;
#ifdef __vita__
    SceUID th = sceKernelCreateThread("stylus_qabre", abre_thread,
                                      PRIO_REDE, PILHA_REDE, 0, 0, NULL);
    if (th < 0) { g_abrindo = 0; return -1; }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_abrindo = 0;
        return -1;
    }
#else
    abre_corpo();
#endif
    return 0;
}

void qobuz_abre_estado(QobuzFaixa *out, int max, int *n, bool *ativo,
                       QobuzAlbum *alb)
{
    if (ativo) *ativo = g_abrindo != 0;
    if (n) *n = g_nfx;
    if (alb) *alb = g_ab_alb;
    if (out && max > 0) {
        int q = g_nfx < max ? g_nfx : max;
        for (int i = 0; i < q; i++) out[i] = g_fx[i];
    }
}

void qobuz_abre_limpa(void)
{
    if (g_abrindo) return;
    g_nfx = 0;
}

/* ═══════════════════════════════════════════════════════════════════════
   CASAR UMA FAIXA LOCAL COM A DO CATÁLOGO — o "toca a versão lossless"
   ═══════════════════════════════════════════════════════════════════════

   O pedido: estou ouvindo um MP3 do cartão; ache esta MESMA música no Qobuz
   e toque a versão em FLAC. O encanamento para tocar já existia inteiro (uma
   Track com `remote_id` é resolvida em URL pelo main), e a busca por faixa
   também — o que faltava era a parte difícil, que não é rede: é decidir se a
   faixa que voltou é A MESMA MÚSICA.

   POR QUE ISTO NÃO É "PEGAR O PRIMEIRO RESULTADO"

   Procurar "Radiohead Creep" traz, em ordem: a de estúdio, a acústica, três
   ao vivo, duas remasterizações, um cover de alguém e uma versão que dura
   oito minutos. Pegar o primeiro troca, em silêncio, a gravação que a pessoa
   escolheu por outra — e o app não teria como dizer que fez isso, porque o
   título e o artista batem em todas. Trocar a gravação sem avisar é pior do
   que não achar nada.

   A DURAÇÃO é o que separa as versões. Título e artista dizem QUAL MÚSICA;
   a duração diz QUAL GRAVAÇÃO — é a única coisa no resultado que muda entre
   o corte de estúdio e o ao vivo, e ela vem de graça na resposta. Daí o
   peso: título parecido é obrigatório, artista parecido conta muito, e a
   duração dentro de três segundos vale mais que as duas — porque é ela que
   responde a pergunta que o título não responde.

   E quando nada passa do piso, isto devolve NÃO ACHEI. Um casamento fraco
   apresentado como certo é a forma cara de errar aqui. */

/* Uma letra "comparável": minúscula, sem acento, sem pontuação. O acervo tem
   "Björk", "Sigur Rós" e "Ágætis byrjun"; o catálogo às vezes escreve os
   mesmos sem acento. Comparar cru faz duas grafias da mesma coisa não casarem.

   Devolve 0 para o que não é letra nem dígito — o chamador pula esses, o que
   também resolve "Song (Remastered 2009)" contra "Song - Remastered". */
static int letra_comparavel(unsigned char c)
{
    if (c >= 'A' && c <= 'Z') return c + 32;
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) return c;
    return 0;
}

static void normaliza(const char *s, char *out, size_t cap)
{
    size_t o = 0;
    if (!s) { if (cap) out[0] = '\0'; return; }
    for (; *s && o + 1 < cap; s++) {
        int c = letra_comparavel((unsigned char)*s);
        if (c) out[o++] = (char)c;
    }
    out[o] = '\0';
}

/* Quanto de `agulha` aparece em `palheiro`, de 0 a 100. Não é distância de
   edição: é contido-em, que é o que serve aqui, porque o catálogo ADICIONA
   coisa ao título ("Creep" -> "Creep (Acoustic Version)") muito mais do que
   tira. */
static int parecenca(const char *a, const char *b)
{
    if (!a[0] || !b[0]) return 0;
    if (!strcmp(a, b)) return 100;
    size_t la = strlen(a), lb = strlen(b);
    const char *curto = la <= lb ? a : b, *longo = la <= lb ? b : a;
    if (strstr(longo, curto)) {
        /* contido, mas o quanto ele é do outro importa: "a" dentro de
           "abracadabra" não é parecença, é acidente */
        size_t lc = strlen(curto), ll = strlen(longo);
        if (lc < 4) return 0;
        int r = (int)((lc * 100) / ll);
        return r < 55 ? 0 : (r > 92 ? 92 : r);
    }
    return 0;
}

/* Extrai uma FAIXA de um item de track/search. */
static bool extrai_faixa(const char *json, QobuzCasamento *c)
{
    memset(c, 0, sizeof(*c));
    if (!qobuz_json_str(json, "id", c->id, (int)sizeof(c->id))) return false;
    qobuz_json_str(json, "title", c->titulo, (int)sizeof(c->titulo));
    qobuz_json_int(json, "duration", &c->segundos);
    /* O artista da FAIXA é o "performer"; o do álbum vem do sub-objeto
       "album" e serve de reserva (numa coletânea o performer é quem toca e o
       artista do álbum é "Various Artists" — a reserva é a pior das duas,
       mas melhor que campo vazio). */
    const char *perf = strstr(json, "\"performer\"");
    if (perf) qobuz_json_str(perf, "name", c->artista, (int)sizeof(c->artista));
    const char *alb = strstr(json, "\"album\"");
    if (alb) {
        qobuz_json_str(alb, "id", c->album_id, (int)sizeof(c->album_id));
        qobuz_json_str(alb, "title", c->album, (int)sizeof(c->album));
        if (!c->artista[0]) {
            const char *art = strstr(alb, "\"artist\"");
            if (art) qobuz_json_str(art, "name", c->artista, (int)sizeof(c->artista));
        }
    }
    /* A CAPA, igual à do álbum: o sub-objeto "image" da própria faixa, três
       tamanhos, e o "small" é o que o deck põe no rótulo. Sem ela o prato
       fica com o marcador âmbar mesmo depois de a troca tocar. */
    const char *img = strstr(json, "\"image\"");
    if (img) qobuz_json_str(img, "small", c->capa, (int)sizeof(c->capa));
    c->hires = strstr(json, "\"hires\":true") != NULL;
    return true;
}

/* A NOTA de um candidato, 0..100. Abaixo de QB_CASA_PISO não vale trocar. */
#define QB_CASA_PISO 60

static int nota_casamento(const QobuzCasamento *c, const char *tit_n,
                          const char *art_n, int segundos)
{
    char ct[320], ca[320];
    normaliza(c->titulo, ct, sizeof(ct));
    normaliza(c->artista, ca, sizeof(ca));

    int pt = parecenca(tit_n, ct);
    if (pt == 0) return 0;                 /* título diferente: nem é a música */
    int pa = art_n[0] ? parecenca(art_n, ca) : 50;

    /* A DURAÇÃO decide qual GRAVAÇÃO. Três segundos é o que separa dois
       masters da mesma tomada; vinte já é outra performance. Sem duração
       local (arquivo sem tag legível) ela não pode nem ajudar nem atrapalhar
       — vale o neutro, e aí título e artista decidem sozinhos. */
    int pd = 50;
    if (segundos > 0 && c->segundos > 0) {
        int d = c->segundos - segundos;
        if (d < 0) d = -d;
        if      (d <= 2)  pd = 100;
        else if (d <= 5)  pd = 85;
        else if (d <= 12) pd = 55;
        else if (d <= 30) pd = 15;
        else              pd = 0;
    }
    return (pt * 30 + pa * 25 + pd * 45) / 100;
}

static QobuzCasamento g_casa;
static int            g_casa_n;        /* 1 achou, 0 não achou, <0 falhou */
static volatile int   g_casando;
static QobuzConfig    g_casa_cfg;
static char           g_casa_tit[192];
static char           g_casa_art[160];
static int            g_casa_seg;

static void casa_corpo(void)
{
    QobuzCasamento melhor;
    memset(&melhor, 0, sizeof(melhor));
    int melhor_nota = 0;
    g_motivo[0] = '\0';

    char termo[384], q[900];
    snprintf(termo, sizeof(termo), "%s %s", g_casa_art, g_casa_tit);
    urlenc(termo, q, sizeof(q));

    char url[1200];
    snprintf(url, sizeof(url),
             QB_API "track/search?query=%s&limit=25&app_id=%s",
             q, g_casa_cfg.app_id);

    static char resp[96 * 1024];
    static char item[16 * 1024];
    if (pega(&g_casa_cfg, url, resp, (int)sizeof(resp)) != 0) {
        if (!g_motivo[0])
            snprintf(g_motivo, sizeof(g_motivo), "%s", "could not reach Qobuz");
        g_casa_n = -3;
        g_casando = 0;
        return;
    }

    char tit_n[320], art_n[320];
    normaliza(g_casa_tit, tit_n, sizeof(tit_n));
    normaliza(g_casa_art, art_n, sizeof(art_n));

    const char *itens = strstr(resp, "\"items\"");
    if (itens) {
        const char *p = itens;
        while ((p = itera_items(p)) != NULL) {
            const char *fim = fim_item(p);
            size_t len = (size_t)(fim - p);
            if (len >= sizeof(item)) len = sizeof(item) - 1;
            memcpy(item, p, len);
            item[len] = '\0';
            QobuzCasamento c;
            if (extrai_faixa(item, &c)) {
                int nota = nota_casamento(&c, tit_n, art_n, g_casa_seg);
                /* Empate desempata pelo HI-RES: se duas gravações são
                   igualmente a mesma música, a de 24 bits é a que se quer —
                   é literalmente o motivo de o botão existir. */
                if (nota > melhor_nota ||
                    (nota == melhor_nota && nota > 0 && c.hires && !melhor.hires)) {
                    melhor = c;
                    melhor.confianca = nota;
                    melhor_nota = nota;
                }
            }
            p = fim;
        }
    }

    if (melhor_nota >= QB_CASA_PISO) {
        g_casa = melhor;
        g_casa_n = 1;
    } else {
        memset(&g_casa, 0, sizeof(g_casa));
        g_casa_n = 0;
        /* Dizer QUASE é diferente de dizer nada: "achei, mas a duração não
           bate" manda a pessoa olhar se o arquivo é uma versão ao vivo, e
           isso é informação. Um "not found" seco não manda a lugar nenhum. */
        if (melhor_nota > 0)
            snprintf(g_motivo, sizeof(g_motivo),
                     "closest was \"%.60s\" — too different to swap",
                     melhor.titulo);
        else
            snprintf(g_motivo, sizeof(g_motivo), "%s",
                     "Qobuz has no track by that name");
    }
    g_casando = 0;
}

#ifdef __vita__
static int casa_thread(SceSize args, void *argp)
{
    (void)args; (void)argp;
    casa_corpo();
    return sceKernelExitDeleteThread(0);
}
#endif

int qobuz_casa_async(const QobuzConfig *cfg, const char *titulo,
                     const char *artista, int segundos)
{
    if (!cfg || !titulo || !titulo[0]) return -1;
    if (g_casando) return -1;
    if (!cfg->app_id[0] || !cfg->token[0]) return -2;
    g_casa_cfg = *cfg;
    snprintf(g_casa_tit, sizeof(g_casa_tit), "%.*s",
             (int)sizeof(g_casa_tit) - 1, titulo);
    snprintf(g_casa_art, sizeof(g_casa_art), "%.*s",
             (int)sizeof(g_casa_art) - 1, artista ? artista : "");
    g_casa_seg = segundos;
    g_casa_n = 0;
    memset(&g_casa, 0, sizeof(g_casa));
    g_casando = 1;
#ifdef __vita__
    SceUID th = sceKernelCreateThread("stylus_qcasa", casa_thread,
                                      PRIO_REDE, PILHA_REDE, 0, 0, NULL);
    if (th < 0) { g_casando = 0; return -1; }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_casando = 0;
        return -1;
    }
#else
    casa_corpo();
#endif
    return 0;
}

void qobuz_casa_estado(QobuzCasamento *out, int *estado, bool *ativo)
{
    if (ativo)  *ativo = g_casando != 0;
    if (estado) *estado = g_casa_n;
    if (out)    *out = g_casa;
}

/* ── GET FLAC: formato e estado ────────────────────────────────────────────

   O format da sessão é escolhido aqui (hi-res quando o catálogo tem
   24 bits, senão FLAC 16/44,1) e guardado para case 28 ler quando
   qobuz_abre_async terminar. Sem isto, case 22 (loja) usaria o formato
   configurado — que é MP3, e o botão GET FLAC promete lossless. */

static bool g_getflac_pendente;
static int  g_getflac_fmt;

void qobuz_setflac_pending(int fmt)
{
    g_getflac_pendente = true;
    g_getflac_fmt = fmt;
}

bool qobuz_getflac_pending(void)
{
    return g_getflac_pendente;
}

int qobuz_getflac_fmt(void)
{
    return g_getflac_fmt;
}

void qobuz_getflac_done(void)
{
    g_getflac_pendente = false;
}
