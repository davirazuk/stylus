#ifndef STYLUS_UI_H
#define STYLUS_UI_H

#include <stddef.h>

#include "library.h"
#include "player.h"
#include "playlist.h"
#include "rec.h"
#include "qobuz.h"

typedef struct Ui Ui;

/* O app conseguiu a porta BGM no arranque? Só isso não garante áudio em 2º
   plano: a taxa da faixa também precisa caber no teto (ver decoder.c). A tela
   cruza os dois — um sozinho seria promessa, não medida. */
void ui_set_bgm(Ui *u, bool ok);

/* As escolhas da tela de ajustes. O main as guarda junto do resto da sessão,
   porque uma preferência que se perde ao fechar o app não é uma preferência. */
int  ui_midia(const Ui *u);
void ui_set_midia(Ui *u, int m);
bool ui_toque_tras(const Ui *u);
/* "segurar o botão PS": a Shell não suspende quem segura o PS_BTN, e é assim
   que o ElevenMPV-A continua tocando fora da frente. Fica DESLIGADO por
   padrão e é AJUSTE, não decisão minha: travar o PS muda o que o aparelho
   inteiro faz quando se aperta, e isso tem de ser reversível por quem está
   com ele na mão. */
bool ui_bg_trava(const Ui *u);
void ui_set_bg_trava(Ui *u, bool on);

/* DE ONDE A BUSCA PROCURA (0 Qobuz, 1 SoundCloud). Escolha da pessoa, na aba
   SETTINGS, e sobrevive ao fechar o app — ver o `fonte` do resume.h. */
int  ui_fonte(const Ui *u);
void ui_set_fonte(Ui *u, int f);

/* A faixa do SoundCloud escolhida na lista de resultados. Devolve 0 quando
   não há uma — o main usa isto para montar a sessão de UMA faixa (ação 27).
   Fica aqui, e não num ponteiro para dentro do Ui, porque quem toca é o main
   e a lista pode ser substituída pela busca seguinte no meio do caminho. */
int  ui_sc_escolhida(const Ui *u, char *id, int id_cap,
                     char *artista, int art_cap,
                     char *titulo, int tit_cap, int *segundos);
int  ui_tema(const Ui *u);
void ui_set_tema(Ui *u, int t);
void ui_set_toque_tras(Ui *u, bool on);

void ui_set_data(Ui *u, Playlist *plists, int nplists, const Track **recs, int nrecs);

/* O HISTÓRICO, para a tela HOME poder dizer "o que você mais toca".

   A UI recebia só a lista de recomendações já pronta; para montar seções
   ("mais tocados", "nunca tocados") ela precisa da CONTAGEM, que mora no
   Rec. Passa-se o ponteiro, não uma cópia: quem é dono continua sendo o
   main, e a tela só lê. */
void ui_set_rec(Ui *u, const Rec *rec);

Ui *ui_create(void);
void ui_destroy(Ui *u);

/* desenha um frame; retorna 0 */
int ui_frame(Ui *u, Library *lib, Player *p);

/* a tela da varredura: chamada de dentro do library_scan, porque varrer um
   cartão cheio leva segundos e um preto parado lê como travado */
void ui_draw_scanning(Ui *u, const char *where, int files);

/* índice da faixa recomendada marcada (o [O] começa por ELA, não pela 1ª) */
int ui_rec_idx(const Ui *u);

/* A CERIMÔNIA (§5.5). Encenada quando a pessoa PÕE um disco agora; nunca ao
   abrir o app com música já tocando — ali o disco foi encontrado no meio, e
   encenar a descida da agulha seria mentira sobre o que aconteceu. */
void ui_begin_ritual(Ui *u);
void ui_skip_ritual(Ui *u);
/* true na primeira chamada DEPOIS da cerimônia terminar. Consumido uma vez. */
bool ui_ritual_done(Ui *u);

/* Repouso: a tela apaga e a música segue. É o mais perto de "ouvir enquanto
   faz outra coisa" que um app comum de Vita chega — o aparelho suspende
   qualquer app que saia da frente, e nenhum VPK contorna isso. */
bool ui_resting(const Ui *u);

/* Para onde o toque quer buscar, em 0..1; <0 quando ninguém está arrastando
   a barra. */
float ui_scrub(const Ui *u);

/* a letra escolhida na régua do [quad] (0..25 = A..Z, 26 = o resto) */
int  ui_jump_letter(const Ui *u);
void ui_set_sel(Ui *u, int i);

