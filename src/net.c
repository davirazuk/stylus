#include "net.h"

#include <stdio.h>
#include <stdbool.h>
#include <string.h>

/* O MOTIVO DA ÚLTIMA FALHA — comum ao caminho do Vita e ao do PC.

   Mora aqui, e não em cada chamador, porque era isso que faltava: cada tela
   inventava a própria frase ("is the Wi-Fi on?") para causas que não tinham
   nada a ver uma com a outra. Só é limpo quando uma chamada dá CERTO; assim
   a frase da falha que matou a rede sobrevive às tentativas seguintes, que
   voltam memorizadas sem chegar a falar com ninguém. */
static char g_net_motivo[128];
static int  g_net_sistema;   /* código cru do sistema (0x8043xxxx no Vita) */
static int  g_net_http;      /* último status HTTP lido, 0 se nenhum */

const char *net_motivo(void)       { return g_net_motivo; }
int         net_erro_sistema(void) { return g_net_sistema; }
int         net_http_ultimo(void)  { return g_net_http; }

/* Anota e DEVOLVE o código, para caber num `return anota(...)`. */
/* Percent-encoding. Veio do `qobuz.c`, onde era `static`, quando o SoundCloud
   passou a montar a mesma busca: duas cópias da mesma regra é por onde elas
   começam a divergir, e esta é de REDE. */
void net_urlenc(const char *s, char *out, size_t cap)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t o = 0;
    if (!out || cap == 0) return;
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

static int anota(int codigo, int sistema, const char *frase)
{
    g_net_sistema = sistema;
    snprintf(g_net_motivo, sizeof(g_net_motivo), "%s", frase ? frase : "");
    return codigo;
}

/* Deu certo: a frase antiga não pode ficar para trás mentindo. */
static void deu_certo(int http)
{
    g_net_motivo[0] = '\0';
    g_net_sistema = 0;
    g_net_http = http;
}

/* ------------------------- UMA PILHA SÓ, E É O CURL -------------------------

   HISTÓRIA CURTA: este arquivo falava sceHttp no aparelho e libcurl no PC.
   O sceHttp vai pelo sceSsl do sistema, cujo teto é TLS 1.0 — o enum do SDK
   (SceHttpSslVersion) para em SCE_HTTPS_TLSV1. Medido desta máquina:

     ws.audioscrobbler.com  aceita AES128-SHA    -> e o last.fm SEMPRE funcionou
     www.qobuz.com          só TLS 1.2 com AEAD  -> e a busca nunca trouxe nada
     lrclib.net             cert ECDSA/ChaCha20  -> e letra nenhuma apareceu

   A lista bate, uma a uma, com o que funciona e o que não funciona. E o
   NAVEGADOR NATIVO do aparelho também não abre site nenhum: a mesma
   assinatura, num programa que não é nosso.

   O que já foi descartado com prova, para ninguém refazer: não é a API (a
   requisição exata devolve HTTP 200 e 14 KB), não é o parser (a busca de
   verdade tira 12 álbuns da resposta de verdade), não é o Wi-Fi (o PKGj
   baixa), não é o teclado (ele abre).

   O vitasdk traz libcurl com OpenSSL para Vita. Usá-lo aqui não SOMA uma
   segunda pilha — TIRA uma: o PC já era curl, e agora os dois caminhos são o
   mesmo código, o que faz um teste daqui valer lá.

   Do sceHttp fica o que ele tinha de bom: a subida PREGUIÇOSA (nada de rede
   no arranque), o "falhou de vez, morreu" e prazo curto em toda etapa. */

#include <curl/curl.h>
#include <stdlib.h>

#ifdef __vita__
#include <psp2/net/net.h>
#include <psp2/net/netctl.h>
#include <psp2/sysmodule.h>

#define POOL_NET (512 * 1024)
static char *g_pool;        /* o pool do sceNet vive enquanto o app viver */

/* O curl do Vita fala pelos sockets do sceNet: sem isto de pé, todo
   curl_easy_perform falha antes de tocar na rede. */
