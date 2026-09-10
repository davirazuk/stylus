#include "library.h"
#include "paths.h"
#include "fsutil.h"
#include "decoder.h"

#include <dirent.h>
#include <sys/stat.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdio.h>
#include <limits.h>

/* ---------------- extensões ---------------- */

/* O que CONTA como música na estante. */
static const char *EXT_AUDIO[] = {
    ".mp3", ".mp2", ".mp1", ".mpga",
    ".m4a", ".aac", ".alac",
    ".flac", ".ogg", ".oga", ".opus",
    ".wav", ".wma", ".aif", ".aiff", ".ape", ".shn",
    NULL
};

/* "Eu sei tocar isto?" quem responde é o decoder.c, que é quem tem os
   decodificadores. Havia uma lista de extensões aqui e outra lá dentro: a
   segunda ganhou FLAC, Vorbis e Opus e esta não, e o resultado teria sido um
   disco marcado "não tocável" na estante que o player toca sem reclamar. */

static bool ends_with_ext(const char *name, const char *ext)
{
    size_t n = strlen(name), e = strlen(ext);
    if (n <= e) return false;   /* ".mp3" sozinho não é faixa, é arquivo oculto */
    return strcasecmp(name + (n - e), ext) == 0;
}

static bool in_ext_list(const char *name, const char **list)
{
    for (int i = 0; list[i]; i++)
        if (ends_with_ext(name, list[i])) return true;
    return false;
}

bool audio_ext(const char *name)     { return name && in_ext_list(name, EXT_AUDIO); }
bool decodable_ext(const char *name) { return name && dec_kind_of(name) != DEC_NONE; }

/* ---------------- nome de arquivo → número + título ---------------- */

/* "01 - Song.mp3" -> 1, "Song";  "05.Song.flac" -> 5, "Song";
   "Song.mp3" -> -1, "Song";      "1979.mp3" -> -1, "1979"
   O último importa: "1979" e "99 Problems" são NOMES DE MÚSICA, e um número
   colado no nome não é numeração de faixa. Só conta como número quando vem
   separado do resto por espaço, hífen, ponto ou sublinhado. */
int track_name_split(const char *filename, char *out, size_t cap)
{
    if (out && cap) out[0] = '\0';
    if (!filename) return -1;

    /* corta a extensão */
    char base[MAX_NAME_LEN];
    snprintf(base, sizeof(base), "%s", filename);
    char *dot = strrchr(base, '.');
    if (dot && dot != base) *dot = '\0';

    const char *p = base;
    while (*p == ' ') p++;

    int num = -1;
    const char *rest = p;
    if (p[0] >= '0' && p[0] <= '9') {
        int v = 0, digits = 0;
        const char *q = p;
        while (*q >= '0' && *q <= '9') { v = v * 10 + (*q - '0'); q++; digits++; if (digits > 4) break; }
        /* o separador é o que distingue "01 - Song" de "1979"; o teto de 999
           é o que distingue "101 - Song" (disco 1, faixa 1) de
           "1979 - Song", que é um ANO e não uma faixa. */
        const char *s = q;
        int sep = 0;
        while (*s == ' ') { s++; sep = 1; }
        if (*s == '-' || *s == '.' || *s == '_') { s++; sep = 1; }
        while (*s == ' ') { s++; sep = 1; }
        if (sep && *s && digits <= 3 && v > 0 && v <= 999) { num = v; rest = s; }
    }

    if (out && cap) {
        size_t l = strlen(rest);
        if (l >= cap) l = cap - 1;
        memcpy(out, rest, l);
        out[l] = '\0';
        /* espaço no fim lê como corte */
        while (l > 0 && out[l - 1] == ' ') out[--l] = '\0';
        if (!out[0]) snprintf(out, cap, "%s", base);
    }
    return num;
}

/* ---------------- o rótulo da estante ---------------- */

/* O que o CARD mostra não é o nome da pasta.

   SINTOMA: quatro cards de Radiohead lado a lado dizendo "1993-02-11 -...",
   "1993-04-02 -...", "1993-10-15 -..." e "1996-05-27 -...". O nome da pasta
   de um bootleg é "data - artista - lugar", o card tem 212 px, e a elisão
   cortava pela direita — ou seja, mostrava exatamente o pedaço que TODOS
   têm igual e escondia o único que distingue um do outro. Aumentar a letra
   para caber a leitura PIOROU isto: quanto maior o texto, mais cedo o corte.

   Então a data sai da frente e volta na linha de baixo, e o artista sai
   quando ele já está escrito logo abaixo. Sobra o que a pessoa procura:

     "1993-02-11 - Radiohead - Signal Radio Session, England [FM]"
      →  Signal Radio Session, England [FM]
         Radiohead · 1993-02-11

   Nada aqui renomeia pasta nenhuma — o `key` e o `path` continuam intactos,
   e é por eles que o scrobble e a retomada acham o disco. Isto é só tela.

   Puro de propósito: quem decide o que se lê na estante é testável sem abrir
   janela (ver tools/host_test.c). */

/* Um prefixo de data: AAAA, AAAA-MM ou AAAA-MM-DD seguido de " - ".
   Devolve o resto, ou NULL quando não há data na frente. */
static const char *pula_data(const char *s, char *data, size_t dcap)
{
    int i = 0;
    while (s[i] >= '0' && s[i] <= '9') i++;
    if (i != 4) return NULL;             /* ano tem quatro dígitos, sempre */

    int j = i;
    for (int p = 0; p < 2; p++) {        /* -MM e depois -DD, os dois opcionais */
        if (s[j] != '-') break;
        int k = j + 1, d = 0;
        while (s[k] >= '0' && s[k] <= '9') { k++; d++; }
        if (d != 2) break;
        j = k;
    }
    if (strncmp(s + j, " - ", 3) != 0) return NULL;
    if (data && dcap) snprintf(data, dcap, "%.*s", j, s);
    return s + j + 3;
}

void album_display(const Album *a, char *titulo, size_t tcap, char *sub, size_t scap)
{
    if (titulo && tcap) titulo[0] = '\0';
    if (sub && scap)    sub[0] = '\0';
    if (!a) return;

    char data[16] = "";
    const char *t = a->album;

    const char *sem_data = pula_data(t, data, sizeof(data));
    if (sem_data && *sem_data) t = sem_data;

    /* o artista só sai da frente porque ele REAPARECE na linha de baixo */
    size_t al = strlen(a->artist);
    if (al && strncasecmp(t, a->artist, al) == 0 && strncmp(t + al, " - ", 3) == 0
        && t[al + 3])
        t += al + 3;

    /* Se sobrou nada, a poda comeu o nome inteiro (um disco chamado só
       "1979", uma pasta que é só o nome do artista). Melhor o nome cru que
       um card em branco. */
    if (!*t) t = a->album;

    if (titulo && tcap) snprintf(titulo, tcap, "%s", t);

    if (sub && scap) {
        const char *ar = a->artist[0] ? a->artist : "";
        if (ar[0] && data[0])      snprintf(sub, scap, "%s  ·  %s", ar, data);
        else if (ar[0])            snprintf(sub, scap, "%s", ar);
        else if (data[0])          snprintf(sub, scap, "%s", data);
        else                       snprintf(sub, scap, "%s", "—");
    }
}

/* ---------------- raízes ---------------- */

/* Os palpites, do mais provável ao menos. Um cartão SD2VITA aparece como
   ux0:; o cartão oficial da Sony como uma0:; a memória interna do modelo
   2000 como imc0:. Uma instalação com o SD2VITA em ux0: ainda pode ter a
   música no cartão oficial — é por isso que são todos varridos, não só o
   primeiro que abrir. */
static int g_mount_init_rc = 0, g_mount_rc = 0, g_mount_feito = 0;
static int g_qb_achou = -1, g_qb_conf = -1;
static int g_bgm_rc = 1, g_bgm_visto = 0;   /* 1 = valor impossível p/ um rc */
static long g_bgm_teto = 0;
static int g_dlg_rc = 1, g_dlg_visto = 0;   /* 1 = valor impossível p/ um rc */

void library_set_qobuz(int achou, int configurado)
{
    g_qb_achou = achou;
    g_qb_conf = configurado;
}

void library_set_bgm(int porta_rc, long teto_hz)
{
    g_bgm_rc = porta_rc;
    g_bgm_teto = teto_hz;
    g_bgm_visto = 1;
}

void library_set_dialog(int rc)
{
    g_dlg_rc = rc;
    g_dlg_visto = 1;
}

void library_set_music_mount(int init_rc, int mount_rc)
{
    g_mount_init_rc = init_rc;
    g_mount_rc = mount_rc;
    g_mount_feito = 1;
}

static const char *DEFAULT_ROOTS[] = {
    /* ux0:music PRIMEIRO, music0: como reserva. Os dois são a mesma pasta
       (ver root_canon) e o de cima é o que tem significado fora daqui: é o
       nome que o app de Música do Vita usa, que a tela do "ouvir enquanto
       joga" manda abrir, e que vai no scrobble. O music0: fica para o caso
       de um firmware em que só o ponto de montagem abra. */
    "ux0:music",
    "music0:",
    STYLUS_OWN_MUSIC,
    "uma0:music",
    "imc0:music",
    "xmc0:music",
    NULL
};

