#include "fonte.h"

#include "net.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* O anel da fonte de rede. 4 MiB: um FLAC de 16/44,1 gasta ~1,4 Mbit/s, então
   isto são uns vinte segundos de colchão. Menos que isso e um soluço de Wi-Fi
   de Vita — que é fraco e some quando a tela apaga — vira estalo. Mais que
   isso e o heap do app começa a doer numa coleção grande. */
#define ANEL (4 * 1024 * 1024)

struct Fonte {
    bool rede;

    /* arquivo */
    FILE *f;

    /* rede */
    char url[2048];
    unsigned char *anel;
    volatile long long r_ini;   /* offset absoluto do 1º byte do anel */
    volatile long long r_fim;   /* offset absoluto logo após o último */
    volatile long long pos;     /* onde o decodificador está lendo */
    volatile long long tam;     /* Content-Length, -1 se não se sabe */
    volatile bool fim, parar, erro_flag, refaz;
    volatile long long refaz_de;
    char erro[160];
    pthread_t th;
    pthread_mutex_t mtx;
    pthread_cond_t cond;
    bool th_viva;
};

/* ---------- arquivo ---------- */

Fonte *fonte_arquivo(const char *path)
{
    if (!path) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    Fonte *s = calloc(1, sizeof(*s));
    if (!s) { fclose(f); return NULL; }
    s->f = f;
    s->tam = -1;
    if (fseek(f, 0, SEEK_END) == 0) {
        long t = ftell(f);
        if (t >= 0) s->tam = t;
        fseek(f, 0, SEEK_SET);
    }
    return s;
}

/* ---------- rede ---------- */

/* A thread que busca adiante.

   Ela é dona do ciclo inteiro: abre, empurra para o anel, e quando alguém
   procurou para fora do anel ela REABRE sozinha, com Range, e continua. Quem
   procura só marca `refaz` e vai embora.

   A primeira versão fazia diferente e travava: o `fonte_procura` marcava
   `refaz` e então dava `pthread_join` nesta thread — que, ao ver `refaz`,
   fazia `continue` e nunca saía. O produtor enchia o anel e bloqueava
   esperando o consumidor, e o único consumidor estava dentro do join. Uns
   4 MiB depois, o app inteiro parava. Dava para chegar lá pelo caminho
   normal: o MP3 mantém o lseek de propósito (ver decoder.c), então qualquer
   arrastão na barra de uma faixa da rede passava por ali. */
