"""Propõe o que acrescentar às playlists a partir dos discos que entraram,
sem encostar nas playlists de verdade.

As playlists são feitas à mão e a pessoa se importa com elas estarem
certas, então sair acrescentando faixa sozinho seria atrevimento. Em vez
disso, isto escreve arquivos paralelos "— sugestões.m3u", que dá para
ouvir com calma e depois juntar com um `cat A >> B` — ou apagar. Nada do
que já existe é modificado.

A correspondência é por artista, e de propósito conservadora: um artista
só é proposto para a playlist em que a obra inteira dele claramente
pertence àquele gênero. O que depende de humor em vez de gênero fica de
fora inteiro — essas são decisões sobre como uma faixa específica soa, que
é justamente a parte que não é mecânica.
"""
import os

from _raiz import raiz, audio_ext, plural   # a coleção, a música e o plural

LIB = raiz()
# A coleção e o lugar das playlists são a mesma pasta: o subdiretório fixo
# que havia aqui era o nome da coleção de uma pessoa só.
ROOT = LIB
MANIFEST = os.path.expanduser("~/.local/share/stylus-added.tsv")
# Era `(".flac", ".mp3")` — ver a mesma lição no _raiz.
AUDIO_EXT = audio_ext()

# artist -> playlist basename (without .m3u)
GENRE = {
    # canonical shoegaze / dreampop
    "My Bloody Valentine": "Shoegaze & Dreampop",
    "Slowdive": "Shoegaze & Dreampop",
    "Cocteau Twins": "Shoegaze & Dreampop",
    "Drop Nineteens": "Shoegaze & Dreampop",
    "Pinkshinyultrablast": "Shoegaze & Dreampop",
    "Beach Fossils": "Shoegaze & Dreampop",
    "Narrow Head": "Shoegaze & Dreampop",
    "Asian Glow": "Shoegaze & Dreampop",
    "Parannoul": "Shoegaze & Dreampop",
    "Hotline TNT": "Shoegaze & Dreampop",
    "Beach House": "Shoegaze & Dreampop",
    "Melody's Echo Chamber": "Shoegaze & Dreampop",
    # slowcore / midwest emo
    "Codeine": "Midwest Emo & Slowcore",
    "Duster": "Midwest Emo & Slowcore",
    "Red House Painters": "Midwest Emo & Slowcore",
    "Mineral": "Midwest Emo & Slowcore",
    "Cap'n Jazz": "Midwest Emo & Slowcore",
    "Title Fight": "Midwest Emo & Slowcore",
    "Sparklehorse": "Midwest Emo & Slowcore",
    # indie / garage
    "Turnover": "Garage & Indie Rock",
    "Alvvays": "Garage & Indie Rock",
    "Car Seat Headrest": "Garage & Indie Rock",
    "Modest Mouse": "Garage & Indie Rock",
    "Built To Spill": "Garage & Indie Rock",
    "Pavement": "Garage & Indie Rock",
    "Interpol": "Garage & Indie Rock",
    "Joy Division": "Garage & Indie Rock",
    "Surf Curse": "Garage & Indie Rock",
    "Alex G": "Bedroom & Underground Pop",
    "Elliott Smith": "Bedroom & Underground Pop",
    "Alex Turner": "Bedroom & Underground Pop",
    "Julian Casablancas": "Strokes Side Projects",
    "Mini Mansions": "Strokes Side Projects",
    "Tame Impala": "Pop & Alt-Pop",
    "Failure": "Classic & Mainstream Rock",
    "Hum": "Classic & Mainstream Rock",
    "Have a Nice Life": "Rage & Catharsis",
}


def track_key(name):
    lead = name.split(" - ")[0].strip()
    return (int(lead) if lead.isdigit() else 0, name)


def main():
    if not os.path.exists(MANIFEST):
        print("ainda não há manifesto do que entrou")
        return

    seen, entries = set(), []
    for line in open(MANIFEST, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) < 3 or (p[1], p[2]) in seen:
            continue
        seen.add((p[1], p[2]))
        entries.append((p[1], p[2]))

    proposals, skipped = {}, []
    for artist, album in sorted(entries):
        pl = GENRE.get(artist)
        if not pl:
            skipped.append(f"{artist} - {album}")
            continue
        d = os.path.join(ROOT, artist, album)
        if not os.path.isdir(d):
            continue
        tracks = sorted((f for f in os.listdir(d) if f.lower().endswith(AUDIO_EXT)),
                        key=track_key)
        for t in tracks:
            rel = os.path.relpath(os.path.join(d, t), LIB)
            proposals.setdefault(pl, []).append(rel)

    for pl, lines in sorted(proposals.items()):
        target = os.path.join(LIB, f"{pl}.m3u")
        existing = set()
        if os.path.exists(target):
            existing = {l.strip() for l in open(target, encoding="utf-8") if l.strip()}
        fresh = [l for l in lines if l not in existing]
        if not fresh:
            continue
        out = os.path.join(LIB, f"{pl} — sugestões.m3u")
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(fresh) + "\n")
        print(f"{os.path.basename(out)}: {plural(len(fresh), 'faixa')} "
              f"(existing playlist has {len(existing)})")

    if skipped:
        print("\nsem gênero conhecido, ficaram de fora:")
        for s in skipped:
            print(f"  {s}")
    print("\nNada do que já existia foi mexido. Para aceitar uma:")
    print('  cat "Shoegaze & Dreampop — sugestões.m3u" >> "Shoegaze & Dreampop.m3u"')
    print("As playlists de humor não foram tocadas, de propósito.")


import sys

if __name__ == "__main__":
    # `--help` tem que IMPRIMIR e sair, sempre. Sem esta guarda, um `--help`
    # caía na execução normal: aqui não existe argparse, então a opção não
    # casava com nada e virava "nenhum argumento" — que para estas ferramentas
    # quer dizer "faça o trabalho inteiro". O `stylus tags --help` saía
    # varrendo a coleção toda e consultando a rede faixa por faixa; quem só
    # queria saber o que o comando faz esperava minutos e desistia.
    if {"-h", "--help"} & set(sys.argv[1:]):
        print((__doc__ or "sem ajuda").strip())
        raise SystemExit(0)

    main()
