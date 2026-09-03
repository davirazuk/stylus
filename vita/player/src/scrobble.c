#include "scrobble.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

int scrobble_log(const char *dir, const Track *t, long timestamp)
{
    if (!dir || !t || timestamp <= 0) return -1;
    const char *artist = t->owner ? t->owner->artist : "";
    const char *album = t->owner ? t->owner->album : "";
    const char *fold = t->owner ? t->owner->key : "";

    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, SCROBBLE_FILE);
    FILE *f = fopen(path, "a");
    if (!f) return -1;

    /* mesma faixa seguida = repetida: não regista duas vezes. Compara a
       última linha do arquivo com a que vem; é barato e mata o duplicado. */
    long last_ts = 0;
    char last_line[4096] = "";
    FILE *r = fopen(path, "r");
    if (r) {
        char buf[4096];
        while (fgets(buf, sizeof(buf), r)) {
            if (buf[0]) {
                strncpy(last_line, buf, sizeof(last_line) - 1);
                last_line[sizeof(last_line) - 1] = '\0';
            }
        }
        fclose(r);
        char *tab = strchr(last_line, '\t');
        if (tab) *tab = '\0';
        last_ts = atol(last_line);
    }
    if (last_ts == timestamp) {
        fclose(f);
        return 0;
    }

    /* artista/álbum com tab/queuebras desmontariam o TSV: poda o que sobra. */
    char a[256], al[256], fo[256];
    snprintf(a, sizeof(a), "%.60s", artist);
    snprintf(al, sizeof(al), "%.60s", album);
    snprintf(fo, sizeof(fo), "%.120s", fold);
    for (char *p = a; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';
    for (char *p = al; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';
    for (char *p = fo; *p; p++) if (*p == '\t' || *p == '\n') *p = ' ';

    fprintf(f, "%ld\t%s\t%s\t%s\n", timestamp, a, al, fo);
    fclose(f);
    return 0;
}
