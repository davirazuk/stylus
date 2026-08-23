#!/usr/bin/env python3
# A linha da letra que está sendo cantada agora, na barra.
#
# O tempo limite aqui é 12s e NÃO é folga: o playerctl nesta classe de
# máquina leva de 5 a 20 segundos na primeira consulta depois de um tempo
# parado (o tocador demora a responder pelo DBus) e 6ms nas seguintes. Com os
# 2s que pareciam razoáveis, toda chamada fria estourava e o módulo
# simplesmente não aparecia — sem erro nenhum à vista.
# ─────────────────────────────────────────────────────────────────────────────
#  The line that is being sung, in the bar.
#
#  There are ~3000 .lrc sidecars in this library, sitting next to the FLACs and
#  read by nothing. This walks the one belonging to whatever is playing and
#  prints the line whose timestamp has passed, so the bar carries the lyric in
#  time with the song.
#
#  POSITION IS EXTRAPOLATED, NOT POLLED. MPRIS deliberately does not emit
#  PropertiesChanged for Position - the spec says so - which means there is no
#  event to follow and the only honest way to know where a track is, is to ask.
#  Asking four times a second is 240 playerctl processes a minute forever, on a
#  laptop, for a decoration. Instead this asks once every few seconds and reads
#  a monotonic clock in between; drift over four seconds of playback is a few
#  milliseconds, and every resync corrects it anyway. A seek shows up at the
#  next resync, which is the one visible cost and is under four seconds.
#
#  Prints only when the rendered line actually changes. A polybar `tail` module
#  redraws the whole bar for every line it is given, and a lyric holds for
#  several seconds at a time.
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import subprocess
import sys
import time
import urllib.parse

TICK = 0.35            # how often the extrapolated position is re-checked
SYNC_EVERY = 4.0       # how often the player is actually asked anything
# 46 -> 32. A barra tem largura fixa, e a letra ganhou a esquerda inteira
# quando saiu do centro — com 46 caracteres ela empurrava a data e o botão de
# desligar para fora da tela. Cortar a frase é o que menos custa: ela dura
# poucos segundos e volta na próxima linha, enquanto o relógio some para
# sempre.
MAX_CHARS = 32

ACCENT = "#5bcefa"
DIM = "#6e7887"
TEXT = "#a8b0bc"

# One call, all four fields, unit-separated - the same reason media.sh uses
# 0x1F: a lyric library is full of titles with dashes, pipes and slashes in
# them, and a track called "Pyramid Song | Live" must not be able to split into
# the wrong number of fields.
SEP = "\x1f"
FMT = SEP.join(("{{status}}", "{{position}}", "{{xesam:url}}"))

TS = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")


#  O playerctl NÃO responde sempre em milissegundos. Medido nesta máquina:
#  depois de um tempo parado, a primeira chamada leva de 5 a 20 SEGUNDOS (o
#  Strawberry demora a responder a consulta de propriedade pelo DBus) e as
#  seguintes voltam a 6ms. Com o timeout de 2s de antes, toda chamada fria
#  estourava e este módulo simplesmente não aparecia na barra — sem erro, sem
#  nada. Aqui esperar é barato: só uma consulta a cada poucos segundos, e o
#  desenho da barra não depende disto.
ASK_TIMEOUT = 12.0


def ask():
    """(status, position_seconds, url) or None when nothing is playing."""
    try:
        out = subprocess.run(
            ["playerctl", "--format", FMT, "metadata"],
            capture_output=True, text=True, timeout=ASK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    parts = out.stdout.strip("\n").split(SEP)
    if len(parts) != 3:
        return None
    status, pos, url = parts
    try:
        # playerctl reports position in microseconds.
        seconds = int(pos) / 1_000_000.0
    except ValueError:
        seconds = 0.0
    return status, seconds, url


def lrc_path_for(url):
    """The .lrc sitting next to the audio file this URL points at."""
    if not url.startswith("file://"):
        return None
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    base, _ = os.path.splitext(path)
    candidate = base + ".lrc"
    return candidate if os.path.isfile(candidate) else None


def load_lrc(path):
    """[(seconds, text)] sorted by time, or [] if there is nothing usable.

    Skips the metadata tags ([ar:], [ti:], [length:] …) by requiring the
    bracket contents to parse as a timestamp, and expands the multi-timestamp
    form - "[00:12.00][01:40.00] chorus line" is one line sung twice, and a
    repeated chorus is exactly the case where a lyric file is worth having.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return []

    lines = []
    for row in raw.splitlines():
        stamps = TS.findall(row)
        if not stamps:
            continue
        text = TS.sub("", row).strip()
        for mm, ss in stamps:
            try:
                at = int(mm) * 60 + float(ss.replace(":", "."))
            except ValueError:
                continue
            lines.append((at, text))
    lines.sort(key=lambda pair: pair[0])
    return lines


def line_at(lines, position):
    """The last lyric whose timestamp has passed. Binary search, because a
    long bootleg .lrc runs to several hundred entries and this is called three
    times a second."""
    lo, hi, found = 0, len(lines) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if lines[mid][0] <= position:
            found = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if found is None:
        return ""
    return lines[found][1]


def render(text):
    if not text:
        return ""
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1] + "…"
    # Quotation marks in the dim tone, the words a step brighter: the marks are
    # punctuation, not content, and at bar size a fully-flat grey run of words
    # is hard to tell apart from the window title on the other side.
    return "%%{F%s}“%%{F%s}%s%%{F%s}”" % (DIM, TEXT, text, DIM)


def main():
    lines = []
    known_url = None
    pos0 = 0.0
    t0 = time.monotonic()
    status = "Stopped"
    last_sync = 0.0
    last_out = None

    while True:
        now = time.monotonic()

        if now - last_sync >= SYNC_EVERY:
            last_sync = now
            info = ask()
            if info is None:
                status, known_url, lines = "Stopped", None, []
            else:
                status, pos0, url = info
                t0 = now
                if url != known_url:
                    known_url = url
                    path = lrc_path_for(url)
                    lines = load_lrc(path) if path else []

        if status == "Playing" and lines:
            position = pos0 + (time.monotonic() - t0)
            out = render(line_at(lines, position))
        elif status == "Paused" and lines:
            out = render(line_at(lines, pos0))
        else:
            out = ""

        if out != last_out:
            last_out = out
            sys.stdout.write(out + "\n")
            sys.stdout.flush()

        time.sleep(TICK)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