int library_default_roots(const char **out, int max)
{
    int n = 0;
    for (int i = 0; DEFAULT_ROOTS[i] && n < max; i++) out[n++] = DEFAULT_ROOTS[i];
    return n;
}

/* "music0:" e "ux0:music" SÃO A MESMA PASTA.

   SINTOMA: o relatório do cartão trouxe as duas abertas, cada uma com
   audio=3729, e a estante ficou com 776 discos onde há 388 — cada disco
   duas vezes, e com ele os lados e a ordem das faixas.

   O `music0:` é o ponto de montagem que o sceAppUtilMusicMount() entrega; o
   `ux0:music` é o mesmo conteúdo pelo caminho do cartão. O detalhe cruel: o
   ux0:music só passou a ABRIR depois que o mount foi acrescentado. Ou seja,
   esta duplicata NASCEU do conserto anterior — antes dele, só uma das duas
   abria e ninguém via o problema.

   O root_covered abaixo só sabia comparar PREFIXO, e "music0:" não é prefixo
   de "ux0:music" nem o contrário. Por isso a forma canônica: comparar o que
   os dois nomes SIGNIFICAM, não como estão escritos.

   E não era só a estante em dobro: o decodificador abre a faixa com fopen(),
   que é o newlib — o mesmo newlib cuja tradução de caminho já obrigou a
   varredura a trocar opendir por sceIoDopen (ver fsutil.h). Metade dos discos
   ficou com caminho "music0:/...", e um disco que não abre é um disco que não
   toca. Preferir ux0:music não é gosto: é o caminho que o resto do sistema
   sabe abrir. */
static void root_canon(const char *p, char *out, size_t cap)
{
    if (!cap) return;
    out[0] = '\0';
    if (!p) return;
    if (strncasecmp(p, "music0:", 7) == 0) {
        const char *resto = p + 7;
        while (*resto == '/') resto++;
        if (*resto) snprintf(out, cap, "ux0:music/%s", resto);
        else        snprintf(out, cap, "%s", "ux0:music");
        return;
    }
    snprintf(out, cap, "%s", p);
}

/* "ux0:music" contém "ux0:music/rock": aceitar as duas varre o mesmo disco
   duas vezes e a estante mostra tudo em dobro. */
static bool root_covered(const Library *lib, const char *cand_bruto)
{
    char cand_buf[MAX_PATH_LEN], have_buf[MAX_PATH_LEN];
    root_canon(cand_bruto, cand_buf, sizeof(cand_buf));
    const char *cand = cand_buf;
    size_t cl = strlen(cand);
    for (int i = 0; i < lib->nroots; i++) {
        root_canon(lib->roots[i].path, have_buf, sizeof(have_buf));
        const char *have = have_buf;
        size_t hl = strlen(have);
        if (cl == hl && strcasecmp(have, cand) == 0) return true;
        /* o sistema de arquivos do Vita não distingue maiúsculas: "ux0:MUSIC"
           e "ux0:music" são a MESMA pasta, e aceitar as duas duplica tudo. */
        if (cl > hl && strncasecmp(cand, have, hl) == 0 && cand[hl] == '/') return true;
        if (hl > cl && strncasecmp(have, cand, cl) == 0 && have[cl] == '/') return true;
    }
    return false;
}

int library_add_root(Library *lib, const char *root)
{
    if (!lib || !root || !root[0]) return -1;
    if (lib->nroots >= MAX_ROOTS) return -1;
    char norm[MAX_PATH_LEN];
    snprintf(norm, sizeof(norm), "%s", root);
    /* tira espaço e barra do fim */
    size_t n = strlen(norm);
    while (n > 0 && (norm[n - 1] == ' ' || norm[n - 1] == '\t' ||
                     norm[n - 1] == '\r' || norm[n - 1] == '\n')) norm[--n] = '\0';
    /* NÃO se normaliza a grafia aqui: quem tenta as duas formas é o
       dir_open_err, e por bons motivos (ver a nota lá). Normalizar na entrada
       consertaria só as raízes — não as subpastas nem a sondagem da
       descoberta — e ainda trocaria, na tela, o caminho que a pessoa
       escreveu por outro. */
    path_trim_slash(norm);
    if (!norm[0]) return -1;
    if (root_covered(lib, norm)) return -1;
    ScanRoot *r = &lib->roots[lib->nroots++];
    memset(r, 0, sizeof(*r));
    snprintf(r->path, sizeof(r->path), "%s", norm);
    return lib->nroots - 1;
}

void library_roots_from(Library *lib, const char *cfg_dir)
{
    if (!lib) return;
    if (cfg_dir && cfg_dir[0]) {
        char p[MAX_PATH_LEN];
        path_join(p, sizeof(p), cfg_dir, ROOTS_FILE);
        FILE *f = fopen(p, "r");
        if (f) {
            char line[MAX_PATH_LEN];
            int added = 0;
            while (fgets(line, sizeof(line), f)) {
                char *s = line;
                while (*s == ' ' || *s == '\t') s++;
                if (*s == '#' || *s == '\0' || *s == '\n' || *s == '\r') continue;
                if (library_add_root(lib, s) >= 0) added++;
            }
            fclose(f);
            if (added > 0) { lib->roots_from_config = true; return; }
        }
    }
    const char *d[MAX_ROOTS];
    int n = library_default_roots(d, MAX_ROOTS);
    for (int i = 0; i < n; i++) library_add_root(lib, d[i]);
}

void library_set_progress(Library *lib, void (*fn)(void *, const char *, int), void *ud)
{
    if (!lib) return;
    lib->progress = fn;
    lib->progress_ud = ud;
}

/* ---------------- artista / álbum ---------------- */

/*  Artista/Álbum -> artist=Artista, album=Álbum
    Álbum         -> album=Álbum, sem artista
    (vazio)       -> as faixas soltas na raiz                                */
static void set_artist_album(const char *rel_dir, char *artist, size_t artist_cap,
                             char *album, size_t album_cap)
{
    if (artist && artist_cap) artist[0] = '\0';
    if (album && album_cap) album[0] = '\0';
    if (!rel_dir || !rel_dir[0]) {
        snprintf(album, album_cap, "%s", "loose tracks");
        return;
    }
    const char *last = strrchr(rel_dir, '/');
    if (!last) {
        /* Disco na RAIZ, sem pasta de artista: "1993-02-11 - Radiohead -
           Signal Radio Session". O nome do disco continua sendo a pasta
           inteira — é o `album_display` que tira a data e o artista dela na
           hora de escrever —, mas o ARTISTA dá para saber daqui, e sem isso
           estes discos ficam fora da tela de ARTISTS por não ter nenhum.
           A tag do arquivo, quando existir, sobrescreve isto depois. */
        snprintf(album, album_cap, "%s", rel_dir);
        const char *sem_data = pula_data(rel_dir, NULL, 0);
        if (sem_data && *sem_data) {
            const char *sep = strstr(sem_data, " - ");
            size_t m = sep ? (size_t)(sep - sem_data) : 0;
            if (m > 0 && m < artist_cap) {
                memcpy(artist, sem_data, m);
                artist[m] = '\0';
            }
        }
        return;
    }
    size_t alen = (size_t)(last - rel_dir);
    /* Artista/Disco/CD1: o artista é o PRIMEIRO segmento, não o caminho todo —
       senão "Radiohead/OK Computer" e "Radiohead/Kid A" viram dois artistas. */
    const char *first = memchr(rel_dir, '/', alen);
    if (first) alen = (size_t)(first - rel_dir);

    /* "1993-02-11 - Radiohead - Signal Radio Session/AMEC2013" —
       O ARTISTA ESTÁ NO MEIO, e o segmento inteiro não é nome de ninguém.

       SINTOMA: a tela de ARTISTS mostrava 113 nomes numa coleção que tem umas
       trinta, e metade deles era uma DATA: "1998-04-02 -…", "2006-06 -…",
       "2013-10-26 -…". Cada show ao vivo virava um artista só dele. Uma tela
       que existe para agrupar, mostrando um grupo por item, é uma lista de
       discos com o nome errado.

       A forma é a mesma que o `album_display` já conhece — data, " - ",
       artista, " - ", título — então a data sai pelo mesmo `pula_data` e o
       artista é o que vem até o " - " seguinte. Onde não houver esse segundo
       separador, vale tudo o que sobrou depois da data: um disco chamado
       "2007 - In Rainbows" numa pasta de artista é o disco, não o artista, e
       aí o `first` já era o artista mesmo. */
    {
        char cand[MAX_NAME_LEN];
        size_t n = alen < sizeof(cand) ? alen : sizeof(cand) - 1;
        memcpy(cand, rel_dir, n);
        cand[n] = '\0';
        const char *sem_data = pula_data(cand, NULL, 0);
        if (sem_data && *sem_data) {
            const char *sep = strstr(sem_data, " - ");
            size_t m = sep ? (size_t)(sep - sem_data) : strlen(sem_data);
            if (m > 0 && m < artist_cap) {
                memcpy(artist, sem_data, m);
                artist[m] = '\0';
                snprintf(album, album_cap, "%s", last + 1);
                return;
            }
        }
    }

    if (alen >= artist_cap) alen = artist_cap - 1;
    memcpy(artist, rel_dir, alen);
    artist[alen] = '\0';
    snprintf(album, album_cap, "%s", last + 1);
}

