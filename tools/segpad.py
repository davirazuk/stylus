#!/usr/bin/env python3
"""Calcula o SEGPAD_BYTES certo — a conta que já foi feita errado quatro vezes.

    ./tools/segpad.py                 # diz quanto está e quanto deveria estar
    ./tools/segpad.py --aplicar       # escreve o valor novo no src/segpad.c

POR QUE ISTO EXISTE

O `vita-elf-create` grava a área SCE (module info + tabelas de import) na
folga entre o fim do segmento de código e a página seguinte. A folga é
`alinhamento - (fim_do_texto % alinhamento)`, e o `src/segpad.c` empurra o fim
do texto com um array de enchimento para deixar essa folga grande.

A armadilha, que o comentário do segpad.c descreve e que ainda assim pegou
quatro vezes seguidas: **somar um pouco PIORA**. A folga é o COMPLEMENTO do
resto, então crescer o pad sem virar a página encolhe a folga. Só compensa
somar o bastante para passar da borda — e aí a conta certa é

    delta = (alinhamento - resto) + folga_desejada

que é justamente a que se erra de cabeça às 3 da manhã.

Roda depois de um `./build.sh`, porque lê o ELF que ele produziu.
"""

import os
import re
import struct
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF = os.path.join(RAIZ, "build", "vitastylus")
FONTE = os.path.join(RAIZ, "src", "segpad.c")
FOLGA_ALVO = 7300          # o mesmo alvo folgado que o check.sh quer ver


def segmento_de_codigo(caminho):
    """(fim_do_texto, alinhamento) do primeiro PT_LOAD executável."""
    with open(caminho, "rb") as f:
        dados = f.read()
    if dados[:4] != b"\x7fELF":
        sys.exit("não é um ELF: %s" % caminho)
    phoff, = struct.unpack_from("<I", dados, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", dados, 0x2A)
    for i in range(phnum):
        o = phoff + i * phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
            struct.unpack_from("<8I", dados, o)
        if p_type == 1 and (p_flags & 0x1):        # PT_LOAD + executável
            return p_vaddr + p_filesz, p_align
    sys.exit("nenhum segmento de código no ELF")


def pad_atual():
    txt = open(FONTE, encoding="utf-8").read()
    m = re.search(r"#define\s+SEGPAD_BYTES\s+(\d+)", txt)
    if not m:
        sys.exit("não achei SEGPAD_BYTES em %s" % FONTE)
    return int(m.group(1)), txt


def main():
    if not os.path.exists(ELF):
        sys.exit("rode ./build.sh antes: não achei %s" % ELF)

    fim, alin = segmento_de_codigo(ELF)
    resto = fim % alin
    folga = alin if resto == 0 else alin - resto
    atual, txt = pad_atual()

    print("fim do texto  0x%08X   alinhamento %d" % (fim, alin))
    print("resto %d  ->  folga %d bytes" % (resto, folga))
    print("SEGPAD_BYTES atual: %d" % atual)

    if folga >= 5500:
        print("está bom: a área SCE cabe com folga.")
        return 0

    # A CONTA CERTA — e eu errei esta na primeira versão deste arquivo, que é
    # exatamente a armadilha que o segpad.c descreve.
    #
    # `delta = (alin - resto) + FOLGA_ALVO` faz o resto NOVO virar FOLGA_ALVO,
    # e a folga é o COMPLEMENTO do resto: pedir folga 7300 devolvia folga 892.
    # O alvo é o RESTO, não a folga: para ter folga F o resto tem de ser
    # `alin - F`. Daí a diferença em aritmética modular.
    alvo_resto = alin - FOLGA_ALVO
    delta = (alvo_resto - resto) % alin
    if delta < 64:
        delta += alin                      # não vale reconstruir por 60 bytes
    delta -= delta % 4                     # o array é alinhado em 4
    novo = atual + delta
    print("\nfolga abaixo do mínimo (5500).")
    print("resto alvo = %d - %d = %d;  delta = (%d - %d) mod %d = %d"
          % (alin, FOLGA_ALVO, alvo_resto, alvo_resto, resto, alin, delta))
    print("SEGPAD_BYTES novo:  %d" % novo)

    if "--aplicar" in sys.argv:
        novo_txt = re.sub(r"(#define\s+SEGPAD_BYTES\s+)\d+",
                          r"\g<1>%d" % novo, txt, count=1)
        open(FONTE, "w", encoding="utf-8").write(novo_txt)
        print("\nescrito em src/segpad.c — rode ./build.sh de novo e confira.")
    else:
        print("\n(--aplicar escreve isso no src/segpad.c)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