static int sobe_plataforma(void)
{
    int rc = sceSysmoduleLoadModule(SCE_SYSMODULE_NET);
    if (rc < 0) return anota(NET_E_MODULO, rc, "the net module did not load");

    g_pool = malloc(POOL_NET);
    if (!g_pool) return anota(NET_E_MODULO, 0, "no memory for the net pool");

    SceNetInitParam np;
    np.memory = g_pool;
    np.size   = POOL_NET;
    np.flags  = 0;
    /* Negativo aqui costuma ser "já iniciado" — o sistema pode ter subido a
       pilha sozinho, e desistir nesse caso perderia o recurso à toa. */
    sceNetInit(&np);
    sceNetCtlInit();
    return 0;
}

/* Tem Wi-Fi AGORA? Conferido a cada envio, e um "não" nunca é definitivo:
   a fila continua no cartão e sai quando a rede voltar. */
static bool tem_link(void)
{
    int estado = 0;
    if (sceNetCtlInetGetState(&estado) < 0) return false;
    return estado == SCE_NETCTL_STATE_CONNECTED;
}
#else
static int  sobe_plataforma(void) { return 0; }
static bool tem_link(void) { return true; }
#endif

static int g_rede;       /* 0 nunca tentou, 1 de pé, -1 morreu de vez */
static int g_rede_cod;   /* com que código morreu, para repetir a resposta */

/* Devolve 0 quando dá para falar HTTP. Só é chamada com algo a enviar.

   O pessimismo é de propósito: `g_rede` vai a -1 ANTES da tentativa e só
   volta a 1 com sucesso explícito, de modo que um `return` acrescentado no
   meio não deixe a rede meio viva. */
static int rede_de_pe(void)
{
    if (g_rede) return g_rede > 0 ? 0 : g_rede_cod;
    g_rede = -1;
    int r = sobe_plataforma();
    if (r == 0 && curl_global_init(CURL_GLOBAL_ALL) != 0)
        r = anota(NET_E_MODULO, 0, "curl did not start");
    if (r == 0) g_rede = 1;
    else        g_rede_cod = r;
    return r;
}

/* A porta de entrada de TODA chamada: pilha de pé e link presente. */
static int rede_ok(void)
{
    int r = rede_de_pe();
    if (r != 0) return r;
    if (!tem_link())
        return anota(NET_E_SEMLINK, 0, "no Wi-Fi connection right now");
    return 0;
}

/* As opções que TODA transferência quer.

   A verificação de certificado fica DESLIGADA no aparelho, de propósito e
   pelo mesmo motivo de antes: a lista de autoridades do Vita é de 2011 e não
   assina o que se usa hoje. Era isso que o sceHttp já fazia com
   sceHttpsDisableOption; a troca de pilha não muda a escolha. No PC a
   verificação fica LIGADA — lá não há motivo para abrir mão dela. */
static void opcoes_comuns(CURL *c)
{
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 15L);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);
#ifdef __vita__
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYHOST, 0L);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "vitastylus/1.0 (PS Vita)");
#endif
}


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
    int pronta = rede_ok();
    if (pronta != 0) return pronta;

    CURL *c = curl_easy_init();
    if (!c) return anota(NET_E_MODULO, 0, "curl handle refused");
    opcoes_comuns(c);
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

    /* Os MESMOS códigos do caminho do Vita: um teste que roda aqui só vale
       alguma coisa se a classificação da falha for a mesma lá. */
    if (res != CURLE_OK)
        return anota(NET_E_ENVIO, (int)res, curl_easy_strerror(res));
    if (http >= 200 && http < 500) { deu_certo((int)http); return 0; }

    g_net_http = (int)http;
    char frase[64];
    snprintf(frase, sizeof(frase), "the server answered HTTP %ld", http);
    return anota(NET_E_HTTP, 0, frase);
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

    int pronta = rede_ok();
    if (pronta != 0) { fclose(f); remove(tmp); return pronta; }

    CURL *c = curl_easy_init();
    if (!c) { fclose(f); remove(tmp);
              return anota(NET_E_MODULO, 0, "curl handle refused"); }
    opcoes_comuns(c);
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

    int pronta = rede_ok();
    if (pronta != 0) return pronta;

    CURL *c = curl_easy_init();
    if (!c) return anota(NET_E_MODULO, 0, "curl handle refused");
    opcoes_comuns(c);
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

    /* Os MESMOS códigos do caminho do Vita: um teste que roda aqui só vale
       alguma coisa se a classificação da falha for a mesma lá. */
    if (res != CURLE_OK)
        return anota(NET_E_ENVIO, (int)res, curl_easy_strerror(res));
    if (http >= 200 && http < 500) { deu_certo((int)http); return 0; }

    g_net_http = (int)http;
    char frase[64];
    snprintf(frase, sizeof(frase), "the server answered HTTP %ld", http);
    return anota(NET_E_HTTP, 0, frase);
}

