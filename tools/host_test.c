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
#include "sides.h"
#include "lyrics.h"

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

    /* um disco tocável em FLAC (era o exemplo do "não toca"; agora toca) */
    touch("Sigur Ros/Agaetis byrjun/01 - Intro.flac");
    touch("Sigur Ros/Agaetis byrjun/02 - Svefn-g-englar.flac");

    /* e um que continua sem decodificador: a estante o mostra apagado */
    touch("Alguem/So No iTunes/01 - Faixa.m4a");
    touch("Alguem/So No iTunes/02 - Outra.m4a");

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
    ok(decodable_ext("a.mp3") && decodable_ext("a.flac") &&
       decodable_ext("a.ogg") && decodable_ext("a.opus") && decodable_ext("a.wav"),
       "o VPK toca MP3, FLAC, Vorbis, Opus e WAV", "");
    /* A estante mostra o que NÃO toca de propósito, apagado: esconder faria
       quem tem a coleção inteira em .m4a ver "0 discos" e concluir que o app
       não acha nada. */
    ok(!decodable_ext("a.m4a") && !decodable_ext("a.wma") && audio_ext("a.m4a"),
       "o que não tem decodificador ainda CONTA como música na estante", "");
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
    okf(lib.audio_found == 22, "achou as 22 faixas de áudio", "achou %d", lib.audio_found);

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
    okf(sigur && sigur->ntracks == 2 && sigur->ndecodable == 2,
        "o disco em FLAC é tocável (o VPK ganhou o decodificador)",
        "%d faixas, %d tocáveis", sigur ? sigur->ntracks : -1,
        sigur ? sigur->ndecodable : -1);

    Album *m4a = album_named(&lib, "Alguem", "So No iTunes");
    okf(m4a && m4a->ntracks == 2 && m4a->ndecodable == 0,
        "o disco em .m4a APARECE na estante, marcado como não-tocável",
        "%d faixas, %d tocáveis", m4a ? m4a->ntracks : -1,
        m4a ? m4a->ndecodable : -1);

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
    okf(strstr(st, "22") != NULL, "o status conta o que achou", "disse \"%s\"", st);
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

        /* As TRÊS coisas sob a barra têm que caber uma abaixo da outra. Elas
           já se sobrepuseram: o sinal e o aviso eram offsets escritos à mão
           no ui.c, a lista era calculada no ui_layout.c, e a primeira faixa
           era desenhada EM CIMA do aviso. Medir é o que pega. */
        snprintf(what, sizeof(what), "%s: sinal, aviso e lista não se sobrepõem", telas[s].nome);
        okf(d.sig_y > d.bar_y && d.note_y >= d.sig_y + 16.0f &&
            d.list_y >= d.note_y + 16.0f,
            what, "barra %.0f, sinal %.0f, aviso %.0f, lista %.0f",
            d.bar_y, d.sig_y, d.note_y, d.list_y);

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

/* ---------- os lados ---------- */

static void test_sides(void)
{
    printf("\n\033[1mos lados (a tese do sistema)\033[0m\n");
    struct { int mins, n, lados, discos; const char *nome; } casos[] = {
        { 45, 10, 2, 1, "45 min: um LP, DOIS lados (era três de quinze)" },
        { 74, 12, 4, 2, "74 min: disco duplo, quatro lados" },
        { 90, 18, 4, 2, "90 min: quatro lados, não cinco" },
        { 21,  5, 1, 1, "21 min cabem INTEIROS num lado — não se manda virar" },
        { 50, 10, 2, 1, "50 min continuam um disco simples (o teto físico)" },
    };
    for (unsigned i = 0; i < sizeof(casos) / sizeof(casos[0]); i++) {
        int total = casos[i].mins * 60, n = casos[i].n;
        int d[64];
        for (int k = 0; k < n; k++) d[k] = total / n;
        d[n - 1] += total - (total / n) * n;
        Sides s;
        sides_build(d, n, &s);
        okf(s.n == casos[i].lados && s.discos == casos[i].discos, casos[i].nome,
            "deu %d lados e %d discos", s.n, s.discos);
    }

    /* uma faixa única de uma hora: o plano pede quatro lados e sobra UM.
       Um lado é um disco — o número vindo do plano dizia "DISCO 2". */
    {
        int d[1] = { 3600 };
        Sides s;
        sides_build(d, 1, &s);
        okf(s.n == 1 && s.discos == 1,
            "uma faixa de uma hora é UM lado de UM disco (não \"DISCO 2\")",
            "deu %d lados, %d discos", s.n, s.discos);
    }

    /* duração zero não é "não sei": três zeros num disco de doze somem com
       um lado inteiro se entrarem como zero */
    {
        int a[12], b[12];
        for (int i = 0; i < 12; i++) { a[i] = 240; b[i] = 240; }
        b[2] = b[7] = b[9] = 0;
        Sides sa, sb;
        sides_build(a, 12, &sa);
        sides_build(b, 12, &sb);
        okf(sa.n == sb.n,
            "faixa sem duração recebe a MEDIANA, e o corte não muda",
            "com durações: %d lados; com três zeros: %d", sa.n, sb.n);
    }

    /* o gesto: virar o disco e TROCAR de disco são gestos diferentes, e num
       duplo a diferença importa */
    {
        int d[12];
        for (int i = 0; i < 12; i++) d[i] = 370;   /* 74 min */
        Sides s;
        sides_build(d, 12, &s);
        char g1[160], g2[160];
        sides_gesture(&s, 1, g1, sizeof(g1));
        sides_gesture(&s, 2, g2, sizeof(g2));
        okf(strstr(g1, "vire o disco") != NULL, "A→B manda VIRAR o disco", "\"%s\"", g1);
        okf(strstr(g2, "DISCO 2") != NULL,
            "B→C manda TROCAR de disco (você levanta e vai à estante)", "\"%s\"", g2);
    }

    /* a faixa sabe em que lado mora */
    {
        int d[12];
        for (int i = 0; i < 12; i++) d[i] = 370;
        Sides s;
        sides_build(d, 12, &s);
        int ok_todas = 1;
        for (int i = 0; i < 12; i++) {
            int l = sides_of_track(&s, i);
            if (l < 0 || l >= s.n) ok_todas = 0;
        }
        okf(ok_todas && sides_of_track(&s, 0) == 0,
            "toda faixa cai em um lado, e a primeira no LADO A", "");
    }
}

