"""
Build a playlist of everything added to the library in this session.

Rationale: dozens of albums landed at once. They're correctly filed by
artist/album, which means they're also invisible — scattered across a
2000-track library with no way to find "the new stuff". A dated playlist is
the difference between "music was added somewhere" and "here, press play".

Self-maintaining: rather than a hand-kept list of albums (which silently goes
stale the moment another batch downloads), this finds album folders whose
mtime is after a cutoff. Default cutoff is 07:00 today, which cleanly
separates the Qobuz work (started ~07:40) from the earlier phone sync
(~02:16-02:30) — that sync pulled files into EXISTING album folders and so
bumped their mtimes too, and those aren't new albums.

Deliberately does NOT touch the curated mood playlists (Suicidio, Shoegaze &
Dreampop, etc.) — those are hand-curated and Davi cares about getting them
exactly right, so auto-populating them would be presumptuous. This is purely
additive: a new file he can keep, rename, or delete.

Ordering is by artist → album → track number, so albums stay intact and in
intended sequence (he listens to albums in order, not shuffled).
"""
import os
import sys
import time
import datetime
from mutagen.flac import FLAC
from mutagen.id3 import ID3

from _raiz import raiz   # onde fica a coleção, decidido num lugar só

LIB = raiz()
# Era um subdiretório com o nome da coleção de uma pessoa; a coleção é a
# raiz configurada, seja qual for.
ROOT = LIB
AUDIO_EXT = (".flac", ".mp3")


def track_num(path):
    """Sort key from the filename's leading NN, falling back to tags."""
    base = os.path.basename(path)
    lead = base.split(" - ")[0].strip()
    if lead.isdigit():
        return int(lead)
    try:
        if path.lower().endswith(".flac"):
            t = FLAC(path).get("tracknumber", ["0"])[0]
        else:
            t = str(ID3(path).get("TRCK", "0"))
        return int(str(t).split("/")[0])
    except Exception:
        return 0


def main():
    """Read the manifest written by integrate_album.py.

    An earlier version inferred "new" from folder mtime, which is wrong here:
    a phone sync pulls files into EXISTING album folders and bumps their
    mtimes too, and those timestamps interleave with real download times, so
    no cutoff separates them. The integrator records what it actually added.
    """
    manifest = os.path.expanduser("~/.local/share/stylus-added.tsv")
    if not os.path.exists(manifest):
        print(f"no manifest at {manifest}")
        return

    seen = set()
    entries = []
    for line in open(manifest, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        date, artist, album = parts[0], parts[1], parts[2]
        if (artist, album) in seen:
            continue
        seen.add((artist, album))
        entries.append((artist, album))

    lines, found, missing = [], [], []
    for artist, album in sorted(entries):
        aldir = os.path.join(ROOT, artist, album)
        if not os.path.isdir(aldir):
            missing.append(f"{artist} - {album}")
            continue
        tracks = [os.path.join(aldir, f) for f in os.listdir(aldir)
                  if f.lower().endswith(AUDIO_EXT)]
        if not tracks:
            missing.append(f"{artist} - {album} (no audio)")
            continue
        tracks.sort(key=track_num)
        found.append((artist, album, len(tracks)))
        for t in tracks:
            lines.append(os.path.relpath(t, LIB))

    today = datetime.date.today()
    out = os.path.join(LIB, f"Novidades {today.isoformat()}.m3u")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {out}")
    print(f"  {len(found)} albums, {len(lines)} tracks")
    by_artist = {}
    for artist, album, n in found:
        by_artist.setdefault(artist, []).append(album)
    for artist in sorted(by_artist):
        print(f"    {artist}: {', '.join(sorted(by_artist[artist]))}")
    if missing:
        print(f"  missing ({len(missing)}): {missing}")


if __name__ == "__main__":
    main()
