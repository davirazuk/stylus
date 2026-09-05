/* Sobe para o last.fm a fila que o Vita deixou no cartão.
 *
 * ISTO NÃO É MAIS O CAMINHO PRINCIPAL. Quando foi escrito, o aparelho só
 * ENFILEIRAVA: subir pedia uma cadeia sceNet/sceSsl/sceHttp que ninguém
 * tinha conferido, e errá-la trava o arranque — muito pior que não
 * scrobblar. Hoje o próprio Vita entra na conta e sobe a fila sozinho, pela
 * tela CONTA (ver lastfm.c: lastfm_login e lastfm_sync_async).
 *
 * Continua útil para duas coisas: esvaziar uma fila grande de uma vez com o
 * cartão no PC, e conferir a assinatura da API daqui, onde há como depurar.
 *
 *   ./lastfm_sync /run/media/.../data/vitastylus
 *
 * A credencial fica em <dir>/lastfm.config, que é do usuário e NUNCA do
 * repo. Sem ela, o programa diz o que falta e não toca na fila.
 */
#include <stdio.h>
#include <string.h>

#include "lastfm.h"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr,
            "uso: %s <pasta de dados do vitastylus>\n"
            "  ex: %s /run/media/davirazuk/VITASD/data/vitastylus\n",
            argv[0], argv[0]);
        return 2;
    }
    const char *dir = argv[1];

    int n = lastfm_queue_size(dir);
    printf("fila: %d escuta%s em %s\n", n, n == 1 ? "" : "s", dir);
    if (n <= 0) { printf("nada a enviar.\n"); return 0; }

    LastfmConfig cfg;
    lastfm_config_load(&cfg, dir);
    if (!cfg.configured) {
        printf("\nsem credencial: nada foi enviado, e a fila continua intacta.\n");
        /* O nome do arquivo e o nome das chaves TÊM de ser os que o
           lastfm_config_load lê de verdade: instruções que não batem com o
           código mandam a pessoa criar um arquivo que ninguém abre. */
        printf("para configurar, crie %s/lastfm.config com:\n", dir);
        printf("  api_key=...\n  api_secret=...\n  sk=...\n  username=...\n");
        printf("(ou entre na conta pela tela CONTA do próprio aparelho, que\n");
        printf(" preenche isso sozinho)\n");
        return 1;
    }

    int r = lastfm_sync(&cfg, dir);
    int sobrou = lastfm_queue_size(dir);
    if (r < 0) {
        printf("o envio falhou; a fila continua com %d — nada se perdeu.\n", sobrou);
        return 1;
    }
    printf("enviadas %d; restam %d na fila.\n", n - sobrou, sobrou);
    return 0;
}