/* ---------------- álbuns e faixas ---------------- */

static Album *find_album(Library *lib, int root_idx, const char *key)
{
    for (int i = 0; i < lib->nalbums; i++) {
        /* o `key[0] &&` que morava aqui fazia a pasta RAIZ nunca casar: cada
           faixa solta em ux0:music/ virava um álbum "?" só dela, e um cartão
           com a música toda solta abria com centenas de discos de uma faixa. */
        if (lib->albums[i].root_idx == root_idx &&
            strcmp(lib->albums[i].key, key) == 0)
            return &lib->albums[i];
    }
    return NULL;
}

/* Os `Track *` de fora apontam para dentro de `a->tracks`; realocar o array de
   álbuns move os Album, e o `owner` de cada faixa apontaria para o lugar
   errado. Por isso o owner é religado depois de cada crescimento. */
static void relink_owners(Library *lib)
{
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        for (int j = 0; j < a->ntracks; j++) a->tracks[j].owner = a;
    }
}

static Album *ensure_album(Library *lib)
{
    if (lib->nalbums >= lib->cap) {
        int n = lib->cap ? lib->cap * 2 : 64;
        Album *a = realloc(lib->albums, (size_t)n * sizeof(Album));
        if (!a) return NULL;
        lib->albums = a;
        lib->cap = n;
        relink_owners(lib);
    }
    Album *a = &lib->albums[lib->nalbums];
    memset(a, 0, sizeof(*a));
    a->seconds_total = -1;
    lib->nalbums++;
    return a;
}

static int add_track(Album *a, const char *full, const char *base)
{
    /* o mesmo arquivo duas vezes (duas raízes que se sobrepõem, um link) sai
       na tela como faixa repetida e conta dobrado no lado */
    for (int i = 0; i < a->ntracks; i++)
        if (strcmp(a->tracks[i].path, full) == 0) return 0;

    if (a->ntracks >= a->cap) {
        int n = a->cap ? a->cap * 2 : 16;
        Track *t = realloc(a->tracks, (size_t)n * sizeof(Track));
        if (!t) return -1;
        a->tracks = t;
        a->cap = n;
    }
    Track *t = &a->tracks[a->ntracks];
    memset(t, 0, sizeof(*t));
    snprintf(t->path, MAX_PATH_LEN, "%s", full);
    snprintf(t->file, MAX_NAME_LEN, "%s", base);
    t->number = track_name_split(base, t->title, MAX_TITLE_LEN);
    t->seconds = -1;
    t->decodable = decodable_ext(base);
    t->owner = a;
    a->ntracks++;
    if (t->decodable) a->ndecodable++;
    return 0;
}

/* ---------------- varredura ---------------- */

#define SCAN_MAX_DEPTH 12

/* Guarda a pasta e a data que ela tem AGORA. Falhar aqui não é erro: sem o
   carimbo o índice simplesmente não vai poder ser conferido depois, e a
   varredura acontece — que é o comportamento de sempre. */
static void marca_pasta(Library *lib, const char *abs)
{
    if (lib->nstamps >= lib->stamps_cap) {
        int n = lib->stamps_cap ? lib->stamps_cap * 2 : 64;
        DirStamp *d = realloc(lib->stamps, (size_t)n * sizeof(DirStamp));
        if (!d) return;
        lib->stamps = d;
        lib->stamps_cap = n;
    }
    DirStamp *d = &lib->stamps[lib->nstamps];
    snprintf(d->path, sizeof(d->path), "%s", abs);
    d->mtime = dir_mtime(abs);
    lib->nstamps++;
}

/* -------- detecção de pastas de disco (multi-disc) --------
   Pastas como "Disc 01", "Disc 2", "CD 1", "CD03" etc. indicam discos
   separados de um mesmo álbum. O scanner deve mesclar as faixas destas
   pastas no álbum-pai, em vez de criar um álbum separado para cada disco. */
static int is_disc_dir(const char *name)
{
    if (!name || !name[0]) return 0;
    const char *p = name;
    /* "Disc" ou "CD" */
    if ((p[0] == 'D' || p[0] == 'd') && (p[1] == 'i' || p[1] == 'I') &&
        (p[2] == 's' || p[2] == 'S') && (p[3] == 'c' || p[3] == 'C')) {
        p += 4;
    } else if ((p[0] == 'C' || p[0] == 'c') && (p[1] == 'D' || p[1] == 'd')) {
        p += 2;
    } else {
        return 0;
    }
    /* espaço opcional */
    if (*p == ' ' || *p == '_') p++;
    /* pelo menos um dígito */
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') p++;
    /* pode terminar aqui ou ter sufixo como "Disc 1 - Bonus" */
    return (*p == '\0' || *p == ' ' || *p == '-' || *p == '_');
}

static void scan_dir(Library *lib, int root_idx, const char *abs, const char *rel, int depth)
{
    if (depth > SCAN_MAX_DEPTH) return;
    int erro = 0;
    DirIter *d = dir_open_err(abs, &erro);
    if (!d) {
        if (depth == 0 && root_idx >= 0 && root_idx < lib->nroots)
            lib->roots[root_idx].err = erro;
        return;
    }
    lib->dirs_seen++;
    marca_pasta(lib, abs);
    if (lib->progress && (lib->dirs_seen % 8) == 0)
        lib->progress(lib->progress_ud, abs, lib->files_seen);

    const char *nome;
    int isdir;
    while (dir_next(d, &nome, &isdir)) {
        if (nome[0] == '.') continue;
        char child_abs[MAX_PATH_LEN], child_rel[MAX_PATH_LEN];
        path_join(child_abs, sizeof(child_abs), abs, nome);
        path_join(child_rel, sizeof(child_rel), rel, nome);

        if (isdir == 1) {
            /* ═══ MESCLAGEM DE DISCOS ════════════════════════════════════════
               Se a pasta se chama "Disc 01", "CD 2" etc., as faixas dela
               pertencem ao ÁLBUM-PAI — não a um álbum separado. */
            const char *merge_rel = is_disc_dir(nome) ? rel : child_rel;
            scan_dir(lib, root_idx, child_abs, merge_rel, depth + 1);
            continue;
        }
        if (isdir != 0) continue;

        lib->files_seen++;
        if (!audio_ext(nome)) { lib->roots[root_idx].other++; continue; }
        lib->audio_found++;
        lib->roots[root_idx].audio++;

        Album *a = find_album(lib, root_idx, rel);
        if (!a) {
            a = ensure_album(lib);
            if (!a) { dir_close(d); return; }
            a->root_idx = root_idx;
            snprintf(a->key, MAX_PATH_LEN, "%s", rel);
            set_artist_album(rel, a->artist, MAX_NAME_LEN, a->album, MAX_NAME_LEN);
            a->mtime = dir_mtime(abs);
        }
        add_track(a, child_abs, nome);
    }
    dir_close(d);
}

/* Compara nome de arquivo tratando dígitos como NÚMERO: sem isso "10" vem
   antes de "2" e um disco de doze faixas toca 1, 10, 11, 12, 2, 3… */
static int natcmp(const char *a, const char *b)
{
    while (*a && *b) {
        if (*a >= '0' && *a <= '9' && *b >= '0' && *b <= '9') {
            long na = 0, nb = 0;
            while (*a >= '0' && *a <= '9') na = na * 10 + (*a++ - '0');
            while (*b >= '0' && *b <= '9') nb = nb * 10 + (*b++ - '0');
            if (na != nb) return na < nb ? -1 : 1;
            continue;
        }
        /* `unsigned char` NÃO É ENFEITE AQUI.

           O `char` puro é ASSINADO no x86 e NÃO ASSINADO no ARM — e esta
           função roda nos dois: no aparelho, e no teste de host que deveria
           provar o que o aparelho faz. Num nome acentuado (esta coleção tem
           vários, e a própria descoberta procura por "Músicas") o primeiro
           byte de "ú" é 0xC3: vira -61 no PC e 195 no Vita.

           Resultado: a estante saía numa ordem no teste e noutra no aparelho,
           com os acentuados ANTES de tudo aqui e DEPOIS de tudo lá. Nenhum
           teste podia pegar, porque o teste é justamente o lado que discorda.
           Com unsigned char os dois concordam, e byte alto vem depois do
           ASCII, que é a única ordem defensável sem uma tabela de collation. */
        int ca = (unsigned char)*a, cb = (unsigned char)*b;
        if (ca >= 'A' && ca <= 'Z') ca += 32;
        if (cb >= 'A' && cb <= 'Z') cb += 32;
        if (ca != cb) return ca < cb ? -1 : 1;
        a++; b++;
    }
    if (*a) return 1;
    if (*b) return -1;
    return 0;
}

