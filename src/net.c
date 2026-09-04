#include "net.h"

#include <stdio.h>
#include <stdbool.h>
#include <string.h>

#ifdef __vita__
/* ------------------------- Caminho Vita -------------------------

   Sobe do PRÓPRIO aparelho. O app é standalone: quem ouve no Vita não
   deveria precisar de um PC ligado para a escuta contar.

   O risco desta cadeia (sysmodule → sceNet → sceNetCtl → sceSsl → sceHttp)
   não é "não scrobblou" — é travar o aparelho. Três regras contêm isso:

     1. NADA acontece no arranque. A subida é PREGUIÇOSA: a rede só é
        iniciada na primeira vez que existe algo para enviar E existe
        credencial. Um app sem last.fm configurado nunca toca em rede, e
        portanto nunca pode ser travado por ela.
     2. Falhou de vez, morreu. Se a inicialização não vinga, `g_rede` vai a
        -1 e NUNCA mais se tenta. Um erro vira uma decepção silenciosa, não
        um laço de tentativas dentro de um aparelho tocando música.
     3. Tudo tem prazo. Conexão, envio e leitura têm timeout curto; sem
        isso, um AP que aceita a conexão e não responde segura a thread
        para sempre.

   Falta de Wi-Fi NÃO mata: `sceNetCtlInetGetState` é conferido a cada
   tentativa, e "desconectado" devolve -1 sem queimar o caminho — a fila
   continua no cartão e sai quando a rede voltar.

   Sobre o HTTPS: a lista de autoridades do Vita é de 2011 e não tem as
   raízes que assinam o ws.audioscrobbler.com hoje; com a verificação
   ligada, TODO handshake falha e o recurso simplesmente não existe. Ela é
   desligada abaixo, de propósito. O que trafega é um scrobble assinado com
   a chave de sessão do last.fm — nada de senha, e a chave já está no
   cartão. É uma troca consciente: sem ela, não há scrobble nenhum. */

#include <stdio.h>
#include <stdlib.h>

#include <psp2/kernel/threadmgr.h>
#include <psp2/net/http.h>
#include <psp2/net/net.h>
#include <psp2/net/netctl.h>
#include <psp2/sysmodule.h>

/* O SDK não declara isto em lugar nenhum, mas o libSceSsl_stub.a exporta. */
extern int sceSslInit(unsigned int poolSize);

#define POOL_NET   (512 * 1024)
#define POOL_SSL   (256 * 1024)
#define POOL_HTTP  ( 64 * 1024)
#define ESPERA_US  (10 * 1000 * 1000)   /* 10 s por etapa */

static int   g_rede;      /* 0 nunca tentou, 1 de pé, -1 morreu de vez */
static char *g_pool;      /* o pool do sceNet vive enquanto o app viver */

/* Devolve 0 quando dá para falar HTTP. Só é chamada com algo a enviar. */
static int rede_de_pe(void)
{
    if (g_rede) return g_rede > 0 ? 0 : -1;
    g_rede = -1;   /* pessimista desde já: qualquer saída daqui sem sucesso
                      explícito deixa a rede morta, inclusive um return no
                      meio que alguém acrescente depois */

    if (sceSysmoduleLoadModule(SCE_SYSMODULE_NET) < 0)   return -1;
    if (sceSysmoduleLoadModule(SCE_SYSMODULE_HTTP) < 0)  return -1;
    if (sceSysmoduleLoadModule(SCE_SYSMODULE_HTTPS) < 0) return -1;

    g_pool = malloc(POOL_NET);
    if (!g_pool) return -1;

    SceNetInitParam np;
    np.memory = g_pool;
    np.size   = POOL_NET;
    np.flags  = 0;
    /* Um retorno negativo aqui costuma ser "já iniciado" (o sistema pode ter
       subido a pilha por conta própria), e desistir nesse caso perderia o
       recurso à toa. Quem decide se dá para falar HTTP é o
       sceHttpCreateTemplate lá embaixo — esse não tem ambiguidade. */
    sceNetInit(&np);
    sceNetCtlInit();

    if (sceSslInit(POOL_SSL) < 0)  { /* idem: pode já estar de pé */ }
    if (sceHttpInit(POOL_HTTP) < 0) { /* idem */ }

    int t = sceHttpCreateTemplate("vitastylus/1.0 (PS Vita)",
                                  SCE_HTTP_VERSION_1_1, 1);
    if (t < 0) return -1;           /* aí sim: não há HTTP nesta máquina */
    sceHttpDeleteTemplate(t);

    sceHttpsDisableOption(SCE_HTTPS_FLAG_SERVER_VERIFY |
                          SCE_HTTPS_FLAG_CLIENT_VERIFY |
                          SCE_HTTPS_FLAG_CN_CHECK |
                          SCE_HTTPS_FLAG_NOT_AFTER_CHECK |
                          SCE_HTTPS_FLAG_NOT_BEFORE_CHECK |
                          SCE_HTTPS_FLAG_KNOWN_CA_CHECK);

    g_rede = 1;
    return 0;
}

