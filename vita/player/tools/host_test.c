/* Exercita o núcleo do vitastylus numa máquina comum, sem VitaSDK e sem Vita.
 *
 * O que ele mede é a VARREDURA — que é onde moravam os defeitos que faziam a
 * estante abrir vazia ou com o disco de trás para a frente. As tags ficam de
 * fora de propósito: quem as lê é o mpg123, e um MP3 de mentira não prova
 * nada sobre ele; o stub abaixo só permite compilar o resto.
 *
 * Rode pelo tools/check.sh. */

#include "library.h"
#include "fsutil.h"
#include "ui_layout.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <sys/stat.h>
#include <unistd.h>

static int fails = 0, checks = 0;

static void ok(int cond, const char *what, const char *detail)
{
    checks++;
    if (cond) {
        printf("  \033[32m✓\033[0m %s\n", what);
    } else {
        fails++;
        printf("  \033[31m✗\033[0m %s\n", what);
        if (detail && detail[0]) printf("      %s\n", detail);
    }
}

static void okf(int cond, const char *what, const char *fmt, ...)
{
    char buf[512] = "";
    if (!cond && fmt) {
        va_list ap; va_start(ap, fmt);
        vsnprintf(buf, sizeof(buf), fmt, ap);
        va_end(ap);
    }
    ok(cond, what, buf);
}

/* ---------- uma coleção de mentira no disco ---------- */

static char ROOT[512];

static void touch(const char *rel)
{
    char p[1024];
    snprintf(p, sizeof(p), "%s/%s", ROOT, rel);
    char dir[1024];
    snprintf(dir, sizeof(dir), "%s", p);
    char *slash = strrchr(dir, '/');
    if (slash) { *slash = '\0'; mkdir_p(dir); }
    FILE *f = fopen(p, "w");
    if (!f) { fprintf(stderr, "não criou %s\n", p); exit(2); }
    /* 512 bytes de nada: a varredura olha nome e tipo, não conteúdo */
    for (int i = 0; i < 512; i++) fputc(0, f);
    fclose(f);
}

static void build_tree(void)
{
    snprintf(ROOT, sizeof(ROOT), "/tmp/vitastylus-host-%d", (int)getpid());
    mkdir_p(ROOT);

    /* o caso normal: Artista/Álbum/NN - Título */
    touch("Radiohead/OK Computer/01 - Airbag.mp3");
    touch("Radiohead/OK Computer/02 - Paranoid Android.mp3");
    touch("Radiohead/OK Computer/03 - Subterranean Homesick Alien.mp3");
    touch("Radiohead/OK Computer/10 - No Surprises.mp3");
    touch("Radiohead/OK Computer/11 - Lucky.mp3");
    touch("Radiohead/OK Computer/12 - The Tourist.mp3");
    touch("Radiohead/OK Computer/folder.jpg");

    /* outro disco do MESMO artista: tem que ser um artista só */
    touch("Radiohead/Kid A/01 - Everything In Its Right Place.mp3");
    touch("Radiohead/Kid A/02 - Kid A.mp3");

    /* a outra metade do mundo: "NN Título", sem hífen */
    touch("Portishead/Dummy/01 Mysterons.mp3");
    touch("Portishead/Dummy/02 Sour Times.mp3");

    /* nomes que PARECEM numerados e não são */
    touch("Mixtape/1979.mp3");
    touch("Mixtape/99 Problems.mp3");
    touch("Mixtape/Song.mp3");

    /* faixas SOLTAS na raiz — o layout que virava um disco por arquivo */
    touch("solta-a.mp3");
    touch("solta-b.mp3");
    touch("solta-c.mp3");

    /* um disco que o VPK não sabe decodificar */
    touch("Sigur Ros/Agaetis byrjun/01 - Intro.flac");
    touch("Sigur Ros/Agaetis byrjun/02 - Svefn-g-englar.flac");

    /* lixo que não é música */
    touch("Radiohead/OK Computer/AlbumArtSmall.jpg");
    touch("leiame.txt");

    /* Artista/Disco/CD1 — o artista continua sendo o primeiro segmento */
    touch("The Beatles/White Album/CD1/01 - Back in the U.S.S.R..mp3");
    touch("The Beatles/White Album/CD2/01 - Birthday.mp3");
}

