#include "sides.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

/* Reparte as faixas em `quantos` lados, com o teto dado. PODE devolver mais:
   um disco cujas faixas não se deixam repartir abaixo do teto sai com mais
   lados do que se pediu, e quem lida com isso é o sides_build. */
static int cut(const double *start, const double *dur, int n, double total,
               int quantos, double teto, Side *out)
{
    int nsides = 0;
    int cur_first = 0, cur_count = 0;
    double cur_start = 0.0;

    for (int i = 0; i < n; i++) {
        double end = start[i] + dur[i];

        /* 1. o teto, que é FÍSICO. Fecha ANTES de pôr a faixa que estoura —
           fechar depois deixa a última faixa entrar inteira por cima dele, e
           era assim que 69 de 374 discos tinham um lado passando do limite
           que o cabeçalho promete. Um lado vazio nunca fecha: uma faixa
           maior que o lado inteiro fica sozinha nele, que é o que acontece
           de verdade — não se corta uma música ao meio. */
        if (cur_count && (end - cur_start) > teto) {
            if (nsides < SIDES_MAX) {
                out[nsides].first = cur_first;
                out[nsides].last  = i - 1;
                out[nsides].start = cur_start;
                out[nsides].end   = start[i];
            }
            nsides++;
            cur_first = i;
            cur_count = 0;
            cur_start = start[i];
        }
        cur_count++;

        /* 2. o equilíbrio. O alvo sai do que RESTA — o que falta dividido
           pelos lados que faltam — e não de `total / n_lados` fixo: com o
           alvo fixo os lados fechavam cedo, o resto não cabia no último, o
           teto cortava de novo, e 90 minutos viravam CINCO lados. */
        int faltam = quantos - nsides;
        if (faltam < 1) faltam = 1;
        double alvo = cur_start + (total - cur_start) / (double)faltam;
        if (faltam > 1 && end >= alvo && (n - i - 1) >= (faltam - 1)) {
            if (nsides < SIDES_MAX) {
                out[nsides].first = cur_first;
                out[nsides].last  = i;
                out[nsides].start = cur_start;
                out[nsides].end   = end;
            }
            nsides++;
            cur_first = i + 1;
            cur_count = 0;
            cur_start = end;
        }
    }
    if (cur_count) {
        if (nsides < SIDES_MAX) {
            out[nsides].first = cur_first;
            out[nsides].last  = n - 1;
            out[nsides].start = cur_start;
            out[nsides].end   = total;
        }
        nsides++;
    }
    return nsides;
}