/* Tem Wi-Fi AGORA? Conferido a cada envio, e um "não" nunca é definitivo. */
static bool tem_link(void)
{
    int estado = 0;
    if (sceNetCtlInetGetState(&estado) < 0) return false;
    return estado == SCE_NETCTL_STATE_CONNECTED;
}

/* Monta e envia um pedido. Devolve o id do pedido (>=0) com a resposta já
   começada, ou -1. Quem chama é dono de fechar tudo pelo `fecha`.

   Está fatorado porque GET e POST diferem em três linhas e mais nada — e as
   outras trinta (prazos, cabeçalhos, a ordem de destruição) são exatamente
   o tipo de coisa que diverge entre duas cópias e vira um vazamento de
   conexão que só aparece depois de vinte pedidos. */
struct Pedido { int tmpl, conn, req; };

static void fecha(struct Pedido *p)
{
    if (p->req  >= 0) sceHttpDeleteRequest(p->req);
    if (p->conn >= 0) sceHttpDeleteConnection(p->conn);
    if (p->tmpl >= 0) sceHttpDeleteTemplate(p->tmpl);
    p->req = p->conn = p->tmpl = -1;
}

static int abre(struct Pedido *p, const char *url, int metodo,
                const char *body, const char *const *headers)
{
    p->tmpl = p->conn = p->req = -1;
    if (rede_de_pe() != 0) return -1;
    if (!tem_link())       return -1;

    p->tmpl = sceHttpCreateTemplate("vitastylus/1.0 (PS Vita)",
                                    SCE_HTTP_VERSION_1_1, 1);
    if (p->tmpl < 0) return -1;
    sceHttpSetConnectTimeOut(p->tmpl, ESPERA_US);
    sceHttpSetSendTimeOut(p->tmpl, ESPERA_US);
    sceHttpSetRecvTimeOut(p->tmpl, ESPERA_US);

    p->conn = sceHttpCreateConnectionWithURL(p->tmpl, url, 0);
    if (p->conn < 0) { fecha(p); return -1; }

    unsigned int n = body ? (unsigned int)strlen(body) : 0;
    p->req = sceHttpCreateRequestWithURL(p->conn, metodo, url, n);
    if (p->req < 0) { fecha(p); return -1; }

    if (body)
        sceHttpAddRequestHeader(p->req, "Content-Type",
                                "application/x-www-form-urlencoded",
                                SCE_HTTP_HEADER_OVERWRITE);
    for (int i = 0; headers && headers[i]; i++) {
        const char *dp = strchr(headers[i], ':');
        if (!dp) continue;
        char nome[64];
        size_t ln = (size_t)(dp - headers[i]);
        if (ln >= sizeof(nome)) continue;
        memcpy(nome, headers[i], ln);
        nome[ln] = '\0';
        const char *val = dp + 1;
        while (*val == ' ') val++;
        sceHttpAddRequestHeader(p->req, nome, val, SCE_HTTP_HEADER_OVERWRITE);
    }

    if (sceHttpSendRequest(p->req, body, n) < 0) { fecha(p); return -1; }
    return 0;
}

/* Mesmo critério nos dois caminhos: 5xx é falha de servidor (vale insistir
   depois); 4xx quem chamou examina, porque "recusado" não deve virar um laço
   de tentativas eternas. */
