import os, re, sys, shutil, requests
from mutagen.flac import FLAC

from _raiz import raiz   # onde fica a coleção, decidido num lugar só

QOBUZ_DIR = os.environ.get("STYLUS_QOBUZ_DIR") or os.path.expanduser("~/Qobuz Downloads")
LIB_ROOT = raiz()
PLAYLIST = os.path.join(LIB_ROOT, "coleção.m3u")


def integrate(folder_name, artist, album_clean):
    src = os.path.join(QOBUZ_DIR, folder_name)
    if not os.path.isdir(src):
        print(f"SKIP (not found): {folder_name}")
        return []

    dest_dir = os.path.join(LIB_ROOT, artist, album_clean)
    os.makedirs(dest_dir, exist_ok=True)

    # ── Achar as faixas ──────────────────────────────────────────────────
    # Recursivo, não os.listdir. Álbum de mais de um disco vem em "Disc 01",
    # "Disc 02", e o listdir de antes achava ZERO faixa nesses — integrava
    # nada, e mesmo assim apagava a origem no fim. É exatamente assim que
    # nasceram as pastas com capa, encarte e nenhuma música desta biblioteca.
    achados = []
    # `pasta`, não `raiz`: `raiz` é a FUNÇÃO importada lá em cima que diz onde
    # fica a coleção, e usá-la como variável de laço a substitui por uma
    # string dentro desta função inteira. Hoje não quebra nada porque ninguém
    # a chama depois do laço; é a próxima linha acrescentada aqui que quebra,
    # com um "str is not callable" que não parece ter nada a ver.
    for pasta, _dirs, arquivos in os.walk(src):
        for f in arquivos:
            if f.lower().endswith(".flac"):
                achados.append(os.path.join(pasta, f))
    achados.sort()

    def _disco_de(caminho):
        """Número do disco: pela pasta 'Disc NN', senão pela tag."""
        pai = os.path.basename(os.path.dirname(caminho))
        m = re.match(r"^disc\s*0*(\d+)$", pai, re.I)
        if m:
            return int(m.group(1))
        try:
            v = FLAC(caminho).get("discnumber", ["1"])[0]
            return int(str(v).split("/")[0])
        except Exception:
            return 1

    discos = {_disco_de(c) for c in achados}
    multi = len(discos) > 1

    def _num_titulo(caminho):
        """Número e título, dos vários jeitos que o qobuz-dl nomeia.

        O padrão antigo só aceitava "NN. Título.flac". O que chega de verdade
        também vem como "NN - Título.flac" e, em álbum de vários discos, com o
        disco embutido: "207 - Golden Hair.flac" (disco 2, faixa 07). Quando
        nada casa, a tag manda — nome de arquivo é palpite, tag é dado.
        """
        base = os.path.splitext(os.path.basename(caminho))[0]
        m = re.match(r"^(\d+)\s*[.\-–]\s*(.+)$", base)
        num, titulo = (m.group(1), m.group(2)) if m else (None, base)
        try:
            tags = FLAC(caminho)
            t_num = str(tags.get("tracknumber", [""])[0]).split("/")[0]
            t_tit = (tags.get("title", [""])[0] or "").strip()
            if t_num.isdigit():
                num = t_num
            if t_tit:
                titulo = t_tit
        except Exception:
            pass
        if num is None:
            num = "0"
        return int(num), titulo

    new_paths = []
    for old_path in achados:
        num, title = _num_titulo(old_path)
        safe_title = re.sub(r'[/\\:*?"<>|]', "_", title).strip() or "faixa"
        new_name = f"{int(num):02d} - {safe_title}.flac"
        if multi:
            sub = os.path.join(dest_dir, f"Disc {_disco_de(old_path):02d}")
            os.makedirs(sub, exist_ok=True)
            new_path = os.path.join(sub, new_name)
        else:
            new_path = os.path.join(dest_dir, new_name)

        audio = FLAC(old_path)
        audio["album"] = album_clean
        audio["artist"] = artist
        audio["albumartist"] = artist
        audio.save()

        shutil.move(old_path, new_path)
        new_paths.append(new_path)
        print(f"  moved: {os.path.relpath(new_path, dest_dir)}")

    cover_src = os.path.join(src, "cover.jpg")
    if os.path.exists(cover_src):
        shutil.move(cover_src, os.path.join(dest_dir, "cover.jpg"))
    booklet_src = os.path.join(src, "Digital Booklet.txt")
    if os.path.exists(booklet_src):
        shutil.move(booklet_src, os.path.join(dest_dir, "Digital Booklet.txt"))

    # ── Só apaga a origem se ela ficou mesmo vazia de música ─────────────
    # O rmtree era incondicional. Integrando 0 faixas, ele apagava um download
    # inteiro e recém-terminado — perda de dados de verdade, silenciosa, e com
    # uma linha final dizendo "Integrated". Agora a origem só some quando não
    # sobrou áudio nenhum nela.
    restou = [os.path.join(r, f)
              for r, _d, fs in os.walk(src) for f in fs
              if f.lower().endswith((".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav"))]
    if not new_paths:
        print(f"!!! NÃO integrei nada de {folder_name} — a origem foi PRESERVADA "
              f"em {src}. Confira o formato dos arquivos antes de rodar de novo.")
        return []
    if restou:
        print(f"  aviso: {len(restou)} arquivo(s) de áudio ficaram em {src}; não apaguei nada.")
    else:
        shutil.rmtree(src, ignore_errors=True)
    print(f"Integrated: {artist} - {album_clean} ({len(new_paths)} tracks) -> {dest_dir}")
    return new_paths