static void rm_tree(const char *p)
{
    char cmd[1100];
    snprintf(cmd, sizeof(cmd), "rm -rf '%s'", p);
    if (system(cmd)) { /* melhor deixar o lixo do que abortar o teste */ }
}

static Album *album_named(Library *lib, const char *artist, const char *album)
{
    for (int i = 0; i < lib->nalbums; i++)
        if (!strcmp(lib->albums[i].artist, artist) &&
            !strcmp(lib->albums[i].album, album))
            return &lib->albums[i];
    return NULL;
}

/* ---------- as conferências ---------- */

static void test_path_join(void)
{
    printf("\n\033[1mcaminho\033[0m\n");
    char b[256];
    path_join(b, sizeof(b), "ux0:music/", "Radiohead");
    okf(!strcmp(b, "ux0:music/Radiohead"),
        "path_join não deixa barra dupla", "deu \"%s\"", b);
    path_join(b, sizeof(b), "ux0:music", "/Radiohead");
    okf(!strcmp(b, "ux0:music/Radiohead"), "barra do filho não duplica", "deu \"%s\"", b);
    path_join(b, sizeof(b), "", "Radiohead");
    okf(!strcmp(b, "Radiohead"), "pai vazio não vira barra solta", "deu \"%s\"", b);

    snprintf(b, sizeof(b), "ux0:music///");
    path_trim_slash(b);
    okf(!strcmp(b, "ux0:music"), "path_trim_slash tira as barras do fim", "deu \"%s\"", b);
    snprintf(b, sizeof(b), "ux0:/");
    path_trim_slash(b);
    okf(!strcmp(b, "ux0:/"), "mas não come a de \"ux0:/\"", "deu \"%s\"", b);

    char deep[1024];
    snprintf(deep, sizeof(deep), "%s/a/b/c/d", ROOT);
    okf(mkdir_p(deep) == 0 && dir_exists(deep),
        "mkdir_p cria a árvore inteira (era isso que faltava em ux0:data)", "%s", deep);
}

static void test_name_split(void)
{
    printf("\n\033[1mnome de arquivo\033[0m\n");
    char t[256];
    struct { const char *in; int num; const char *out; } cases[] = {
        { "01 - Airbag.mp3",        1,  "Airbag" },
        { "02. Sour Times.mp3",     2,  "Sour Times" },
        { "03_Song.mp3",            3,  "Song" },
        { "04 Song.mp3",            4,  "Song" },
        { "10 - No Surprises.mp3", 10,  "No Surprises" },
        { "1979.mp3",              -1,  "1979" },
        { "99 Problems.mp3",       99,  "Problems" }, /* ambíguo aqui; o disco decide */
        { "1979 - Song.mp3",       -1,  "1979 - Song" }, /* ano, não faixa */
        { "101 - Song.mp3",       101,  "Song" },        /* disco 1, faixa 1 */
        { "007 - Song.mp3",         7,  "Song" },
        { "Song.mp3",              -1,  "Song" },
        { "Song.with.dots.mp3",    -1,  "Song.with.dots" },
    };
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        int n = track_name_split(cases[i].in, t, sizeof(t));
        char what[256];
        snprintf(what, sizeof(what), "\"%s\" → %d / \"%s\"", cases[i].in, cases[i].num, cases[i].out);
        okf(n == cases[i].num && !strcmp(t, cases[i].out), what, "deu %d / \"%s\"", n, t);
    }
}

