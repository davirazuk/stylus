#ifndef STYLUS_IME_H
#define STYLUS_IME_H

#include <stdbool.h>
#include <stddef.h>

/* O teclado do sistema.

   Existe para o app ser STANDALONE de verdade: entrar na conta do last.fm
   sem precisar de um PC, de um cabo, ou de editar um .txt no cartão. Quem
   está com o Vita na mão tem tudo de que precisa na mão.

   NÃO bloqueia — não pode. O laço principal continua desenhando a agulha e
   alimentando o áudio enquanto o teclado está aberto; travar aqui pararia a
   música. O uso é: `ime_abrir` uma vez, e `ime_poll` a cada quadro até
   deixar de devolver 0.

   Uma caixa de cada vez. Abrir com outra aberta é ignorado, porque o
   diálogo do sistema é único e insistir nele devolve erro. */

/* Abre a caixa. `senha` esconde o que for digitado. 0 se abriu. */
int  ime_abrir(const char *titulo, const char *inicial, size_t max, bool senha);

/* Há uma caixa aberta agora? A UI usa isto para não reagir aos botões
   enquanto o teclado está na frente — senão o [X] do teclado também
   confirmaria a faixa marcada atrás dele. */
bool ime_aberto(void);

/* A cada quadro: 0 ainda digitando, 1 confirmou (texto em `out`),
   -1 cancelou. */
int  ime_poll(char *out, size_t cap);

/* Depois de desenhar e antes de trocar o quadro: deixa o diálogo do sistema
   pintar por cima. Chamada SEMPRE, tenha ou não caixa aberta — é barata, e
   esquecê-la nos quadros em que o teclado abre é o que faz o teclado
   aparecer só depois de um toque. */
void ime_desenhar(void);

#endif
