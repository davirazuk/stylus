/* A busca acha música com QUALQUER nome de pasta?
 *
 * Este teste existe por causa de um relato de campo: o aparelho dizia "as
 * raízes não existem" e estava certo — a música estava numa pasta que os
 * palpites não previam. A correção foi procurar em vez de adivinhar, e o que
 * se mede aqui é exatamente isso, com uma árvore falsa apontada por
 * STYLUS_DEVICES.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "library.h"

static char RAIZ[512];

static void mk(const char *rel)
{
    char p[1024];
    snprintf(p, sizeof(p), "%s/%s", RAIZ, rel);
    mkdir(p, 0755);
}
static void arq(const char *rel)
{
    char p[1024];
    snprintf(p, sizeof(p), "%s/%s", RAIZ, rel);
    FILE *f = fopen(p, "w");
    if (f) { fputs("x", f); fclose(f); }
}

static int achou_raiz(const Library *lib, const char *sufixo)
{
    for (int i = 0; i < lib->nroots; i++) {
        size_t l = strlen(lib->roots[i].path), s = strlen(sufixo);
        if (l >= s && strcmp(lib->roots[i].path + l - s, sufixo) == 0) return 1;
    }
    return 0;
}

int main(void)
{
    snprintf(RAIZ, sizeof(RAIZ), "/tmp/stylus-busca-%d", (int)getpid());
    mkdir(RAIZ, 0755);
    setenv("STYLUS_DEVICES", RAIZ, 1);

    /* Um nome que NENHUM palpite previa, com um álbum dentro. */
    mk("Minhas Musicas");
    mk("Minhas Musicas/Radiohead - OK Computer");
    arq("Minhas Musicas/Radiohead - OK Computer/01 Airbag.mp3");
    arq("Minhas Musicas/Radiohead - OK Computer/02 Paranoid Android.mp3");

    /* Fundo: a música pode estar a três pastas de distância. */
    mk("media"); mk("media/audio"); mk("media/audio/Disco");
    arq("media/audio/Disco/01 Faixa.flac");

    /* Uma pasta do sistema COM áudio dentro: não pode virar raiz, senão a
       estante enche de som de interface e de jogo. */
    mk("app"); mk("app/GRAVE0001");
    arq("app/GRAVE0001/bgm.ogg");

    /* Uma pasta sem áudio nenhum: não vira raiz. */
    mk("fotos");
    arq("fotos/ferias.jpg");

    /* O DEFEITO DO BLOONS.

       Relato de campo, com o relatório do próprio app como prova: a estante
       do usuário virou 47 efeitos sonoros do Bloons TD 5 enquanto 3.728 MP3
       em `ux0:music` ficavam invisíveis. `ux0:data` tinha 39 .wav + 6 .mp3 +
       2 .ogg = exatamente o `audio=47` que o relatório mostrava.

       Três coisas tinham de dar errado juntas, e as três estão aqui:
       "data" não era pasta de sistema, o .wav contava como prova de coleção,
       e a ordem alfabética fazia "data" ser sondada antes de "music". */
    mk("data"); mk("data/btd5"); mk("data/btd5/assets");
    arq("data/btd5/assets/SwampSpawn.wav");
    arq("data/btd5/assets/Pop.wav");
    arq("data/btd5/assets/tema.mp3");     /* jogo também tem mp3 solto */
    mk("data/outrojogo");
    arq("data/outrojogo/menu.ogg");

    /* A discoteca de verdade, com o nome óbvio. */
    mk("music"); mk("music/Pink Floyd"); mk("music/Pink Floyd/The Wall");
    arq("music/Pink Floyd/The Wall/01 - In the Flesh.mp3");
    arq("music/Pink Floyd/The Wall/02 - The Thin Ice.mp3");

    /* Uma pasta de jogo SÓ com wav: nem com o nome fora da lista ela entra,
       porque ninguém guarda discoteca em wav. */
    mk("jogoqualquer"); mk("jogoqualquer/sfx");
    arq("jogoqualquer/sfx/click.wav");
    arq("jogoqualquer/sfx/boom.wav");

    Library lib;
    library_init(&lib);
    int n = library_discover(&lib);

    printf("raizes achadas: %d\n", n);
    for (int i = 0; i < lib.nroots; i++) printf("  %s\n", lib.roots[i].path);

    assert(achou_raiz(&lib, "Minhas Musicas") && "nome imprevisto tem de ser achado");
    assert(achou_raiz(&lib, "media") && "audio a 3 pastas de fundo tem de ser achado");
    assert(!achou_raiz(&lib, "app") && "pasta de sistema NAO pode virar raiz");
    assert(!achou_raiz(&lib, "fotos") && "pasta sem audio NAO pode virar raiz");
    assert(lib.roots_discovered && "a flag tem de dizer que foram descobertas");

    /* O defeito do Bloons, travado: */
    assert(!achou_raiz(&lib, "/data") &&
           "ux0:data NAO pode virar raiz: e onde o homebrew guarda arquivo");
    assert(achou_raiz(&lib, "music") &&
           "a pasta com o nome obvio tem de entrar");
    assert(!achou_raiz(&lib, "jogoqualquer") &&
           "pasta so de .wav e banco de som de jogo, nao discoteca");

    /* E a discoteca tem de ser sondada ANTES das outras, senao numa estante
       cheia ela pode nem caber em MAX_ROOTS. */
    assert(lib.nroots > 0 && strstr(lib.roots[0].path, "music") &&
           "a discoteca tem de ser a PRIMEIRA raiz, nao a ultima");

    /* E o caminho completo funciona: varrer as raízes achadas dá álbuns. */
    library_scan(&lib);
    printf("albuns: %d  audio: %d\n", lib.nalbums, lib.audio_found);
    assert(lib.nalbums >= 2 && "os dois discos tem de aparecer na estante");

    library_free(&lib);
    printf("ok: a busca acha musica com qualquer nome de pasta\n");
    return 0;
}