static void test_ext(void)
{
    printf("\n\033[1mextensões\033[0m\n");
    ok(audio_ext("a.mp3") && audio_ext("a.MP3"), "mp3 conta, com e sem maiúscula", "");
    ok(audio_ext("a.flac") && audio_ext("a.m4a") && audio_ext("a.opus"),
       "flac/m4a/opus contam como música", "");
    ok(!audio_ext("folder.jpg") && !audio_ext("leiame.txt"), "capa e texto não contam", "");
    ok(!audio_ext(".mp3"), "\".mp3\" sozinho não é faixa", "");
    ok(decodable_ext("a.mp3") && !decodable_ext("a.flac"),
       "o que ESTE VPK toca é a família MPEG", "");
}

static void test_roots(void)
{
    printf("\n\033[1mraízes\033[0m\n");
    Library l;
    library_init(&l);
    ok(library_add_root(&l, "ux0:music") == 0, "primeira raiz entra", "");
    ok(library_add_root(&l, "ux0:music/") < 0, "a mesma com barra não entra de novo", "");
    ok(library_add_root(&l, "ux0:MUSIC") < 0,
       "nem com outra caixa (o FS do Vita não distingue: entraria em dobro)", "");
    ok(library_add_root(&l, "ux0:music/rock") < 0, "nem uma que mora dentro dela", "");
    ok(library_add_root(&l, "uma0:music") == 1, "outro dispositivo entra", "");
    okf(l.nroots == 2, "duas raízes ao todo", "ficaram %d", l.nroots);

    Library d;
    library_init(&d);
    library_roots_from(&d, "/caminho/que/nao/existe");
    ok(d.nroots >= 4 && !d.roots_from_config,
       "sem roots.txt valem os palpites (ux0/uma0/imc0/xmc0)", "");
    int tem_uma = 0;
    for (int i = 0; i < d.nroots; i++)
        if (!strcmp(d.roots[i].path, "uma0:music")) tem_uma = 1;
    ok(tem_uma, "o cartão oficial da Sony está entre os palpites", "");

    /* roots.txt manda: quem escreveu o arquivo escolheu */
    char cfg[1024], rp[1100];
    snprintf(cfg, sizeof(cfg), "%s/cfg", ROOT);
    mkdir_p(cfg);
    snprintf(rp, sizeof(rp), "%s/roots.txt", cfg);
    FILE *f = fopen(rp, "w");
    fprintf(f, "# a minha pasta\nux0:MinhaMusica\n\numa0:outra\n");
    fclose(f);
    Library c;
    library_init(&c);
    library_roots_from(&c, cfg);
    okf(c.nroots == 2 && c.roots_from_config &&
        !strcmp(c.roots[0].path, "ux0:MinhaMusica"),
        "com roots.txt, os palpites saem de cena", "ficaram %d raízes", c.nroots);
}