/* ---------- a letra ---------- */

static void write_file(const char *path, const char *body)
{
    FILE *f = fopen(path, "w");
    if (!f) { fprintf(stderr, "não criou %s\n", path); exit(2); }
    fputs(body, f);
    fclose(f);
}

static void test_lyrics(void)
{
    printf("\n\033[1ma letra (.lrc)\033[0m\n");
    char dir[600], mp3[700], lrc[700];
    snprintf(dir, sizeof(dir), "%s/letra", ROOT);
    mkdir_p(dir);
    snprintf(mp3, sizeof(mp3), "%s/faixa.mp3", dir);
    snprintf(lrc, sizeof(lrc), "%s/faixa.lrc", dir);
    write_file(mp3, "x");
    write_file(lrc,
        "[ti:Teste]\n"
        "[offset:-500]\n"
        "[00:10.00]primeira\n"
        "[00:20.50]segunda\n"
        "[00:30][01:00]refrao\n"     /* UMA linha, DOIS momentos */
        "[00:40]sem centesimos\n"
        "[00:50.5]um decimo so\n");

    Lyrics l;
    memset(&l, 0, sizeof(l));
    lyrics_load(&l, mp3);

    okf(l.n == 6, "o .lrc rende SEIS linhas (o refrão conta duas vezes)",
        "deu %d", l.n);
    okf(l.offset_ms == -500, "o [offset:] é lido (era ignorado nos dois lados)",
        "deu %d", l.offset_ms);

    int n_refrao = 0;
    for (int i = 0; i < l.n; i++)
        if (!strcmp(l.lines[i].text, "refrao")) n_refrao++;
    okf(n_refrao == 2,
        "\"[00:30][01:00]refrao\" vira DUAS entradas do mesmo texto",
        "achei %d", n_refrao);

    int tem_colchete = 0;
    for (int i = 0; i < l.n; i++)
        if (strchr(l.lines[i].text, '[')) tem_colchete = 1;
    okf(!tem_colchete, "nenhum colchete sobra impresso no texto", "");

    int tem_sem_cent = 0;
    for (int i = 0; i < l.n; i++)
        if (!strcmp(l.lines[i].text, "sem centesimos")) tem_sem_cent = 1;
    okf(tem_sem_cent, "\"[00:40]\" sem centésimos NÃO some", "");

    /* o offset é -500 ms, então tudo acontece meio segundo mais tarde */
    okf(lyrics_at(&l, 5000) == -1, "antes da primeira linha, ninguém canta", "");
    int i10 = lyrics_at(&l, 10600);
    okf(i10 >= 0 && !strcmp(l.lines[i10].text, "primeira"),
        "aos 10,6 s canta a PRIMEIRA (a atual, não a seguinte)",
        "deu %d (%s)", i10, i10 >= 0 ? l.lines[i10].text : "—");
    int i20 = lyrics_at(&l, 25000);
    okf(i20 >= 0 && !strcmp(l.lines[i20].text, "segunda"),
        "aos 25 s ainda é a SEGUNDA (a busca binária devolve lo-1)",
        "deu %d (%s)", i20, i20 >= 0 ? l.lines[i20].text : "—");
    int i60 = lyrics_at(&l, 61000);
    okf(i60 >= 0 && !strcmp(l.lines[i60].text, "refrao"),
        "ao 1:01 o refrão volta, pelo segundo carimbo", "");

    /* sem .lrc: "não tem" é resposta, e ela não pode ser recalculada por quadro */
    char sem[700];
    snprintf(sem, sizeof(sem), "%s/outra.mp3", dir);
    write_file(sem, "x");
    Lyrics l2;
    memset(&l2, 0, sizeof(l2));
    lyrics_load(&l2, sem);
    okf(l2.n == 0 && l2.loaded,
        "faixa sem .lrc fica marcada como carregada (nada de I/O por quadro)", "");
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
    test_sides();
    test_lyrics();

    rm_tree(ROOT);
    printf("\n%d conferências, %d \033[31mfalha%s\033[0m\n",
           checks, fails, fails == 1 ? "" : "s");
    return fails ? 1 : 0;
}
