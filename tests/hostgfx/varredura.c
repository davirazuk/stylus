/* A VARREDURA: aperta tudo, em toda tela, e desenha DEPOIS DE CADA APERTO.
 *
 *   varredura <raiz-de-musica>          # 0 = passou, 1 = achou algo
 *
 * Por que ela existe
 * ------------------
 * "o app do Vita travou em menos de 2 minutos" é a queixa mais cara que este
 * projeto tem, e a única ferramenta que existia para ela era instalar o VPK e
 * esperar. As fotos do `preview.sh` mostram cada tela EM REPOUSO — e nenhum
 * travamento acontece em repouso: acontece depois de uma tecla pôr a tela num
 * sub-estado que o desenho seguinte não aguenta.
 *
 * Daí as três regras deste arquivo:
 *
 *  1. **Desenhar depois de cada aperto, não no fim.** A última tecla desfaz o
 *     estado que a anterior criou; uma varredura que só desenha no fim mede o
 *     estado de UMA tecla e diz que mediu quinze.
 *  2. **Desenhar mais de um quadro.** A tecla não estoura ao ser apertada —
 *     estoura no quadro seguinte, quando o desenho vai ler o que ela mudou.
 *  3. **Com o prato CHEIO e VAZIO.** Sem nada tocando, metade do deck nem é
 *     desenhada: varrer só o prato vazio deixa a tela mais complexa do app de
 *     fora justamente da conferência.
 *
 * O que ela mede
 * --------------
 * - **Estouro de memória**: é para rodar sob AddressSanitizer. Uso de textura
 *   depois de solta — o defeito que o cemitério de texturas do ui.c existe
 *   para impedir — só aparece assim, sem aparelho.
 * - **O custo do quadro**: cada chamada de desenho é um `sceGxmDraw` lá. Foi
 *   estourar a lista de display que encheu o cartão de GPUCRASH, então o
 *   número que interessa não é o da tela parada: é o PIOR de todos os
 *   sub-estados que uma tecla alcança.
 * - **Textura vazando**: passear pelas telas e voltar tem que devolver a VRAM.
 *   O que não volta some do orçamento sem aparecer em lugar nenhum.
 */

#include <vita2d.h>
#include <psp2/ctrl.h>
#include <psp2/touch.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "library.h"
#include "player.h"
#include "ui.h"
#include "playlist.h"
#include "rec.h"

void hostplayer_espectro_hostil(int on);
void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

/* os números de View, na ordem do enum do ui.c */
enum { V_ESTANTE = 0, V_DECK, V_RECS, V_PLAYLISTS, V_JOGANDO, V_CONTA,
       V_QOBUZ, V_AJUSTES, V_CONTROLES, V_ARTISTAS, V_HOME };

/* O TETO DO QUADRO. Acima disto a lista de display do SGX543 fica perigosa —
   é o mesmo número que o preview.c já anota em cada foto. Não é uma medida do
   aparelho, é o limite de onde este projeto já se queimou; mexa nele para
   BAIXO quando souber mais, nunca para cima porque uma tela nova não coube. */
#define TETO_DRAWS 8000

/* O TETO DE PREENCHIMENTO, em telas cheias por quadro.

   MEDIDO: o pior quadro do app pinta 3,8 telas (o deck, com o disco inteiro).
   Antes do conserto do fundo o MESMO quadro pintava 8,8 — o `deck_backdrop`
   sozinho respondia por 7,0 delas (seis passes tingidos da capa ampliada,
   cada um cobrindo a tela toda, mais o véu) em SETE chamadas de desenho.
   Nenhum teto de chamada podia ver isso, e foi por isso que a varredura deu
   verde durante uma semana de GPUCRASH.

   Cinco é folga sobre 3,8 sem deixar voltar nada parecido com aquilo.
   Ver a nota do `gg_px_caixa` no ui.c. */
#define TETO_TELAS 5.0

