#ifndef STYLUS_UI_H
#define STYLUS_UI_H

#include "library.h"
#include "player.h"

typedef struct Ui Ui;

Ui *ui_create(void);
void ui_destroy(Ui *u);

/* desenha um frame; retorna 0 */
int ui_frame(Ui *u, Library *lib, Player *p);

/* controle: reserva para o main ler input
   0=sem, -1=sair, 2=abrir album, 4=toggle play, 5=next, 6=prev, 7=seek-10 */
int ui_handle_input(Ui *u);

/* índice do álbum selecionado na estante */
int ui_selected(const Ui *u);

#endif