static void *buscador(void *arg)
{
    Fonte *s = arg;

    for (;;) {
        long long de;
        pthread_mutex_lock(&s->mtx);
        s->refaz = false;
        de = s->refaz_de;
        pthread_mutex_unlock(&s->mtx);

        long long total = -1;
        char erro[160] = {0};
        NetStream *ns = net_stream_open(s->url, NULL, de, &total, erro, sizeof(erro));
        if (!ns) {
            pthread_mutex_lock(&s->mtx);
            if (!s->parar && !s->refaz) {
                snprintf(s->erro, sizeof(s->erro), "%s",
                         erro[0] ? erro : "não abriu");
                s->erro_flag = true;
                pthread_cond_broadcast(&s->cond);
            }
            bool outra = s->refaz && !s->parar;
            pthread_mutex_unlock(&s->mtx);
            if (outra) continue;
            break;
        }

        pthread_mutex_lock(&s->mtx);
        if (total > 0) s->tam = total;
        pthread_mutex_unlock(&s->mtx);

        bool caiu = false, acabou = false, recomeca = false;
        unsigned char buf[16 * 1024];
        for (;;) {
            long r = net_stream_read(ns, buf, sizeof(buf));
            if (r < 0) { caiu = true; break; }
            if (r == 0) { acabou = true; break; }

            /* empurra para o anel, esperando o decodificador consumir */
            size_t n = (size_t)r;
            const unsigned char *p = buf;
            while (n > 0) {
                pthread_mutex_lock(&s->mtx);
                while (!s->parar && !s->refaz &&
                       (s->r_fim - s->r_ini) >= ANEL - 1) {
                    /* joga fora o que já foi lido, guardando um pouco atrás:
                       procurar um pouquinho para trás é comum (o mpg123 faz
                       isso ao sincronizar quadro) */
                    long long sobra = s->pos - s->r_ini;
                    if (sobra > 65536) { s->r_ini += sobra - 65536; break; }
                    pthread_cond_wait(&s->cond, &s->mtx);
                }
                if (s->parar || s->refaz) {
                    recomeca = s->refaz && !s->parar;
                    pthread_mutex_unlock(&s->mtx);
                    n = 0;
                    break;
                }
                size_t livre = (size_t)(ANEL - 1 - (s->r_fim - s->r_ini));
                size_t take = n < livre ? n : livre;
                for (size_t i = 0; i < take; i++)
                    s->anel[(size_t)((s->r_fim + (long long)i) % ANEL)] = p[i];
                s->r_fim += (long long)take;
                pthread_cond_broadcast(&s->cond);
                pthread_mutex_unlock(&s->mtx);
                p += take;
                n -= take;
            }
            if (recomeca || s->parar) break;
        }
        net_stream_close(ns);

        pthread_mutex_lock(&s->mtx);
        if (s->parar) { pthread_mutex_unlock(&s->mtx); break; }
        if (s->refaz || recomeca) { pthread_mutex_unlock(&s->mtx); continue; }
        if (caiu) {
            /* Uma queda no meio NÃO é fim de faixa. Distinguir importa: o
               fim faz o player passar para a próxima, o erro faz a tela
               dizer que a rede caiu. Confundir os dois faz um disco
               "terminar" sozinho quando o Wi-Fi pisca. */
            snprintf(s->erro, sizeof(s->erro), "a rede caiu no meio da faixa");
            s->erro_flag = true;
        } else if (acabou) {
            s->fim = true;
        }
        pthread_cond_broadcast(&s->cond);
        pthread_mutex_unlock(&s->mtx);
        break;
    }

    pthread_mutex_lock(&s->mtx);
    /* Só marca fim se ninguém pediu outra volta: senão o leitor veria "fim"
       no instante entre uma conexão e a seguinte. */
    if (!s->refaz) s->fim = true;
    pthread_cond_broadcast(&s->cond);
    pthread_mutex_unlock(&s->mtx);
    return NULL;
}

Fonte *fonte_rede(const char *url)
{
    if (!url || !url[0]) return NULL;
    Fonte *s = calloc(1, sizeof(*s));
    if (!s) return NULL;
    s->rede = true;
    s->tam = -1;
    snprintf(s->url, sizeof(s->url), "%s", url);
    s->anel = malloc(ANEL);
    if (!s->anel) { free(s); return NULL; }
    pthread_mutex_init(&s->mtx, NULL);
    pthread_cond_init(&s->cond, NULL);
    if (pthread_create(&s->th, NULL, buscador, s) != 0) {
        free(s->anel);
        pthread_mutex_destroy(&s->mtx);
        pthread_cond_destroy(&s->cond);
        free(s);
        return NULL;
    }
    s->th_viva = true;
    return s;
}

/* ---------- comum ---------- */

void fonte_fecha(Fonte *s)
{
    if (!s) return;
    if (s->rede) {
        pthread_mutex_lock(&s->mtx);
        s->parar = true;
        pthread_cond_broadcast(&s->cond);
        pthread_mutex_unlock(&s->mtx);
        if (s->th_viva) pthread_join(s->th, NULL);
        pthread_mutex_destroy(&s->mtx);
        pthread_cond_destroy(&s->cond);
        free(s->anel);
    } else if (s->f) {
        fclose(s->f);
    }
    free(s);
}

