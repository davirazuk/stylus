/* Enchimento do fim do segmento de código. Não tem função em execução.

   SINTOMA: o build morre em
     "vita-elf-create: Cannot allocate 3480 bytes for SCE data at end of
      segment 0; segment 1 overlaps"
   e o app nem chega a existir. Aparece "do nada" ao acrescentar código.

   CAUSA: o vita-elf-create grava a área SCE (module info + tabelas de import)
   no espaço que sobra entre o FIM do segmento 0 (código+rodata) e o início do
   segmento 1 (dados), e o segmento 1 começa sempre numa borda de página de
   4096. Ou seja, a folga é `4096 - (fim_do_texto % 4096)`. Se o texto termina
   fundo na página, não sobra espaço. Mexer no alinhamento do linker NÃO
   resolve: o endereço do segmento 1 já é múltiplo de tudo.

   CONSERTO: empurrar o fim do texto até a borda, deixando uma página inteira
   livre para a área SCE.

   COMO REGULAR (quando voltar a quebrar, porque o texto muda de tamanho):
     ~/vitasdk/bin/arm-vita-eabi-readelf -l build/vitastylus | grep 'R E'
   some VirtAddr+FileSiz = fim do texto; a folga e' `A - (fim % A)`, onde A e'
   o alinhamento de segmento. Ela precisa ser >= o numero de bytes que o erro
   pediu. Ajuste SEGPAD_BYTES, sempre multiplo de 4, ate a folga passar.
   O `tools/check.sh` confere isso e avisa antes de o build quebrar.

   ATENCAO ao teto: a folga NUNCA passa do alinhamento de segmento. Com os
   4096 padrao, uma area SCE de 4948 bytes nao cabia em ajuste nenhum — e foi
   o que aconteceu ao app ganhar rede e teclado, porque cada modulo importado
   engorda a tabela de imports. Por isso o CMakeLists linka com
   `-z max-page-size=8192`: dobra o alinhamento e, com ele, o teto. Se um dia
   4948 virar 8200, e' esse numero que se dobra de novo, nao este pad. */

#ifndef SEGPAD_BYTES
#define SEGPAD_BYTES 7592
#endif

#if SEGPAD_BYTES > 0
/* `const` põe em .rodata, que é o fim do segmento 0 — onde queremos o espaço. */
__attribute__((aligned(4)))
const volatile unsigned char stylus_segment_pad[SEGPAD_BYTES] = { 0 };

/* O `used` sozinho NÃO basta: ele segura o compilador, mas o
   `-Wl,--gc-sections` do link continua jogando a seção fora por ninguém a
   referenciar — e o pad some sem aviso, deixando o build quebrado do mesmo
   jeito. (O atributo `retain`, que resolveria, é ignorado neste alvo.)
   Um construtor entra no .init_array, que o script de link preserva com KEEP,
   e a referência daqui segura o array junto. Não faz nada em execução. */
__attribute__((used, constructor))
static void segpad_keep(void)
{
    (void)stylus_segment_pad[0];
}
#endif
