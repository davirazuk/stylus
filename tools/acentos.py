#!/usr/bin/env python3
"""Palavra sem acento em texto que a pessoa lê.

POR QUE ISTO EXISTE

"a spelling issue in the thing" foi relatado três vezes ao longo do
desenvolvimento e sobreviveu a todas: um "tambem NAO abre" no meio de um
diagnóstico não salta aos olhos de quem está lendo o CÓDIGO, e quem está
lendo a TELA não abre o editor. Revisão manual já provou que não pega — por
isso virou conferência.

O que ele mede: literais de string dos fontes, que é o que vira texto na
tela. Comentário fica de fora de propósito — não porque não importe, mas
porque a taxa de falso positivo em prosa longa afogaria o sinal.

A lista abaixo só tem palavra que NÃO EXISTE sem o acento. "esta" e "está"
são as duas palavras de verdade, e "e" e "é" também; incluí-las faria a
conferência gritar em texto correto, e uma conferência que grita à toa é
desligada — que é o mesmo que não existir.
"""
import re
import sys
from pathlib import Path

CERTO = {
    "nao": "não", "tambem": "também", "voce": "você", "ate": "até",
    "apos": "após", "sao": "são", "entao": "então", "versao": "versão",
    "opcao": "opção", "opcoes": "opções", "posicao": "posição",
    "informacao": "informação", "duracao": "duração", "cancao": "canção",
    "coracao": "coração", "musica": "música", "musicas": "músicas",
    "numero": "número", "numeros": "números", "ultimo": "último",
    "ultima": "última", "proximo": "próximo", "proxima": "próxima",
    "minimo": "mínimo", "maximo": "máximo", "unico": "único",
    "unica": "única", "possivel": "possível", "impossivel": "impossível",
    "dificil": "difícil", "facil": "fácil", "silencio": "silêncio",
    "video": "vídeo", "audio": "áudio", "area": "área", "pagina": "página",
    "historico": "histórico", "codigo": "código", "memoria": "memória",
    "sequencia": "sequência", "frequencia": "frequência",
    "referencia": "referência", "aparencia": "aparência", "nivel": "nível",
    "disponivel": "disponível", "invalido": "inválido", "album": "álbum",
    "albuns": "álbuns", "sera": "será", "havera": "haverá", "esta`": "está",
    "ninguem": "ninguém", "alguem": "alguém", "porem": "porém",
    "ordenacao": "ordenação", "reproducao": "reprodução", "cartao": "cartão",
    "botao": "botão", "sessao": "sessão", "conexao": "conexão",
}

# Uma string que é caminho, formato ou nome de símbolo não é texto de tela.
TECNICA = re.compile(r"^[\w./:%\-+*#\[\]()|$&=<>,{}\\ ]*$", re.A)

def literais(txt):
    """Strings de C, já juntando as coladas por concatenação implícita."""
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"', txt):
        yield m.start(), m.group(1)

def main(argv):
    achados = []
    for arq in argv[1:]:
        p = Path(arq)
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        linhas = txt[: 0].count("\n")
        for pos, s in literais(txt):
            if TECNICA.match(s):
                continue          # caminho, formato, nome de símbolo
            linha = txt.count("\n", 0, pos) + 1
            for m in re.finditer(r"[A-Za-zÀ-ÿ]+", s):
                w = m.group(0)
                # Vizinhança de caminho: em "ux0:music/Artista/Album/*.mp3" a
                # palavra "Album" é o nome de uma PASTA, não prosa — acentuá-la
                # mudaria uma instrução em algo que não funciona.
                antes = s[m.start() - 1] if m.start() else " "
                depois = s[m.end()] if m.end() < len(s) else " "
                if antes in "/:._" or depois in "/:._":
                    continue
                cert = CERTO.get(w.lower())
                if cert:
                    achados.append((str(p), linha, w, cert, s.strip()[:70]))
    for a in achados:
        print(f"{a[0]}:{a[1]}: \"{a[2]}\" deveria ser \"{a[3]}\"  em: {a[4]}")
    return 1 if achados else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
