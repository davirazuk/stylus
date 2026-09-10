/* Quantas chamadas de desenho um quadro emite.

   POR QUE ISTO É UM TESTE, e não uma curiosidade: no Vita cada
   vita2d_draw_rectangle vira um sceGxmDraw PRÓPRIO — não há agrupamento,
   conferido desmontando o libvita2d.a. O custo lá é o NÚMERO de chamadas.

   E é a classe de defeito que esta máquina não tem como sentir: o shim do
   preview rasteriza em C, e o tempo que ELE leva não diz nada sobre a GPU do
   aparelho. Contar diz. A estante já emitiu 21.272 chamadas por quadro (1,3
   milhão por segundo a 60 fps) sem nada acusar, porque no PC "funcionava".

   O teto abaixo tem folga sobre o número de hoje. Se um desenho novo o
   estourar, a pergunta certa não é "aumenta o teto" — é "dá para desenhar
   isto com menos chamadas", que foi como se saiu de 21 mil para 5 mil. */

#include <stdio.h>
#include <string.h>

#include <psp2/ctrl.h>
#include <vita2d.h>

#include "library.h"
#include "player.h"
#include "ui.h"
#include "ui_layout.h"

void preview_player_set(Player *p, const Album *a, const Track *t, PlayerState st,
                        int pos, int dur, int idx, int count, RepeatMode rep,
                        bool shuf, const char *kind, long rate_file, int bits_file,
                        long rate_out);

/* Tetos por tela. Não são gosto: 60 fps x 8000 chamadas já são meio milhão
   de sceGxmDraw por segundo, e a partir daí a submissão sozinha come uma
   fatia grande do processador de 444 MHz. */
#define TETO_ESTANTE 9000
#define TETO_DECK    6000

static int falhas = 0;

static void ok(long obtido, long teto, const char *tela)
{
    if (obtido <= teto) {
        printf("  \033[32m✓\033[0m %s: %ld chamadas de desenho (teto %ld)\n",
               tela, obtido, teto);
        return;
    }
    falhas++;
    printf("  \033[31m✗\033[0m %s: %ld chamadas de desenho, teto %ld\n",
           tela, obtido, teto);
    printf("      a 60 fps são %.1f milhões por segundo\n", obtido * 60 / 1e6);
}

/* A PORTEIRA DA GPU RECUSA MESMO?

   Uma coordenada NaN entregue ao sceGxm trava a GPU do Vita, e a trava
   derruba o sistema inteiro — é o que enchia o cartão de
   `psp2core-*-GPUCRASH.psp2dmp`. O ui.c passou a filtrar TODA chamada de
   desenho, e o problema de um filtro que funciona é que ele fica invisível:
   o relatório diz "zero recusas" tanto quando ele está de pé quanto quando
   alguém o desligou sem querer.

   Então empurra-se um NaN de propósito e confere-se as duas metades: que a
   porteira CONTOU, e que o desenho NÃO SAIU. A segunda importa mais — contar
   e deixar passar seria pior que não contar. */
static void ok_porteira(void)
{
    unsigned long antes_r = ui_gpu_recusas();
    long antes_d = hostgfx_draws();
    ui_gpu_forca_nan();
    unsigned long recusou = ui_gpu_recusas() - antes_r;
    long saiu = hostgfx_draws() - antes_d;

    if (recusou == 5 && saiu == 0) {
        printf("  \033[32m✓\033[0m a porteira: 5 coordenadas sujas recusadas, 0 chegaram à GPU\n");
        printf("      a primeira: %s\n", ui_gpu_primeira());
        return;
    }
    falhas++;
    printf("  \033[31m✗\033[0m a porteira deixou passar: %lu recusas (esperado 5), "
           "%ld desenho(s) emitidos (esperado 0)\n", recusou, saiu);
}

