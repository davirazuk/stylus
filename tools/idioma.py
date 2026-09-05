#!/usr/bin/env python3
"""Português sobrando em texto de tela.

POR QUE ISTO EXISTE

A UI deste app era em português e passou para o inglês. Uma tradução de ~200
strings feita de uma vez SEMPRE deixa alguma para trás, e a que fica não
aparece para quem lê o código — aparece para quem está com o aparelho na mão,
numa tela que talvez só abra em caso de erro. "there's a spelling issue in the
thing" já foi relatado três vezes neste projeto justamente assim.

Este arquivo substitui o antigo `acentos.py`, que media o contrário: palavra
portuguesa SEM acento. Com a tela em inglês aquela pergunta perdeu o sentido;
esta é a que ficou.

O que ele mede: literais de string dos fontes, que é o que vira texto na tela.
Comentário fica de fora DE PROPÓSITO — o comentário deste projeto é em
português por regra, e reclamar dele seria reclamar do que está certo.

O sinal é de dois tipos:
  - acento latino num literal (á é í ó ú ã õ ç ...), que em inglês não ocorre;
  - palavra funcional portuguesa inequívoca ("não", "para", "com", ...).

A lista de palavras é curta e conservadora de propósito: só entra o que não
existe em inglês. "disco", "radio" e "local" são palavras das duas línguas, e
incluí-las faria a conferência gritar em texto correto — uma conferência que
grita à toa é desligada, que é o mesmo que não existir.
"""
import re
import sys
from pathlib import Path

ACENTO = re.compile(r"[àáâãäçèéêëìíîïñòóôõöùúûü]", re.I)

# só palavra portuguesa que NÃO é também palavra inglesa
PT = {
    "não", "nao", "são", "sao", "está", "esta", "então", "então", "também",
    "você", "voce", "sem", "com", "para", "pela", "pelo", "uma", "uns",
    "umas", "dos", "das", "aos", "às", "isso", "isto", "aqui", "ali",
    "quando", "porque", "muito", "pouco", "tudo", "nada", "algum", "nenhum",
    "faixa", "faixas", "pasta", "pastas", "estante", "cartão", "cartao",
    "arquivo", "arquivos", "música", "musica", "músicas", "agulha", "prato",
    "disco?", "guardado", "guardada", "achou", "achei", "abriu", "abre",
    "tocar", "tocando", "pausa", "buscar", "buscando", "baixar", "senha",
    "usuário", "usuario", "segredo", "chave", "sorteio", "soneca", "letra",
    "volta", "volte", "ponha", "escreva", "aperte", "veja", "entre",
    "escuta", "escutas", "fila", "conta", "tela", "aparelho", "rede",
    "sulco", "lado", "lados", "capa", "ouvir", "jogo", "jogando",
    "vira", "acaba", "virar", "trocar", "agora", "pronto", "falta",
    # os verbos no infinitivo sao o formato das DICAS de botao, e foi assim
    # que "editar" e "confirmar" sobreviveram a traducao em massa 
    "editar", "confirmar", "apagar", "guardar", "parar", "cancelar",
    "escolher", "navegar", "voltar", "abrir", "fechar", "salvar",
    "procurar", "mostrar", "seguir", "aplicar",
    "toca", "tocar", "conta", "contas", "lista", "listas", "letra",
}

# Literais que são DADO, e não texto de tela: nomes de pasta que a descoberta
# procura no cartão. Eles têm de continuar em português — é assim que a pasta
# se chama no cartão de quem escreve em português, e traduzi-los faria a
# varredura deixar de achar a coleção. Ficam listados aqui, e não numa exceção
# solta, porque uma exceção que ninguém enumera vira uma porta aberta.
DADO = {
    # nomes de pasta que a descoberta procura no cartão
    "Música", "Músicas", "Musica", "Musicas", "música", "musicas", "musica",
    # a assinatura do índice da estante: é um marcador em arquivo, não texto
    "vitastylus-estante",
}

# Um literal que é só técnica não é frase de tela. A regra passou por dois
# erros opostos, e os dois deixaram passar defeito de verdade:
#
#   1ª versão: qualquer coisa sem pontuação era "técnica" — e aí toda frase
#      passava. Foi assim que "vire o disco para o %s" escapou.
#   2ª versão: exigi que não tivesse ESPAÇO. Aí toda PALAVRA SOLTA virou
#      técnica — e as dicas de botão são exatamente palavras soltas:
#      "editar", "confirmar", "conta", "toca" atravessaram inteiras.
#
# O que separa de verdade: caminho e chave têm ':' ou '/'; formato puro não
# tem letra nenhuma. Uma palavra solta em português é texto de tela e TEM de
# ser conferida.
TECNICA = re.compile(r"^(?:[^A-Za-zÀ-ÿ]*|[\w.\-+]*[:/][\w./:%\-+*#?=&]*)$", re.A)


def literais(txt):
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"', txt):
        yield m.group(1)


def main(argv):
    ruim = []
    for arq in argv[1:]:
        txt = Path(arq).read_text(encoding="utf-8", errors="replace")
        # tira comentários: eles são em português por regra
        txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S)
        txt = re.sub(r"//[^\n]*", " ", txt)
        for s in literais(txt):
            if not s.strip() or TECNICA.match(s) or s in DADO:
                continue
            achado = None
            if ACENTO.search(s):
                achado = "acento"
            else:
                for w in re.finditer(r"[A-Za-zÀ-ÿ]+", s):
                    if w.group(0).lower() in PT:
                        achado = w.group(0)
                        break
            if achado:
                ruim.append(f"  {arq}: {achado!r} em {s!r}")
    if ruim:
        print("\n".join(ruim))
        print("  a tela deste app é em inglês; o comentário é que fica em português.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
