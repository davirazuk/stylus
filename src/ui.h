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

/* controle: reserva para o main ler input
   0=sem, -1=sair, 2=abrir album, 4=toggle play, 5=next, 6=prev, 7=seek-10,
   10=voltar à estante, 11=tocar recomendações, 12=tocar playlist,
   13=criar playlist do atual, 14=ciclar repetição, 15=alternar sorteio,
   16=seek +10s, 17=apagar playlist */
int ui_handle_input(Ui *u);

/* acessores de estado */
int ui_selected(const Ui *u);          /* álbum marcado na estante */
int ui_playlist_idx(const Ui *u);      /* playlist marcada na lista */

#endif
