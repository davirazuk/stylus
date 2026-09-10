/* O índice da estante: vale quando nada mudou, e NUNCA quando mudou.
 *
 * A metade perigosa de um cache não é ele ser lento — é ele MENTIR. Uma
 * estante montada a partir de um índice velho mostra disco que não existe
 * mais e esconde o que acabou de entrar, e nada na tela explica. Por isso o
 * que este teste mede não é "o índice carrega": é que ele RECUSA nos três
 * jeitos de a coleção mudar.
 *
 * O caso do meio é o que decide o desenho: uma faixa nova DENTRO de um álbum
 * que já existia. Guardar só a data das raízes seria mais barato e não pegaria
 * esse — e é justamente o que acontece quando se está enchendo um disco.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "library.h"

static char RAIZ[512];
static char IDX[600];

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
static void rm(const char *rel)
{
    char c[1200];
    snprintf(c, sizeof(c), "rm -rf '%s/%s'", RAIZ, rel);
    if (system(c)) { /* o teste falha adiante se não apagou */ }
}

/* O mtime de uma pasta tem resolução de 1 s em vários sistemas de arquivos.
   Sem esta pausa o teste passaria por acidente ou falharia por acidente,
   conforme a máquina — e um teste que depende do relógio não é um teste. */
static void espera_o_relogio(void) { usleep(1100 * 1000); }

static int varre_e_salva(void)
{
    Library l;
    library_init(&l);
    library_add_root(&l, RAIZ);
    library_scan(&l);
    int n = l.audio_found;
    assert(library_cache_save(&l, IDX) == 0 && "o indice tem de gravar");
    library_free(&l);
    return n;
}

static int carrega(int *faixas)
{
    Library l;
    library_init(&l);
    int r = library_cache_load(&l, IDX);
    if (faixas) *faixas = l.audio_found;
    library_free(&l);
    return r;
}

static void ok(int cond, const char *msg)
{
    printf("  %s %s\n", cond ? "\033[32mok\033[0m" : "\033[31mFALHOU\033[0m", msg);
    if (!cond) exit(1);
}

int main(void)
{
    snprintf(RAIZ, sizeof(RAIZ), "/tmp/stylus-indice-%d", (int)getpid());
    snprintf(IDX, sizeof(IDX), "%s.idx", RAIZ);
    mkdir(RAIZ, 0755);

    mk("Pink Floyd");
    mk("Pink Floyd/The Wall");
    arq("Pink Floyd/The Wall/01 - In the Flesh.mp3");
    arq("Pink Floyd/The Wall/02 - The Thin Ice.mp3");
    mk("Radiohead");
    mk("Radiohead/OK Computer");
    arq("Radiohead/OK Computer/01 - Airbag.mp3");

    int n = varre_e_salva();
    ok(n == 3, "a varredura achou as tres faixas");

    int f = 0;
    ok(carrega(&f) == 0 && f == 3, "o indice vale quando nada mudou");

    /* 1. faixa nova DENTRO de um album que ja existia */
    espera_o_relogio();
    arq("Radiohead/OK Computer/02 - Paranoid Android.mp3");
    ok(carrega(&f) != 0, "faixa nova num album existente INVALIDA o indice");

    /* 2. album novo dentro de um artista que ja existia */
    varre_e_salva();
    espera_o_relogio();
    mk("Radiohead/In Rainbows");
    arq("Radiohead/In Rainbows/01 - 15 Step.mp3");
    ok(carrega(&f) != 0, "album novo INVALIDA o indice");

    /* 3. pasta apagada */
    varre_e_salva();
    espera_o_relogio();
    rm("Pink Floyd");
    ok(carrega(&f) != 0, "pasta apagada INVALIDA o indice");

    /* 4. o indice reproduz a estante FIELMENTE, e nao so o numero */
    n = varre_e_salva();
    Library a, b;
    library_init(&a);
    library_add_root(&a, RAIZ);
    library_scan(&a);
    library_init(&b);
    ok(library_cache_load(&b, IDX) == 0, "o indice recarrega");
    ok(a.nalbums == b.nalbums, "mesmo numero de discos");
    int dif = 0;
    for (int i = 0; i < a.nalbums && i < b.nalbums; i++) {
        Album *x = &a.albums[i], *y = &b.albums[i];
        if (strcmp(x->key, y->key) || strcmp(x->artist, y->artist) ||
            strcmp(x->album, y->album) || x->ntracks != y->ntracks) { dif++; continue; }
        for (int j = 0; j < x->ntracks; j++) {
            if (strcmp(x->tracks[j].path, y->tracks[j].path) ||
                strcmp(x->tracks[j].title, y->tracks[j].title) ||
                x->tracks[j].number != y->tracks[j].number ||
                x->tracks[j].decodable != y->tracks[j].decodable) dif++;
        }
    }
    ok(dif == 0, "cada faixa volta igual: caminho, titulo, numero e tocavel");
    library_free(&a);
    library_free(&b);

    /* 5. um indice corrompido nao pode montar meia estante */
    FILE *g = fopen(IDX, "r+");
    if (g) { fseek(g, 0, SEEK_END); long sz = ftell(g); fclose(g);
             if (truncate(IDX, sz / 2) != 0) { /* segue */ } }
    Library c;
    library_init(&c);
    ok(library_cache_load(&c, IDX) != 0, "indice cortado no meio e RECUSADO");
    ok(c.nalbums == 0 && c.audio_found == 0,
       "e nao deixa meia estante montada para a varredura duplicar");
    library_free(&c);

    /* 6. o indice VAZIO — o que quase custou mais uma viagem ao aparelho.
       O app rodou meses sem conseguir abrir ux0:music (era homebrew "safe")
       e gravou esse nada: R=5, D=0, A=0. Com D=0 nao ha pasta cuja data
       conferir, entao a validacao acima nao roda uma vez e o indice passa
       PARA SEMPRE — mesmo depois de o sandbox ser consertado. */
    FILE *v = fopen(IDX, "w");
    if (v) {
        fprintf(v, "vitastylus-estante\t1\n");
        fprintf(v, "R\t1\nr\t%s\n", RAIZ);
        fprintf(v, "D\t0\n");
        fprintf(v, "A\t0\n");
        fclose(v);
    }
    Library e;
    library_init(&e);
    ok(library_cache_load(&e, IDX) != 0,
       "indice com ZERO discos e RECUSADO (senao a estante vazia vira eterna)");
    ok(e.nalbums == 0, "e nao deixa nada montado");
    library_free(&e);

    rm("");
    unlink(IDX);
    printf("ok: o indice vale quando vale, e recusa quando mudou\n");
    return 0;
}
