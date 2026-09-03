/* Despeja o corte dos lados em texto, para o compara_lados.py conferir contra
   o `Album._build_sides` do desktop. Uma linha por forma de disco:
   `<total> <faixas> | <lados> <discos> | <faixas do lado 0> <do 1> ...` */
#include "sides.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    /* grade: de 20 a 130 minutos, faixas de 2 a 18 */
    int t0 = 20, t1 = 130, n0 = 2, n1 = 18;
    if (argc == 5) { t0 = atoi(argv[1]); t1 = atoi(argv[2]); n0 = atoi(argv[3]); n1 = atoi(argv[4]); }

    for (int mins = t0; mins <= t1; mins += 1) {
        for (int n = n0; n <= n1; n++) {
            int total = mins * 60;
            int d[64];
            for (int i = 0; i < n; i++) {
                /* reparte o total em n faixas iguais, com o resto na última:
                   durações inteiras, como as que o decodificador devolve */
                d[i] = total / n;
            }
            d[n - 1] += total - (total / n) * n;
            Sides s;
            sides_build(d, n, &s);
            printf("%d %d | %d %d |", total, n, s.n, s.discos);
            for (int i = 0; i < s.n; i++)
                printf(" %d", s.sides[i].last - s.sides[i].first + 1);
            printf("\n");
        }
    }
    return 0;
}