static void test_scan(void)
{
    printf("\n\033[1mvarredura\033[0m\n");
    Library lib;
    library_init(&lib);
    library_add_root(&lib, ROOT);
    library_scan(&lib);

    okf(lib.nalbums > 0, "a estante NÃO abre vazia", "%d discos", lib.nalbums);
    okf(lib.audio_found == 20, "achou as 20 faixas de áudio", "achou %d", lib.audio_found);

    Album *ok_computer = album_named(&lib, "Radiohead", "OK Computer");
    ok(ok_computer != NULL, "Artista/Álbum vira artista + álbum", "");
    if (ok_computer) {
        okf(ok_computer->ntracks == 6, "seis faixas (a capa .jpg ficou de fora)",
            "%d faixas", ok_computer->ntracks);
        /* O DEFEITO GRANDE: a ordenação antiga invertia o álbum inteiro. */
        const char *want[] = { "Airbag", "Paranoid Android", "Subterranean Homesick Alien",
                               "No Surprises", "Lucky", "The Tourist" };
        int order_ok = 1;
        char got[512] = "";
        for (int i = 0; i < ok_computer->ntracks && i < 6; i++) {
            if (strcmp(ok_computer->tracks[i].title, want[i])) order_ok = 0;
            snprintf(got + strlen(got), sizeof(got) - strlen(got), "%s%s",
                     i ? " | " : "", ok_computer->tracks[i].title);
        }
        okf(order_ok, "o disco toca na ORDEM (não de trás para a frente)", "veio: %s", got);
        okf(ok_computer->tracks[0].number == 1 && ok_computer->tracks[5].number == 12,
            "os números vêm do nome do arquivo", "1º=%d 6º=%d",
            ok_computer->tracks[0].number, ok_computer->tracks[5].number);
        /* 2 antes de 10: ordenação alfabética crua põe "10" antes de "2" */
        okf(!strcmp(ok_computer->tracks[3].title, "No Surprises"),
            "a faixa 10 vem depois da 3 e não depois da 1", "4ª é \"%s\"",
            ok_computer->tracks[3].title);
        ok(ok_computer->ndecodable == 6, "as seis são tocáveis", "");
    }

    Album *kid_a = album_named(&lib, "Radiohead", "Kid A");
    ok(kid_a != NULL, "o segundo disco do mesmo artista é outro álbum", "");

    Album *dummy = album_named(&lib, "Portishead", "Dummy");
    if (dummy && dummy->ntracks == 2)
        okf(!strcmp(dummy->tracks[0].title, "Mysterons"),
            "\"01 Mysterons.mp3\" (sem hífen) também perde o número",
            "deu \"%s\"", dummy->tracks[0].title);
    else
        ok(0, "Portishead/Dummy com duas faixas", "");

    /* faixas soltas na raiz: UM álbum, não três */
    Album *soltas = album_named(&lib, "", "(sem pasta)");
    okf(soltas && soltas->ntracks == 3,
        "as faixas soltas na raiz viram UM disco, não um por arquivo",
        "%s", soltas ? "contagem errada" : "não existe álbum para elas");

    /* o disco cujos nomes não são numeração de faixa */
    Album *mix = album_named(&lib, "", "Mixtape");
    if (mix) {
        int tem1979 = 0;
        for (int i = 0; i < mix->ntracks; i++)
            if (!strcmp(mix->tracks[i].title, "1979")) tem1979 = 1;
        ok(tem1979, "\"1979\" continua se chamando 1979", "");
        int all_unnumbered = 1;
        for (int i = 0; i < mix->ntracks; i++)
            if (mix->tracks[i].number >= 0) all_unnumbered = 0;
        ok(all_unnumbered,
           "num disco que não é numerado, ninguém fica com número (\"99 Problems\")", "");
        int tem99 = 0;
        for (int i = 0; i < mix->ntracks; i++)
            if (!strcmp(mix->tracks[i].title, "99 Problems")) tem99 = 1;
        ok(tem99, "e \"99 Problems\" não vira \"Problems\"", "");
    } else {
        ok(0, "existe o álbum Mixtape", "");
    }

    Album *sigur = album_named(&lib, "Sigur Ros", "Agaetis byrjun");
    if (sigur) {
        okf(sigur->ntracks == 2 && sigur->ndecodable == 0,
            "o disco em FLAC APARECE na estante, marcado como não-tocável",
            "%d faixas, %d tocáveis", sigur->ntracks, sigur->ndecodable);
    } else {
        ok(0, "o disco em FLAC aparece na estante", "");
    }

    Album *cd1 = album_named(&lib, "The Beatles", "CD1");
    okf(cd1 != NULL, "Artista/Disco/CD1: o artista é o PRIMEIRO segmento", "");

    /* a estante ordenada por artista */
    int sorted = 1;
    for (int i = 1; i < lib.nalbums; i++)
        if (strcasecmp(lib.albums[i - 1].artist, lib.albums[i].artist) > 0) sorted = 0;
    ok(sorted, "a estante sai ordenada por artista", "");

    /* o dono de cada faixa continua apontando para o álbum certo depois do
       realloc e do qsort — foi assim que o scrobble mandava a pasta errada */
    int owners_ok = 1;
    for (int i = 0; i < lib.nalbums; i++)
        for (int j = 0; j < lib.albums[i].ntracks; j++)
            if (lib.albums[i].tracks[j].owner != &lib.albums[i]) owners_ok = 0;
    ok(owners_ok, "toda faixa aponta para o seu próprio álbum", "");

    /* nada de caminho com barra dupla */
    int no_dslash = 1;
    char bad[1024] = "";
    for (int i = 0; i < lib.nalbums; i++)
        for (int j = 0; j < lib.albums[i].ntracks; j++)
            if (strstr(lib.albums[i].tracks[j].path, "//")) {
                no_dslash = 0;
                snprintf(bad, sizeof(bad), "%s", lib.albums[i].tracks[j].path);
            }
    okf(no_dslash, "nenhum caminho com \"//\" (o sceIoGetstat recusa)", "%s", bad);

    /* achar pelo caminho: é como a sessão volta de onde parou */
    if (ok_computer) {
        Album *found = NULL;
        int ti = library_find_track_by_path(&lib, &found, ok_computer->tracks[2].path);
        okf(ti == 2 && found == ok_computer, "acha a faixa pelo caminho (continuar de onde parou)",
            "deu %d", ti);
    }

    char st[512];
    library_status(&lib, st, sizeof(st));
    okf(strstr(st, "20") != NULL, "o status conta o que achou", "disse \"%s\"", st);
    library_free(&lib);
}

