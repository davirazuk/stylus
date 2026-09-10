#include "soundcloud.h"

#include "net.h"
#include "paths.h"     /* STYLUS_DATA_DIR: o rastro da busca vai para o cartão */
#include "qobuz.h"      /* qobuz_json_str: o leitor de JSON já existe, e dois
                           leitores de JSON no mesmo binário divergem */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SC_API "https://api-v2.soundcloud.com"

static char g_motivo[160];

const char *sc_motivo(void)
{
    return g_motivo[0] ? g_motivo : "no reason reported";
}

static int falha(const char *m)
{
    snprintf(g_motivo, sizeof(g_motivo), "%s", m);
    return -1;
}

int sc_config_load(ScConfig *c, const char *dir)
{
    if (!c) return 0;
    memset(c, 0, sizeof(*c));
    if (!dir) return 0;

    char caminho[512];
    snprintf(caminho, sizeof(caminho), "%s/soundcloud.config", dir);
    FILE *f = fopen(caminho, "r");
    if (!f) return 0;

    char linha[256];
    while (fgets(linha, sizeof(linha), f)) {
        char *nl = strpbrk(linha, "\r\n");
        if (nl) *nl = '\0';
        if (!strncmp(linha, "client_id=", 10)) {
            /* Um client_id do SoundCloud tem 32 caracteres. Copiar uma linha
               de 256 num campo de 64 truncaria em silêncio e a chave cortada
               daria "não achei a faixa" — que é indistinguível de faixa
               privada. Melhor recusar o que não pode ser uma chave. */
            const char *v = linha + 10;
            size_t lv = strlen(v);
            if (lv > 0 && lv < sizeof(c->client_id)) {
                memcpy(c->client_id, v, lv);
                c->client_id[lv] = '\0';
            }
        }
    }
    fclose(f);
    c->ok = c->client_id[0] != '\0';
    return c->ok;
}

/* A TRANSCODIFICAÇÃO QUE SERVE.
 *
 * Cada faixa traz um vetor `media.transcodings[]`, e a resposta REAL (olhada,
 * não suposta) tem esta forma, nesta ordem:
 *
 *   { "url": "...", "preset": "aac_96k", "duration": 122142,
 *     "snipped": false,
 *     "format": { "protocol": "hls", "mime_type": "audio/mp4; codecs=..." },
 *     "quality": "lq" }
 *
 * Só serve `protocol: progressive` — o `hls` é uma PLAYLIST, não um arquivo, e
 * entregá-la ao `fonte.c` seria entregar texto onde ele espera MP3. E só serve
 * `snipped: false`: uma prévia de trinta segundos com nome de música é pior
 * que um erro, porque não parece um erro.
 *
 * A varredura anda de `"url"` em `"url"`: o `url` vem PRIMEIRO no objeto,
 * então tudo entre um `"url"` e o seguinte é um item só.
 */
int sc_acha_progressiva_dbg(const char *json, char *out, int cap)
{
    const char *p = json;
    const char *melhor = NULL;
    int melhor_mpeg = 0;

    while ((p = strstr(p, "\"url\":\"")) != NULL) {
        const char *ini = p + 7;
        const char *fim = strchr(ini, '"');
        if (!fim) break;

        /* a janela deste item vai até o próximo "url" (ou o fim) */
        const char *prox = strstr(fim, "\"url\":\"");
        const char *lim = prox ? prox : json + strlen(json);

        int progressiva = 0, previa = 0, mpeg = 0;
        for (const char *q = fim; q < lim; q++) {
            if (!strncmp(q, "\"protocol\":\"progressive\"", 24)) progressiva = 1;
            else if (!strncmp(q, "\"snipped\":true", 14)) previa = 1;
            else if (!strncmp(q, "audio/mpeg", 10)) mpeg = 1;
        }

        if (progressiva && !previa && (int)(fim - ini) < cap) {
            /* MP3 na frente do resto: o Opus do SoundCloud vem a 64 kbps,
               metade do MP3, e os dois tocam neste aparelho. */
            if (!melhor || (mpeg && !melhor_mpeg)) {
                melhor = ini;
                melhor_mpeg = mpeg;
                int n = (int)(fim - ini);
                memcpy(out, ini, (size_t)n);
                out[n] = '\0';
            }
        }
        p = fim;
    }
    return melhor != NULL;
}

