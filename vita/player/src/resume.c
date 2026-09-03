#include "resume.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int resume_save(const char *dir, const Resume *r)
{
    if (!dir || !r || !r->valid || !r->track_path[0]) return -1;
    char path[1100];
    snprintf(path, sizeof(path), "%s/%s", dir, RESUME_FILE);
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    fprintf(f, "track=%s\n", r->track_path);
    fprintf(f, "pos=%d\n", r->position_sec);
    fprintf(f, "repeat=%d\n", r->repeat);
    fprintf(f, "shuffle=%d\n", r->shuffle ? 1 : 0);
    fclose(f);
    return 0;
}

void resume_load(const char *dir, Resume *r)
{
    memset(r, 0, sizeof(*r));
    if (!dir) return;
    char path[1100];
    snprintf(path, sizeof(path), "%s/%s", dir, RESUME_FILE);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char line[1100];
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "track=", 6) == 0) {
            size_t l = strlen(line + 6);
            if (l && line[6 + l - 1] == '\n') l--;
            if (l >= sizeof(r->track_path)) l = sizeof(r->track_path) - 1;
            memcpy(r->track_path, line + 6, l);
            r->track_path[l] = '\0';
            if (r->track_path[0]) r->valid = true;
        } else if (strncmp(line, "pos=", 4) == 0) {
            r->position_sec = (line[4] >= '0' && line[4] <= '9') ? atoi(line + 4) : 0;
        } else if (strncmp(line, "repeat=", 7) == 0) {
            r->repeat = atoi(line + 7);
        } else if (strncmp(line, "shuffle=", 8) == 0) {
            r->shuffle = atoi(line + 8) != 0;
        }
    }
    fclose(f);
}
