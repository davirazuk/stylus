#!/usr/bin/env python3
"""stylus stats — o formato do seu ano de escuta.

O `stylus diary` é uma LISTA: o que você pôs, na ordem. Isto é a outra
pergunta, a que uma lista não responde — em que dia da semana você ouve
disco, a que horas, quantos da estante nunca saíram da prateleira, há quantos
dias seguidos você põe alguma coisa.

Tudo sai do mesmo `plays.tsv` que o sistema escreve sozinho quando a agulha
desce. Nada aqui mede áudio nem abre arquivo de música: é de propósito, para
o comando responder na hora mesmo com uma estante grande.

    stylus stats              o retrato inteiro
    stylus stats --ano 2026   só um ano
    stylus stats -n 12        listas mais longas
"""
import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, "/usr/share/stylus/lib")
import vinyl  # noqa: E402

D = "\033[2m"; B = "\033[1m"; A = "\033[38;5;117m"; P = "\033[38;5;218m"
V = "\033[38;5;150m"; O = "\033[0m"

DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
BLOCOS = " ▁▂▃▄▅▆▇█"


def barra(v, maximo, largura=22):
    """Barra sólida. Zero é uma barra VAZIA e não uma linha ausente: um dia
    em que você não ouve nada é um dado, e some se a linha não for impressa."""
    if maximo <= 0:
        return " " * largura
    n = int(round(largura * v / maximo))
    return "█" * n + D + "·" * (largura - n) + O


def faixa(valores):
    """Sparkline. Escala pelo máximo; tudo zero desenha o traço de baixo."""
    m = max(valores) if valores else 0
    if m <= 0:
        return BLOCOS[0] * len(valores)
    return "".join(BLOCOS[max(1, min(8, int(round(8 * v / m))))] if v else BLOCOS[0]
                   for v in valores)


def plural(n, um, muitos):
    """"1 disco, posto 1 vez" e não "1 discos, postos 1 vezes". É pequeno e é
    a diferença entre um texto escrito e um texto montado."""
    return f"{n} {um if abs(n) == 1 else muitos}"


def quando(ts):
    d = (time.time() - ts) / 86400
    if d < 1:
        return "hoje"
    if d < 2:
        return "ontem"
    if d < 30:
        return f"há {int(d)} dias"
    if d < 365:
        return f"há {int(d / 30)} meses"
    return f"há {int(d / 365)} anos"


