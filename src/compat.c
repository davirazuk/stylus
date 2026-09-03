/* O que o newlib do Vita não tem e uma biblioteca de terceiros pede assim
   mesmo.

   O libFLAC traz o escritor de metadados (metadata_iterators.o) no mesmo
   arquivo .a do leitor, e esse escritor preserva o carimbo de tempo do
   arquivo com utimensat(). Nós só LEMOS FLAC — nada aqui reescreve tag
   nenhuma — mas o linker estático puxa o objeto inteiro e cobra o símbolo.

   O stub devolve erro em vez de fingir sucesso: se um dia alguém realmente
   chamar isto, é melhor a chamada falhar de forma visível do que o programa
   acreditar que gravou um carimbo que não gravou. */

#include <errno.h>
#include <time.h>

int utimensat(int dirfd, const char *path, const struct timespec times[2], int flags);

int utimensat(int dirfd, const char *path, const struct timespec times[2], int flags)
{
    (void)dirfd; (void)path; (void)times; (void)flags;
    errno = ENOSYS;
    return -1;
}