static void test_scan_empty(void)
{
    printf("\n\033[1mquando não acha nada\033[0m\n");
    /* nenhuma raiz abre: a tela precisa DIZER onde olhou */
    Library l;
    library_init(&l);
    library_add_root(&l, "ux0:music");
    library_add_root(&l, "uma0:music");
    library_scan(&l);
    char st[512];
    library_status(&l, st, sizeof(st));
    okf(strstr(st, "ux0:music") && strstr(st, "uma0:music"),
        "a estante vazia NOMEIA as pastas em que olhou", "disse \"%s\"", st);
    library_free(&l);

    /* a pasta abre e só tem arquivo que não é música */
    char only[1024];
    snprintf(only, sizeof(only), "%s/naomusica", ROOT);
    mkdir_p(only);
    char f1[1100];
    snprintf(f1, sizeof(f1), "%s/x.txt", only);
    FILE *f = fopen(f1, "w"); fputc('x', f); fclose(f);

    Library o;
    library_init(&o);
    library_add_root(&o, only);
    library_scan(&o);
    library_status(&o, st, sizeof(st));
    okf(strstr(st, "nenhum de áudio") != NULL,
        "\"achei arquivos, nenhum é música\" é outra frase que \"não achei pasta\"",
        "disse \"%s\"", st);
    library_free(&o);
}

/* ---------- a tela cabe na tela? ---------- */

/* A varredura que faltava. Um número fixo de largura não estoura, não avisa e
   lê como página montada para outro monitor — e foi o defeito mais repetido
   deste projeto inteiro. Aqui a geometria é pura, então dá para MEDIR sem
   abrir janela: o Vita é 960x544, e as outras resoluções guardam a
   aritmética de continuar certa se alguém mexer nela. */
