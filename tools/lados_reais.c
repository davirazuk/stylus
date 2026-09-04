/* Os LADOS contra discos REAIS, não uma grade sintética.
 *
 * O tools/sides_dump.c já prova a REGRA, repartindo uma grade de formas e
 * comparando com a do desktop. Isto prova a JUNÇÃO, que é outra coisa: que
 * as durações chegam mesmo — vindas do ID3 de arquivos de verdade, pelo
 * album_load_meta — e que o corte que sai delas é sensato.
 *
 * Uma duração ausente não estoura: o sides.c trata <= 0 como a mediana. Mas
 * se TODAS faltarem, o disco não tem lados que signifiquem nada, e este
 * programa conta quantos casos assim existem no acervo.
 *
 * Reprova (código 1) se algum lado passar do teto FÍSICO de 30 minutos —
 * um lado que não cabe num disco de verdade é a única coisa aqui que seria
 * inequivocamente errada.
 *
 *   ./lados_reais ~/staging-vita/vita-mp3 40
 */
#include <stdio.h>
#include <stdlib.h>
#include "library.h"
#include "sides.h"
#include "decoder.h"

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "uso: %s <raiz> [quantos]\n", argv[0]); return 2; }
    int max = argc > 2 ? atoi(argv[2]) : 40;
    dec_global_init();
    Library lib; library_init(&lib);
    library_add_root(&lib, argv[1]);
    library_scan(&lib);
    printf("%d álbuns; olhando os %d primeiros com faixas\n", lib.nalbums, max);

    int sem_duracao = 0, com = 0, um_lado = 0, dois = 0, mais = 0, duplos = 0;
    int maior_lado = 0;
    for (int i = 0, vistos = 0; i < lib.nalbums && vistos < max; i++) {
        Album *a = &lib.albums[i];
        if (a->ntracks <= 0) continue;
        album_load_meta(a);
        vistos++;
        int *d = malloc(sizeof(int) * (size_t)a->ntracks);
        int desconhecidas = 0, total = 0;
        for (int t = 0; t < a->ntracks; t++) {
            d[t] = a->tracks[t].seconds;
            if (d[t] <= 0) desconhecidas++; else total += d[t];
        }
        if (desconhecidas == a->ntracks) { sem_duracao++; free(d); continue; }
        com++;
        Sides s; sides_build(d, a->ntracks, &s);
        if (s.n == 1) um_lado++; else if (s.n == 2) dois++; else mais++;
        if (s.discos > 1) duplos++;
        for (int k = 0; k < s.n; k++) {
            int dur = (int)(s.sides[k].end - s.sides[k].start);
            if (dur > maior_lado) maior_lado = dur;
        }
        if (vistos <= 6) {
            char g[128]; sides_gesture(&s, 0, g, sizeof(g));
            printf("  %-42.42s %2d faixas %3d min -> %d lado(s), %d disco(s)  \"%s\"\n",
                   a->album, a->ntracks, total/60, s.n, s.discos, g);
        }
        free(d);
    }
    printf("\ncom duração: %d   sem NENHUMA duração: %d\n", com, sem_duracao);
    printf("1 lado: %d   2 lados: %d   3+: %d   duplos: %d\n", um_lado, dois, mais, duplos);
    printf("lado mais longo visto: %d min (teto físico 30)\n", maior_lado/60);
    return maior_lado > 30*60 ? 1 : 0;
}
