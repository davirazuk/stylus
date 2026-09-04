#include "qobuz.h"

#include "md5.h"
#include "net.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define QB_API "https://www.qobuz.com/api.json/0.2/"

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

static void urlenc(const char *s, char *out, size_t cap)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t o = 0;
    for (; s && *s && o + 4 < cap; s++) {
        unsigned char c = (unsigned char)*s;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~')
            out[o++] = (char)c;
        else {
            out[o++] = '%';
            out[o++] = hex[c >> 4];
            out[o++] = hex[c & 15];
        }
    }
    out[o] = '\0';
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
    return net_get(url, hdrs, resp, cap);
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

int qobuz_busca(const QobuzConfig *cfg, const char *termo,
                QobuzAlbum *out, int max)
{
    if (!cfg || !termo || !out || max <= 0) return -1;
    if (!cfg->app_id[0]) return -2;

    char q[512];
    urlenc(termo, q, sizeof(q));
    char url[1024];
    snprintf(url, sizeof(url),
             QB_API "album/search?query=%s&limit=%d&app_id=%s",
             q, max > 30 ? 30 : max, cfg->app_id);

    static char resp[96 * 1024];
    if (pega(cfg, url, resp, (int)sizeof(resp)) != 0) return -3;

    const char *itens = strstr(resp, "\"items\"");
    if (!itens) return 0;
    int n = 0;
    const char *p = itens;
    while (n < max && (p = proximo_item(p)) != NULL) {
        const char *fim = fim_item(p);
        size_t len = (size_t)(fim - p);
        static char item[16 * 1024];
        if (len >= sizeof(item)) len = sizeof(item) - 1;
        memcpy(item, p, len);
        item[len] = '\0';

        QobuzAlbum *a = &out[n];
        memset(a, 0, sizeof(*a));
        if (!qobuz_json_str(item, "id", a->id, (int)sizeof(a->id))) { p = fim; continue; }
        qobuz_json_str(item, "title", a->titulo, (int)sizeof(a->titulo));
        /* O artista vem dentro de "artist":{"name":...}; procurar "name" a
           partir do "artist" é o que evita casar com o nome da gravadora. */
        const char *art = strstr(item, "\"artist\"");
        if (art) qobuz_json_str(art, "name", a->artista, (int)sizeof(a->artista));
        qobuz_json_int(item, "tracks_count", &a->faixas);
        /* booleano: o extrator devolve texto/número, não true/false, então
           a pergunta é feita direto. */
        a->hires = strstr(item, "\"hires\":true") != NULL;
        n++;
        p = fim;
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
                 n == 0 ? "o disco não trouxe faixas" : "não deu para falar com o Qobuz");
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
        snprintf(g_job.erro, sizeof(g_job.erro), "não deu para criar a pasta");
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
        snprintf(g_job.erro, sizeof(g_job.erro), "nenhuma faixa baixou");
        g_job.falhou = true;
    } else {
        if (erros > 0)
            snprintf(g_job.erro, sizeof(g_job.erro),
                     "%d faixa%s não veio", erros, erros == 1 ? "" : "s");
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
                                      0x10000100 + 32, 256 * 1024, 0, 0, NULL);
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

static void busca_corpo(void)
{
    int n = qobuz_busca(&g_bus_cfg, g_bus_termo, g_res, QB_MAX_RES);
    g_nres = n;                 /* <0 fica <0: a tela distingue "nada achado"
                                   de "não deu para perguntar" */
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
    if (!cfg || !termo || !termo[0] || g_buscando) return -1;
    if (!cfg->app_id[0]) return -1;
    g_bus_cfg = *cfg;
    snprintf(g_bus_termo, sizeof(g_bus_termo), "%.*s",
             (int)sizeof(g_bus_termo) - 1, termo);
    g_nres = 0;
    g_buscando = 1;
#ifdef __vita__
    SceUID th = sceKernelCreateThread("stylus_qbusca", busca_thread,
                                      0x10000100 + 32, 256 * 1024, 0, 0, NULL);
    if (th < 0) { g_buscando = 0; return -1; }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_buscando = 0;
        return -1;
    }
#else
    busca_corpo();
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
