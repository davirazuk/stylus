#include "net.h"

#include <stdio.h>
#include <string.h>

#ifdef __vita__
/* ------------------------- Caminho Vita -------------------------
   Estruturalmente previsto, MAS NÃO validado em hardware (não há Vita
   conectado aqui). Usaria sceHttp* de <psp2/net/http.h> com os módulos de
   rede já carregados. Sem validação, devolve offline e deixa a fila do
   last.fm intacta — o banco local standalone continua funcionando sempre. */
#include <psp2/net/http.h>

int net_post(const char *url, const char *body, char *resp, int resplen)
{
    (void)url;
    (void)body;
    (void)resp;
    (void)resplen;
    /* TODO(vita): implementar via sceHttpInit/sceHttpCreateTemplate/
       sceHttpCreateConnectionWithURL com certificados — requer o aparelho
       para testar. Enquanto isso, sem rede → cai no offline (fila guarda). */
    return -1;
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