static const struct { unsigned bits; const char *nome; } BOTOES[] = {
    { SCE_CTRL_UP,       "cima"      },
    { SCE_CTRL_DOWN,     "baixo"     },
    { SCE_CTRL_LEFT,     "esquerda"  },
    { SCE_CTRL_RIGHT,    "direita"   },
    { SCE_CTRL_CROSS,    "X"         },
    { SCE_CTRL_CIRCLE,   "O"         },
    { SCE_CTRL_SQUARE,   "quadrado"  },
    { SCE_CTRL_TRIANGLE, "triangulo" },
    { SCE_CTRL_L1,       "L1"        },
    { SCE_CTRL_R1,       "R1"        },
    { SCE_CTRL_LTRIGGER, "L2"        },
    { SCE_CTRL_RTRIGGER, "R2"        },
    { SCE_CTRL_START,    "start"     },
    { SCE_CTRL_SELECT,   "select"    },
};
#define NBOTOES ((int)(sizeof(BOTOES) / sizeof(BOTOES[0])))

static const char *VNOME[] = {
    "estante", "deck", "recs", "playlists", "jogando", "conta",
    "qobuz", "ajustes", "controles", "artistas", "home"
};

/* O MODO RÁPIDO existe para a varredura poder morar no check.sh.

   A completa leva doze minutos com o sanitizador ligado — tempo demais para
   uma conferência que se roda antes de todo empurrão, e uma conferência que
   se pula é uma que não existe. A rápida faz o essencial (toda tecla em toda
   tela, com o prato cheio) em segundos e sem sanitizador: pega tela que some,
   índice que estoura a lista de desenho e textura que vaza. O que ela NÃO
   pega — acesso a memória solta — é justamente o que precisa do ASAN, e por
   isso a completa continua sendo o que se roda antes de mandar VPK. */
static int   g_rapido;
static int   g_falhas;
static long  g_pior;
static long  g_pior_deck;
static char  g_onde_linhas[64], g_onde_ret[64], g_onde_circ[64], g_onde_ar[64];
static long  g_linhas_pior, g_ret_pior, g_circ_pior, g_ar_pior;
static char  g_pior_onde[160] = "—";
static double g_pior_tel;
static char  g_tel_onde[160] = "—";

/* Um quadro, medido. O `onde` só é montado quando estoura: montar a string em
   toda chamada custa mais que o desenho em si nas telas baratas. */
static void quadro(Ui *ui, Library *lib, Player *p,
                   const char *tela, const char *acao, int n)
{
    hostgfx_draws_reset();
    ui_frame(ui, lib, p);
    long d = hostgfx_draws();

    /* ═══ E O PREENCHIMENTO, QUE É O QUE FALTAVA MEDIR ════════════════════
     *
     * Esta varredura conferia CHAMADAS e dava tudo verde enquanto o aparelho
     * travava. O `deck_backdrop` desenhava a capa ampliada seis vezes: sete
     * chamadas — nada — e sete TELAS CHEIAS de pixel misturado, todo quadro,
     * na tela que caía. Nenhum teto de chamada podia ver isso.
     *
     * Agora vê. A unidade é a tela: 1,0 = 960x544 pintados uma vez. */
    double tel = ui_gpu_telas_agora();
    if (tel > g_pior_tel) {
        g_pior_tel = tel;
        snprintf(g_tel_onde, sizeof(g_tel_onde), "%s + %s (quadro %d)", tela, acao, n);
    }
    if (tel > TETO_TELAS) {
        printf("  \033[31m✗\033[0m %s + %s: %.1f telas de preenchimento (teto %.1f)\n",
               tela, acao, tel, TETO_TELAS);
        g_falhas++;
    }
    if (strstr(tela, "deck") && d > g_pior_deck) {
        g_pior_deck = d;
        snprintf(g_onde_linhas, 64, "%s + %s (quadro %d)", tela, acao, n);
        g_linhas_pior = hostgfx_linhas(); g_ret_pior = hostgfx_ret();
        g_circ_pior = hostgfx_circ(); g_ar_pior = hostgfx_ar();
    }
    if (d > g_pior) {
        g_pior = d;
        snprintf(g_pior_onde, sizeof(g_pior_onde), "%s + %s (quadro %d)", tela, acao, n);
    }
    if (d > TETO_DRAWS) {
        printf("  \033[31m✗\033[0m %s + %s: %ld chamadas de desenho (teto %d)\n",
               tela, acao, d, TETO_DRAWS);
        g_falhas++;
    }
}

