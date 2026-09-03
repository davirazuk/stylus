#ifndef STYLUS_PATHS_H
#define STYLUS_PATHS_H

/* Onde as coisas moram. UM lugar.
   O desktop já pagou por isto duas vezes: seis listas de extensão de áudio e
   cinco de nome de capa, todas discordando, e a que ninguém olhava derivava.
   Aqui a mesma pasta era escrita à mão no main, no scanner e no texto de
   ajuda da tela — três lugares, e o texto de ajuda é justamente o que a
   pessoa vai DIGITAR quando o app não achar as músicas dela. */

#define STYLUS_DATA_DIR   "ux0:data/vitastylus"
#define STYLUS_PLAYLISTS  STYLUS_DATA_DIR "/playlists"
#define STYLUS_ROOTS_TXT  STYLUS_DATA_DIR "/" ROOTS_FILE
/* a raiz de música que fica ao lado dos dados, para quem não quer usar
   ux0:music (pasta do sistema, e nem todo firmware a mostra) */
#define STYLUS_OWN_MUSIC  STYLUS_DATA_DIR "/music"

#endif