static void test_layout(void)
{
    printf("\n\033[1ma tela cabe na tela\033[0m\n");
    struct { int w, h; const char *nome; } telas[] = {
        { 960, 544, "Vita" },
        { 960, 512, "Vita, mais baixa" },
        { 1280, 720, "hipotética larga" },
        { 800, 480, "hipotética pequena" },
    };
    for (unsigned s = 0; s < sizeof(telas) / sizeof(telas[0]); s++) {
        int W = telas[s].w, H = telas[s].h;
        char what[160];
        UiFrameGeom f;
        ui_frame_geom(W, H, &f);

        UiShelfGeom g;
        ui_shelf_geom(W, H, &g);
        float right = g.x0 + UI_SHELF_COLS * g.card_w + (UI_SHELF_COLS - 1) * g.gap;
        float bottom = g.y0 + UI_SHELF_ROWS * g.card_h + (UI_SHELF_ROWS - 1) * g.gap;
        snprintf(what, sizeof(what), "%s: a grade da estante cabe", telas[s].nome);
        okf(right <= (float)W - f.pad_x + 0.5f && bottom <= f.foot_y + 0.5f,
            what, "direita %.0f (tela %d), base %.0f (rodapé %.0f)",
            right, W, bottom, f.foot_y);

        snprintf(what, sizeof(what), "%s: a capa cabe no card, com os rótulos", telas[s].nome);
        okf(g.cover_side > 0 && g.cover_side <= g.card_w - 2 * g.cover_pad + 0.5f &&
            g.cover_pad + g.cover_side <= g.label_dy - 14.0f,
            what, "capa %.0f, card %.0fx%.0f, rótulo em +%.0f",
            g.cover_side, g.card_w, g.card_h, g.label_dy);

        snprintf(what, sizeof(what), "%s: os rótulos ficam dentro do card", telas[s].nome);
        okf(g.sub_dy <= g.card_h + 0.5f && g.label_dy < g.sub_dy,
            what, "rótulo +%.0f, sub +%.0f, card alto %.0f", g.label_dy, g.sub_dy, g.card_h);

        UiDeckGeom d;
        ui_deck_geom(W, H, &d);
        snprintf(what, sizeof(what), "%s: o disco cabe no monitor", telas[s].nome);
        okf(d.cx - d.r >= -0.5f && d.cx + d.r <= (float)W + 0.5f &&
            d.cy - d.r >= 0.0f && d.cy + d.r <= (float)H + 0.5f,
            what, "disco em (%.0f,%.0f) r=%.0f numa tela %dx%d", d.cx, d.cy, d.r, W, H);

        /* a coluna de texto não pode nascer POR CIMA do disco nem sair pela
           direita: os dois pisos dividem a largura e um deles tem que ceder */
        snprintf(what, sizeof(what), "%s: a coluna de texto não pisa no disco", telas[s].nome);
        okf(d.text_x >= d.cx + d.r && d.text_w > 60.0f &&
            d.text_x + d.text_w <= (float)W - f.pad_x + 0.5f,
            what, "texto em %.0f larg %.0f; disco acaba em %.0f; tela %d",
            d.text_x, d.text_w, d.cx + d.r, W);

        snprintf(what, sizeof(what), "%s: a ordem do lado para antes do rodapé", telas[s].nome);
        okf(d.list_rows >= 1 &&
            d.list_y + (d.list_rows - 1) * d.list_step <= f.foot_y - 26.0f + 0.5f,
            what, "%d linhas de %.0f a partir de %.0f, rodapé em %.0f",
            d.list_rows, d.list_step, d.list_y, f.foot_y);

        UiListGeom l;
        ui_list_geom(W, H, &l);
        snprintf(what, sizeof(what), "%s: a lista para antes do rodapé", telas[s].nome);
        okf(l.rows >= 1 && l.y0 + l.rows * l.row_h <= f.foot_y - 12.0f + 0.5f &&
            l.x + l.w <= (float)W - f.pad_x + 0.5f,
            what, "%d linhas de %.0f a partir de %.0f, rodapé em %.0f",
            l.rows, l.row_h, l.y0, f.foot_y);
    }
}

int main(void)
{
    printf("\033[1mvitastylus — núcleo, sem Vita\033[0m\n");
    build_tree();
    printf("coleção de mentira em %s\n", ROOT);

    test_path_join();
    test_name_split();
    test_ext();
    test_roots();
    test_scan();
    test_scan_empty();
    test_layout();

    rm_tree(ROOT);
    printf("\n%d conferências, %d \033[31mfalha%s\033[0m\n",
           checks, fails, fails == 1 ? "" : "s");
    return fails ? 1 : 0;
}