static int track_cmp(const void *pa, const void *pb)
{
    const Track *a = pa, *b = pb;
    /* faixa numerada vem antes de faixa sem número */
    int na = a->number >= 0 ? a->number : INT_MAX;
    int nb = b->number >= 0 ? b->number : INT_MAX;
    if (na != nb) return na < nb ? -1 : 1;
    return natcmp(a->file, b->file);
}

static int album_cmp(const void *pa, const void *pb)
{
    const Album *a = pa, *b = pb;
    int r = strcasecmp(a->artist, b->artist);
    if (r) return r;
    r = strcasecmp(a->album, b->album);
    if (r) return r;
    return a->root_idx - b->root_idx;
}

void library_sort(Library *lib)
{
    if (!lib || lib->nalbums <= 1) return;
    qsort(lib->albums, (size_t)lib->nalbums, sizeof(Album), album_cmp);
    relink_owners(lib);
}

/* ---------------- vida ---------------- */

void library_init(Library *lib)
{
    memset(lib, 0, sizeof(*lib));
}

/* ---------------- descoberta ----------------

   Por que isto existe: os palpites acima são NOMES DE PASTA. Eles acertam
   quem guardou a música em `ux0:music` e erram todo o resto — quem escreveu
   "Music", quem pôs em `ux0:MP3`, quem deixou dentro de `ux0:media/audio`.
   O aparelho reportava, com toda a razão, "as raízes não existem", e a
   pessoa não tinha o que fazer a respeito sem um PC e um editor de texto.
   Adivinhar mais nomes só empurra o problema: a lista nunca fica completa.

   Então em vez de adivinhar, PROCURA. Abre cada dispositivo, olha as pastas
   de primeiro nível e pergunta a cada uma "tem áudio aí dentro?". A que
   tiver vira raiz. Custa uma varredura rasa e resolve o caso inteiro, com
   qualquer nome de pasta, sem a pessoa configurar nada.

   Duas coisas seguram o custo. A lista de pastas do SISTEMA é pulada — sem
   ela, `ux0:app` (centenas de pastas) e `ux0:pspemu` (um cartão de PSP
   inteiro) seriam vasculhados atrás de um MP3 que não está lá. E a sonda
   tem ORÇAMENTO: para na primeira faixa que achar, e desiste depois de
   algumas centenas de entradas. Uma pasta gigante de fotos atrasa a busca
   por um instante, não por um minuto. */

static const char *DEVICES[] = { "ux0:", "uma0:", "imc0:", "xmc0:", "ur0:", NULL };

/* A lista de dispositivos a sondar. No aparelho é a de cima e ponto.

   No PC ela vem de STYLUS_DEVICES (caminhos separados por vírgula), porque
   `ux0:` não existe aqui e sem isso a única forma de provar que a busca
   funciona seria instalar no Vita e olhar. Com o gancho, o teste monta uma
   árvore falsa e mede o comportamento de verdade — inclusive o orçamento e
   a lista de pastas puladas. O aparelho nunca lê variável de ambiente. */
static const char **devices_list(void)
{
#ifdef __vita__
    return DEVICES;
#else
    static char buf[1024];
    static const char *lista[MAX_ROOTS + 1];
    const char *env = getenv("STYLUS_DEVICES");
    if (!env || !*env) return DEVICES;
    snprintf(buf, sizeof(buf), "%s", env);
    int n = 0;
    char *save = NULL;
    for (char *p = strtok_r(buf, ",", &save); p && n < MAX_ROOTS;
         p = strtok_r(NULL, ",", &save))
        lista[n++] = p;
    lista[n] = NULL;
    return lista;
#endif
}

/* Pastas que o sistema usa e onde música do usuário não mora. Comparadas
   sem diferenciar maiúsculas, porque o cartão é FAT e o Vita não é
   consistente sobre isso. */
static const char *PULAR[] = {
    "app", "appmeta", "bgdl", "cache", "calendar", "license", "message",
    "near", "patch", "pspemu", "psm", "shell", "tai", "temp", "theme",
    "user", "system", "vitastylus", "iconlayout.xml", "id.dat",
    /* "data" é onde TODO homebrew guarda arquivo, e um jogo guarda o banco de
       som dele ali. SINTOMA: a estante do usuário virou 47 efeitos sonoros do
       Bloons TD 5 (`ux0:/data/btd5/.../SwampSpawn.wav`) enquanto 3.728 MP3
       em ux0:music ficavam invisíveis — a descoberta adotou `ux0:/data`
       porque achou áudio lá dentro, e achou mesmo. Música do usuário não mora
       na raiz de `data`; a nossa própria (STYLUS_OWN_MUSIC) é palpite
       explícito e não passa por aqui. */
    "data",
    "downloads", "video", "picture", "photo", "savegames", "shader_cache",
    "addcont", "nonpdrm", "vitacheat", "vitashell", "customtheme",
    "custombootsplash", "email", "mms", "sceiotrash",
    NULL
};

static bool eh_sistema(const char *nome)
{
    for (int i = 0; PULAR[i]; i++)
        if (strcasecmp(nome, PULAR[i]) == 0) return true;
    /* Tudo que a Sony prefixa com "sce_" ou "PS" também não é do usuário. */
    if (strncasecmp(nome, "sce_", 4) == 0) return true;
    return false;
}

/* PROVA de que ali mora uma coleção — não é a mesma pergunta que "isto é
   áudio?".

   O `.wav` fica de fora DE PROPÓSITO: ninguém guarda a discoteca em WAV, e
   toda pasta de jogo tem dezenas deles. Foi assim que a estante virou os
   efeitos sonoros do Bloons TD 5. O `.wav` continua sendo áudio para todo o
   resto do app — é tocável e aparece na estante quando está numa raiz de
   verdade; o que ele não faz é ELEGER uma pasta como raiz.

   Idem `.shn`/`.ape`, que são de arquivo morto e não de coleção montada. */
static const char *EXT_PROVA[] = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma",
    NULL
};

static bool prova_de_musica(const char *name)
{
    return name && in_ext_list(name, EXT_PROVA);
}

/* Tem algum arquivo de áudio aqui dentro? Para no primeiro. `orcamento`
   conta entradas visitadas e é decrementado através da recursão — é o que
   impede uma pasta enorme de segurar o arranque. */
static bool tem_audio(const char *dir, int prof, int *orcamento)
{
    if (prof < 0 || *orcamento <= 0) return false;
    DirIter *d = dir_open(dir);
    if (!d) return false;

    bool achou = false;
    const char *nome;
    int isdir;
    /* Os subdiretórios são deixados para uma segunda passada: um álbum tem
       dezenas de faixas e nenhuma subpasta, então olhar os ARQUIVOS antes
       acerta na primeira volta e nem chega a descer. */
    char subs[16][MAX_NAME_LEN];
    int nsubs = 0;

    while (!achou && dir_next(d, &nome, &isdir)) {
        if (nome[0] == '.') continue;
        if ((*orcamento)-- <= 0) break;
        if (isdir == 1) {
            if (nsubs < 16 && !eh_sistema(nome))
                snprintf(subs[nsubs++], MAX_NAME_LEN, "%s", nome);
        } else if (isdir == 0 && prova_de_musica(nome)) {
            achou = true;
        }
    }
    dir_close(d);

    for (int i = 0; !achou && i < nsubs; i++) {
        char filho[MAX_PATH_LEN];
        path_join(filho, sizeof(filho), dir, subs[i]);
        achou = tem_audio(filho, prof - 1, orcamento);
    }
    return achou;
}

int library_discover(Library *lib)
{
    if (!lib) return 0;
    int achadas = 0;

    const char **devs = devices_list();
    for (int i = 0; devs[i] && lib->nroots < MAX_ROOTS; i++) {
        DirIter *dev = dir_open(devs[i]);
        if (!dev) continue;

        /* Os nomes são copiados ANTES de sondar: o `nome` do dir_next vale
           só até a próxima chamada, e sondar uma pasta abre outro iterador. */
        char cands[32][MAX_NAME_LEN];
        int nc = 0;
        const char *nome;
        int isdir;
        while (nc < 32 && dir_next(dev, &nome, &isdir)) {
            if (isdir != 1 || nome[0] == '.') continue;
            if (eh_sistema(nome)) continue;
            snprintf(cands[nc++], MAX_NAME_LEN, "%s", nome);
        }
        dir_close(dev);

        /* Os nomes ÓBVIOS primeiro. Não é otimização: é ordem de preferência.
           Num cartão com `music/` e uma pasta de jogo, as duas têm áudio
           dentro, e quem for sondado primeiro é quem vira raiz — a ordem do
           diretório é alfabética, então "data" ganhava de "music" sempre.
           Aqui a discoteca ganha por ser discoteca. */
        static const char *OBVIOS[] = {
            "music", "Music", "MUSIC", "musica", "musicas",
            "Musica", "Musicas", "Música", "Músicas", "songs", "Songs",
            NULL
        };
        for (int o = 0; OBVIOS[o] && lib->nroots < MAX_ROOTS; o++) {
            for (int j = 0; j < nc; j++) {
                if (strcasecmp(cands[j], OBVIOS[o]) != 0) continue;
                if (!cands[j][0]) break;          /* já consumido */
                char cam[MAX_PATH_LEN];
                path_join(cam, sizeof(cam), devs[i], cands[j]);
                int orc = 400;
                if (tem_audio(cam, 3, &orc) && library_add_root(lib, cam) >= 0)
                    achadas++;
                cands[j][0] = '\0';               /* não sondar de novo abaixo */
                break;
            }
        }

        for (int j = 0; j < nc && lib->nroots < MAX_ROOTS; j++) {
            if (!cands[j][0]) continue;
            char cam[MAX_PATH_LEN];
            path_join(cam, sizeof(cam), devs[i], cands[j]);
            if (lib->progress)
                lib->progress(lib->progress_ud, cam, lib->files_seen);
            int orcamento = 400;
            if (!tem_audio(cam, 3, &orcamento)) continue;
            /* >= 0, não > 0: a função devolve o ÍNDICE da raiz, e o da
               primeira é zero — com `> 0` a primeira pasta achada não era
               contada, e o número que a tela mostra saía errado. */
            if (library_add_root(lib, cam) >= 0) achadas++;
        }
    }

    if (achadas > 0) lib->roots_discovered = true;
    return achadas;
}

