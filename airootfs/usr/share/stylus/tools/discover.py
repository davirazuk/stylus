"""Para cada artista, lista os discos do Qobuz que parecem lançamentos de
estúdio de verdade e que ainda não estão na coleção.

Filtra o ruído que tornava a busca à mão cansativa: artista trocado,
single e EP, gravação ao vivo e coletânea.
"""
import json, os, sys, urllib.parse
import requests

from _raiz import raiz, audio_ext   # a coleção e o que é música: um lugar só

LIB = raiz()
API = "http://127.0.0.1:8765/api/search"

# Compilations/live/reissue noise. Kept deliberately conservative — better to
# surface one dubious candidate for review than silently drop a real album.
SKIP_WORDS = (
    "live", "remix", "deluxe", "anniversary", "greatest", "best of",
    "collection", "compilation", "single", "ep)", "demos", "b-sides",
    "rarities", "session", "soundtrack", "instrumental", "acoustic",
    "karaoke", "tribute", "covers", "boxset", "box set", "peel",
)


# Ver o `audio_ext` no _raiz: uma lista só para todas as ferramentas.
AUDIO_EXT = audio_ext()


def _tem_audio(d):
    """Pasta com capa e encarte e nenhuma música NÃO conta como ter o álbum.

    Era o buraco: o `gaps` perguntava só se a PASTA existe. Três álbuns desta
    biblioteca têm capa, encarte e zero arquivo de áudio — download que trouxe
    os metadados e não trouxe o som — e por causa disso eram invisíveis aqui,
    justamente os que mais precisavam aparecer. Desce um nível, porque álbum
    de mais de um disco guarda as faixas em "Disc 01".
    """
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if n.lower().endswith(AUDIO_EXT) and os.path.isfile(p):
                return True
            if os.path.isdir(p):
                try:
                    if any(x.lower().endswith(AUDIO_EXT) for x in os.listdir(p)):
                        return True
                except OSError:
                    pass
    except OSError:
        return False
    return False


def owned(artist):
    d = os.path.join(LIB, artist)
    if not os.path.isdir(d):
        return set()
    return {x.lower().strip() for x in os.listdir(d)
            if os.path.isdir(os.path.join(d, x))
            and _tem_audio(os.path.join(d, x))}


def discover(artist, min_tracks=7):
    q = urllib.parse.quote(artist)
    try:
        r = requests.get(f"{API}?q={q}&type=album&limit=25", timeout=30)
        data = r.json()
    except Exception as e:
        print(f"  !! {artist}: {e}", file=sys.stderr)
        return []

    have = owned(artist)
    out = []
    seen_titles = set()
    for res in data.get("results", []):
        if res.get("display_subtitle", "").strip().lower() != artist.lower():
            continue
        title = res.get("display_title", "").strip()
        tl = title.lower()
        if any(w in tl for w in SKIP_WORDS):
            continue
        if res.get("tracks", 0) < min_tracks:
            continue
        if tl in have:
            continue
        # Qobuz lists the same album many times (regional/quality variants).
        # Keep the first, preferring HI-RES since results are roughly ordered.
        key = tl
        if key in seen_titles:
            continue
        seen_titles.add(key)
        out.append({
            "artist": artist,
            "title": title,
            "year": res.get("release_year"),
            "tracks": res.get("tracks"),
            "quality": res.get("quality"),
            "url": res.get("url"),
        })
    return out


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

    artists = [a.strip() for a in sys.argv[1:]]
    all_found = []
    for a in artists:
        found = discover(a)
        for f in found:
            print(f"{f['url']}|{f['artist']} - {f['title']}"
                  f"   [{f['year']}, {f['tracks']}tr, {f['quality']}]")
        all_found.extend(found)
    print(f"\n# {len(all_found)} candidates across {len(artists)} artists",
          file=sys.stderr)
