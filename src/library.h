#ifndef STYLUS_LIBRARY_H
#define STYLUS_LIBRARY_H

#include <stdbool.h>
#include <stddef.h>

#include "sides.h"

#define MAX_PATH_LEN 1024
#define MAX_TITLE_LEN 256
#define MAX_NAME_LEN 256

/* Quantas raízes a estante aceita varrer. A do desktop varre TODAS as pastas
   configuradas e não só a primeira; aqui vale a mesma regra, porque no Vita a
   música pode estar no SD2VITA (ux0:), no cartão oficial (uma0:), na memória
   interna (imc0:) ou na do modelo 2000 (xmc0:) — e apontar para uma só era o
   jeito mais provável de a estante abrir vazia. */
#define MAX_ROOTS 8

/* O arquivo que a pessoa escreve quando a música não está em nenhum dos
   palpites: uma raiz por linha, `#` é comentário. Mora ao lado dos dados. */
#define ROOTS_FILE "roots.txt"

typedef struct Album Album;

typedef struct {
    char path[MAX_PATH_LEN];   /* caminho completo do arquivo */
    char title[MAX_TITLE_LEN]; /* título: tag se houver, senão o nome limpo */
    char file[MAX_NAME_LEN];   /* nome do arquivo, cru — a chave de ordenação */
    int  number;               /* número da faixa, -1 se desconhecido */
    int  seconds;              /* duração, -1 se desconhecida */
    bool decodable;            /* este VPK sabe tocar (mpg123: MP1/2/3) */
    /* Faixa que vem da REDE: o id dela no Qobuz. Vazio numa faixa do cartão.
       Fica aqui, e não numa segunda espécie de faixa ao lado, porque tudo o
       que já sabe ler um Track — a estante, o deck, os LADOS, o scrobble,
       as recomendações — passa a saber ler uma faixa transmitida sem uma
       linha de mudança. Uma segunda espécie seria um segundo tocador.
       O `path` de uma faixa dessas guarda o destino de DOWNLOAD, e não uma
       URL: a URL do Qobuz vale uma hora e é resolvida na hora de tocar. */
    char remote_id[32];
    Album *owner;              /* álbum que contém esta faixa */
} Track;

struct Album {
    char key[MAX_PATH_LEN];      /* dir do álbum relativo à raiz — é o que o
                                    scrobble manda ao PC como "pasta" */
    int  root_idx;               /* qual raiz; (root_idx, key) é o id único */
    char artist[MAX_NAME_LEN];
    char album[MAX_NAME_LEN];
    Track *tracks;
    int ntracks;
    int cap;
    int ndecodable;              /* quantas destas o VPK toca */
    int seconds_total;           /* soma das durações conhecidas, -1 se nenhuma */
    Sides lados;                 /* a tese do sistema: o disco tem LADOS */
    bool meta_loaded;            /* já leu as tags (título/duração) */
    /* capa embutida do primeiro arquivo que tiver APIC front cover */
    unsigned char *cover;
    size_t cover_len;
    bool cover_loaded;
};

/* O que a varredura encontrou em cada raiz — para a tela poder DIZER por que
   está vazia em vez de mostrar "0 discos" e deixar a pessoa adivinhando. */
typedef struct {
    char path[MAX_PATH_LEN];
    bool opened;      /* o diretório abriu */
    int  err;         /* o que o sistema disse quando NÃO abriu (0 = abriu) */
    int  audio;       /* arquivos de áudio achados aqui */
    int  other;       /* arquivos ignorados (extensão desconhecida) */
} ScanRoot;

/* Uma pasta visitada pela varredura, com a data que ela tinha na hora.
   É com isto que o índice se confere sem revarrer — ver library_cache_load. */
typedef struct {
    char path[MAX_PATH_LEN];
    long long mtime;
} DirStamp;

typedef struct {
    Album *albums;
    int nalbums;
    int cap;
    DirStamp *stamps;      /* pastas visitadas, para conferir o índice */
    int nstamps, stamps_cap;
    ScanRoot roots[MAX_ROOTS];
    int nroots;
    bool roots_from_config;   /* vieram do roots.txt, não dos palpites */
    bool roots_discovered;    /* achadas procurando, porque os palpites falharam */
    int files_seen;
    int dirs_seen;
    int audio_found;
    /* chamado a cada punhado de arquivos para a tela não parecer travada */
    void (*progress)(void *ud, const char *where, int files);
    void *progress_ud;
} Library;

void library_init(Library *lib);
/* Acrescenta uma raiz (dedup por caminho, ignorando maiúsculas, e recusa uma
   que esteja dentro de outra já aceita — senão o mesmo disco entra duas vezes) */