/* Lê a entrada e devolve uma AÇÃO para o main executar.

   A lista estava incompleta: 1, 8, 9, 18, 19 e 20 existiam no ui.c e não
   apareciam aqui. Isso não é detalhe — quem conferir "toda ação tem um
   `case` no main?" contra uma lista furada não distingue a ação que é
   INFORMATIVA de propósito da que alguém esqueceu de tratar, e a segunda é
   um recurso morto. Estão separadas abaixo por isso.

    O main AGE nestas:
      -1  sair                      11  tocar as recomendações
       2  abrir o álbum marcado     12  tocar a playlist marcada
       4  tocar/pausar              13  salvar o que toca como playlist
       5  próxima faixa             14  ciclar a repetição
       6  faixa anterior            15  alternar o sorteio
       7  recuar 10 s               17  apagar a playlist marcada
      16  avançar 10 s              18  buscar na fração tocada (ui_scrub)
      19  pular para a letra (ui_jump_letter)
      20  ciclar a soneca
      21  revarrer a estante (depois de um download do Qobuz)
      22  tocar da rede (o disco foi aberto, as faixas estão prontas)

   Estas o main IGNORA de propósito — a UI já fez o que havia para fazer
   (trocou de tela, moveu o cursor) e não há nada do lado do tocador:
      0  nada aconteceu             9  abriu as playlists
      1  o cursor andou            10  voltou à estante
      8  abriu as recomendações                                         */
int ui_handle_input(Ui *u);

/* A tela atual, como número. Existe para o teste de host poder afirmar em
   qual tela se está — sem isso, provar que um atalho leva aonde promete
   depende de olhar uma imagem. */
int ui_view_dbg(const Ui *u);

/* O FILTRO DA ESTANTE, para o teste. Expostos pelo mesmo motivo do
   ui_view_dbg: o que precisa ser medido é a TRADUÇÃO do índice filtrado para
   o índice real da biblioteca, e ela não aparece na tela — um filtro que
   traduz errado não desenha nada de estranho, só toca o disco errado. */
void ui_set_busca(Ui *u, const char *termo);
int  ui_shelf_count_dbg(const Ui *u);

/* O saneamento do texto que vem DE FORA (nome de arquivo, tag, título do
   Qobuz), como o desenho o aplica. Exposto pelo mesmo motivo do ui_view_dbg:
   sem isto, provar que a aspa curva de um nome de arquivo não vira
   quadradinho na tela depende de olhar uma foto da tela. */
void ui_texto_dbg(char *dst, size_t cap, const char *src);

/* acessores de estado */
int ui_selected(const Ui *u);          /* álbum marcado na estante */
int ui_playlist_idx(const Ui *u);      /* playlist marcada na lista */
QobuzConfig *ui_qobuz_cfg(Ui *u);     /* config do Qobuz (para o resolvedor) */

/* A TROCA POR LOSSLESS. Quem dispara a busca é o main (ação 24), porque é
   ele que tem a faixa que está no prato; a tela só precisa saber que ela
   está em curso, para o botão dizer "looking…" em vez de aceitar um segundo
   aperto que começaria tudo de novo. */
void ui_set_casando(Ui *u, bool on);
void ui_diz_casa(Ui *u, const char *msg);

/* Só o preview usa: impede a tela da loja de reler o qobuz.config por cima da
   conta de mentira que ele montou. Ver a nota no ui.c. */
void ui_qobuz_finge_conta(Ui *u);

/* Qual faixa o dedo escolheu na lista do deck (ação 26). -1 quando nenhuma. */
int  ui_deck_alvo(const Ui *u);

/* A PORTEIRA DA GPU, para quem quiser conferir de fora (o teste, o
   `gpu.txt`). Uma coordenada NaN entregue ao sceGxm trava a GPU do Vita e a
   trava derruba o sistema — a porteira recusa antes, e conta. Zero recusas é
   o estado são; qualquer número acima disso é um defeito de conta em algum
   desenho, e `ui_gpu_primeira` diz qual. Ver a nota no topo do ui.c. */
void          ui_gpu_forca_nan(void);  /* só o teste: empurra NaN na porteira */
unsigned long ui_gpu_recusas(void);
/* Janelas de textura que passavam do fim da textura e foram aparadas. Ler
   fora do bloco mapeado TRAVA a GPU do Vita — ver a nota no `gg_tex_part`.
   Zero é o estado são; qualquer número acima é geometria errada em quem
   desenha. */
unsigned long ui_gpu_aparadas(void);
/* Primitivas com coordenada FINITA mas muito fora da tela. O tiler do SGX
   percorre a área coberta: um triângulo gigante é tempo de GPU que o
   watchdog do aparelho mata. Zero é o estado são. */
unsigned long ui_gpu_longe(void);
const char   *ui_gpu_longe1(void);
const char   *ui_gpu_apara1(void);
const char   *ui_gpu_primeira(void);
long          ui_gpu_pior(void);      /* desenhos no pior quadro até agora */
long          ui_gpu_ultimo(void);    /* desenhos no quadro anterior */
/* PREENCHIMENTO, em TELAS CHEIAS (960x544 = 1,0). O contador de chamadas não
   vê custo de pixel: sete chamadas que cobrem a tela sete vezes passam por
   ele como sete. Ver a nota do `gg_px_caixa` no ui.c. */
double        ui_gpu_telas_agora(void);
double        ui_gpu_telas_ultimo(void);
double        ui_gpu_telas_pior(void);
int           ui_gpu_pior_tela(void); /* que View fez o pior quadro, -1 se nenhuma */
void          ui_gpu_pior_por_tipo(char *out, int cap);  /* rect=.. glyph=.. */
int           ui_gpu_estourou(void);  /* o teto por quadro chegou a pegar */

#endif