static int status_ok(int http) { return http >= 200 && http < 500; }

static int corpo_para_buffer(int req, char *resp, int resplen)
{
    int usado = 0;
    for (;;) {
        int r = sceHttpReadData(req, resp + usado, (unsigned)(resplen - 1 - usado));
        if (r <= 0) break;
        usado += r;
        if (usado >= resplen - 1) break;
    }
    resp[usado] = '\0';
    return usado;
}

int net_post(const char *url, const char *body, char *resp, int resplen)
{
    if (!url || !body || !resp || resplen <= 0) return -1;
    resp[0] = '\0';

    struct Pedido p;
    if (abre(&p, url, SCE_HTTP_METHOD_POST, body, NULL) != 0) return -1;

    int http = 0, ret = -1;
    if (sceHttpGetStatusCode(p.req, &http) >= 0) {
        corpo_para_buffer(p.req, resp, resplen);
        ret = status_ok(http) ? 0 : -1;
    }
    fecha(&p);
    return ret;
}

int net_get(const char *url, const char *const *headers, char *resp, int resplen)
{
    if (!url || !resp || resplen <= 0) return -1;
    resp[0] = '\0';

    struct Pedido p;
    if (abre(&p, url, SCE_HTTP_METHOD_GET, NULL, headers) != 0) return -1;

    int http = 0, ret = -1;
    if (sceHttpGetStatusCode(p.req, &http) >= 0) {
        corpo_para_buffer(p.req, resp, resplen);
        ret = status_ok(http) ? 0 : -1;
    }
    fecha(&p);
    return ret;
}

int net_download(const char *url, const char *const *headers, const char *path,
                 void (*prog)(void *ud, long feitos, long total), void *ud)
{
    if (!url || !path) return -1;

    struct Pedido p;
    if (abre(&p, url, SCE_HTTP_METHOD_GET, NULL, headers) != 0) return -1;

    int http = 0;
    if (sceHttpGetStatusCode(p.req, &http) < 0 || http < 200 || http >= 300) {
        fecha(&p);
        return -1;
    }
    unsigned long long total = 0;
    int tem_total = (sceHttpGetResponseContentLength(p.req, &total) >= 0);

    /* Grava num parcial e só renomeia no fim — ver a nota no net.h. */
    char tmp[512];
    snprintf(tmp, sizeof(tmp), "%s.parcial", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) { fecha(&p); return -1; }

    static char buf[32 * 1024];
    long feitos = 0;
    int ok = 1;
    for (;;) {
        int r = sceHttpReadData(p.req, buf, sizeof(buf));
        if (r < 0) { ok = 0; break; }
        if (r == 0) break;
        if (fwrite(buf, 1, (size_t)r, f) != (size_t)r) { ok = 0; break; }
        feitos += r;
        if (prog) prog(ud, feitos, tem_total ? (long)total : -1);
    }
    fclose(f);
    fecha(&p);

    /* Um arquivo que chegou curto é um arquivo quebrado, e a estante não pode
       recebê-lo: melhor não existir do que existir pela metade. */
    if (ok && tem_total && total > 0 && feitos != (long)total) ok = 0;
    if (!ok) { remove(tmp); return -1; }
    remove(path);
    return rename(tmp, path) == 0 ? 0 : -1;
}

#else
/* ------------------------- Caminho PC (teste) -------------------------
   Usa libcurl: valida o upload real do last.fm daqui da máquina. */

#include <curl/curl.h>

static size_t write_cb(char *ptr, size_t n, size_t m, void *ud)
{
    (void)ud;
    (void)ptr;
    return n * m;
}

/* Recolhe o corpo num buffer de tamanho fixo, cortando o excesso: o mesmo
   contrato do caminho do Vita, para que um teste aqui signifique alguma
   coisa lá. */
struct Balde { char *p; int cap; int n; };

