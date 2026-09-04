/* Sobe para o last.fm a fila que o Vita deixou no cartão.
 *
 * O aparelho só ENFILEIRA (ver a nota no src/net.c): subir pediria uma
 * cadeia sceNet/sceSsl/sceHttp que não tem como ser conferida sem um Vita na
 * mão, e errá-la trava o arranque — muito pior do que não scrobblar. Aqui há
 * libcurl e há como conferir, então é aqui que se sobe.
 *
 *   ./lastfm_sync /run/media/.../data/vitastylus
 *
 * A credencial fica em <dir>/lastfm.txt, que é do usuário e NUNCA do repo.
 * Sem ela, o programa diz o que falta e não toca na fila.
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
        printf("para configurar, crie %s/lastfm.txt com:\n", dir);
        printf("  api_key=...\n  api_secret=...\n  session_key=...\n");
        printf("(a chave de sessão sai de uma autorização feita uma vez no PC)\n");
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