/* ═══ LER UMA LEVA DE RESULTADOS ══════════════════════════════════════════
 *
 * A resposta de `search/tracks` é `{"collection":[ … ]}`, e cada item começa
 * pela chave `artwork_url` — que é a PRIMEIRA do objeto e aparece uma vez por
 * faixa (conferido na resposta de verdade guardada em
 * `tests/fixtures-sc-busca.json`: oito itens, oito ocorrências). Então o item
 * é o trecho entre um `"artwork_url"` e o seguinte, e tudo o que interessa —
 * `urn`, `title`, `full_duration`, `media`, `policy`, `user` — cai dentro.
 *
 * Não se usa `"kind":"track"` como âncora: ela também aparece oito vezes, mas
 * vem DEPOIS de `duration` e `id`, e um item ancorado nela perde os dois.
 *
 * O QUE ESTA FUNÇÃO EXISTE PARA DESCARTAR: a busca por "aphex twin avril 14"
 * devolve, em PRIMEIRO lugar, a faixa oficial da gravadora com
 * `"policy":"SNIP"`, `duration: 30000` e nenhuma transcodificação
 * progressiva — trinta segundos de prévia. Oferecê-la como música é pior que
 * não achar nada, porque não parece um erro: parece a música acabando.
 * (`full_duration` diz 125520 na mesma faixa, e é por isso que a duração sai
 * dele e não de `duration`.)
 */
int sc_le_busca_dbg(const char *json, ScTrack *out, int max)
{
    if (!json || !out || max <= 0) return 0;
    int n = 0;
    const char *p = json;
    const char *fim_txt = json + strlen(json);

    while (n < max && (p = strstr(p, "\"artwork_url\"")) != NULL) {
        const char *prox = strstr(p + 13, "\"artwork_url\"");
        const char *lim = prox ? prox : fim_txt;
        const char *item = p;
        p = p + 13;

        /* O item vai para um buffer próprio porque os leitores de JSON deste
           projeto trabalham com string terminada — e sem o corte eles achariam
           o `title` da faixa SEGUINTE quando esta não tivesse um.
        
           E VAI ENTRE CHAVES. O recorte começa no meio do objeto (em
           `"artwork_url"`), e o `valor_no_topo` do qobuz.c procura a chave na
           profundidade 1 A PARTIR DA PRIMEIRA `{` QUE ENCONTRA — que, sem o
           embrulho, seria a de `publisher_metadata`. Era por isso que id e
           prévia saíam certos (varredura de texto) e título, artista e
           duração saíam vazios (leitor de JSON): dois mecanismos, e só um
           deles estava olhando o objeto certo. */
        size_t tam = (size_t)(lim - item);
        if (tam >= 64 * 1024) tam = 64 * 1024 - 1;
        char *buf = malloc(tam + 3);
        if (!buf) break;
        buf[0] = '{';
        memcpy(buf + 1, item, tam);
        buf[tam + 1] = '}';
        buf[tam + 2] = '\0';

        int serve = 1;

        /* prévia declarada pela política da faixa */
        if (strstr(buf, "\"policy\":\"SNIP\"")) serve = 0;

        /* e prévia declarada pelo stream: tem de haver UMA progressiva que
           não seja recorte. É a mesma pergunta que o sc_url faz na hora de
           tocar — perguntá-la aqui é a diferença entre escolher no escuro e
           escolher sabendo. */
        char media[1024];
        if (serve && !sc_acha_progressiva_dbg(buf, media, (int)sizeof(media)))
            serve = 0;

        if (serve) {
            ScTrack *t = &out[n];
            memset(t, 0, sizeof(*t));

            /* o id sai do `urn` (`soundcloud:tracks:123`) e não de `"id":`:
               dentro do item há vários `id` (o do usuário, o da visual) e o
               urn é o único que só pode ser o da faixa */
            const char *u = strstr(buf, "soundcloud:tracks:");
            if (u) {
                u += 18;
                int k = 0;
                while (k < (int)sizeof(t->id) - 1 && *u >= '0' && *u <= '9')
                    t->id[k++] = *u++;
                t->id[k] = '\0';
            }

            if (!qobuz_json_str(buf, "title", t->titulo, (int)sizeof(t->titulo)))
                snprintf(t->titulo, sizeof(t->titulo), "?");

            /* `username` mora DENTRO de `user`, e o leitor só enxerga o topo.
               Entregar a ele o objeto do usuário é mais barato (e mais
               honesto) que ensiná-lo a descer. */
            const char *usr = strstr(buf, "\"user\":{");
            if (!usr || !qobuz_json_str(usr + 7, "username",
                                        t->artista, (int)sizeof(t->artista)))
                snprintf(t->artista, sizeof(t->artista), "?");

            int ms = 0;
            if (!qobuz_json_int(buf, "full_duration", &ms))
                qobuz_json_int(buf, "duration", &ms);
            t->segundos = ms > 0 ? ms / 1000 : 0;

            if (t->id[0]) n++;
        }
        free(buf);
    }
    return n;
}