static size_t balde_cb(char *ptr, size_t n, size_t m, void *ud)
{
    struct Balde *b = ud;
    size_t bytes = n * m;
    if (b && b->p) {
        int cabe = b->cap - 1 - b->n;
        if (cabe > 0) {
            int q = (int)bytes < cabe ? (int)bytes : cabe;
            memcpy(b->p + b->n, ptr, (size_t)q);
            b->n += q;
            b->p[b->n] = '\0';
        }
    }
    return bytes;      /* sempre "consumiu tudo": abortar aqui vira erro */
}

static int curl_faz(const char *url, const char *const *headers,
                    const char *body, char *resp, int resplen)
{
    CURL *c = curl_easy_init();
    if (!c) return -1;
    struct curl_slist *hdrs = NULL;
    if (body)
        hdrs = curl_slist_append(hdrs, "Content-Type: application/x-www-form-urlencoded");
    for (int i = 0; headers && headers[i]; i++)
        hdrs = curl_slist_append(hdrs, headers[i]);

    struct Balde b = { resp, resplen, 0 };
    if (resp && resplen > 0) resp[0] = '\0';

    curl_easy_setopt(c, CURLOPT_URL, url);
    if (body) {
        curl_easy_setopt(c, CURLOPT_POST, 1L);
        curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    }
    if (hdrs) curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, balde_cb);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &b);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 20L);

    CURLcode res = curl_easy_perform(c);
    long http = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &http);
    if (hdrs) curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);

    if (res != CURLE_OK) return -1;
    return (http >= 200 && http < 500) ? 0 : -1;
}

int net_get(const char *url, const char *const *headers, char *resp, int resplen)
{
    if (!url || !resp || resplen <= 0) return -1;
    return curl_faz(url, headers, NULL, resp, resplen);
}

struct Baixa {
    FILE *f;
    long feitos;
    void (*prog)(void *, long, long);
    void *ud;
};

static size_t baixa_cb(char *ptr, size_t n, size_t m, void *ud)
{
    struct Baixa *d = ud;
    size_t bytes = n * m;
    if (fwrite(ptr, 1, bytes, d->f) != bytes) return 0;   /* 0 aborta */
    d->feitos += (long)bytes;
    return bytes;
}

static int baixa_prog(void *ud, curl_off_t dltotal, curl_off_t dlnow,
                      curl_off_t ul, curl_off_t un)
{
    struct Baixa *d = ud;
    (void)ul; (void)un;
    if (d->prog) d->prog(d->ud, (long)dlnow, dltotal > 0 ? (long)dltotal : -1);
    return 0;
}

int net_download(const char *url, const char *const *headers, const char *path,
                 void (*prog)(void *ud, long feitos, long total), void *ud)
{
    if (!url || !path) return -1;
    char tmp[512];
    snprintf(tmp, sizeof(tmp), "%s.parcial", path);
    FILE *f = fopen(tmp, "wb");
    if (!f) return -1;

    CURL *c = curl_easy_init();
    if (!c) { fclose(f); remove(tmp); return -1; }
    struct curl_slist *hdrs = NULL;
    for (int i = 0; headers && headers[i]; i++)
        hdrs = curl_slist_append(hdrs, headers[i]);

    struct Baixa d = { f, 0, prog, ud };
    curl_easy_setopt(c, CURLOPT_URL, url);
    if (hdrs) curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, baixa_cb);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &d);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, baixa_prog);
    curl_easy_setopt(c, CURLOPT_XFERINFODATA, &d);
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);

    CURLcode res = curl_easy_perform(c);
    long http = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &http);
    if (hdrs) curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);
    fclose(f);

    if (res != CURLE_OK || http < 200 || http >= 300) { remove(tmp); return -1; }
    remove(path);
    return rename(tmp, path) == 0 ? 0 : -1;
}

int net_post(const char *url, const char *body, char *resp, int resplen)
{
    if (!url || !body) return -1;
    if (resplen <= 0) return -1;
    resp[0] = '\0';

    CURL *c = curl_easy_init();
    if (!c) return -1;
    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/x-www-form-urlencoded");

    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_POST, 1L);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 15L);

    CURLcode res = curl_easy_perform(c);
    long http = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &http);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);

    if (res != CURLE_OK) return -1;
    return (http >= 200 && http < 500) ? 0 : -1;
}

#endif