def _embed_after(paths, cover_bytes):
    """Embed cover art and .lrc lyrics into each file (see integrate())."""
    from mutagen.flac import FLAC as _F, Picture as _P
    n_art = n_lyr = 0
    for pth in paths:
        try:
            au = _F(pth)
            changed = False
            if cover_bytes and not au.pictures:
                pic = _P()
                pic.data, pic.mime, pic.type, pic.desc = cover_bytes, "image/jpeg", 3, "Cover"
                au.add_picture(pic); n_art += 1; changed = True
            lrcp = os.path.splitext(pth)[0] + ".lrc"
            if os.path.exists(lrcp) and not au.get("lyrics"):
                au["lyrics"] = open(lrcp, encoding="utf-8").read().strip()
                n_lyr += 1; changed = True
            if changed:
                au.save()
        except Exception as e:
            print(f"  embed failed for {os.path.basename(pth)}: {e}")
    print(f"  embedded: art {n_art}, lyrics {n_lyr}")


def fetch_lyrics(flac_paths, artist, album_clean):
    found = 0
    for path in flac_paths:
        lrc_path = os.path.splitext(path)[0] + ".lrc"
        if os.path.exists(lrc_path):
            continue
        audio = FLAC(path)
        title = audio.get("title", [os.path.basename(path)])[0]
        duration = int(audio.info.length)
        try:
            r = requests.get(
                "https://lrclib.net/api/get",
                params={"artist_name": artist, "track_name": title, "album_name": album_clean, "duration": duration},
                headers={"User-Agent": "stylus-tool/1.0"},
                timeout=15,
            )
            if r.ok:
                synced = r.json().get("syncedLyrics")
                if synced:
                    with open(lrc_path, "w", encoding="utf-8") as f:
                        f.write(synced)
                    found += 1
        except Exception as e:
            print(f"  lyrics lookup failed for {title}: {e}")
    print(f"  lyrics found: {found}/{len(flac_paths)}")


def add_to_playlist(flac_paths):
    with open(PLAYLIST, "a", encoding="utf-8") as f:
        for p in flac_paths:
            rel = os.path.relpath(p, LIB_ROOT)
            f.write(rel + "\n")


MANIFEST = os.path.expanduser("~/.local/share/stylus-added.tsv")


def record(artist, album_clean, n_tracks):
    """Append to a manifest of albums this tooling added.

    Needed because mtime alone can't identify new albums: a phone sync pulls
    files into EXISTING album folders and bumps their mtimes too, and its
    timestamps interleave with download timestamps, so no cutoff separates
    them. The integrator is the only thing that actually knows.
    """
    import datetime
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(f"{datetime.date.today().isoformat()}\t{artist}\t{album_clean}\t{n_tracks}\n")


if __name__ == "__main__":
    folder_name, artist, album_clean = sys.argv[1], sys.argv[2], sys.argv[3]
    paths = integrate(folder_name, artist, album_clean)
    if paths:
        fetch_lyrics(paths, artist, album_clean)
        cover_path = os.path.join(os.path.dirname(paths[0]), "cover.jpg")
        cover_bytes = open(cover_path, "rb").read() if os.path.exists(cover_path) else None
        _embed_after(paths, cover_bytes)
        add_to_playlist(paths)
        record(artist, album_clean, len(paths))