int sc_busca(const ScConfig *c, const char *termo, ScTrack *out, int max)
{
    g_motivo[0] = '\0';
    if (!c || !c->ok || !c->client_id[0]) {
        falha("no SoundCloud client_id on the card");
        return -1;
    }
    if (!termo || !termo[0] || !out || max <= 0) {
        falha("empty search term");
        return -1;
    }

    /* 256 KB: oito resultados de verdade dão 32 KB, e cada item carrega
       descrição e metadados do usuário. Vinte resultados cabem com folga.
       Do MONTE, não da pilha: a thread de rede tem 1 MB. */
    const int CAP = 256 * 1024;
    char *resp = malloc((size_t)CAP);
    if (!resp) { falha("out of memory reading the search"); return -1; }

    char q[512];
    net_urlenc(termo, q, sizeof(q));

    char url[1024];
    snprintf(url, sizeof(url), SC_API "/search/tracks?q=%s&limit=%d&client_id=%s",
             q, max > 25 ? 25 : max, c->client_id);

    if (net_get(url, NULL, resp, CAP) != 0) {
        free(resp);
        falha("could not reach SoundCloud");
        return -1;
    }

    int n = sc_le_busca_dbg(resp, out, max);
    free(resp);
    if (n == 0)
        falha("nothing playable found (the results were previews only)");
    return n;
}

/* ---------- a busca em segundo plano ---------- */

/* Escrito pela thread de rede, lido pela do desenho. Sem mutex, pelo mesmo
   motivo do qobuz.c: são palavras alinhadas, o `g_sc_n` só é publicado depois
   de o vetor estar pronto, e o pior caso de uma leitura fora de hora é um
   quadro com a lista antiga. */
static ScTrack g_sc_res[SC_MAX_RES];
static int     g_sc_n;
static int     g_sc_buscando;
static ScConfig g_sc_cfg;
static char    g_sc_termo[128];

/* O MESMO RASTRO DO QOBUZ, e pelo mesmo motivo: uma thread que morre no
   handshake não escreve nada, e a AUSÊNCIA do arquivo já foi lida três vezes
   como "a busca nunca rodou". START gravado e fechado ANTES da chamada; um
   arquivo com START e sem END diz "entrou e não voltou". */
static void anota_sc(const char *fase, const char *termo, int rc)
{
    const char *caminho = STYLUS_DATA_DIR "/rede.txt";
    long tam = 0;
    FILE *g = fopen(caminho, "rb");
    if (g) { fseek(g, 0, SEEK_END); tam = ftell(g); fclose(g); }
    FILE *f = fopen(caminho, tam > 4096 ? "w" : "a");
    if (!f) return;
    if (!strcmp(fase, "start"))
        fprintf(f, "soundcloud search START \"%.40s\"\n", termo ? termo : "");
    else
        fprintf(f, "soundcloud search END   n=%d  %s\n",
                rc, g_motivo[0] ? g_motivo : "(no reason: it worked)");
    fclose(f);
}

static void sc_busca_corpo(void)
{
    anota_sc("start", g_sc_termo, 0);
    int n = sc_busca(&g_sc_cfg, g_sc_termo, g_sc_res, SC_MAX_RES);
    g_sc_n = n;
    anota_sc("end", g_sc_termo, n);
    g_sc_buscando = 0;
}