/* O aperto: soltar, apertar, soltar — o ui_handle_input lê a BORDA. E entre
   eles, quadros: é aí que o desenho vai ler o que a tecla mudou. */
static void aperta(Ui *ui, Library *lib, Player *p, unsigned bits,
                   const char *tela, const char *acao)
{
    hostctrl_press(0);    ui_handle_input(ui);
    hostctrl_press(bits); ui_handle_input(ui);
    quadro(ui, lib, p, tela, acao, 1);
    hostctrl_press(0);    ui_handle_input(ui);
    for (int i = 2; i <= (g_rapido ? 2 : 4); i++)
        quadro(ui, lib, p, tela, acao, i);
}

static void va_para(Ui *ui, Library *lib, Player *p, int view)
{
    for (int i = 0; i < 14 && ui_view_dbg(ui) != view; i++) {
        hostctrl_press(0);            ui_handle_input(ui);
        hostctrl_press(SCE_CTRL_R1);  ui_handle_input(ui);
        hostctrl_press(0);            ui_handle_input(ui);
        ui_frame(ui, lib, p);
    }
    (void)view;
}

/* Uma tela inteira: toda tecla, e depois o dedo numa grade. */
static void varre_tela(Ui *ui, Library *lib, Player *p, int view, const char *sufixo)
{
    char tela[64];
    snprintf(tela, sizeof(tela), "%s%s", VNOME[view], sufixo);

    for (int b = 0; b < NBOTOES; b++) {
        va_para(ui, lib, p, view);
        aperta(ui, lib, p, BOTOES[b].bits, tela, BOTOES[b].nome);
    }

    /* R1 SEGURADO + cada botão: as combinações do deck (o handoff é uma
       delas) põem a tela em estados que tecla solta nenhuma alcança. */
    for (int b = 0; b < NBOTOES; b++) {
        if (BOTOES[b].bits == SCE_CTRL_R1) continue;
        va_para(ui, lib, p, view);
        char nome[48];
        snprintf(nome, sizeof(nome), "R1+%s", BOTOES[b].nome);
        hostctrl_press(0);                              ui_handle_input(ui);
        hostctrl_press(SCE_CTRL_R1);                    ui_handle_input(ui);
        hostctrl_press(SCE_CTRL_R1 | BOTOES[b].bits);   ui_handle_input(ui);
        quadro(ui, lib, p, tela, nome, 1);
        hostctrl_press(SCE_CTRL_R1);                    ui_handle_input(ui);
        hostctrl_press(0);                              ui_handle_input(ui);
        quadro(ui, lib, p, tela, nome, 2);
        quadro(ui, lib, p, tela, nome, 3);
    }

    /* O DEDO. Numa tela sensível ao toque, um alvo que ninguém previu é tão
       alcançável quanto um que se previu — e a grade acha os dois. Inclui as
       bordas, que é onde a conta de um alvo costuma sair do vetor. */
    va_para(ui, lib, p, view);
    for (int gy = 0; gy < (g_rapido ? 3 : 6); gy++) {
        for (int gx = 0; gx < (g_rapido ? 4 : 8); gx++) {
            int x = gx * (960 / 7);
            int y = gy * (544 / 5);
            if (x > 959) x = 959;
            if (y > 543) y = 543;
            char nome[48];
            snprintf(nome, sizeof(nome), "toque %d,%d", x, y);
            hosttouch_tap(-1, -1); ui_handle_input(ui);
            hosttouch_tap(x, y);   ui_handle_input(ui);
            quadro(ui, lib, p, tela, nome, 1);
            hosttouch_tap(-1, -1); ui_handle_input(ui);
            quadro(ui, lib, p, tela, nome, 2);
            va_para(ui, lib, p, view);
        }
    }

    /* O PAINEL DE TRÁS, que é opção do usuário e por isso vive desligado no
       padrão: ligá-lo aqui é a única forma de o código dele ser exercitado. */
    ui_set_toque_tras(ui, true);
    va_para(ui, lib, p, view);
    for (int gy = 0; gy < (g_rapido ? 1 : 3); gy++) {
        for (int gx = 0; gx < 4; gx++) {
            hosttouch_back(-1, -1); ui_handle_input(ui);
            hosttouch_back(gx * 300, gy * 250); ui_handle_input(ui);
            quadro(ui, lib, p, tela, "toque de tras", 1);
            hosttouch_back(-1, -1); ui_handle_input(ui);
            quadro(ui, lib, p, tela, "toque de tras", 2);
        }
    }
    ui_set_toque_tras(ui, false);
    hosttouch_tap(-1, -1);
    hosttouch_back(-1, -1);
    ui_handle_input(ui);
}