int library_scan(Library *lib)
{
    if (!lib) return -1;
    int primeira = lib->nroots;
    for (int i = 0; i < lib->nroots; i++) {
        ScanRoot *r = &lib->roots[i];
        int erro = 0;
        DirIter *d = dir_open_err(r->path, &erro);
        if (!d) { r->err = erro; continue; }
        dir_close(d);
        r->opened = true;
        scan_dir(lib, i, r->path, "", 0);
    }

    /* Nenhum palpite vingou. Antes de mostrar uma estante vazia e mandar a
       pessoa editar um arquivo de texto, PROCURA — ver a nota acima. Só
       neste caso: quem já tem música achada não paga a busca, e um
       roots.txt escrito à mão continua sendo a palavra final. */
    if (lib->audio_found == 0 && !lib->roots_from_config) {
        library_discover(lib);
        for (int i = primeira; i < lib->nroots; i++) {
            ScanRoot *r = &lib->roots[i];
            int erro = 0;
            DirIter *d = dir_open_err(r->path, &erro);
            if (!d) { r->err = erro; continue; }
            dir_close(d);
            r->opened = true;
            scan_dir(lib, i, r->path, "", 0);
        }
    }
    /* A ordem da faixa dentro do disco sai do NOME do arquivo. A insertion
       sort que morava aqui comparava o número já normalizado para 0 contra o
       -1 cru do outro lado: a condição de parada nunca dava verdadeira e o
       laço INVERTIA o álbum inteiro. Todo disco tocava de trás para a frente,
       sem erro nenhum, e o sintoma ("a ordem está errada") não aponta para uma
       comparação. */
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        if (a->ntracks > 1)
            qsort(a->tracks, (size_t)a->ntracks, sizeof(Track), track_cmp);
    }
    library_sort(lib);
    /* Um disco cujas faixas não são TODAS numeradas, ou cuja numeração não
       forma a de um disco, fica com o nome de arquivo inteiro como título —
       senão "1979.mp3" viraria a faixa 1979 e "99 Problems" a faixa 99. */
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        int numbered = 0, prev = 0, ok = 1;
        for (int j = 0; j < a->ntracks; j++) {
            if (a->tracks[j].number < 0) { ok = 0; break; }
            if (a->tracks[j].number <= prev) { ok = 0; break; }  /* sobe e não repete */
            prev = a->tracks[j].number;
            numbered++;
        }
        /* DENSIDADE, não "o maior é o número de faixas": num cartão de Vita a
           pessoa copia as favoritas, e um disco com as faixas 1,2,3,10,11,12
           é normal — a regra apertada do desktop reprovava esse e devolvia
           "10 - No Surprises" como título. O que ela precisa recusar de
           verdade é uma pasta de nomes como "99 Problems" e "50 Ways...",
           onde os números são esparsos porque não são numeração nenhuma. */
        if (ok && numbered == a->ntracks && numbered > 0 &&
            prev <= a->ntracks * 3 + 4)
            continue;   /* é numeração de disco: o título já veio sem o número */
        for (int j = 0; j < a->ntracks; j++) {
            a->tracks[j].number = -1;
            char *dot;
            snprintf(a->tracks[j].title, MAX_TITLE_LEN, "%s", a->tracks[j].file);
            dot = strrchr(a->tracks[j].title, '.');
            if (dot && dot != a->tracks[j].title) *dot = '\0';
        }
    }
    return 0;
}

/* Os códigos que o sceIo* devolve, nos casos que importam aqui.

   No Vita o erro de arquivo é 0x80010000 | errno, e o errno é o do newlib —
   em DECIMAL. A tabela antiga tratava o byte baixo como se o hexadecimal já
   fosse o número e errava quase todas: 0x13 é 19 (ENODEV, "não existe esse
   aparelho") e estava escrito "read only"; 0x18 é 24 (EMFILE) e estava "not a
   folder"; 0x1C é 28 (ENOSPC) e estava "out of memory".

   SINTOMA: o relatório do cartão dizia "unknown error" na única linha que
   importava — 0x80010001, EPERM, que não estava na lista — e "read only" em
   três aparelhos que só estavam AUSENTES. Quem leu o relatório concluiu que o
   problema era o nome do caminho e passou a tentar duas grafias; o problema
   era permissão, e a estante continuou vazia. Um relatório que erra o nome do
   erro é pior que um que só mostra o número: manda procurar no lugar errado. */
const char *scan_err_str(int err)
{
    if (err == 0) return "";

    /* no PC vem o errno cru; no Vita vem embrulhado */
    unsigned u = (unsigned)err;
    int e = ((u & 0xFFFF0000u) == 0x80010000u) ? (int)(u & 0xFFFFu) : (int)u;

    switch (e) {
    case 1:  return "not allowed (app is 'safe' homebrew)";
    case 2:  return "does not exist";
    case 9:  return "bad handle";
    case 12: return "out of memory";
    case 13: return "permission denied";
    case 16: return "device busy";
    case 19: return "no such device";
    case 20: return "not a folder";
    case 22: return "invalid path";
    case 24: return "too many open files";
    case 28: return "card full";
    case 30: return "read only";
    case 36: return "path too long";
    default: return "unknown error";
    }
}

/* A SONDA.

   Duas explicações diferentes produzem exatamente a mesma tela vazia, e
   escolher errado entre elas já custou duas viagens ao aparelho:

     (a) o sandbox de homebrew "safe" — ux0: inteiro fechado menos ux0:data;
     (b) ux0:music ser pasta de MÍDIA do Content Manager, fechada para
         qualquer app comum, safe ou não.

   O relatório antigo só sondava pastas de música, e por isso não separava as
   duas. Estas linhas separam: se ux0:app e ux0:tai ABREM e ux0:music não, é
   (b) — e mexer em "Enable unsafe homebrew" não vai adiantar nada. Se nada
   fora de ux0:data abrir, é (a).

   Custa uns dez sceIoDopen por arranque, uma vez, e evita uma viagem. */
