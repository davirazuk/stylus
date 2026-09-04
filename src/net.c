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

int net_post(const char *url, const char *body, char *resp, int resplen)
{
    if (!url || !body || !resp || resplen <= 0) return -1;
    resp[0] = '\0';

    if (rede_de_pe() != 0) return -1;
    if (!tem_link())       return -1;

    int tmpl = -1, conn = -1, req = -1, ret = -1;

    tmpl = sceHttpCreateTemplate("vitastylus/1.0 (PS Vita)",
                                 SCE_HTTP_VERSION_1_1, 1);
    if (tmpl < 0) goto fim;
    sceHttpSetConnectTimeOut(tmpl, ESPERA_US);
    sceHttpSetSendTimeOut(tmpl, ESPERA_US);
    sceHttpSetRecvTimeOut(tmpl, ESPERA_US);

    conn = sceHttpCreateConnectionWithURL(tmpl, url, 0);
    if (conn < 0) goto fim;

    unsigned int n = (unsigned int)strlen(body);
    req = sceHttpCreateRequestWithURL(conn, SCE_HTTP_METHOD_POST, url, n);
    if (req < 0) goto fim;
    sceHttpAddRequestHeader(req, "Content-Type",
                            "application/x-www-form-urlencoded",
                            SCE_HTTP_HEADER_OVERWRITE);

    if (sceHttpSendRequest(req, body, n) < 0) goto fim;

    int http = 0;
    if (sceHttpGetStatusCode(req, &http) < 0) goto fim;

    /* A resposta importa: o lastfm.c precisa distinguir "aceito" de um erro
       que veio com 200. Lê até encher o buffer e para — o resto não faz
       falta, e um servidor teimoso não pode ditar quanto se lê. */
    int usado = 0;
    for (;;) {
        int r = sceHttpReadData(req, resp + usado, (unsigned)(resplen - 1 - usado));
        if (r <= 0) break;
        usado += r;
        if (usado >= resplen - 1) break;
    }
    resp[usado] = '\0';

    /* Mesmo critério do caminho PC: 5xx é falha de servidor (vale insistir
       depois, a fila fica); 4xx o lastfm.c examina, porque "faixa recusada"
       não deve prender a fila para sempre. */
    ret = (http >= 200 && http < 500) ? 0 : -1;

fim:
    if (req  >= 0) sceHttpDeleteRequest(req);
    if (conn >= 0) sceHttpDeleteConnection(conn);
    if (tmpl >= 0) sceHttpDeleteTemplate(tmpl);
    return ret;
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
