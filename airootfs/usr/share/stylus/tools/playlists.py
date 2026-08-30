#!/usr/bin/env python3
"""stylus playlists — as listas .m3u da coleção, e como pôr uma para tocar.

POR QUE ISTO EXISTE
-------------------
O sistema ESCREVIA playlists e não sabia tocar nenhuma. O `stylus suggest`,
o `make_new_playlist` e o `integrate_album` põem .m3u na raiz da coleção —
"Shoegaze & Dreampop.m3u", "Novidades 2026-08-30.m3u", "coleção.m3u" — e não
havia caminho nenhum daqui até o tocador, nem um comando que as listasse. É
a família do `stylus-welcome` que o i3 abria e nunca existiu: a peça está
escrita, o fio não.

Uma playlist não é um disco: entra como um lado só e CONTÍNUO, sem "vire o
disco". O aviso de virar o lado é verdade sobre um objeto que tem dois
lados; numa lista de duzentas faixas viraria um alarme a cada vinte minutos.
Com --limpar, tira das listas as faixas cujo arquivo não existe mais — e
guarda a antiga ao lado como .m3u.bak.
"""
import os
import sys

_aqui = os.path.dirname(os.path.abspath(__file__))
for _p in ("/usr/share/stylus/lib", os.path.join(os.path.dirname(_aqui), "lib")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
import vinyl  # noqa: E402

D = "\033[2m"; B = "\033[1m"; A = "\033[38;5;117m"; O = "\033[0m"


def humano(seg):
    seg = int(seg or 0)
    h, m = seg // 3600, (seg % 3600) // 60
    if h:
        return f"{h}h{m:02d}"
    return f"{m} min"


# A regra é a do `vinyl.plural`: uma cópia nova aqui seria a próxima a
# esquecer o caso do 1.
plural = vinyl.plural


def limpar(listas):
    """Tira das listas as faixas cujo arquivo não existe mais.

    Isto existe porque a listagem RECLAMAVA e não resolvia: dizia "3 faixas
    sem arquivo" e não havia comando nenhum para tirá-las. Apontar um
    problema sem dar o caminho de sair dele é meia ferramenta.

    A lista velha fica ao lado como `.m3u.bak` — uma playlist é feita à mão
    e a pessoa se importa com ela; reescrever sem deixar volta seria
    atrevimento. Endereço http nunca é apagado: não dá para saber daqui se
    ele ainda responde, e sumir com o que talvez esteja bom é pior do que
    deixar uma linha morta.
    """
    total = 0
    for pl in listas:
        itens = vinyl.ler_m3u(pl)
        vivos = [(c, t, d) for c, t, d in itens
                 if c.startswith(("http://", "https://")) or os.path.isfile(c)]
        if len(vivos) == len(itens):
            continue
        base = os.path.dirname(os.path.abspath(pl))
        linhas = ["#EXTM3U"]
        for caminho, titulo, dur in vivos:
            if titulo or dur:
                linhas.append("#EXTINF:%d,%s" % (int(dur or -1), titulo))
            if caminho.startswith(("http://", "https://")):
                linhas.append(caminho)
            else:
                try:
                    rel = os.path.relpath(caminho, base)
                except ValueError:
                    rel = caminho
                linhas.append(caminho if rel.startswith("..") else rel)
        try:
            import shutil
            shutil.copy2(pl, pl + ".bak")
            with open(pl, "w", encoding="utf-8") as fh:
                fh.write("\n".join(linhas) + "\n")
        except OSError as e:                               # noqa: BLE001
            print(f"    {D}não deu para reescrever {os.path.basename(pl)}: "
                  f"{e}{O}")
            continue
        sumiram = len(itens) - len(vivos)
        total += sumiram
        print(f"    {A}{os.path.splitext(os.path.basename(pl))[0]}{O}"
              f"{D} — tirei {plural(sumiram, 'faixa')} "
              f"(a antiga ficou em .m3u.bak){O}")
    if not total:
        print(f"\n  {D}nenhuma faixa morta nas playlists.{O}\n")
    else:
        print(f"\n  {plural(total, 'faixa')} sem arquivo, "
              f"{'tirada' if total == 1 else 'tiradas'}.\n")
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    listas = vinyl.playlists()
    if not listas:
        raizes = ", ".join(vinyl.library_roots()) or "nenhuma pasta configurada"
        print(f"\n  {D}nenhuma playlist em {raizes}.{O}")
        print(f"  {D}`stylus suggest` escreve algumas a partir do que você "
              f"ouve.{O}\n")
        return 0

    if "--limpar" in sys.argv[1:]:
        print(f"\n  {B}tirando as faixas que sumiram{O}\n")
        return limpar(listas)

    # Com argumento: PÕE aquela para tocar. Listar e não poder tocar é
    # metade do caminho, e é justamente a metade que já existia.
    if args:
        querido = " ".join(args).lower()
        alvo = None
        for p in listas:
            nome = os.path.splitext(os.path.basename(p))[0].lower()
            if nome == querido:
                alvo = p
                break
        if alvo is None:
            for p in listas:
                nome = os.path.splitext(os.path.basename(p))[0].lower()
                if querido in nome:
                    alvo = p
                    break
        if alvo is None:
            print(f"\n  não achei nenhuma playlist chamada \"{' '.join(args)}\".\n")
            return 1
        os.execvp("stylus-deck", ["stylus-deck", alvo])

    print(f"\n  {B}playlists{O}\n")
    for p in listas:
        nome = os.path.splitext(os.path.basename(p))[0]
        itens = vinyl.ler_m3u(p)
        # Faixa que não existe mais: a coleção mudou de lugar, o disco foi
        # renomeado. Dizer quantas faltam é a diferença entre "esta lista
        # está velha" e "esta lista está quebrada e você não sabia".
        somem = sum(1 for c, _t, _d in itens
                    if not c.startswith(("http://", "https://"))
                    and not os.path.isfile(c))
        aviso = f"   {D}({plural(somem, 'faixa')} sem arquivo){O}" if somem else ""
        print(f"    {A}{nome[:44]:<46}{O}{D}{plural(len(itens), 'faixa'):>12}{O}"
              f"{aviso}")
    print(f"\n  {D}stylus playlists NOME{O} põe uma para tocar   "
          f"{D}·   --limpar{O} tira as faixas que sumiram\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