int  library_add_root(Library *lib, const char *root);
/* Os palpites, na ordem. Devolve o número escrito em `out`. */
int  library_default_roots(const char **out, int max);
/* Lê `<cfg_dir>/roots.txt` se existir; senão põe os palpites. */
void library_roots_from(Library *lib, const char *cfg_dir);
void library_set_progress(Library *lib, void (*fn)(void *, const char *, int), void *ud);

/* Procura música nos dispositivos quando os palpites não acharam nada:
   olha as pastas de 1º nível de ux0:/uma0:/imc0:/xmc0:/ur0: e adota como
   raiz toda que tenha áudio dentro. Devolve quantas achou.

   É o que faz o app funcionar sem ninguém configurar nada — a pessoa pôs a
   música em `ux0:Musicas` e o app acha, em vez de dizer "ux0:music não
   existe" e ficar por isso mesmo. Chamada de dentro do library_scan; é
   pública para o teste de host poder exercitá-la contra uma árvore falsa. */
int  library_discover(Library *lib);

int  library_scan(Library *lib);

/* ---------- o índice da estante ----------

   POR QUE EXISTE: são 3.729 faixas em 507 pastas no cartão do dono deste app,
   e varrer tudo isso é o que a tela de "procurando os discos" mostra a cada
   arranque. O índice guarda o resultado; o arranque seguinte lê e mostra.

   COMO SE CONFERE, que é a parte que importa: guardando a data de cada pasta
   VISITADA. Em FAT/exFAT, mexer em qualquer coisa dentro de uma pasta muda a
   data DELA — então uma faixa nova numa pasta de álbum muda a data do álbum,
   e um álbum novo muda a data do artista. Conferir são ~500 stats; revarrer é
   abrir 500 pastas e ler 3.700 entradas. Se qualquer data mudou, ou alguma
   pasta sumiu, o índice é descartado inteiro e a varredura é feita.

   Nunca é a palavra final: um índice que não abre, que é de outra versão, ou
   que não confere simplesmente não existe, e a varredura acontece como antes.
   Cache que mente é pior que cache que não existe. */
int  library_cache_save(const Library *lib, const char *path);

/* 0 = o índice servia e a estante está montada; -1 = varra. */
int  library_cache_load(Library *lib, const char *path);
void library_free(Library *lib);
Album *library_album(Library *lib, int i);
void library_sort(Library *lib);

/* Uma frase dizendo o que a varredura viu — a estante vazia mostra ESTA, não
   um silêncio. */
void library_status(const Library *lib, char *out, size_t cap);

/* Grava um relatório da varredura em `path`, uma linha por raiz.

   POR QUE, se a estante já mostra o library_status: porque a tela some
   quando se muda de tela, e porque quem conserta o app quase nunca é quem
   está com o aparelho na mão. Foi exatamente um arquivo assim, deixado no
   cartão por uma build de teste, que revelou que o `opendir("ux0:music")`
   devolvia NULL — coisa que nenhuma leitura do código pegava e que a tela,
   sozinha, não teria como provar depois.

   É pequeno, roda uma vez por arranque, e nunca falha o arranque. */
void library_report(const Library *lib, const char *path);

/* O que o sistema disse, em palavra. Devolve "" quando abriu. */
const char *scan_err_str(int err);

/* Lê as tags (título, número, duração) do álbum. Caro: uma abertura de arquivo
   por faixa. NÃO reordena — a ordem sai do nome do arquivo na varredura, e
   reordenar aqui invalidaria os `Track *` que o player e as recomendações já
   estão segurando. Idempotente. */
int album_load_meta(Album *alb);

/* Carrega (uma vez) a capa embutida. 0 achou, 1 não tem, -1 erro. */
int album_load_cover(Album *alb);
void album_free_cover(Album *alb);

/* Índice da faixa dentro do álbum dono, -1 se não achar. */
int library_find_track_by_path(Library *lib, Album **out_album, const char *path);

/* Extensões: UMA lista. No desktop eram seis e discordavam entre si; aqui a
   pergunta "é áudio?" e a pergunta "eu sei tocar?" têm respostas separadas e
   um único dono cada. */
bool audio_ext(const char *name);
bool decodable_ext(const char *name);

/* Tira o número da frente e a extensão de um nome de arquivo.
   Devolve o número achado (ou -1) e escreve o resto em `out`. Público porque
   é o que o teste de host mede. */
int  track_name_split(const char *filename, char *out, size_t cap);

#endif