long fonte_le(Fonte *s, void *buf, size_t n)
{
    if (!s || !buf || n == 0) return -1;
    if (!s->rede) return (long)fread(buf, 1, n, s->f);

    pthread_mutex_lock(&s->mtx);
    for (;;) {
        if (s->pos < s->r_ini) {
            /* alguém procurou para trás de mais e o anel já jogou fora.
               O alvo é copiado SOB A TRAVA: solto, a thread podia mexer em
               `pos` entre a leitura e o uso, e a busca iria para outro lugar. */
            long long alvo = s->pos;
            pthread_mutex_unlock(&s->mtx);
            if (fonte_procura(s, alvo, SEEK_SET) < 0) return -1;
            pthread_mutex_lock(&s->mtx);
            continue;
        }
        long long tem = s->r_fim - s->pos;
        if (tem > 0) {
            size_t take = (size_t)(tem < (long long)n ? tem : (long long)n);
            unsigned char *o = buf;
            for (size_t i = 0; i < take; i++)
                o[i] = s->anel[(size_t)((s->pos + (long long)i) % ANEL)];
            s->pos += (long long)take;
            pthread_cond_broadcast(&s->cond);
            pthread_mutex_unlock(&s->mtx);
            return (long)take;
        }
        if (s->erro_flag) { pthread_mutex_unlock(&s->mtx); return -1; }
        if (s->fim) { pthread_mutex_unlock(&s->mtx); return 0; }
        pthread_cond_wait(&s->cond, &s->mtx);
    }
}

long long fonte_procura(Fonte *s, long long off, int whence)
{
    if (!s) return -1;
    if (!s->rede) {
        if (fseek(s->f, (long)off, whence) != 0) return -1;
        return ftell(s->f);
    }

    long long alvo;
    pthread_mutex_lock(&s->mtx);
    if (whence == SEEK_SET) alvo = off;
    else if (whence == SEEK_CUR) alvo = s->pos + off;
    else {
        if (s->tam < 0) { pthread_mutex_unlock(&s->mtx); return -1; }
        alvo = s->tam + off;
    }
    if (alvo < 0) alvo = 0;

    /* Dentro do que já está no anel: é só mover o ponteiro, de graça. É o
       caso da maioria dos saltos que um decodificador faz sozinho. */
    if (alvo >= s->r_ini && alvo <= s->r_fim) {
        s->pos = alvo;
        pthread_cond_broadcast(&s->cond);
        pthread_mutex_unlock(&s->mtx);
        return alvo;
    }

    /* Fora: pede à thread que reabra com Range. Caro — uns segundos —, e é o
       preço de procurar dentro de uma faixa que está vindo pela rede.

       Quem procura NÃO espera a thread e NÃO cria outra: só marca e acorda.
       A thread é dona do próprio ciclo. Antes daqui saía um `pthread_join`
       numa thread que, vendo `refaz`, fazia `continue` — ela não saía nunca,
       e o app parava de vez (ver a nota no buscador). Criar uma segunda
       thread depois disso ainda duplicaria bytes no anel. */
    s->refaz = true;
    s->refaz_de = alvo;
    s->r_ini = s->r_fim = s->pos = alvo;
    s->fim = false;
    s->erro_flag = false;
    s->erro[0] = '\0';
    pthread_cond_broadcast(&s->cond);
    pthread_mutex_unlock(&s->mtx);
    return alvo;
}

long long fonte_posicao(const Fonte *s)
{
    if (!s) return -1;
    if (!s->rede) return ftell(s->f);
    return s->pos;
}

long long fonte_tamanho(const Fonte *s) { return s ? s->tam : -1; }

bool fonte_fim(const Fonte *s)
{
    if (!s) return true;
    if (!s->rede) return feof(s->f) != 0;
    return s->fim && s->pos >= s->r_fim;
}

bool fonte_e_rede(const Fonte *s) { return s && s->rede; }

long fonte_colchao(const Fonte *s)
{
    if (!s || !s->rede) return 0;
    long long c = s->r_fim - s->pos;
    return c < 0 ? 0 : (long)c;
}

long fonte_colchao_max(const Fonte *s)
{
    return (s && s->rede) ? (long)ANEL : 0;
}

const char *fonte_erro(const Fonte *s)
{
    if (!s) return "";
    return s->erro_flag ? s->erro : "";
}