void sides_build(const int *durations, int ntracks, Sides *out)
{
    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!durations || ntracks <= 0) return;

    static double start[SIDES_MAX * 64];
    static double dur[SIDES_MAX * 64];
    int n = ntracks;
    if (n > (int)(sizeof(dur) / sizeof(dur[0]))) n = (int)(sizeof(dur) / sizeof(dur[0]));

    /* Duração zero não é "não sei", é "não dura nada": três faixas ilegíveis
       num disco de doze tiram um quarto do total e some um LADO inteiro, sem
       erro nenhum. As que faltam recebem a MEDIANA das que deram — a média
       quebra num disco com uma faixa de vinte minutos. */
    int known[SIDES_MAX * 64], nk = 0;
    for (int i = 0; i < n; i++)
        if (durations[i] > 0) known[nk++] = durations[i];
    double median = 0.0;
    if (nk > 0) {
        for (int i = 1; i < nk; i++) {          /* insertion: nk é pequeno */
            int v = known[i], j = i - 1;
            while (j >= 0 && known[j] > v) { known[j + 1] = known[j]; j--; }
            known[j + 1] = v;
        }
        median = (double)known[nk / 2];
    }

    double total = 0.0;
    for (int i = 0; i < n; i++) {
        dur[i] = durations[i] > 0 ? (double)durations[i] : median;
        start[i] = total;
        total += dur[i];
    }
    if (total <= 0.0) return;

    /* Quantos LADOS. Quem se arredonda para cima é o número de DISCOS, porque
       o disco é o objeto físico e ele tem dois lados sempre. Arredondar os
       LADOS dava discos de TRÊS lados — um LP de 45 min, que é a forma mais
       comum que um disco tem, saía com três lados de quinze. */
    int n_sides;
    if (total <= (double)SIDE_MAX_SECONDS)
        n_sides = 1;
    else
        n_sides = 2 * (int)ceil(total / (2.0 * (double)SIDE_MAX_SECONDS));

    Side buf[SIDES_MAX];
    int cnt = cut(start, dur, n, total, n_sides, (double)SIDE_MAX_SECONDS, buf);

    /* O disco simples ANTES do duplo: quando o corte devolve mais lados que o
       plano, tenta com o teto físico antes de aceitar um disco a mais, que é
       a coisa mais cara que esta função decide. */
    if (cnt > n_sides) {
        Side alt[SIDES_MAX];
        int c2 = cut(start, dur, n, total, n_sides, (double)SIDE_HARD_SECONDS, alt);
        if (c2 <= n_sides) {
            cnt = c2;
            memcpy(buf, alt, sizeof(buf));
        }
    }
    /* Número ímpar de lados: tenta o par seguinte. Poucas voltas, e a última
       resposta vale mesmo ímpar — há discos que não se repartem em par
       abaixo do teto, e inventar um lado vazio seria pior. */
    for (int k = 0; k < 3; k++) {
        if (cnt <= 1 || cnt % 2 == 0) break;
        n_sides = cnt + 1;
        cnt = cut(start, dur, n, total, n_sides, (double)SIDE_MAX_SECONDS, buf);
    }

    if (cnt > SIDES_MAX) cnt = SIDES_MAX;
    out->n = cnt;
    memcpy(out->sides, buf, sizeof(Side) * (size_t)cnt);
    /* Contado dos lados que EXISTEM: uma faixa única de uma hora pede quatro
       lados no plano e sobra UM, e um lado é um disco. O número vindo do
       plano dizia "DISCO 2 · LADO A" de um disco simples. */
    out->discos = (cnt + 1) / 2;
    if (out->discos < 1) out->discos = 1;
    for (int i = 0; i < cnt; i++)
        snprintf(out->sides[i].label, sizeof(out->sides[i].label),
                 "LADO %c", (char)('A' + (i < 26 ? i : 25)));
}

int sides_of_track(const Sides *s, int track)
{
    if (!s || s->n <= 0) return -1;
    for (int i = 0; i < s->n; i++)
        if (track >= s->sides[i].first && track <= s->sides[i].last) return i;
    return -1;
}

void sides_label(const Sides *s, int i, char *out, size_t cap)
{
    if (!out || !cap) return;
    if (!s || i < 0 || i >= s->n) { snprintf(out, cap, "LADO"); return; }
    snprintf(out, cap, "%s", s->sides[i].label);
}

void sides_gesture(const Sides *s, int i, char *out, size_t cap)
{
    if (!out || !cap) return;
    char rot[12];
    sides_label(s, i, rot, sizeof(rot));
    /* A pergunta certa não é "este é o último lado?" — é "que gesto o objeto
       pede?", e o objeto responde pelo ÍNDICE: lado ímpar é o verso do que já
       está no prato; lado par é o começo de OUTRO disco, e ali você levanta e
       vai até a estante. As três telas do desktop perguntavam a primeira, que
       acerta por acidente num LP simples e erra em todo duplo. */
    if (i % 2 == 1) {
        snprintf(out, cap, "vire o disco para o %s", rot);
        return;
    }
    if (i > 0 && s && s->discos > 1) {
        snprintf(out, cap, "ponha o DISCO %d, %s", i / 2 + 1, rot);
        return;
    }
    snprintf(out, cap, "agora o %s", rot);
}
