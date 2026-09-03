#ifndef STYLUS_LIBRARY_H
#define STYLUS_LIBRARY_H

#include <stdbool.h>
#include <stddef.h>

#define MUSIC_ROOT_DEFAULT "ux0:music/"

#define MAX_PATH_LEN 1024
#define MAX_TITLE_LEN 256
#define MAX_NAME_LEN 256

typedef struct Album Album;

typedef struct {
    char path[MAX_PATH_LEN];   /* caminho completo do arquivo */
    char title[MAX_TITLE_LEN]; /* título da faixa (tag) ou base do arquivo */
    int  number;               /* número da faixa, -1 se sem tag */
    int  seconds;              /* duração, -1 se desconhecida */
    Album *owner;              /* álbum que contém esta faixa */
} Track;

struct Album {
    char key[MAX_PATH_LEN];      /* caminho do dir do álbum relativo ao root (id único) */
    char artist[MAX_NAME_LEN];
    char album[MAX_NAME_LEN];    /* último segmento do key, para exibição */
    Track *tracks;
    int ntracks;
    int cap;
    /* capa embutida do primeiro mp3 que tiver APIC front cover */
    unsigned char *cover;      /* dono dos bytes (JPEG/PNG) */
    size_t cover_len;
    bool cover_loaded;
};

typedef struct {
    Album *albums;
    int nalbums;
    int cap;
    char root[MAX_PATH_LEN];
} Library;

void library_init(Library *lib, const char *root);
int  library_scan(Library *lib);            /* 0 ok, -1 erro */
void library_free(Library *lib);
Album *library_album(Library *lib, int i);

/* ordena a estante: por artista, depois álbum, alfabético (case-insensitive) */
void library_sort(Library *lib);

/* carrega (uma vez) a capa embutida do álbum a partir do primeiro mp3 com APIC */
int album_load_cover(Album *alb);           /* 0 ok / tem; 1 sem; -1 erro */
void album_free_cover(Album *alb);

#endif