#ifdef __vita__
#include <psp2/kernel/threadmgr.h>
static int sc_busca_thread(SceSize args, void *argp)
{
    (void)args; (void)argp;
    sc_busca_corpo();
    return sceKernelExitDeleteThread(0);
}
#endif

int sc_busca_async(const ScConfig *c, const char *termo)
{
    g_motivo[0] = '\0';
    if (!c || !c->ok) return falha("no SoundCloud client_id on the card");
    if (!termo || !termo[0]) return falha("no search term typed");
    if (g_sc_buscando) return falha("a search is still running");

    g_sc_cfg = *c;
    snprintf(g_sc_termo, sizeof(g_sc_termo), "%.*s",
             (int)sizeof(g_sc_termo) - 1, termo);
    g_sc_n = 0;
    g_sc_buscando = 1;
#ifdef __vita__
    SceUID th = sceKernelCreateThread("stylus_scbusca", sc_busca_thread,
                                      PRIO_REDE, PILHA_REDE, 0, 0, NULL);
    if (th < 0) {
        g_sc_buscando = 0;
        char m[96];
        snprintf(m, sizeof(m), "search thread refused (0x%08X)", (unsigned)th);
        return falha(m);
    }
    if (sceKernelStartThread(th, 0, NULL) < 0) {
        sceKernelDeleteThread(th);
        g_sc_buscando = 0;
        return falha("the search thread would not start");
    }
#else
    sc_busca_corpo();
#endif
    return 0;
}

void sc_busca_estado(ScTrack *out, int max, int *n, bool *ativo)
{
    if (ativo) *ativo = g_sc_buscando != 0;
    if (n) *n = g_sc_n;
    if (!out || max <= 0) return;
    int k = g_sc_n > 0 ? g_sc_n : 0;
    if (k > max) k = max;
    for (int i = 0; i < k; i++) out[i] = g_sc_res[i];
}

int sc_url(const ScConfig *c, const char *track_id, char *out, int cap)
{
    g_motivo[0] = '\0';
    if (!c || !c->ok || !c->client_id[0])
        return falha("no SoundCloud client_id on the card");
    if (!track_id || !track_id[0] || !out || cap <= 0)
        return falha("empty SoundCloud track id");

    /* 96 KB: a resposta de uma faixa traz descrição, avatar, contadores e o
       vetor de transcodificações. Medido, a maior fica bem abaixo disso; o
       buffer é do MONTE porque a pilha das threads de rede é 1 MB e um vetor
       destes nela é metade do orçamento. */
    const int CAP = 96 * 1024;
    char *resp = malloc((size_t)CAP);
    if (!resp) return falha("out of memory reading the track");

    char url[1024];
    snprintf(url, sizeof(url), SC_API "/tracks/%s?client_id=%s",
             track_id, c->client_id);
    if (net_get(url, NULL, resp, CAP) != 0) {
        free(resp);
        return falha("could not reach SoundCloud");
    }

    char auth[256];
    if (!qobuz_json_str(resp, "track_authorization", auth, (int)sizeof(auth)) ||
        !auth[0]) {
        free(resp);
        /* Sem `track_authorization` o SoundCloud não assina stream nenhum. É
           o que acontece com faixa privada, apagada, ou com o client_id
           vencido — e as três dão a mesma resposta, então a mensagem diz as
           três. */
        return falha("SoundCloud gave no track authorization "
                     "(private track, or the client_id expired)");
    }

    char media[1024];
    if (!sc_acha_progressiva_dbg(resp, media, (int)sizeof(media))) {
        free(resp);
        return falha("this track has no progressive stream (HLS or preview only)");
    }
    free(resp);

    /* O `media/...` responde com um JSON de uma linha: {"url":"https://..."} */
    char pedido[2048];
    snprintf(pedido, sizeof(pedido), "%s%cclient_id=%s&track_authorization=%s",
             media, strchr(media, '?') ? '&' : '?', c->client_id, auth);

    char curto[4096];
    if (net_get(pedido, NULL, curto, (int)sizeof(curto)) != 0)
        return falha("could not reach the SoundCloud stream endpoint");

    if (!qobuz_json_str(curto, "url", out, cap) || !out[0])
        return falha("SoundCloud did not return a stream URL");
    return 0;
}