int main(int argc, char **argv)
{
    const char *root = "/run/media/davirazuk/VITASD/music";
    const char *capas = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--rapido")) g_rapido = 1;
        else if (!strcmp(argv[i], "--capas") && i + 1 < argc) capas = argv[++i];
        else root = argv[i];
    }

    Library lib;
    library_init(&lib);
    library_add_root(&lib, root);
    library_scan(&lib);
    if (lib.nalbums == 0) {
        fprintf(stderr, "varredura: nada varrido em %s\n", root);
        return 2;
    }

    vita2d_init();
    /* Ninguém aqui olha um pixel: o que se mede é chamada de desenho e
       memória. Sem isto a varredura passa 98% do tempo misturando meio milhão
       de pixels por quadro para jogar fora. */
    hostgfx_sem_pintar(1);
    Ui *ui = ui_create();
    Player *p = player_create();
    if (!ui || !p) { fprintf(stderr, "varredura: ui/player\n"); return 2; }

    static const Track *recs[64];
    int nrecs = 0;
    for (int a = 0; a < lib.nalbums && nrecs < 40; a++)
        if (lib.albums[a].ntracks > 0) recs[nrecs++] = &lib.albums[a].tracks[0];

    Playlist *pls = NULL;
    int npls = 0;
    for (int k = 0; k < 4 && k < lib.nalbums; k++) {
        const Track *t[8];
        int n = 0;
        for (int i = 0; i < lib.albums[k].ntracks && n < 8; i++)
            t[n++] = &lib.albums[k].tracks[i];
        if (n) playlist_new(&pls, &npls, "Mix", t, n);
    }
    static Rec rec;
    rec_load(&rec, "/tmp");
    ui_set_data(ui, pls, npls, recs, nrecs);
    ui_set_rec(ui, &rec);
    ui_set_bgm(ui, true);

    Album *alb = &lib.albums[0];
    for (int i = 0; i < lib.nalbums; i++)
        if (album_load_cover(&lib.albums[i]) == 0 && lib.albums[i].cover
            && lib.albums[i].ntracks > 0) { alb = &lib.albums[i]; break; }
    album_load_meta(alb);
    const Track *tr = alb->ntracks ? &alb->tracks[0] : NULL;
    int dur = (tr && tr->seconds > 0) ? tr->seconds : 231;

    printf("varredura%s: %d álbuns, %d telas, %d botões\n",
           g_rapido ? " (rápida)" : "",
           lib.nalbums, (int)(sizeof(VNOME) / sizeof(VNOME[0])), NBOTOES);

    long tex0 = hostgfx_tex_vivas();

    /* ── prato CHEIO ─────────────────────────────────────────────────────
       O deck com disco é a tela mais cara do app, e a única em que a
       cerimônia, a agulha, o espectro e a lista do lado existem. */
    preview_player_set(p, alb, tr, PLAYER_PLAYING, dur * 38 / 100, dur, 0,
                       alb->ntracks, REPEAT_ALL, true, "FLAC", 44100, 16, 44100);
    ui_skip_ritual(ui);
    for (int v = 0; v <= V_HOME; v++) {
        if (v == V_CONTROLES) continue;   /* alcançada pelos ajustes, não pelo anel */
        varre_tela(ui, &lib, p, v, "");
    }

    /* o deck nas duas mídias e nos dois temas: o CD tem desenho próprio, e é
       o mais caro dos dois (34 arcos de irisação contra 5 anéis) */
    for (int midia = 0; midia <= 1 && !g_rapido; midia++) {
        for (int tema = 0; tema <= 1; tema++) {
            ui_set_midia(ui, midia);
            ui_set_tema(ui, tema);
            char suf[32];
            snprintf(suf, sizeof(suf), " [%s/%s]",
                     midia ? "cd" : "vinil", tema ? "vita" : "ambar");
            varre_tela(ui, &lib, p, V_DECK, suf);
        }
    }
    ui_set_midia(ui, 0);
    ui_set_tema(ui, 0);

    /* ── O ESPECTRO HOSTIL ────────────────────────────────────────────
       O desenho do disco só põe o espectro quando há SOM, e o espectro vem
       do áudio. Um NaN ali vira coordenada, e coordenada NaN trava a GPU do
       Vita. Era este o GPUCRASH que sobrava. Varre o deck nas duas mídias
       com o stub cuspindo NaN, infinito, negativo e absurdo. */
    hostplayer_espectro_hostil(1);
    for (int midia = 0; midia <= 1; midia++) {
        ui_set_midia(ui, midia);
        varre_tela(ui, &lib, p, V_DECK, midia ? " [veneno/cd]" : " [veneno]");
    }
    ui_set_midia(ui, 0);
    for (int i = 0; i < 90; i++)
        quadro(ui, &lib, p, "deck", "espectro hostil", i);
    hostplayer_espectro_hostil(0);

    /* a CERIMÔNIA: três momentos em que a agulha não está onde ela costuma
       estar, e foi ali que a divisão por zero do rastro do sulco morava */
    ui_begin_ritual(ui);
    for (int i = 0; i < (g_rapido ? 60 : 120); i++)
        quadro(ui, &lib, p, "deck", "cerimonia", i);
    ui_skip_ritual(ui);

    /* ── prato VAZIO ───────────────────────────────────────────────────
       Sem nada tocando, metade do deck nem é desenhada — é o estado em que
       uma varredura descuidada acha que mediu a tela e não mediu. */
    preview_player_set(p, NULL, NULL, PLAYER_STOPPED, 0, -1, 0, 0,
                       REPEAT_OFF, false, "—", 0, 0, 0);
    for (int v = 0; v <= V_HOME && !g_rapido; v++) {
        if (v == V_CONTROLES) continue;
        varre_tela(ui, &lib, p, v, " (vazio)");
    }
    if (g_rapido) varre_tela(ui, &lib, p, V_DECK, " (vazio)");

    /* ── o FILTRO, que é o outro jeito de a estante ter forma ─────────── */
    ui_set_busca(ui, "zzqqxx");            /* nenhum resultado: os índices ficam sem chão */
    varre_tela(ui, &lib, p, V_ESTANTE, " (filtro vazio)");
    if (!g_rapido) {
        ui_set_busca(ui, "a");             /* quase tudo */
        varre_tela(ui, &lib, p, V_ESTANTE, " (filtro largo)");
    }
    ui_set_busca(ui, "");

    /* ── a COLEÇÃO VAZIA ──────────────────────────────────────────────
       Cartão novo, ou música em pasta que o sandbox não abre — foi esse o
       estado do app no dia em que ele não achava música nenhuma. Toda tela
       que indexa a estante tem de aguentar `nalbums == 0`. */
    {
        Library vazia;
        memset(&vazia, 0, sizeof(vazia));
        library_init(&vazia);
        for (int v = 0; v <= V_HOME; v++) {
            if (v == V_CONTROLES) continue;
            if (g_rapido && v != V_ESTANTE && v != V_HOME && v != V_DECK) continue;
            varre_tela(ui, &vazia, p, v, " (sem coleção)");
        }
        library_free(&vazia);
    }

    /* ═══ A PASSADA COM CAPA EM TODA TELA ════════════════════════════════

       É a que faltava, e a falta dela custou uma semana de GPUCRASH.

       A coleção de teste deste PC não tem UMA capa. Sem capa, o cache de
       capas do ui.c nunca enche, nunca despeja e nunca solta textura — então
       tudo acima passa por cima do código onde o defeito morava, e passa
       VERDE. No aparelho, com 339 capas guardadas no cartão, a tela de
       ARTISTS desenhava doze círculos num cache de dez lugares e debulhava a
       cada quadro.

       Vinte e quatro discos de mentira, todos com arte embutida: mais do que
       qualquer tela desenha de uma vez, que é exatamente a condição em que o
       cache quebra. As telas varridas são as que DESENHAM CAPA. */
    if (capas) {
        Library cheia;
        memset(&cheia, 0, sizeof(cheia));
        library_init(&cheia);
        library_add_root(&cheia, capas);
        library_scan(&cheia);
        if (cheia.nalbums > 0) {
            printf("passada com capa: %d discos, todos com arte\n", cheia.nalbums);
            static const Track *r2[64];
            int n2 = 0;
            for (int a = 0; a < cheia.nalbums && n2 < 40; a++)
                if (cheia.albums[a].ntracks > 0) r2[n2++] = &cheia.albums[a].tracks[0];
            ui_set_data(ui, pls, npls, r2, n2);
            preview_player_set(p, &cheia.albums[0],
                               cheia.albums[0].ntracks ? &cheia.albums[0].tracks[0] : NULL,
                               PLAYER_PLAYING, 30, 120, 0,
                               cheia.albums[0].ntracks, REPEAT_ALL, false,
                               "MP3", 44100, 16, 44100);
            ui_skip_ritual(ui);
            const int comcapa[] = { V_HOME, V_ARTISTAS, V_ESTANTE, V_RECS, V_DECK };
            for (int k = 0; k < (int)(sizeof(comcapa) / sizeof(comcapa[0])); k++)
                varre_tela(ui, &cheia, p, comcapa[k], " [com capa]");
            /* E TROCANDO DE ABA sem parar: é ali que um cache do tamanho da
               tela despeja tudo de uma vez, que é o pior caso dele. */
            for (int volta = 0; volta < 40; volta++) {
                for (int k = 0; k < (int)(sizeof(comcapa) / sizeof(comcapa[0])); k++) {
                    va_para(ui, &cheia, p, comcapa[k]);
                    quadro(ui, &cheia, p, "troca de aba [com capa]", "R1", volta);
                }
            }
            ui_set_data(ui, pls, npls, recs, nrecs);
        }
        library_free(&cheia);
    }

    long tex1 = hostgfx_tex_vivas();

    /* A CAUSA DOS GPUCRASH, conferida sem aparelho.

       Soltar uma textura que a GPU do Vita ainda pode estar lendo não dói no
       PC — nada leu aquela memória de verdade — e dói no aparelho a ponto de
       derrubar o sistema. O shim guarda em que quadro cada textura foi
       desenhada e reprova quem for solta cedo demais. Ver a nota do
       VITA_BUFFERS no vita2d_host.c. */
    /* A PORTEIRA DA GPU DO PRÓPRIO APP.

       Ela recusa a coordenada suja ANTES do vita2d, então o detector do shim
       (logo abaixo) nunca mais vê nenhuma: a porteira come todas. Um detector
       que não pode mais disparar é um detector morto — quem conta agora é o
       contador dela, e é ESTE número que tem de ser zero. O do shim fica como
       segunda rede, para o que porventura escapar dos `#define`. */
    /* A JANELA DE TEXTURA QUE PASSA DO FIM DA TEXTURA.
       Ler fora do bloco que o sceGxm mapeou trava a GPU do Vita — e era o
       `draw_cover_round` (o rótulo do vinil no deck, os dezoito retratos da
       ARTISTS) que pedia isso em todo quadro. Zero é o estado são. */
    if (ui_gpu_aparadas() > 0) {
        printf("\n\033[31m✗\033[0m %lu janela(s) de textura passavam do fim da textura\n",
               ui_gpu_aparadas());
        printf("     a primeira: %s\n", ui_gpu_apara1());
        printf("     no Vita isso é leitura fora do bloco mapeado: a GPU trava\n");
        g_falhas++;
    }

    /* O POOL DE VÉRTICES QUE ACABAVA E DESCARTAVA DESENHO EM SILÊNCIO.
       Era 64 KB no shim contra 16 MB no aparelho, e por causa disso uma
       mudança real (34 -> 96 arcos no CD) não apareceu no preview: nem na
       imagem, nem na contagem. Um preview que esconde a mudança de quem a fez
       é pior que preview nenhum. */
    if (hostgfx_pool_faltou() > 0) {
        printf("\n\033[31m✗\033[0m %ld desenho(s) descartados por falta de pool de vértices\n",
               hostgfx_pool_faltou());
        printf("     o preview está escondendo desenho — o aparelho tem 16 MB de pool\n");
        g_falhas++;
    }

    if (ui_gpu_longe() > 0) {
        printf("\n\033[31m✗\033[0m %lu primitiva(s) longe demais da tela de 960x544\n",
               ui_gpu_longe());
        printf("     a primeira: %s\n", ui_gpu_longe1());
        printf("     o tiler do SGX percorre a área coberta: isso é tempo de GPU\n");
        g_falhas++;
    }

    if (ui_gpu_recusas() > 0) {
        printf("\n\033[31m✗\033[0m %lu coordenada(s) recusadas pela porteira da GPU\n",
               ui_gpu_recusas());
        printf("     a primeira: %s\n", ui_gpu_primeira());
        printf("     a porteira impediu a trava, mas a CONTA que gerou isso é um defeito\n");
        g_falhas++;
    }

    if (ui_gpu_estourou()) {
        printf("\n\033[31m✗\033[0m o teto de desenho por quadro PEGOU (pior: %ld)\n",
               ui_gpu_pior());
        printf("     um quadro foi cortado no meio — algum laço de desenho escapou\n");
        g_falhas++;
    }

    if (hostgfx_coord_suja() > 0) {
        printf("\n\033[31m✗\033[0m %d coordenada(s) NaN/absurdas entregues à GPU\n",
               hostgfx_coord_suja());
        printf("     a primeira: %s\n", hostgfx_coord_suja_onde());
        printf("     no Vita isso não dá erro: a GPU trava e derruba o sistema\n");
        g_falhas++;
    }

    if (hostgfx_tex_na_cena() > 0) {
        printf("\n\033[31m✗\033[0m %d textura(s) criadas/soltas COM A CENA ABERTA\n",
               hostgfx_tex_na_cena());
        printf("     %s\n", hostgfx_tex_na_cena_onde());
        g_falhas++;
    }

    if (hostgfx_solta_cedo() > 0) {
        printf("\n\033[31m✗\033[0m %d textura(s) soltas cedo demais para a GPU do Vita\n",
               hostgfx_solta_cedo());
        printf("     %s\n", hostgfx_solta_cedo_onde());
        g_falhas++;
    }

    printf("\npior quadro: %ld chamadas em %s (teto %d)\n",
           g_pior, g_pior_onde, TETO_DRAWS);
    printf("pior preenchimento: %.1f telas em %s (teto %.1f)\n",
           g_pior_tel, g_tel_onde, TETO_TELAS);
    printf("pior quadro (deck): %ld chamadas em %s\n", g_pior_deck, g_onde_linhas);
    printf("  └ linhas=%ld retângulos=%ld círculos=%ld arcos/lotes=%ld (no deck)\n",
           g_linhas_pior, g_ret_pior, g_circ_pior, g_ar_pior);
    printf("textura viva: %ld antes, %ld depois (%+ld), %ld KB\n",
           tex0, tex1, tex1 - tex0, hostgfx_tex_bytes() / 1024);

    /* O que VAZA é o que sobe e não volta. Umas poucas a mais são as capas
       que a tela atual legitimamente segura; o que denuncia é a ordem de
       grandeza — uma por álbum visitado. */
    if (tex1 - tex0 > 64) {
        printf("\033[31m✗\033[0m %ld texturas a mais depois de passear: cheira a vazamento\n",
               tex1 - tex0);
        g_falhas++;
    }

    playlist_free(pls, npls);
    player_destroy(p);
    ui_destroy(ui);
    library_free(&lib);
    vita2d_fini();

    if (g_falhas) {
        printf("\033[31m%d problema(s)\033[0m\n", g_falhas);
        return 1;
    }
    printf("\033[32mnada estourou\033[0m\n");
    return 0;
}
