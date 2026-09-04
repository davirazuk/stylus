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

/* ---------------- raízes ---------------- */

/* Os palpites, do mais provável ao menos. Um cartão SD2VITA aparece como
   ux0:; o cartão oficial da Sony como uma0:; a memória interna do modelo
   2000 como imc0:. Uma instalação com o SD2VITA em ux0: ainda pode ter a
   música no cartão oficial — é por isso que são todos varridos, não só o
   primeiro que abrir. */
static const char *DEFAULT_ROOTS[] = {
    "ux0:music",
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

/* "ux0:music" contém "ux0:music/rock": aceitar as duas varre o mesmo disco
   duas vezes e a estante mostra tudo em dobro. */
static bool root_covered(const Library *lib, const char *cand)
{
    size_t cl = strlen(cand);
    for (int i = 0; i < lib->nroots; i++) {
        const char *have = lib->roots[i].path;
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
        snprintf(album, album_cap, "%s", "(sem pasta)");
        return;
    }
    const char *last = strrchr(rel_dir, '/');
    if (!last) {
        snprintf(album, album_cap, "%s", rel_dir);
        return;
    }
    size_t alen = (size_t)(last - rel_dir);
    /* Artista/Disco/CD1: o artista é o PRIMEIRO segmento, não o caminho todo —
       senão "Radiohead/OK Computer" e "Radiohead/Kid A" viram dois artistas. */
    const char *first = memchr(rel_dir, '/', alen);
    if (first) alen = (size_t)(first - rel_dir);
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

static void scan_dir(Library *lib, int root_idx, const char *abs, const char *rel, int depth)
{
    if (depth > SCAN_MAX_DEPTH) return;
    /* dir_open, não opendir: no aparelho o opendir devolveu NULL para
       "ux0:music" nas três formas, e a API do sistema não tem essa dúvida.
       Ver a nota grande no fsutil.h. */
    int erro = 0;
    DirIter *d = dir_open_err(abs, &erro);
    if (!d) {
        /* guarda o motivo NA RAIZ, não numa subpasta qualquer: é a raiz que
           a tela mostra, e uma subpasta que some no meio da varredura não é
           a mesma história que a raiz não abrir */
        if (depth == 0 && root_idx >= 0 && root_idx < lib->nroots)
            lib->roots[root_idx].err = erro;
        return;
    }
    lib->dirs_seen++;
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
            scan_dir(lib, root_idx, child_abs, child_rel, depth + 1);
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
        }
        add_track(a, child_abs, nome);
    }
    dir_close(d);
}

/* ---------------- ordenação ---------------- */

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
        int ca = *a, cb = *b;
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

int library_scan(Library *lib)
{
    if (!lib) return -1;
    for (int i = 0; i < lib->nroots; i++) {
        ScanRoot *r = &lib->roots[i];
        r->opened = dir_exists(r->path);
        if (!r->opened) continue;
        scan_dir(lib, i, r->path, "", 0);
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

   "não existe" e "sem permissão" pedem consertos OPOSTOS, e a tela dizia
   "(não existe)" para os dois — mandando a pessoa procurar a pasta que já
   está lá. Um número que ninguém sabe ler não serve; o nome, sim. */
const char *scan_err_str(int err)
{
    if (err == 0) return "";
    switch ((unsigned)err) {
    case 0x80010002u: return "não existe";
    case 0x8001000Du: return "sem permissão";
    case 0x80010013u: return "só leitura";
    case 0x80010014u: return "dispositivo ocupado";
    case 0x80010016u: return "caminho inválido";
    case 0x80010018u: return "não é uma pasta";
    case 0x8001001Cu: return "sem memória";
    case 0x80010024u: return "arquivos demais abertos";
    /* no PC os erros são os do errno, pequenos */
    case 2:  return "não existe";
    case 13: return "sem permissão";
    case 20: return "não é uma pasta";
    default: return "erro desconhecido";
    }
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
    fprintf(f, "raizes      %d%s\n", lib->nroots,
            lib->roots_from_config ? " (de roots.txt)" : " (padrao)");
    for (int i = 0; i < lib->nroots; i++) {
        const ScanRoot *r = &lib->roots[i];
        if (r->opened)
            fprintf(f, "  [x] %-28s audio=%d outros=%d\n",
                    r->path, r->audio, r->other);
        else
            fprintf(f, "  [ ] %-28s NAO ABRIU: 0x%08X (%s)\n",
                    r->path, (unsigned)r->err, scan_err_str(r->err));
    }
    fprintf(f, "pastas      %d\n", lib->dirs_seen);
    fprintf(f, "arquivos    %d  (audio %d)\n", lib->files_seen, lib->audio_found);
    fprintf(f, "albuns      %d\n", lib->nalbums);

    int faixas = 0, maior = 0;
    for (int i = 0; i < lib->nalbums; i++) {
        faixas += lib->albums[i].ntracks;
        if (lib->albums[i].ntracks > maior) maior = lib->albums[i].ntracks;
    }
    /* Nada de contar duração aqui: o ID3 é lido sob demanda, então neste
       instante NENHUMA foi lida, e um "sem duracao: 3728" pareceria defeito
       sendo o funcionamento normal. */
    fprintf(f, "faixas      %d  (maior album: %d)\n", faixas, maior);

    char st[512];
    library_status(lib, st, sizeof(st));
    fprintf(f, "estado      %s\n", st);
    fclose(f);
}

void library_status(const Library *lib, char *out, size_t cap)
{
    if (!out || !cap) return;
    out[0] = '\0';
    if (!lib) return;

    if (lib->nroots == 0) {
        snprintf(out, cap, "nenhuma pasta para varrer");
        return;
    }
    int opened = 0;
    for (int i = 0; i < lib->nroots; i++) if (lib->roots[i].opened) opened++;

    if (opened == 0) {
        /* o caso mais comum de "não acha nada": a música não está onde o app
           olhou. Dizer QUAIS pastas foram tentadas transforma um mistério num
           conserto de trinta segundos. */
        size_t n = (size_t)snprintf(out, cap, "nenhuma destas pastas abriu: ");
        for (int i = 0; i < lib->nroots && n + 2 < cap; i++)
            n += (size_t)snprintf(out + n, cap - n, "%s%s",
                                  i ? ", " : "", lib->roots[i].path);
        return;
    }
    if (lib->audio_found == 0) {
        int other = 0;
        for (int i = 0; i < lib->nroots; i++) other += lib->roots[i].other;
        if (lib->files_seen == 0)
            snprintf(out, cap, "as pastas abriram e estão vazias (%d subpastas)",
                     lib->dirs_seen);
        else
            snprintf(out, cap,
                     "vi %d arquivo%s, nenhum de áudio (%d de outro tipo)",
                     lib->files_seen, lib->files_seen == 1 ? "" : "s", other);
        return;
    }
    snprintf(out, cap, "%d faixa%s em %d pasta%s",
             lib->audio_found, lib->audio_found == 1 ? "" : "s",
             lib->dirs_seen, lib->dirs_seen == 1 ? "" : "s");
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
    dec_global_exit();
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
        if (dt.album[0] && (!alb->album[0] || !strcmp(alb->album, "(sem pasta)")))
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

int album_load_cover(Album *alb)
{
    if (!alb) return -1;
    if (alb->cover_loaded) return alb->cover ? 0 : 1;
    alb->cover_loaded = true;
    if (!alb->tracks || alb->ntracks == 0) return 1;

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
