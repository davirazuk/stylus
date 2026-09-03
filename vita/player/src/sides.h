#ifndef STYLUS_SIDES_H
#define STYLUS_SIDES_H

#include <stddef.h>

/* OS LADOS. É a tese do sistema inteiro, e o tocador do Vita não a tinha:
 * um álbum aqui era uma fila de arquivos, como em qualquer outro tocador.
 *
 * Esta é a transliteração do `Album._build_sides` do desktop
 * (airootfs/usr/share/stylus/lib/vinyl.py). Nada aqui foi reinventado, de
 * propósito: duas metades que decidem a mesma coisa por conta própria
 * DIVERGEM — foi o que aconteceu com o celular, que repartia o mesmo disco
 * com um teto de 22 min contra os 26 do computador, e ninguém percebeu
 * porque nenhuma tela mostra as duas ao mesmo lado. O tools/check.sh reparte
 * a mesma grade de formas pelas duas regras e compara lado a lado. */

/* 26 min: o lado CONFORTÁVEL, que decide quantos lados PLANEJAR.
   30 min: o teto FÍSICO, que só entra quando o plano não fecha. Dois tetos
   com papéis diferentes — com um só, 50 minutos viravam quatro lados. */
#define SIDE_MAX_SECONDS  (26 * 60)
#define SIDE_HARD_SECONDS (30 * 60)
#define SIDES_MAX 32

typedef struct {
    int    first, last;   /* faixas deste lado, inclusive */
    double start, end;    /* segundos, dentro do álbum */
    char   label[12];     /* "LADO A" */
} Side;

typedef struct {
    Side sides[SIDES_MAX];
    int  n;
    int  discos;          /* contado dos lados que EXISTEM, não dos planejados */
} Sides;

/* `durations` em segundos, uma por faixa. Uma duração <= 0 é tratada como a
   MEDIANA das conhecidas: zero não é "não sei", e três zeros num disco de
   doze somem com um LADO inteiro sem erro nenhum. */
void sides_build(const int *durations, int ntracks, Sides *out);

/* Em que lado mora a faixa `track`. -1 se não houver lados. */
int sides_of_track(const Sides *s, int track);

/* O gesto que o objeto pede ao começar o lado `i`:
   "vire o disco para o LADO B" / "ponha o DISCO 2, LADO C" / "agora o LADO A".
   Mora aqui, junto dos lados, porque a mesma frase escrita em três telas
   deriva — e derivou, no desktop. */
void sides_gesture(const Sides *s, int i, char *out, size_t cap);
void sides_label(const Sides *s, int i, char *out, size_t cap);

#endif
