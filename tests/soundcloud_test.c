/* A ESCOLHA DA TRANSCODIFICAÇÃO DO SOUNDCLOUD, contra a resposta DE VERDADE.
 *
 * POR QUE ISTO É UM TESTE.
 *
 * O `sc_acha_progressiva_dbg` é uma varredura escrita à mão sobre JSON, e o
 * que ela decide não aparece em lugar nenhum da tela: se errar, o `fonte.c`
 * recebe uma PLAYLIST onde espera um MP3 e a faixa simplesmente não toca —
 * com a mesma cara de "a rede caiu".
 *
 * E a armadilha está na resposta real, não numa imaginada. A faixa 3585879
 * traz QUATRO transcodificações:
 *
 *     hls          audio/mp4; codecs="mp4a.40.2"
 *     hls          audio/mpegurl
 *     hls          audio/mpeg          <- esta
 *     progressive  audio/mpeg
 *
 * Uma busca por "audio/mpeg" acha a TERCEIRA. Uma busca pela primeira `url`
 * acha a primeira, que é HLS. Só serve olhar o `protocol` de CADA item, e é
 * exatamente isso que este teste prende.
 *
 * A fixture é a resposta gravada do aparelho de verdade (o campo `media` e o
 * `track_authorization`), não um JSON inventado — ver a lição do repositório
 * sobre teste que passa e aparelho que reprova.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "soundcloud.h"

static int falhas;

static void ok(int cond, const char *o_que)
{
    if (cond) { printf("  \033[32m✓\033[0m %s\n", o_que); return; }
    falhas++;
    printf("  \033[31m✗\033[0m %s\n", o_que);
}

static char *le(const char *caminho)
{
    FILE *f = fopen(caminho, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1);
    if (!b) { fclose(f); return NULL; }
    if (fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); fclose(f); return NULL; }
    b[n] = '\0';
    fclose(f);
    return b;
}

int main(int argc, char **argv)
{
    const char *cam = argc > 1 ? argv[1] : "tests/fixtures-soundcloud.json";
    char *json = le(cam);
    if (!json) { printf("não achei a fixture %s\n", cam); return 2; }

    printf("\033[1ma escolha do stream do soundcloud\033[0m\n");

    char url[1024];
    int achou = sc_acha_progressiva_dbg(json, url, (int)sizeof(url));
    ok(achou, "acha uma transcodificação utilizável");
    ok(achou && strstr(url, "/stream/progressive") != NULL,
       "é a PROGRESSIVA (um arquivo), e não uma das três HLS");
    ok(achou && strstr(url, "/stream/hls") == NULL,
       "não escolheu playlist — nem a HLS que se anuncia como audio/mpeg");

    /* Só prévia: tem de recusar. Trinta segundos com nome de música inteira é
       pior que um erro, porque não parece um erro. */
    const char *so_previa =
        "{\"media\":{\"transcodings\":["
        "{\"url\":\"https://x/stream/progressive\",\"snipped\":true,"
        "\"format\":{\"protocol\":\"progressive\",\"mime_type\":\"audio/mpeg\"}}"
        "]}}";
    ok(!sc_acha_progressiva_dbg(so_previa, url, (int)sizeof(url)),
       "recusa a prévia de 30 s (snipped)");

    /* Só HLS: tem de recusar em vez de entregar a playlist. */
    const char *so_hls =
        "{\"media\":{\"transcodings\":["
        "{\"url\":\"https://x/stream/hls\",\"snipped\":false,"
        "\"format\":{\"protocol\":\"hls\",\"mime_type\":\"audio/mpeg\"}}"
        "]}}";
    ok(!sc_acha_progressiva_dbg(so_hls, url, (int)sizeof(url)),
       "recusa quando só há HLS");

    /* MP3 na frente do Opus: o Opus do SoundCloud vem a 64 kbps. */
    const char *dois =
        "{\"media\":{\"transcodings\":["
        "{\"url\":\"https://x/opus/progressive\",\"snipped\":false,"
        "\"format\":{\"protocol\":\"progressive\",\"mime_type\":\"audio/ogg; codecs=\\\"opus\\\"\"}},"
        "{\"url\":\"https://x/mp3/progressive\",\"snipped\":false,"
        "\"format\":{\"protocol\":\"progressive\",\"mime_type\":\"audio/mpeg\"}}"
        "]}}";
    ok(sc_acha_progressiva_dbg(dois, url, (int)sizeof(url)) &&
       strstr(url, "/mp3/") != NULL,
       "prefere o MP3 ao Opus de 64 kbps quando há os dois");

    /* Sem transcodificação nenhuma: não pode inventar nem estourar. */
    ok(!sc_acha_progressiva_dbg("{}", url, (int)sizeof(url)),
       "não inventa nada num JSON vazio");

    /* ═══ A BUSCA, contra a resposta DE VERDADE ═══════════════════════════
     *
     * A fixture é a resposta crua de `search/tracks?q=aphex twin avril 14`,
     * gravada do servidor (o client_id foi removido do texto). Ela contém
     * exatamente a armadilha que a busca existe para desviar: o PRIMEIRO
     * resultado é a faixa oficial da gravadora, `"policy":"SNIP"`,
     * `duration: 30000` e sem nenhuma transcodificação progressiva — trinta
     * segundos de prévia com nome de música inteira.
     *
     * Se ela passar, a pessoa escolhe a primeira linha da lista (que é o que
     * se faz) e ouve a música parar sozinha aos trinta segundos, sem nada na
     * tela dizendo por quê. */
    char *busca = le("tests/fixtures-sc-busca.json");
    if (!busca) {
        printf("  \033[31m✗\033[0m não achei tests/fixtures-sc-busca.json\n");
        falhas++;
    } else {
        ScTrack tr[16];
        int n = sc_le_busca_dbg(busca, tr, 16);
        ok(n > 0, "a busca extrai faixas da resposta de verdade");

        int tem_snip = 0, sem_id = 0, sem_titulo = 0;
        for (int i = 0; i < n; i++) {
            if (!strcmp(tr[i].id, "271226416")) tem_snip = 1;
            if (!tr[i].id[0]) sem_id = 1;
            if (!tr[i].titulo[0]) sem_titulo = 1;
        }
        ok(!tem_snip, "descarta a faixa SNIP (a prévia de 30 s vinha em 1º)");
        ok(!sem_id, "toda faixa devolvida tem id");
        ok(!sem_titulo, "toda faixa devolvida tem título");

        /* a duração sai de `full_duration`: na faixa recortada o `duration`
           mente (30 s), e é a mesma chave nas duas */
        int plausivel = 1;
        for (int i = 0; i < n; i++)
            if (tr[i].segundos <= 0 || tr[i].segundos > 4 * 3600) plausivel = 0;
        ok(plausivel, "as durações são plausíveis (vêm de full_duration)");

        /* e o campo do artista não pode sair vazio: numa lista de resultados
           "?" repetido é o que faz a tela parecer quebrada */
        int com_artista = 0;
        for (int i = 0; i < n; i++)
            if (tr[i].artista[0] && strcmp(tr[i].artista, "?")) com_artista++;
        ok(com_artista == n, "toda faixa devolvida tem o nome de quem publicou");

        printf("      %d faixa(s) utilizáveis de 8 resultados\n", n);
        for (int i = 0; i < n && i < 3; i++)
            printf("        sc:%s  %s — %s (%d s)\n",
                   tr[i].id, tr[i].artista, tr[i].titulo, tr[i].segundos);
        free(busca);
    }

    /* Nada utilizável: tem de devolver zero, não lixo. */
    {
        ScTrack tr[4];
        ok(sc_le_busca_dbg("{\"collection\":[]}", tr, 4) == 0,
           "uma leva vazia devolve zero");
        ok(sc_le_busca_dbg("", tr, 4) == 0, "texto vazio devolve zero");
    }

    free(json);
    if (falhas) {
        printf("\033[31m%d falha(s)\033[0m\n", falhas);
        return 1;
    }
    printf("\033[32ma escolha do stream está certa\033[0m\n");
    return 0;
}