def sequencias(dias):
    """(sequência que está de pé, a maior de todas) em dias seguidos.

    A de pé só conta se o último dia for hoje ou ontem: às oito da manhã você
    ainda não pôs nada e uma sequência que morre à meia-noite seria mentira
    metade do dia.
    """
    if not dias:
        return 0, 0
    ordenados = sorted(dias)
    melhor = atual = 1
    for anterior, seguinte in zip(ordenados, ordenados[1:]):
        if (seguinte - anterior).days == 1:
            atual += 1
            melhor = max(melhor, atual)
        else:
            atual = 1
    hoje = datetime.now().date()
    de_pe = atual if (hoje - ordenados[-1]).days <= 1 else 0
    return de_pe, melhor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=8, help="quantos nomes em cada lista")
    ap.add_argument("--ano", type=int, default=None)
    args = ap.parse_args()

    linhas = list(vinyl._play_rows())
    if args.ano:
        linhas = [(ts, f) for ts, f in linhas
                  if datetime.fromtimestamp(ts).year == args.ano]
    if not linhas:
        alvo = f" em {args.ano}" if args.ano else ""
        print(f"\n  {D}nada anotado{alvo} — o sistema anota sozinho quando "
              f"você põe um disco.{O}\n")
        return 0

    contagem = Counter(os.path.normpath(f) for _ts, f in linhas)
    ultima = {}
    for ts, f in linhas:
        k = os.path.normpath(f)
        ultima[k] = max(ultima.get(k, 0.0), ts)
    artistas = Counter()
    for caminho, n in contagem.items():
        art, _nome = vinyl.folder_names(caminho)
        if art:
            artistas[art] += n

    momentos = [datetime.fromtimestamp(ts) for ts, _f in linhas]
    primeiro, ultimo = min(momentos), max(momentos)
    dias_corridos = max(1, (ultimo.date() - primeiro.date()).days + 1)

    titulo = f"o seu {args.ano}" if args.ano else "a sua escuta"
    print(f"\n  {B}{titulo}{O}\n")
    print(f"    {P}{len(contagem)}{O} {'disco' if len(contagem) == 1 else 'discos'}"
          f", {'posto' if len(contagem) == 1 else 'postos'} "
          f"{P}{len(linhas)}{O} {'vez' if len(linhas) == 1 else 'vezes'}")
    print(f"    {D}desde {primeiro.strftime('%d/%m/%Y')} "
          f"— {len(linhas) * 7 / dias_corridos:.1f} por semana, em média{O}")

    de_pe, melhor = sequencias({m.date() for m in momentos})
    dias_com = len({m.date() for m in momentos})
    print(f"    {D}{plural(dias_com, 'dia', 'dias')} com música, "
          f"de {dias_corridos}"
          f"{f' · {de_pe} dias seguidos agora' if de_pe > 1 else ''}"
          f"{f' · a maior foi de {melhor}' if melhor > 1 else ''}{O}")

    # ── o que volta ────────────────────────────────────────────────────────
    voltam = [(c, f) for f, c in contagem.items() if c > 1]
    if voltam:
        print(f"\n  {B}os que voltam{O}\n")
        for c, f in sorted(voltam, key=lambda x: (-x[0], x[1]))[:args.n]:
            art, nome = vinyl.folder_names(f)
            print(f"    {P}{c:>3}x{O}  {art[:22]:<24}{A}{nome[:34]:<36}{O}"
                  f"{D}{quando(ultima[f])}{O}")

    if len(artistas) > 1:
        print(f"\n  {B}quem você mais põe{O}\n")
        maior = artistas.most_common(1)[0][1]
        for art, n in artistas.most_common(args.n):
            print(f"    {art[:22]:<24}{barra(n, maior, 18)} {P}{n}{O}")

    # ── quando ─────────────────────────────────────────────────────────────
    por_dia = Counter(m.weekday() for m in momentos)
    print(f"\n  {B}em que dia{O}\n")
    maior = max(por_dia.values())
    for i, nome in enumerate(DIAS):
        n = por_dia.get(i, 0)
        print(f"    {nome:<9}{barra(n, maior, 20)} "
              f"{D + str(n) + O if not n else n}")

    por_hora = [0] * 24
    for m in momentos:
        por_hora[m.hour] += 1
    pico = por_hora.index(max(por_hora))
    print(f"\n  {B}a que horas{O}\n")
    print(f"    {V}{faixa(por_hora)}{O}")
    # A régua é montada coluna a coluna e não com espaços contados à mão: com
    # espaços, "6h" caía na coluna 10 e o desenho passava a mentir sobre a
    # hora — que é a única coisa que este gráfico tem para dizer.
    regua = [" "] * 24
    for col, rot in ((0, "0h"), (6, "6h"), (12, "12h"), (18, "18h")):
        for i, ch in enumerate(rot):
            if col + i < 24:
                regua[col + i] = ch
    print(f"    {D}{''.join(regua)}{O}")
    print(f"    {D}o seu horário é por volta das {pico}h{O}")

    # ── os doze meses ──────────────────────────────────────────────────────
    #  Do mês corrente para trás, para a última coluna ser sempre agora.
    hoje = datetime.now()
    chaves = []
    ano, mes = hoje.year, hoje.month
    for _ in range(12):
        chaves.append((ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    chaves.reverse()
    por_mes = Counter((m.year, m.month) for m in momentos)
    serie = [por_mes.get(k, 0) for k in chaves]
    if sum(serie):
        print(f"\n  {B}os doze meses{O}\n")
        print(f"    {V}{faixa(serie)}{O}   {D}{plural(sum(serie), 'vez', 'vezes')}{O}")
        # A inicial do mês, indexada pelo NÚMERO do mês. A primeira versão
        # tinha a string em outra ordem e os rótulos saíam dois meses
        # deslocados do que o desenho mostrava.
        rotulos = "".join("jfmamjjasond"[k[1] - 1] for k in chaves)
        print(f"    {D}{rotulos}{O}")

    # ── a prateleira parada ────────────────────────────────────────────────
    #  A pergunta que só a estante inteira responde: o que está aí e nunca
    #  saiu. É a razão de o `stylus record` existir.
    try:
        estante = vinyl.shelf()
    except Exception:                                     # noqa: BLE001
        estante = []
    if estante:
        nunca = [f for f in estante if os.path.normpath(f) not in ultima]
        print(f"\n  {B}a prateleira parada{O}\n")
        print(f"    {P}{len(nunca)}{O} dos {len(estante)} discos "
              f"{'nunca foi posto' if len(nunca) == 1 else 'nunca foram postos'}"
              f"{D} — `stylus record` sorteia puxando para eles{O}")
        for f in sorted(nunca)[:args.n]:
            art, nome = vinyl.folder_names(f)
            print(f"    {D}·{O} {art[:22]:<24}{A}{nome[:34]}{O}")
        if len(nunca) > args.n:
            print(f"    {D}… e mais {len(nunca) - args.n}{O}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