/* ---------- leitura aos poucos, no PC (ver a nota no net.h) ----------

   Aqui é a interface MULTI do curl, e não a easy: a easy só sabe empurrar o
   corpo inteiro por um callback, e o que se quer é PUXAR. O laço abaixo só
   roda o curl quando o balde está vazio, então o callback nunca recebe mais
   do que cabe (o curl entrega no máximo CURL_MAX_WRITE_SIZE por vez). */

#define BALDE_CAP (256 * 1024)

struct NetStream {
    CURLM *m;
    CURL *e;
    struct curl_slist *hdrs;
    unsigned char balde[BALDE_CAP];
    size_t ini, fim;      /* [ini, fim) é o que ainda não foi lido */
    int vivos;            /* transferências ainda correndo */
    int erro;
};

/* COLHE O RESULTADO assim que a transferência termina, e guarda.

   Aqui morava um defeito meu, e o teste de fluxo o pegou: o resultado só era
   consultado no instante em que `vivos` virava 0 E o balde estava vazio. Se a
   última volta trouxe bytes junto com o fim, o leitor entregava esses bytes e,
   na chamada seguinte, via `vivos == 0` com o balde vazio e devolvia 0 — fim
   de faixa — sem NUNCA perguntar por que a transferência acabou. Uma conexão
   derrubada no meio virava "a música acabou", que é exatamente o que a fonte
   de rede inteira existe para não fazer.

   Passava ou não conforme o tamanho do último pedaço. Um teste que passa por
   sorte é pior que um que reprova. */
static void colhe_resultado(NetStream *s)
{
    CURLMsg *msg;
    int rest = 0;
    while ((msg = curl_multi_info_read(s->m, &rest)))
        if (msg->msg == CURLMSG_DONE && msg->data.result != CURLE_OK)
            s->erro = 1;
}

static size_t fluxo_write(char *ptr, size_t n, size_t m, void *ud)
{
    NetStream *s = ud;
    size_t bytes = n * m;
    if (s->fim + bytes > BALDE_CAP) return 0;   /* estoura → curl aborta */
    memcpy(s->balde + s->fim, ptr, bytes);
    s->fim += bytes;
    return bytes;
}