int main(int argc, char **argv)
{
    const char *raiz = argc > 1 ? argv[1] : NULL;
    vita2d_init();

    Library lib;
    library_init(&lib);
    if (raiz) library_add_root(&lib, raiz);
    library_scan(&lib);

    Ui *u = ui_create();
    Player *p = player_create();
    if (!u || !p) { printf("nao criei ui/player\n"); return 2; }

    printf("\033[1mchamadas de desenho por quadro\033[0m\n");

    /* aquece: as capas carregam sob demanda e o primeiro quadro não é o que
       a pessoa vê */
    for (int i = 0; i < 30; i++) ui_frame(u, &lib, p);
    hostgfx_draws_reset();
    ui_frame(u, &lib, p);
    ok(hostgfx_draws(), TETO_ESTANTE, "estante");
    printf("      (a porteira contou %ld neste quadro)\n", ui_gpu_pior());
    ok_porteira();
    /* A JANELA DE TEXTURA QUE PASSAVA DO FIM — o defeito que travava a GPU.
       Zero é o estado são. Antes do conserto do `draw_cover_round` este
       número era diferente de zero em toda tela com rótulo redondo. */
    if (ui_gpu_aparadas() == 0) {
        printf("  \033[32m✓\033[0m nenhuma janela de textura passa do fim da textura\n");
    } else {
        falhas++;
        printf("  \033[31m✗\033[0m %lu janela(s) de textura fora dos limites — a GPU do Vita trava com isso\n",
               ui_gpu_aparadas());
        printf("      a primeira: %s\n", ui_gpu_apara1());
    }

    /* deck com um disco tocando */
    Album *a = lib.nalbums ? &lib.albums[0] : NULL;
    if (a && a->ntracks) {
        album_load_meta(a);
        hostctrl_press(0);              ui_handle_input(u);
        hostctrl_press(SCE_CTRL_CROSS); ui_handle_input(u);
        hostctrl_press(0);              ui_handle_input(u);
        ui_skip_ritual(u);
        preview_player_set(p, a, &a->tracks[0], PLAYER_PLAYING, 60, 240, 0,
                           a->ntracks, REPEAT_ALL, true, "FLAC", 44100, 16, 44100);
        for (int i = 0; i < 30; i++) ui_frame(u, &lib, p);
        hostgfx_draws_reset();
        ui_frame(u, &lib, p);
        ok(hostgfx_draws(), TETO_DECK, "deck");
    printf("      (a porteira contou %ld no pior quadro ate agora)\n", ui_gpu_pior());

        /* ---- PARA QUE LADO OS BOTÕES APONTAM ----

           Os três botões do transporte saíram ESPELHADOS e ninguém viu lendo
           o código: o de tocar apontava para a esquerda, o de anterior
           mostrava ">>" e o de próxima "<<". Os chamadores estavam certos; a
           inversão morava no ajudante que empilha os retângulos do triângulo,
           e ler aquilo não denuncia nada — só olhar a tela denuncia.

           Então aqui se pergunta à TELA, contando pixels acesos de cada lado
           do centro de cada botão:

             tocar     um triângulo só, apontando à direita: a base (a parte
                       larga) fica à ESQUERDA, então pesa mais à esquerda.
             anterior  "|<<": a barra do batente fica à esquerda -> pesa à
                       esquerda.
             próxima   ">>|": a barra fica à direita -> pesa à direita.

           Espelhar os ícones inverte os três de uma vez, que foi exatamente
           o que aconteceu. É medida de FORMA, não de estilo: muda a cor, a
           espessura ou o tamanho e ela continua valendo. */
        {
            UiDeckGeom g;
            ui_deck_geom(960, 544, &g);
            preview_player_set(p, a, &a->tracks[0], PLAYER_PAUSED, 60, 240, 0,
                               a->ntracks, REPEAT_ALL, true, "FLAC",
                               44100, 16, 44100);
            ui_frame(u, &lib, p);       /* parado: o botão do meio é o de TOCAR */

            /* conta pixel aceso nas duas metades de cada botão */
            for (int b = 0; b < 3; b++) {
                float bx = g.cx + (float)(b - 1) * g.tr_gap;
                int esq = 0, dir = 0;
                for (int dy = -8; dy <= 8; dy++) {
                    for (int dx = -9; dx <= 9; dx++) {
                        unsigned px = hostgfx_pixel((int)bx + dx, (int)g.tr_y + dy);
                        /* âmbar aceso: vermelho alto e azul baixo */
                        int r = (int)((px >> 16) & 0xFF), bl = (int)(px & 0xFF);
                        if (r < 120 || bl > 110) continue;
                        if (dx < 0) esq++; else if (dx > 0) dir++;
                    }
                }
                const char *nome = b == 0 ? "anterior: a barra fica a ESQUERDA"
                                 : b == 1 ? "tocar: o triangulo aponta a DIREITA"
                                          : "proxima: a barra fica a DIREITA";
                int certo = (b == 2) ? (dir > esq) : (esq > dir);
                if (certo) printf("  \033[32m✓\033[0m %s\n", nome);
                else { printf("  \033[31m✗\033[0m %s (esq=%d dir=%d)\n",
                              nome, esq, dir); falhas++; }
            }
        }
    } else {
        printf("  (sem coleção: só a estante foi medida)\n");
    }

    /* ---- o texto que vem DE FORA ----
       Nome de arquivo, tag e título do Qobuz não foram escritos por nós, e um
       caractere que a fonte do aparelho não tem não some: vira quadradinho.
       Aconteceu nesta coleção — a tela de recomendados mostrava
       "[]All I need[] but its finally shoegazed". */
    printf("\n\033[1mo texto que vem de fora\033[0m\n");
    {
        static const struct { const char *cru, *esperado, *o_que; } casos[] = {
            /* as strings vêm partidas de propósito: "\x9CAll" faria o compilador
   engolir o "A" como dígito hexa e virar outro caractere */
            { "\xE2\x80\x9C" "All I need" "\xE2\x80\x9D", "\"All I need\"",
              "aspas curvas em UTF-8 viram aspas retas" },
            { "\x93" "All I need" "\x94", "\"All I need\"",
              "aspas curvas em CP1252 (nome de arquivo do Windows) tambem" },
            { "Sigur R\xC3\xB3s", "Sigur R\xC3\xB3s",
              "acento que JA e UTF-8 fica intacto" },
            { "Sigur R\xF3s", "Sigur R\xC3\xB3s",
              "acento em Latin-1 vira UTF-8 em vez de virar lixo" },
            { "Don\xE2\x80\x99t Look Back", "Don't Look Back",
              "apostrofo tipografico vira o reto" },
            { "A \xE2\x80\x94 B", "A \xE2\x80\x94 B",
              "o travessao, que a fonte TEM, fica" },
            /* U+FF02: o que o baixador de video poe no lugar da aspa, para o
               nome caber num sistema de arquivos. Foi ESTE que apareceu. */
            { "\xEF\xBC\x82" "All I need" "\xEF\xBC\x82", "\"All I need\"",
              "a aspa de largura inteira do nome de arquivo baixado" },
            { "quem\xEF\xBC\x9F", "quem?",
              "e a interrogacao de largura inteira, do mesmo bloco" },
            { NULL, NULL, NULL }
        };
        for (int i = 0; casos[i].cru; i++) {
            char saida[256];
            ui_texto_dbg(saida, sizeof(saida), casos[i].cru);
            if (strcmp(saida, casos[i].esperado) == 0) {
                printf("  \033[32m✓\033[0m %s\n", casos[i].o_que);
            } else {
                falhas++;
                printf("  \033[31m✗\033[0m %s\n", casos[i].o_que);
                printf("      saiu \"%s\", esperava \"%s\"\n",
                       saida, casos[i].esperado);
            }
        }
    }

    ui_destroy(u);
    library_free(&lib);
    printf(falhas ? "\n\033[31malgo acima do teto ou fora da fonte\033[0m\n"
                  : "\n\033[32mo desenho cabe no orçamento, e o texto na fonte\033[0m\n");
    return falhas ? 1 : 0;
}