static void library_sonda(FILE *f)
{
#ifdef __vita__
    static const char *ALVOS[] = {
        "ux0:",             /* a raiz: abre?                          */
        "ux0:data",         /* a única pasta que o modo safe libera    */
        "ux0:app",          /* fora da lista branca, e NÃO é mídia     */
        "ux0:tai",          /* idem — e é onde mora o MusicPremium     */
        "ux0:pkgj",         /* idem, de um app que sabidamente funciona*/
        "ux0:music",        /* mídia                                  */
        "ux0:/music",       /* a mesma, com a outra grafia            */
        "music0:",          /* o que o sceAppUtilMusicMount entrega    */
        "music0:/",         /* idem, com barra                        */
        "ux0:photo",        /* mídia                                  */
        "ux0:video",        /* mídia                                  */
        "ux0:downloads",    /* comum                                  */
        NULL
    };
    fprintf(f, "\nmusic mount sceAppUtilInit=0x%08X  MusicMount=0x%08X%s\n",
            (unsigned)g_mount_init_rc, (unsigned)g_mount_rc,
            g_mount_feito ? "" : "  (NOT CALLED)");
    if (g_bgm_visto)
        fprintf(f, "bgm port    sceAppMgrAcquireBgmPort=0x%08X (%s)  cap=%ld Hz\n",
                (unsigned)g_bgm_rc, g_bgm_rc >= 0 ? "granted" : "REFUSED",
                g_bgm_teto);
    if (g_dlg_visto)
        fprintf(f, "dialog cfg  sceCommonDialogSetConfigParam=0x%08X (%s)\n",
                (unsigned)g_dlg_rc,
                g_dlg_rc == 0 ? "keyboard can open" : "NO KEYBOARD");
    if (g_qb_achou >= 0)
        fprintf(f, "qobuz       config file %s, credentials %s\n",
                g_qb_achou ? "found" : "MISSING",
                g_qb_conf ? "complete (search screen)"
                          : "incomplete (setup screen)");
    /* O MUSICPREMIUM ESTÁ MESMO CARREGADO?

       "tocar dentro do jogo" não é a porta BGM sozinha: a porta faz o som
       sobreviver à tela apagada e à LiveArea, e só. Quem impede o sistema de
       SUSPENDER o app quando um jogo entra na frente é o plugin de kernel
       MusicPremium. (O VitaWave, citado como referência, promete no próprio
       README apenas "screen is off or in LiveArea" — ele também não toca
       dentro de jogo.)

       E o plugin só vale se estiver em ur0:tai E listado no ur0:tai/config.txt
       sob *KERNEL. O cartão tem uma cópia em ux0:tai, que é onde ela NÃO
       basta. Do PC não dá para conferir — ur0: é a memória interna. Daqui
       dá: o app roda no aparelho e, como homebrew unsafe, lê ur0: à vontade.
       Sem esta conferência, "o segundo plano não funciona" continua sendo
       indistinguível de "o plugin nunca subiu". */
    {
        fprintf(f, "\nmusicpremium (background audio INSIDE a game)\n");
        static const char *SKPRX[] = { "ur0:tai/music_premium.skprx",
                                       "ux0:tai/music_premium.skprx", NULL };
        for (int i = 0; SKPRX[i]; i++) {
            FILE *m = fopen(SKPRX[i], "rb");
            fprintf(f, "  [%c] %-30s %s\n", m ? 'x' : ' ', SKPRX[i],
                    m ? "present" : "missing");
            if (m) fclose(m);
        }
        const char *CFG = "ur0:tai/config.txt";
        FILE *c = fopen(CFG, "r");
        if (!c) {
            fprintf(f, "  [ ] %-30s COULD NOT READ\n", CFG);
        } else {
            char linha[256];
            int citado = 0, kernel = 0, em_kernel = 0;
            while (fgets(linha, sizeof(linha), c)) {
                if (strstr(linha, "*KERNEL")) { kernel = 1; em_kernel = 1; }
                else if (linha[0] == '*')     { em_kernel = 0; }
                else if (strstr(linha, "music_premium")) {
                    citado = 1;
                    fprintf(f, "  ->  listed%s: %.90s",
                            em_kernel ? " under *KERNEL" : " but NOT under *KERNEL",
                            linha);
                    if (linha[strlen(linha) - 1] != '\n') fprintf(f, "\n");
                }
            }
            fclose(c);
            fprintf(f, "  [%c] %-30s %s\n", citado ? 'x' : ' ', CFG,
                    !kernel ? "no *KERNEL section!"
                            : citado ? "plugin is listed"
                                     : "PLUGIN NOT LISTED — this is why");
        }
    }

    fprintf(f, "\nprobe       (tells a sandbox apart from a media folder)\n");
    for (int i = 0; ALVOS[i]; i++) {
        int e = 0;
        DirIter *d = dir_open_err(ALVOS[i], &e);
        if (d) {
            int n = 0;
            const char *nome;
            int isdir;
            while (n < 9999 && dir_next(d, &nome, &isdir)) n++;
            dir_close(d);
            fprintf(f, "  [x] %-16s opened, %d entries\n", ALVOS[i], n);
        } else {
            fprintf(f, "  [ ] %-16s 0x%08X (%s)\n", ALVOS[i], (unsigned)e,
                    scan_err_str(e));
        }
    }
#else
    (void)f;
#endif
}

void library_report(const Library *lib, const char *path)
{
    if (!lib || !path) return;
    FILE *f = fopen(path, "w");
    if (!f) return;                       /* nunca atrapalha o arranque */

    fprintf(f, "vitastylus  build %s %s\n", __DATE__, __TIME__);
    /* Qual API abriu as pastas: o opendir do newlib já devolveu NULL para
       "ux0:music" nas três formas, e a troca pelo sceIoDopen é justamente o
       conserto — se um dia isto voltar a falhar, é a primeira coisa a saber. */
#ifdef __vita__
    fprintf(f, "dir api     sceIoDopen/sceIoDread\n");
#else
    fprintf(f, "dir api     opendir/readdir\n");
#endif
    fprintf(f, "roots       %d%s\n", lib->nroots,
            lib->roots_from_config ? " (from roots.txt)" : " (default)");
    for (int i = 0; i < lib->nroots; i++) {
        const ScanRoot *r = &lib->roots[i];
        if (r->opened)
            fprintf(f, "  [x] %-28s audio=%d outros=%d\n",
                    r->path, r->audio, r->other);
        else
            fprintf(f, "  [ ] %-28s DID NOT OPEN: 0x%08X (%s)\n",
                    r->path, (unsigned)r->err, scan_err_str(r->err));
    }
    fprintf(f, "folders     %d\n", lib->dirs_seen);
    fprintf(f, "files       %d  (audio %d)\n", lib->files_seen, lib->audio_found);
    fprintf(f, "albuns      %d\n", lib->nalbums);

    int faixas = 0, maior = 0;
    for (int i = 0; i < lib->nalbums; i++) {
        faixas += lib->albums[i].ntracks;
        if (lib->albums[i].ntracks > maior) maior = lib->albums[i].ntracks;
    }
    /* Nada de contar duração aqui: o ID3 é lido sob demanda, então neste
       instante NENHUMA foi lida, e um "sem duracao: 3728" pareceria defeito
       sendo o funcionamento normal. */
    fprintf(f, "tracks      %d  (largest album: %d)\n", faixas, maior);

    char st[512];
    library_status(lib, st, sizeof(st));
    fprintf(f, "state       %s\n", st);
    library_sonda(f);
    fclose(f);
}

void library_status(const Library *lib, char *out, size_t cap)
{
    if (!out || !cap) return;
    out[0] = '\0';
    if (!lib) return;

    if (lib->nroots == 0) {
        snprintf(out, cap, "no folder to scan");
        return;
    }
    int opened = 0;
    for (int i = 0; i < lib->nroots; i++) if (lib->roots[i].opened) opened++;

    if (opened == 0) {
        /* Nem os palpites nem a BUSCA acharam pasta que abrisse. Antes esta
           frase listava os palpites — "ux0:music não abriu" — e mandava a
           pessoa consertar um nome de pasta que o app agora nem precisa
           acertar. O que sobrou de verdade é mais simples e mais útil: não
           há música alcançável em nenhum dispositivo montado. */
        int cartao = dir_exists("ux0:");
        snprintf(out, cap,
                 cartao ? "searched every device and found no audio"
                        : "the card (ux0:) will not open — is it in the device?");
        return;
    }
    if (lib->audio_found == 0) {
        int other = 0;
        for (int i = 0; i < lib->nroots; i++) other += lib->roots[i].other;
        if (lib->files_seen == 0)
            snprintf(out, cap, "the folders opened and are empty (%d subfolders)",
                     lib->dirs_seen);
        else
            snprintf(out, cap,
                     "saw %d file%s, none of them audio (%d of other kinds)",
                     lib->files_seen, lib->files_seen == 1 ? "" : "s", other);
        return;
    }
    size_t n = (size_t)snprintf(out, cap, "%d track%s in %d folder%s",
                                lib->audio_found, lib->audio_found == 1 ? "" : "s",
                                lib->dirs_seen, lib->dirs_seen == 1 ? "" : "s");
    /* Quando as raízes foram DESCOBERTAS, dizer onde: a pessoa não escolheu
       essa pasta e merece saber de onde veio o que está vendo. */
    if (lib->roots_discovered && lib->nroots > 0 && n + 8 < cap)
        snprintf(out + n, cap - n, " — found in %s%s",
                 lib->roots[lib->nroots - 1].path,
                 lib->nroots > 1 ? " e outras" : "");
}

void library_free(Library *lib)
{
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        free(a->tracks);
        free(a->cover);
    }
    free(lib->albums);
    lib->albums = NULL;
    lib->nalbums = lib->cap = 0;
    free(lib->stamps);
    lib->stamps = NULL;
    lib->nstamps = lib->stamps_cap = 0;
    dec_global_exit();
}

/* ---------------- o índice da estante (ver library.h) ---------------- */

/* Uma linha por registro, campos separados por TAB, texto puro.

   Podia ser binário e seria menor. Não é, de propósito: quando a estante
   aparecer errada, quem for consertar vai querer ABRIR este arquivo no
   VitaShell e ver o que ele diz — e um despejo de struct não diz nada. O
   arquivo tem ~500 KB numa coleção de 3.700 faixas; ler isso do cartão é
   muito mais barato do que reabrir 500 pastas.

   A versão na primeira linha é o que impede um índice velho de ser lido com
   um layout novo: mudou a struct, muda o número, e todo índice antigo passa
   a ser simplesmente descartado. */
#define CACHE_MAGIC "vitastylus-estante"
/* 2: a linha do álbum ganhou a DATA DA PASTA no fim. Subir a versão faz o
   índice velho ser recusado e a estante revarrida uma vez — que é o que se
   quer: um índice sem a data faria a fileira "recém-chegados" da home mentir
   (tudo com data zero, ordenada por acidente) em vez de simplesmente
   aparecer na varredura seguinte. */
