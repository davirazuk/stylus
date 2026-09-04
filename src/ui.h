#ifndef STYLUS_UI_H
#define STYLUS_UI_H

#include "library.h"
#include "player.h"
#include "playlist.h"

typedef struct Ui Ui;

/* O app conseguiu a porta BGM no arranque? Só isso não garante áudio em 2º
   plano: a taxa da faixa também precisa caber no teto (ver decoder.c). A tela
   cruza os dois — um sozinho seria promessa, não medida. */
void ui_set_bgm(Ui *u, bool ok);

void ui_set_data(Ui *u, Playlist *plists, int nplists, const Track **recs, int nrecs);

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

/* acessores de estado */
int ui_selected(const Ui *u);          /* álbum marcado na estante */
int ui_playlist_idx(const Ui *u);      /* playlist marcada na lista */

#endif