NetStream *net_stream_open(const char *url, const char *const *headers,
                           long long de, long long *total,
                           char *erro, int erolen)
{
    if (total) *total = -1;
    if (erro && erolen > 0) erro[0] = '\0';
    if (!url || !url[0]) return NULL;

    if (rede_ok() != 0) {
        if (erro && erolen > 0) snprintf(erro, (size_t)erolen, "%s", net_motivo());
        return NULL;
    }

    NetStream *s = calloc(1, sizeof(*s));
    if (!s) return NULL;
    s->m = curl_multi_init();
    s->e = curl_easy_init();
    if (!s->m || !s->e) { net_stream_close(s); return NULL; }
    opcoes_comuns(s->e);

    for (int i = 0; headers && headers[i]; i++)
        s->hdrs = curl_slist_append(s->hdrs, headers[i]);

    curl_easy_setopt(s->e, CURLOPT_URL, url);
    curl_easy_setopt(s->e, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(s->e, CURLOPT_MAXREDIRS, 5L);
    curl_easy_setopt(s->e, CURLOPT_CONNECTTIMEOUT, 15L);
    curl_easy_setopt(s->e, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(s->e, CURLOPT_USERAGENT, "vitastylus/1.0");
    curl_easy_setopt(s->e, CURLOPT_WRITEFUNCTION, fluxo_write);
    curl_easy_setopt(s->e, CURLOPT_WRITEDATA, s);
    if (s->hdrs) curl_easy_setopt(s->e, CURLOPT_HTTPHEADER, s->hdrs);
    if (de > 0) {
        char r[64];
        snprintf(r, sizeof(r), "%lld-", de);
        curl_easy_setopt(s->e, CURLOPT_RANGE, r);
    }
    curl_multi_add_handle(s->m, s->e);
    s->vivos = 1;

    /* Roda até os cabeçalhos chegarem (o primeiro corpo, ou o fim). Só
       depois disso o status e o tamanho existem. */
    while (s->vivos && s->fim == 0 && !s->erro) {
        int n = 0;
        if (curl_multi_perform(s->m, &s->vivos) != CURLM_OK) { s->erro = 1; break; }
        if (!s->vivos) colhe_resultado(s);
        else if (s->fim == 0) curl_multi_poll(s->m, NULL, 0, 200, &n);
    }

    long http = 0;
    curl_easy_getinfo(s->e, CURLINFO_RESPONSE_CODE, &http);
    /* ABRIU é sobre o CABEÇALHO, não sobre a transferência inteira.

       Uma conexão que responde 200 e cai no meio ABRIU: os bytes que já
       chegaram são música boa, e quem lê tem direito a eles antes de saber
       que a rede caiu — o erro sai da leitura seguinte, quando não houver
       mais nada para entregar. Recusar a abertura por causa do `erro` jogava
       fora os ~42 KB que o servidor mandou antes de fechar, e o teste de
       fluxo reprovava com "chegaram 0 de 128023 bytes".

       O que faz a abertura falhar é o status estar errado — um 404 tem corpo,
       e o corpo do 404 não é áudio — ou não ter havido resposta nenhuma. */
    int esperado = (de > 0) ? 206 : 200;
    if (http != esperado && !(de == 0 && http == 206)) {
        if (erro && erolen > 0) {
            if (http) snprintf(erro, (size_t)erolen, "HTTP %ld", http);
            else      snprintf(erro, (size_t)erolen, "no network");
        }
        net_stream_close(s);
        return NULL;
    }
    if (total) {
        curl_off_t cl = -1;
        curl_easy_getinfo(s->e, CURLINFO_CONTENT_LENGTH_DOWNLOAD_T, &cl);
        if (cl > 0) *total = (long long)cl + de;
    }
    return s;
}

long net_stream_read(NetStream *s, void *buf, size_t n)
{
    if (!s || !buf || n == 0) return -1;
    for (;;) {
        /* O QUE JÁ CHEGOU SAI PRIMEIRO, mesmo que a conexão tenha caído: os
           bytes recebidos antes da queda são música boa, e jogá-los fora
           perderia o fim do que dava para ouvir. O erro sai na chamada
           seguinte, quando não houver mais nada para entregar. */
        size_t tem = s->fim - s->ini;
        if (tem > 0) {
            size_t take = tem < n ? tem : n;
            memcpy(buf, s->balde + s->ini, take);
            s->ini += take;
            if (s->ini == s->fim) s->ini = s->fim = 0;
            return (long)take;
        }
        if (s->erro) return -1;
        if (!s->vivos) return 0;                    /* acabou de verdade */
        int nf = 0;
        if (curl_multi_perform(s->m, &s->vivos) != CURLM_OK) { s->erro = 1; continue; }
        /* Sempre que a transferência acaba, PERGUNTA por quê — tenha ou não
           trazido bytes nesta volta. Ver a nota no colhe_resultado. */
        if (!s->vivos) colhe_resultado(s);
        else if (s->fim == 0) curl_multi_poll(s->m, NULL, 0, 200, &nf);
    }
}

void net_stream_close(NetStream *s)
{
    if (!s) return;
    if (s->m && s->e) curl_multi_remove_handle(s->m, s->e);
    if (s->e) curl_easy_cleanup(s->e);
    if (s->m) curl_multi_cleanup(s->m);
    if (s->hdrs) curl_slist_free_all(s->hdrs);
    free(s);
}

