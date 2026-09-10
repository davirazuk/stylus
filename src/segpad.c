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

   CUIDADO COM O SENTIDO — e' contra-intuitivo e ja custou uma volta: somar
   pad faz o RESTO crescer, e a folga e' `A - resto`, entao somar um pouco
   PIORA. So compensa somar o bastante para VIRAR a borda. Com resto 3320 e
   alinhamento 8192, somar 4680 deixou resto 8000 e folga 192; o que servia
   era somar 5064 (= 8192 - 3320 + 192), que passa da pagina e devolve resto
   ~184 com folga ~8008. Em suma: some (A - resto) + a folga que voce NAO
   quer sobrando — ou simplesmente va somando ate a folga dar um salto.

   ATENCAO ao teto: a folga NUNCA passa do alinhamento de segmento. Com os
   4096 padrao, uma area SCE de 4948 bytes nao cabia em ajuste nenhum — e foi
   o que aconteceu ao app ganhar rede e teclado, porque cada modulo importado
   engorda a tabela de imports. Por isso o CMakeLists linka com
   `-z max-page-size=8192`: dobra o alinhamento e, com ele, o teto. Se um dia
   4948 virar 8200, e' esse numero que se dobra de novo, nao este pad.

   2026-09-05: de 16500 para 21936. O app trocou o sceHttp pelo curl com
   OpenSSL (ver o topo do net.c) e o texto cresceu ~1,3 MB de uma vez; o resto
   virou 3756 e a folga caiu para 4436. Somar 5436 (= 8192 - 3756 + ~1000)
   passa da borda e devolve folga ~6828. Exatamente o caso que o CUIDADO acima
   descreve: somar menos que 4436 teria PIORADO.

   2026-09-05, de novo: 21936 -> 28284. As capas do Qobuz e a fonte em grupo
   fizeram o resto virar 3036 (folga 5156, já no aviso do check.sh). Somar
   6348 devolveu 5556 — passa, mas raspando. Mais 6248 (34532) põe a folga
   perto de 7,5 KB, que é onde se quer ficar enquanto ainda se acrescenta
   código.

   2026-09-06: 34532 -> 40420. A tela de ajustes e o CD no prato derrubaram a
   folga para 4996. Resto 3196; somar 5888 passa a borda e devolve ~7,3 KB.

   2026-09-06, noite: 89256 -> 93752. A porteira da GPU (o filtro de
   coordenada que embrulha as 148 chamadas de desenho do ui.c) e a caixa-preta
   do `gpu.txt` puseram o resto em 4588 e a folga em 3604 — abaixo do teto do
   check.sh, que avisou antes de o build morrer. Somar 4496 (= 8192 - 4588 +
   892) vira a borda e devolve ~7,3 KB.

   2026-09-06, mais tarde: 93752 -> 100264. As sugestões da loja e a fila
   larga da HOME comeram a folga até 5604 — ainda passa, mas é a faixa em que
   o `check.sh` começa a avisar, e regular isto com o build SÃO é muito
   melhor do que descobrir com ele quebrado. Resto 2588; somar 6512
   (= 8192 - 2588 + 908) vira a borda e devolve ~7,3 KB.

   2026-09-06, mais tarde ainda: 100264 -> 105816. O `soundcloud.c` (a segunda
   fonte de streaming) pôs o resto em 3532 e a folga em 4660. O
   `tools/segpad.py` calculou o delta: 5552. */

#ifndef SEGPAD_BYTES
#define SEGPAD_BYTES 133208
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
