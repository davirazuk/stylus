#!/usr/bin/env python3
"""Roda a fila do Qobuz, um disco de cada vez, falando direto com a API da
interface web.

Por que não o run_queue.sh:

  * O `_download_overrides()` da API monta o dicionário com
    `data.get("embed_art", False)` — uma chave AUSENTE vira um `False` de
    verdade, e o `as_bool(False, cfg_default)` devolve esse `False` porque
    ele é um booleano legítimo. Ou seja: uma opção que você não mandou GANHA
    do config.ini. Mandar só {"urls": ...} desligava calado o og_cover e o
    embed_art mesmo com os dois ligados no config.ini. Agora toda opção que
    importa vai escrita.
  * Procurar `^Completed$` no log é uma corrida: a linha sai por ÁLBUM, lá
    dentro do baixador, mas a thread de trabalho ainda está etiquetando e
    movendo arquivo depois disso. Quem sabe de verdade é o `download_active`.
  * O script não conferia repetido, não sabia lidar com disco duplo e não
    guardava o erro de cada álbum.

Como se sabe que acabou: um POST /api/download com a lista de urls vazia. A
rota confere o `state["download_active"]` ANTES de validar as urls, então um
servidor ocupado responde "A download is already running." e um parado
responde "No URLs provided". Não causa efeito nenhum, e é uma resposta
confiável de um jeito que o log não é.

Cada disco é terminado por inteiro — baixar, mover, reetiquetar, letra,
embutir, playlist principal, manifesto — antes de o próximo começar, para
que uma interrupção nunca deixe um álbum pela metade.

Uso:  run_queue_api.py ARQUIVO-DA-FILA [--limit N] [--dry]
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request

from _raiz import raiz   # onde fica a coleção, decidido num lugar só

API = os.environ.get("STYLUS_QOBUZ_API") or "http://127.0.0.1:8765/api"
QOBUZ_DIR = os.environ.get("STYLUS_QOBUZ_DIR") or os.path.expanduser("~/Qobuz Downloads")
LIB = raiz()
# As ferramentas ficam AO LADO deste arquivo. Isto dizia
# ~/.local/share/stylus/tools, que não existe em máquina nenhuma: numa
# instalação elas estão em /usr/share/stylus/tools. Como o caminho só era
# usado como `cwd=` de um subprocess, o efeito era um FileNotFoundError cru
# no meio da fila — não um "falhou este álbum", um traceback que parava tudo,
# depois de o disco já ter sido baixado.
TOOLS = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get("STYLUS_QOBUZ_LOG") or "/tmp/qobuz-gui.log"
PROGRESS = os.path.expanduser("~/.local/share/stylus/queue-progress.tsv")

DL_TIMEOUT = 3600     # per album, seconds
POLL = 5


def post(path, payload):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def busy():
    """True while a download is running. See module docstring."""
    r = post("/download", {"urls": ""})
    return "already running" in str(r.get("error", ""))


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(the|a|an)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def in_library(artist, album):
    # Sem a coleção no lugar, "não tenho este disco" é a resposta certa — e
    # era um FileNotFoundError no os.listdir logo abaixo, na PRIMEIRA linha da
    # fila, numa máquina onde a estante ainda não tinha sido apontada.
    if not os.path.isdir(LIB):
        return None
    ad = os.path.join(LIB, artist)
    if not os.path.isdir(ad):
        # artist folder may differ in punctuation
        na = norm(artist)
        match = [d for d in os.listdir(LIB)
                 if os.path.isdir(os.path.join(LIB, d)) and norm(d) == na]
        if not match:
            return None
        ad = os.path.join(LIB, match[0])
    nb = norm(album)
    for d in os.listdir(ad):
        p = os.path.join(ad, d)
        if os.path.isdir(p) and norm(d) == nb:
            n = len([f for f in os.listdir(p) if f.lower().endswith(".flac")])
            if n:
                return f"{os.path.basename(ad)}/{d} ({n} tracks)"
    return None


def staging_dirs():
    if not os.path.isdir(QOBUZ_DIR):
        return []
    return sorted(d for d in os.listdir(QOBUZ_DIR)
                  if os.path.isdir(os.path.join(QOBUZ_DIR, d)))


def flatten_discs(folder):
    """Multi-disc releases land in `Disc N/` subfolders (multiple_disc_one_dir
    is off). integrate_album.py only looks at the top level, so merge them up
    first, renumbering continuously so track order survives."""
    path = os.path.join(QOBUZ_DIR, folder)
    subs = sorted(d for d in os.listdir(path)
                  if os.path.isdir(os.path.join(path, d)))
    if not subs:
        return 0
    moved = 0
    offset = 0
    for sub in subs:
        sp = os.path.join(path, sub)
        flacs = sorted(f for f in os.listdir(sp) if f.lower().endswith(".flac"))
        hi = 0
        for f in flacs:
            m = re.match(r"^(\d+)[.\s-]+(.+)\.flac$", f)
            if not m:
                continue
            num, title = int(m.group(1)), m.group(2)
            hi = max(hi, num)
            dst = os.path.join(path, f"{offset + num:02d}. {title}.flac")
            os.rename(os.path.join(sp, f), dst)
            moved += 1
        offset += hi
        for leftover in os.listdir(sp):
            src = os.path.join(sp, leftover)
            dst = os.path.join(path, leftover)
            if not os.path.exists(dst) and os.path.isfile(src):
                os.rename(src, dst)
        try:
            os.rmdir(sp)
        except OSError:
            pass
    return moved


def log_size():
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def log_since(offset):
    try:
        with open(LOG, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def record(status, artist, album, detail):
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')}\t{status}\t{artist}\t{album}\t{detail}\n")
    print(f"  -> {status}: {detail}", flush=True)


def main():
    queue_file = sys.argv[1]
    dry = "--dry" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    entries = []
    for n, line in enumerate(open(queue_file, encoding="utf-8"), 1):
        line = line.strip()
        if not line.startswith("http"):
            continue
        # split("|") sem limite estoura com ValueError num álbum que tem "|"
        # no nome, e a fila INTEIRA morre por causa de uma linha. Com limite,
        # o que sobra fica no nome do álbum, que é onde ele estava.
        partes = line.split("|", 2)
        if len(partes) != 3:
            print(f"  linha {n} ignorada (não é url|artista|álbum): "
                  f"{line[:80]}", flush=True)
            continue
        url, artist, album = (p.strip() for p in partes)
        entries.append((url, artist, album))
    if limit:
        entries = entries[:limit]

    print(f"{len(entries)} linhas de {queue_file}\n", flush=True)
    counts = {"ok": 0, "skip": 0, "fail": 0}

    for i, (url, artist, album) in enumerate(entries, 1):
        print(f"[{i}/{len(entries)}] {artist} — {album}", flush=True)

        have = in_library(artist, album)
        if have:
            counts["skip"] += 1
            record("SKIP", artist, album, f"already in library: {have}")
            continue
        if dry:
            record("WOULD-GET", artist, album, url)
            continue

        # Staging must be empty: the post-download folder is identified by
        # being the only thing there.
        stray = staging_dirs()
        if stray:
            record("FAIL", artist, album, f"staging not empty: {stray}")
            counts["fail"] += 1
            continue

        off = log_size()
        r = post("/download", {
            "urls": url,
            "quality": 27,          # Hi-Res; falls back on its own when absent
            "embed_art": True,
            "og_cover": True,       # full-resolution cover.jpg
            "no_fallback": False,   # lower quality beats no album at all
            "no_cover": False,
            "no_db": True,          # library check is our authority, not its db
            "albums_only": False,
            "no_m3u": False,
        })
        if not r.get("ok"):
            counts["fail"] += 1
            record("FAIL", artist, album, f"queue rejected: {r.get('error')}")
            continue

        waited = 0
        time.sleep(3)
        while busy() and waited < DL_TIMEOUT:
            time.sleep(POLL)
            waited += POLL
        if waited >= DL_TIMEOUT:
            counts["fail"] += 1
            record("FAIL", artist, album, f"timed out after {DL_TIMEOUT}s")
            continue

        time.sleep(2)
        tail = log_since(off)
        dirs = staging_dirs()
        if not dirs:
            reason = "no folder produced"
            for marker in ("not available", "not streamable", "non_streamable",
                           "Already downloaded", "Error", "error"):
                if marker in tail:
                    hit = [ln for ln in tail.splitlines() if marker in ln]
                    if hit:
                        reason = hit[-1].strip()[:160]
                        break
            counts["fail"] += 1
            record("FAIL", artist, album, reason)
            continue

        folder = dirs[0]
        fpath = os.path.join(QOBUZ_DIR, folder)
        n_disc = flatten_discs(folder)
        if n_disc:
            print(f"  {n_disc} faixas trazidas das subpastas de disco", flush=True)
        n_flac = len([f for f in os.listdir(fpath) if f.lower().endswith(".flac")])
        if not n_flac:
            counts["fail"] += 1
            record("FAIL", artist, album, f"folder '{folder}' has no FLACs")
            continue

        res = subprocess.run(
            [sys.executable, "integrate_album.py", folder, artist, album],
            cwd=TOOLS, capture_output=True, text=True, timeout=120)
        out = (res.stdout or "") + (res.stderr or "")
        if "Integrated:" not in out:
            counts["fail"] += 1
            record("FAIL", artist, album, f"integrate failed: {out.strip()[-200:]}")
            continue

        # Safety net: integrate embeds art + whatever .lrc it fetched; this
        # catches anything it missed without rescanning the whole library.
        dest = None
        for d in os.listdir(LIB) if os.path.isdir(LIB) else []:
            if norm(d) != norm(artist):
                continue
            cand = os.path.join(LIB, d)
            if not os.path.isdir(cand):
                continue
            for sub in os.listdir(cand):
                if norm(sub) == norm(album):
                    dest = os.path.join(cand, sub)
                    break
            if dest:
                break
        if dest:
            subprocess.run([sys.executable, "embed_metadata.py", "--apply", dest],
                           cwd=TOOLS, capture_output=True, text=True, timeout=60)

        counts["ok"] += 1
        quality = ""
        m = re.search(r"\[(\d+)B-([\d.]+)kHz\]", folder)
        if m:
            quality = f"{m.group(1)}bit/{m.group(2)}kHz"
        record("OK", artist, album, f"{n_flac} tracks {quality}")

    print(f"\n=== fim: ok={counts['ok']} pulados={counts['skip']} "
          f"fail={counts['fail']}", flush=True)


if __name__ == "__main__":
    main()
