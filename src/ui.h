#ifndef STYLUS_UI_H
#define STYLUS_UI_H

#include "library.h"
#include "player.h"
#include "playlist.h"

typedef struct Ui Ui;

void ui_set_data(Ui *u, Playlist *plists, int nplists, const Track **recs, int nrecs);
void ui_set_recs(Ui *u, const Track **recs, int nrecs);

Ui *ui_create(void);
void ui_destroy(Ui *u);

/* desenha um frame; retorna 0 */
int ui_frame(Ui *u, Library *lib, Player *p);

/* controle: reserva para o main ler input
   0=sem, -1=sair, 2=abrir album, 4=toggle play, 5=next, 6=prev, 7=seek-10,
   10=voltar à estante, 11=tocar recomendações, 12=tocar playlist,
   13=criar playlist do atual, 14=ciclar repetição, 15=alternar sorteio,
   16=seek +10s */
int ui_handle_input(Ui *u);

/* acessores de estado */
int ui_selected(const Ui *u);          /* álbum marcado na estante */
int ui_playlist_idx(const Ui *u);      /* playlist marcada na lista */
int ui_view(const Ui *u);              /* View atual */

#endif