#define CACHE_VER   3

static void escapa(char *s)
{
    /* TAB e quebra de linha são os separadores; um nome de arquivo pode ter
       os dois. Vira espaço — o nome guardado aqui é só para reconstruir a
       estante, e o `path` é a chave de verdade. */
    for (; *s; s++) if (*s == '\t' || *s == '\n' || *s == '\r') *s = ' ';
}

int library_cache_save(const Library *lib, const char *path)
{
    if (!lib || !path) return -1;
    /* Nada a guardar. O carregamento já RECUSA um índice de zero disco (ver a
       nota lá), então gravá-lo só produz um arquivo que ninguém vai aceitar —
       e um que engana quem for ler o cartão para entender por que a estante
       está vazia. Foi exatamente o que aconteceu. */
    if (lib->nalbums <= 0) return -1;
    /* Grava num parcial e renomeia: um índice cortado no meio (bateria
       acabando, cartão retirado) não pode virar uma estante pela metade. */
    char tmp[MAX_PATH_LEN];
    snprintf(tmp, sizeof(tmp), "%s.parcial", path);
    FILE *f = fopen(tmp, "w");
    if (!f) return -1;

    fprintf(f, "%s\t%d\n", CACHE_MAGIC, CACHE_VER);
    fprintf(f, "R\t%d\n", lib->nroots);
    for (int i = 0; i < lib->nroots; i++)
        fprintf(f, "r\t%s\n", lib->roots[i].path);
    fprintf(f, "D\t%d\n", lib->nstamps);
    for (int i = 0; i < lib->nstamps; i++)
        fprintf(f, "d\t%lld\t%s\n", lib->stamps[i].mtime, lib->stamps[i].path);

    fprintf(f, "A\t%d\n", lib->nalbums);
    for (int i = 0; i < lib->nalbums; i++) {
        const Album *a = &lib->albums[i];
        char key[MAX_PATH_LEN], art[MAX_NAME_LEN], alb[MAX_NAME_LEN];
        snprintf(key, sizeof(key), "%s", a->key);
        snprintf(art, sizeof(art), "%s", a->artist);
        snprintf(alb, sizeof(alb), "%s", a->album);
        escapa(key); escapa(art); escapa(alb);
        fprintf(f, "a\t%d\t%d\t%s\t%s\t%s\t%lld\n",
                a->root_idx, a->ntracks, key, art, alb, a->mtime);
        for (int j = 0; j < a->ntracks; j++) {
            const Track *t = &a->tracks[j];
            char tp[MAX_PATH_LEN], ti[MAX_TITLE_LEN], fl[MAX_NAME_LEN];
            snprintf(tp, sizeof(tp), "%s", t->path);
            snprintf(ti, sizeof(ti), "%s", t->title);
            snprintf(fl, sizeof(fl), "%s", t->file);
            escapa(tp); escapa(ti); escapa(fl);
            fprintf(f, "t\t%d\t%d\t%s\t%s\t%s\n",
                    t->number, t->seconds, tp, ti, fl);
        }
    }
    int ok = (fflush(f) == 0);
    fclose(f);
    if (!ok) { remove(tmp); return -1; }
    remove(path);
    return rename(tmp, path) == 0 ? 0 : -1;
}

/* Corta a linha em campos por TAB. Devolve quantos. */
static int campos(char *linha, char **out, int max)
{
    int n = 0;
    char *p = linha;
    size_t l = strlen(p);
    while (l && (p[l - 1] == '\n' || p[l - 1] == '\r')) p[--l] = '\0';
    while (n < max) {
        out[n++] = p;
        char *t = strchr(p, '\t');
        if (!t) break;
        *t = '\0';
        p = t + 1;
    }
    return n;
}

int library_cache_load(Library *lib, const char *path)
{
    if (!lib || !path) return -1;
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    char linha[MAX_PATH_LEN + 512];
    char *c[8];
    int ok = 0;

    if (fgets(linha, sizeof(linha), f) && campos(linha, c, 8) == 2 &&
        strcmp(c[0], CACHE_MAGIC) == 0 && atoi(c[1]) == CACHE_VER)
        ok = 1;
    if (!ok) { fclose(f); return -1; }

    /* Primeiro as raízes e as datas. Se qualquer pasta mudou ou sumiu, nem
       vale a pena ler o resto: fecha e manda varrer. */
    int nroots = 0, ndirs = 0;
    char roots[MAX_ROOTS][MAX_PATH_LEN];

    if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 2 ||
        c[0][0] != 'R') { fclose(f); return -1; }
    nroots = atoi(c[1]);
    if (nroots < 0 || nroots > MAX_ROOTS) { fclose(f); return -1; }
    for (int i = 0; i < nroots; i++) {
        if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 2 ||
            c[0][0] != 'r') { fclose(f); return -1; }
        snprintf(roots[i], MAX_PATH_LEN, "%s", c[1]);
    }

    if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 2 ||
        c[0][0] != 'D') { fclose(f); return -1; }
    ndirs = atoi(c[1]);
    if (ndirs < 0) { fclose(f); return -1; }
    for (int i = 0; i < ndirs; i++) {
        if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 3 ||
            c[0][0] != 'd') { fclose(f); return -1; }
        long long antes = atoll(c[1]);
        if (dir_mtime(c[2]) != antes) { fclose(f); return -1; }   /* mudou */
    }

    /* Conferiu. Agora sim monta a estante.

       Daqui para baixo, qualquer falha tem de deixar a `lib` como estava: o
       contrato desta função é "0 = montada, -1 = NADA mudou". Sem isso, um
       índice cortado no meio deixaria meia estante montada e o main varreria
       por cima dela — cada disco apareceria duas vezes. */
    for (int i = 0; i < nroots; i++) {
        int idx = library_add_root(lib, roots[i]);
        if (idx >= 0) lib->roots[idx].opened = true;
    }

    if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 2 ||
        c[0][0] != 'A') goto falhou;
    int nalb = atoi(c[1]);

    /* UM ÍNDICE VAZIO NÃO É ÍNDICE.

       SINTOMA: o app rodou meses com a estante vazia (o VPK era homebrew
       "safe" e o sandbox do HENkaku não deixava abrir ux0:music — ver o
       CMakeLists). Ao sair, ele GRAVOU esse nada como índice: R=5, D=0, A=0.
       E um índice com D=0 não tem pasta nenhuma para conferir a data, então
       o laço de validação acima não roda uma vez sequer e o índice passa —
       para sempre. Consertado o sandbox, o arranque seguinte carregaria o
       "nenhum álbum" do cartão e NÃO VARRERIA. O conserto pareceria não ter
       funcionado, e a próxima pessoa iria procurar de novo no lugar errado.

       Guardar "não achei nada" nunca compensa: varrer uma coleção que não
       existe é justamente o caso barato, e um zero em cache é indistinguível
       de uma varredura que falhou — que foi exatamente o que aconteceu. */
    if (nalb <= 0) goto falhou;

    for (int i = 0; i < nalb; i++) {
        /* 7 campos desde a versão 2 do índice: a data da pasta entrou no fim.
           A versão já foi conferida lá em cima, então um arquivo com 6 aqui é
           corrompido, não velho — e o `goto falhou` manda revarrer. */
        if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 7 ||
            c[0][0] != 'a') goto falhou;
        Album *a = ensure_album(lib);
        if (!a) goto falhou;
        a->root_idx = atoi(c[1]);
        a->seconds_total = -1;
        int nt = atoi(c[2]);
        snprintf(a->key, MAX_PATH_LEN, "%s", c[3]);
        snprintf(a->artist, MAX_NAME_LEN, "%s", c[4]);
        snprintf(a->album, MAX_NAME_LEN, "%s", c[5]);
        a->mtime = atoll(c[6]);
        for (int j = 0; j < nt; j++) {
            if (!fgets(linha, sizeof(linha), f) || campos(linha, c, 8) != 6 ||
                c[0][0] != 't') goto falhou;
            if (add_track(a, c[3], c[5]) != 0) goto falhou;
            Track *t = &a->tracks[a->ntracks - 1];
            t->number = atoi(c[1]);
            t->seconds = atoi(c[2]);
            snprintf(t->title, MAX_TITLE_LEN, "%s", c[4]);
            lib->audio_found++;
            if (a->root_idx >= 0 && a->root_idx < lib->nroots)
                lib->roots[a->root_idx].audio++;
        }
    }
    fclose(f);

    lib->dirs_seen = ndirs;
    lib->files_seen = lib->audio_found;
    /* Os LADOS não são montados aqui: eles saem das DURAÇÕES, que saem das
       tags, que são lidas sob demanda por álbum (album_load_meta). O índice
       reproduz o estado logo depois da varredura, e logo depois da varredura
       nenhuma tag foi lida — montar lados agora seria inventar um corte a
       partir de durações que ainda são -1. */
    return 0;

falhou:
    fclose(f);
    for (int i = 0; i < lib->nalbums; i++) {
        free(lib->albums[i].tracks);
        free(lib->albums[i].cover);
    }
    free(lib->albums);
    free(lib->stamps);
    memset(lib, 0, sizeof(*lib));
    return -1;
}

Album *library_album(Library *lib, int i)
{
    if (i < 0 || i >= lib->nalbums) return NULL;
    return &lib->albums[i];
}

/* ---------------- tags ---------------- */

int album_load_meta(Album *alb)
{
    if (!alb || alb->meta_loaded) return 0;
    alb->meta_loaded = true;
    int total = 0, known = 0;
    for (int i = 0; i < alb->ntracks; i++) {
        Track *t = &alb->tracks[i];
        if (!t->decodable) continue;
        DecTags dt;
        if (dec_probe(t->path, &dt, 0) != 0) continue;
        if (dt.title[0]) snprintf(t->title, MAX_TITLE_LEN, "%s", dt.title);
        if (dt.number > 0 && t->number < 0) t->number = dt.number;
        if (dt.seconds > 0) { t->seconds = dt.seconds; total += dt.seconds; known++; }
        if (!alb->artist[0] && dt.artist[0]) snprintf(alb->artist, MAX_NAME_LEN, "%s", dt.artist);
        if (dt.album[0] && (!alb->album[0] || !strcmp(alb->album, "loose tracks")))
            snprintf(alb->album, MAX_NAME_LEN, "%s", dt.album);
        dec_tags_free(&dt);
    }
    /* Duração zero não é "não sei", é "não dura nada": as faixas que faltam
       recebem a MEDIANA das que deram, senão o total mente e a agulha aponta
       para o sulco errado. Aqui basta a média das conhecidas — o VPK não
       reparte lados. */
    if (known > 0) {
        int med = total / known;
        for (int i = 0; i < alb->ntracks; i++)
            if (alb->tracks[i].seconds <= 0) { alb->tracks[i].seconds = med; total += med; }
        alb->seconds_total = total;
    }
    /* Os LADOS. Só agora: antes das tags não há duração, e sem duração não há
       lado — repartir por número de faixas seria inventar um objeto. */
    if (known > 0) {
        int durs[512];
        int n = alb->ntracks < 512 ? alb->ntracks : 512;
        for (int i = 0; i < n; i++) durs[i] = alb->tracks[i].seconds;
        sides_build(durs, n, &alb->lados);
    }
    return 0;
}

/* OS NOMES DE ARQUIVO DE CAPA — UMA lista, e é esta.

   O lado desktop deste projeto teve CINCO listas destas, discordando entre
   si, e a que ninguém olhava não achava capa nenhuma. Uma só, aqui.

   `cover.jpg` primeiro porque é o que o `tools/musica-para-o-vita.py`
   escreve; os outros são o que um acervo vindo do Windows ou de um ripador
   costuma trazer. `back.jpg` e `albumartsmall.jpg` NÃO entram de propósito:
   a contracapa e a miniatura de 32 px não são a capa, e um "pega a primeira
   imagem em ordem alfabética" põe justamente essas duas na frente. */
static const char *CAPA_NOMES[] = {
    "cover.jpg", "cover.jpeg", "folder.jpg", "front.jpg", "album.jpg",
    "cover.png", "folder.png", "front.png", NULL
};

/* A CAPA COMO ARQUIVO, ao lado das faixas.

   POR QUE ISTO EXISTE: o app só sabia ler arte EMBUTIDA no áudio, e esta
   coleção quase não tem — 388 discos, um punhado de arquivos com APIC. Toda
   a estante era capa gerada. E o cartão do aparelho tinha, o tempo todo,
   324 `cover.jpg` de 500x500 dentro das pastas dos discos: postos lá pelo
   `musica-para-o-vita.py` para o app Música da Sony, e invisíveis para este.
   Duas metades do mesmo sistema, uma escrevendo e a outra sem saber ler —
   a mesma família do módulo da polybar que ninguém desenhava.

   Compara SEM MAIÚSCULA: um acervo passado por um Windows guarda
   `Folder.jpg` e `Cover.jpg`, e comparar cru descartaria metade. */
static int capa_do_diretorio(const char *dir, unsigned char **out, size_t *len)
{
    if (!dir || !dir[0]) return 1;
    DIR *d = opendir(dir);
    if (!d) return 1;

    char achado[MAX_PATH_LEN];
    achado[0] = '\0';
    int melhor = 9999;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        for (int i = 0; CAPA_NOMES[i]; i++) {
            if (i >= melhor) break;          /* já tenho um nome preferido */
            if (strcasecmp(e->d_name, CAPA_NOMES[i]) != 0) continue;
            path_join(achado, sizeof(achado), dir, e->d_name);
            melhor = i;
            break;
        }
    }
    closedir(d);
    if (!achado[0]) return 1;

    FILE *f = fopen(achado, "rb");
    if (!f) return 1;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    /* 4 MB de teto: uma capa de 500x500 tem ~100 KB, e um arquivo maior que
       isto numa pasta de disco é outra coisa (um scan de encarte inteiro).
       Decodificá-lo custaria a memória de vídeo de várias capas de verdade. */
    if (n <= 4 || n > 4 * 1024 * 1024) { fclose(f); return 1; }
    unsigned char *buf = malloc((size_t)n);
    if (!buf) { fclose(f); return 1; }
    size_t lidos = fread(buf, 1, (size_t)n, f);
    fclose(f);
    if (lidos != (size_t)n) { free(buf); return 1; }
    *out = buf;
    *len = lidos;
    return 0;
}

int album_load_cover(Album *alb)
{
    if (!alb) return -1;
    if (alb->cover_loaded) return alb->cover ? 0 : 1;
    alb->cover_loaded = true;
    if (!alb->tracks || alb->ntracks == 0) return 1;

    /* O ARQUIVO PRIMEIRO, a arte embutida depois.

       Nesta ordem porque o arquivo é mais barato (uma leitura contra abrir e
       varrer os metadados de até oito faixas) e porque quem pôs um cover.jpg
       na pasta escolheu aquela imagem — é uma decisão de quem monta o acervo,
       e ela ganha da que veio de fábrica dentro do MP3. */
    {
        const char *p0 = alb->tracks[0].path;
        const char *barra = strrchr(p0, '/');
        if (barra && barra > p0) {
            char dir[MAX_PATH_LEN];
            size_t n = (size_t)(barra - p0);
            if (n < sizeof(dir)) {
                memcpy(dir, p0, n);
                dir[n] = '\0';
                if (capa_do_diretorio(dir, &alb->cover, &alb->cover_len) == 0)
                    return 0;
                /* ═══ FALLBACK: diretório-pai ═══════════════════════════════════
                   Álbuns multi-disco mesclados (via is_disc_dir) têm a primeira
                   faixa numa subpasta "Disc 01" etc. Se não achou capa ali,
                   sobe um nível — é onde o batch ripper costuma colocar. */
                const char *barra2 = NULL;
                for (const char *q = barra - 1; q > dir; q--)
                    if (*q == '/') { barra2 = q; break; }
                if (barra2 && barra2 > dir) {
                    char pai[MAX_PATH_LEN];
                    size_t pn = (size_t)(barra2 - dir);
                    if (pn < sizeof(pai)) {
                        memcpy(pai, dir, pn);
                        pai[pn] = '\0';
                        if (capa_do_diretorio(pai, &alb->cover, &alb->cover_len) == 0)
                            return 0;
                    }
                }
            }
        }
    }

    /* Uma passada por faixa, não duas. A versão anterior chamava o leitor
       DUAS vezes por arquivo — a primeira só para medir o tamanho da capa —
       o que num FLAC significa abrir e varrer os metadados duas vezes. */
    for (int i = 0, tried = 0; i < alb->ntracks && tried < 8; i++) {
        if (!alb->tracks[i].decodable) continue;
        tried++;
        DecTags dt;
        if (dec_probe(alb->tracks[i].path, &dt, 1) != 0) continue;
        if (!alb->artist[0] && dt.artist[0])
            snprintf(alb->artist, MAX_NAME_LEN, "%s", dt.artist);
        if (dt.cover && dt.cover_len > 0) {
            alb->cover = dt.cover;          /* passa a posse; não libera */
            alb->cover_len = dt.cover_len;
            dt.cover = NULL;
            dec_tags_free(&dt);
            return 0;
        }
        dec_tags_free(&dt);
    }
    return 1;
}

void album_free_cover(Album *alb)
{
    free(alb->cover);
    alb->cover = NULL;
    alb->cover_len = 0;
    alb->cover_loaded = false;
}

int library_find_track_by_path(Library *lib, Album **out_album, const char *path)
{
    if (out_album) *out_album = NULL;
    if (!lib || !path) return -1;
    for (int i = 0; i < lib->nalbums; i++) {
        Album *a = &lib->albums[i];
        for (int j = 0; j < a->ntracks; j++) {
            if (strcmp(a->tracks[j].path, path) == 0) {
                if (out_album) *out_album = a;
                return j;
            }
        }
    }
    return -1;
}
