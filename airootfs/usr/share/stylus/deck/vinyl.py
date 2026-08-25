#!/usr/bin/env python3
"""The record. Everything ritual-mode needs that isn't OpenGL.

WHY THIS EXISTS
---------------
scope.py is an instrument: it tells you what the signal is doing. An
instrument is not a listening ritual. A record player is — you commit to a
side, you look at an object while it plays, you can see how much is left
without reading a number, and halfway through you have to get up.

Ritual mode turns the visualiser into that object. This module holds all of
its non-GL parts so scope.py only gains the drawing glue:

  * Session   — what is playing, and exactly where in it we are. Prefers an
                mpv IPC socket (the `vinyl` launcher opens one, giving exact
                position and the whole album's running order); falls back to
                playerctl/MPRIS for Strawberry, VLC, browsers.
  * Album     — the local folder behind that track: running order, real
                durations, cover art, .lrc lyrics, and the LOUDNESS ENVELOPE
                of the whole record.
  * Deck      — the ceremony state machine (spin-up, cue, needle drop, play,
                side break, lift, spin-down).
  * geometry  — pure numpy builders for the disc, its grooves, the tonearm,
                the dust and scratches. All return arrays in the same shape
                scope.py's build_ribbon_strip already consumes, so nothing
                new has to be invented on the GL side.

THE ONE IDEA WORTH KNOWING
--------------------------
On a real LP you can SEE the music before you hear it. Loud passages cut a
wider groove and catch the light differently, so a record shows visible
bands, and the near-silent spiral between tracks shows as a bright thin
line — you can count the tracks on a record by eye, and see where the quiet
one is.

That is real data and we have the files on disk, so the record drawn here is
not decorative: every ring is the actual measured loudness of that moment of
the album, and every bright gap ring is an actual track boundary. Radius is
time. The tonearm sits at the radius for right now. Glancing at it tells you
how much side is left, the way a record does, without a number anywhere.
"""
import hashlib
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import threading
import time

import numpy as np

# ── real 12" LP proportions, as fractions of the 152mm outer radius ─────────
# Kept as real numbers rather than eyeballed ones because the proportions are
# most of what makes a drawn disc read as a record instead of a dartboard —
# in particular how much of the face the label takes (a third of the radius,
# which is much more than people draw from memory) and how far in the
# program area actually runs.
R_OUTER      = 1.000
R_LEADIN     = 0.962   # where the lead-in spiral starts
R_PROG_OUT   = 0.945   # first modulated groove
R_PROG_IN    = 0.395   # last modulated groove (60mm)
R_RUNOUT     = 0.360   # run-out / lock groove
R_LABEL      = 0.329   # label edge (50mm)
R_SPINDLE    = 0.024   # spindle hole (3.6mm)

RPM = 33.0 + 1.0 / 3.0
REV_PER_SEC = RPM / 60.0

# A side of a 12" LP holds about 22 minutes before the groove pitch has to
# get tight enough to hurt. Albums longer than that were pressed as doubles,
# so packing into <=22-minute sides and letting a long record become A/B/C/D
# is not a gimmick, it is what the object would actually be.
SIDE_MAX_SECONDS = 22 * 60

# Groove rings across the program area. 96 across ~380px of band on a 1600px
# screen is ~4px apart: fine enough to read as grooves rather than as a
# target, coarse enough that each ring still covers a chunk of time big
# enough for its loudness to mean something.
N_RINGS = 96

# Loudness envelope resolution. 8 Hz is far finer than one ring (a ring on a
# 22-minute side spans ~14s), so each ring gets a real distribution to reduce
# rather than a single sample, which is what lets a quiet intro inside a loud
# track still show up.
ENV_HZ = 8

# ═══════════════════════════════════════════════════════════════════════════
# Onde ficam as coisas
# ═══════════════════════════════════════════════════════════════════════════
# Num sistema, isto não pode ser o caminho da casa de quem escreveu. A ordem
# é: o que o usuário configurou, o que o sistema configurou, e por último os
# lugares onde uma coleção costuma estar. A primeira pasta da lista que
# EXISTE é a estante; as outras continuam servindo para achar um arquivo que
# está tocando de fora dela.
#
#   ~/.config/stylus/library    uma pasta por linha, a primeira é a estante
#   /etc/stylus/library         o mesmo, para a máquina inteira
#
# `stylus library` escreve o primeiro dos dois.

STATE_DIR = os.path.expanduser("~/.local/share/stylus")
CACHE_DIR = os.path.expanduser("~/.cache/stylus/envelopes")
SOCKET_PATH = os.path.join(STATE_DIR, "deck.sock")
_USER_LIBRARY_CONF = os.path.expanduser("~/.config/stylus/library")
_SYSTEM_LIBRARY_CONF = "/etc/stylus/library"
_FALLBACK_ROOTS = ("~/Music", "~/Músicas", "~/Musica", "~/Musique", "/srv/music")


def _read_library_conf(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [os.path.expanduser(ln.strip()) for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def music_roots():
    """As pastas onde procurar um disco, na ordem em que valem.

    STYLUS_LIBRARY na frente de tudo: serve para apontar para um HD externo
    por uma sessão só, e é como se testa isto sem escrever na configuração
    de ninguém.

    Relido a cada chamada de propósito: `stylus library` pode apontar para
    outro lugar com o deck já aberto, e ter que reiniciar o programa para
    trocar de estante seria ridículo num sistema cujo assunto é a estante.
    """
    out = []
    env = [p for p in (os.environ.get("STYLUS_LIBRARY") or "").split(os.pathsep) if p]
    for p in (env
              + _read_library_conf(_USER_LIBRARY_CONF)
              + _read_library_conf(_SYSTEM_LIBRARY_CONF)
              + [os.path.expanduser(p) for p in _FALLBACK_ROOTS]):
        p = os.path.normpath(p)
        if p not in out:
            out.append(p)
    return out


def library_root():
    """A estante: a primeira pasta configurada que existe de verdade."""
    roots = music_roots()
    for p in roots:
        if os.path.isdir(p):
            return p
    return roots[0] if roots else os.path.expanduser("~/Music")


def _configured_roots():
    """Só as pastas que ALGUÉM escolheu — sem os palpites.

    A diferença importa: `music_roots()` termina com `~/Music`, `~/Músicas`,
    `/srv/music` e companhia, que são chutes para a primeira execução. Varrer
    tudo isso como se fosse estante encheria a grade com o que houver em
    qualquer uma delas.
    """
    env = [p for p in (os.environ.get("STYLUS_LIBRARY") or "").split(os.pathsep) if p]
    return [os.path.normpath(p) for p in
            (env + _read_library_conf(_USER_LIBRARY_CONF)
                 + _read_library_conf(_SYSTEM_LIBRARY_CONF))]


def library_roots():
    """TODAS as estantes que existem agora, sem repetir.

    A coleção deixou de caber num lugar só. O `stylus webdav` monta o
    servidor do celular numa pasta e a acrescenta à configuração; antes disto
    ela era escrita, montada, e simplesmente ignorada — porque a estante só
    olhava para a PRIMEIRA pasta que existisse, e a primeira era a local.
    Uma pasta configurada que o sistema não varre é pior do que não ter
    configurado nada: a pessoa fez o que era para fazer e não aconteceu nada.

    Desduplica por caminho real, senão um link para a mesma pasta faz cada
    disco aparecer duas vezes na grade.
    """
    out, vistos = [], set()
    for p in _configured_roots():
        if not os.path.isdir(p):
            continue
        try:
            chave = os.path.realpath(p)
        except OSError:
            chave = p
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(p)
    if out:
        return out
    # Nada configurado ainda: vale o palpite, e só o primeiro que existir.
    r = library_root()
    return [r] if os.path.isdir(r) else []


class _Roots(list):
    """MUSIC_ROOTS continua sendo uma lista para quem já a usava, mas relê a
    configuração a cada iteração em vez de congelar o que valia na importação."""

    def __iter__(self):
        return iter(music_roots())

    def __len__(self):
        return len(music_roots())

    def __getitem__(self, i):
        return music_roots()[i]


MUSIC_ROOTS = _Roots()
AUDIO_EXT = (".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma")


# ═══════════════════════════════════════════════════════════════════════════
# Palette
# ═══════════════════════════════════════════════════════════════════════════
# Rich, vivid but physically correct for the additive phosphor buffer
# (blend GL_ONE/GL_ONE). Anything above ~0.35 blooms on screen, so the
# vinyl body stays in the hundredths to remain matte — otherwise the whole
# disc glows like a lamp and stops being an object. Grooves are brighter
# than before for punch and track-gap legibility, but kept below whiteout
# so the disc still reads as vinyl, not neon.
VINYL_CORE      = (0.012, 0.015, 0.022)   # deep black plastic — matte centre
VINYL_RIM       = (0.034, 0.042, 0.060)   # edge catches a touch more light
SHEEN           = (0.072, 0.088, 0.120)   # gloss lobes — more presence, still subtle
GROOVE_UNPLAYED = (0.098, 0.118, 0.160)   # ahead of needle: cold slate, darker
GROOVE_PLAYED   = (0.150, 0.380, 0.620)   # behind needle: vivid electric blue
GROOVE_GAP      = (0.360, 0.400, 0.520)   # track gaps: bright silver-blue, countable
STYLUS_HOT      = (0.740, 0.520, 0.140)   # live groove: hot amber, contrasts blue
ARM_METAL       = (0.300, 0.340, 0.400)   # brushed gunmetal — not glowing
ARM_HIGHLIGHT   = (0.560, 0.620, 0.720)   # highlight catches the sheen
EDGE_RING       = (0.200, 0.235, 0.310)   # outer edge / label rim
DUST            = (0.195, 0.220, 0.280)   # dust & fine scratches
ALARM           = (0.780, 0.250, 0.250)   # side break — urgent but not blown


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# ═══════════════════════════════════════════════════════════════════════════
# Where we are: mpv IPC first, MPRIS second
# ═══════════════════════════════════════════════════════════════════════════

class _MpvIPC:
    """Talks to the mpv the `vinyl` launcher started.

    Worth the extra path over just using playerctl for three reasons that
    matter here and nowhere else in this app: the position is exact rather
    than a once-a-second poll (the tonearm is a continuous physical thing and
    a 1Hz staircase is visible on it), the full running order is known up
    front instead of one track at a time (which is what lets sides exist at
    all), and pause/unpause is available so the side break can be a real
    stop rather than a caption claiming to be one.
    """

    def __init__(self, path=SOCKET_PATH):
        self.path = path
        self.sock = None
        self._rid = 0
        self._buf = b""

    def connect(self):
        if self.sock is not None:
            return True
        if not os.path.exists(self.path):
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.35)
            s.connect(self.path)
            self.sock = s
            self._buf = b""
            return True
        except Exception:
            self.sock = None
            return False

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def command(self, *args):
        if not self.connect():
            return None
        self._rid += 1
        rid = self._rid
        try:
            self.sock.sendall(
                (json.dumps({"command": list(args), "request_id": rid}) + "\n").encode()
            )
            deadline = time.time() + 0.35
            while time.time() < deadline:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                self._buf += chunk
                lines = self._buf.split(b"\n")
                self._buf = lines.pop()
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    # mpv interleaves unsolicited event messages with
                    # replies; only the one carrying our request_id answers
                    # the question we asked.
                    if msg.get("request_id") == rid:
                        return msg.get("data") if msg.get("error") == "success" else None
        except Exception:
            self.close()
        return None

    def get(self, prop):
        return self.command("get_property", prop)

    def set_pause(self, paused):
        return self.command("set_property", "pause", bool(paused))


class Session:
    """Polls "what is playing and where are we" on a background thread.

    Spawning playerctl costs tens of milliseconds and even the mpv socket
    round-trip is not free, so neither belongs on the render thread. The
    position returned to the renderer is EXTRAPOLATED between polls from the
    wall clock (see .position) — without that the tonearm advances in visible
    once-a-second steps, which instantly kills the illusion of a physical arm
    resting in a groove.
    """

    def __init__(self, poll_interval=0.5):
        self.mpv = _MpvIPC()
        self._have_playerctl = shutil.which("playerctl") is not None
        self._lock = threading.Lock()
        self._stop = False
        self.path = None
        self.artist = ""
        self.album = ""
        self.title = ""
        self.playlist = []      # absolute paths, in running order
        self.track_index = 0
        self.paused = True
        self.source = "none"    # "mpv" | "mpris" | "none"
        self._track_pos = 0.0   # position within the current TRACK
        self._track_dur = 0.0
        self._stamp = 0.0       # monotonic time that position was measured
        self.thread = threading.Thread(target=self._run, args=(poll_interval,), daemon=True)
        self.thread.start()

    # -- reading -----------------------------------------------------------
    def position(self):
        """(track_position_seconds, track_duration_seconds), extrapolated."""
        with self._lock:
            pos, dur, paused, stamp = self._track_pos, self._track_dur, self.paused, self._stamp
        if not paused and stamp:
            pos += max(0.0, time.monotonic() - stamp)
        if dur > 0:
            pos = min(pos, dur)
        return pos, dur

    def snapshot(self):
        with self._lock:
            return {
                "path": self.path, "artist": self.artist, "album": self.album,
                "title": self.title, "playlist": list(self.playlist),
                "track_index": self.track_index, "paused": self.paused,
                "source": self.source,
            }

    def pause(self, paused):
        """Only ever acts on a player we started ourselves. Reaching into
        someone else's Spotify because a drawn tonearm reached a drawn edge
        would be obnoxious; the side break falls back to visual-only there."""
        if self.source == "mpv":
            self.mpv.set_pause(paused)
            with self._lock:
                self.paused = bool(paused)
                self._stamp = time.monotonic()
            return True
        return False

    def close(self):
        self._stop = True
        self.mpv.close()

    # -- polling -----------------------------------------------------------
    def _run(self, interval):
        while not self._stop:
            if not self._poll_mpv():
                self._poll_mpris()
            time.sleep(interval)

    def _poll_mpv(self):
        if not self.mpv.connect():
            return False
        pos = self.mpv.get("time-pos")
        if pos is None:
            return False
        dur = self.mpv.get("duration") or 0.0
        path = self.mpv.get("path")
        idx = self.mpv.get("playlist-pos")
        paused = bool(self.mpv.get("pause"))
        count = self.mpv.get("playlist-count") or 0
        playlist = []
        # The running order only has to be read once; it does not change
        # mid-record, and asking for N filenames every half second would
        # dominate the poll.
        if count and len(self.playlist) != count:
            for i in range(int(count)):
                p = self.mpv.get(f"playlist/{i}/filename")
                if p:
                    playlist.append(p)
        with self._lock:
            self.source = "mpv"
            self._track_pos = float(pos)
            self._track_dur = float(dur)
            self._stamp = time.monotonic()
            self.paused = paused
            self.path = path
            self.track_index = int(idx or 0)
            if playlist:
                self.playlist = playlist
        return True

    # O playerctl NÃO responde sempre em milissegundos. Medido nesta máquina:
    # depois de um tempo parado, a primeira chamada leva de 5 a 20 SEGUNDOS
    # (o Strawberry demora a responder a consulta de propriedade pelo DBus),
    # e as seguintes voltam a levar 6ms. Com o timeout de 2s de antes, toda
    # chamada fria estourava, e o `except` zerava a fonte para "none" — então
    # o modo ritual e a barra simplesmente não achavam o disco que estava
    # tocando, sem erro nenhum à vista. Foi assim que o suporte a MPRIS
    # pareceu funcionar por meses sem nunca ter funcionado com o Strawberry.
    MPRIS_TIMEOUT = 12.0

    def _poll_mpris(self):
        if not self._have_playerctl:
            with self._lock:
                self.source = "none"
            return False
        try:
            status = subprocess.run(["playerctl", "status"], capture_output=True,
                                    text=True, timeout=self.MPRIS_TIMEOUT).stdout.strip()
            if status not in ("Playing", "Paused"):
                with self._lock:
                    self.source = "none"
                    self.paused = True
                return False
            fmt = "{{artist}}\t{{title}}\t{{album}}\t{{position}}\t{{mpris:length}}\t{{xesam:url}}"
            out = subprocess.run(["playerctl", "metadata", "--format", fmt],
                                 capture_output=True, text=True,
                                 timeout=self.MPRIS_TIMEOUT).stdout.strip()
            parts = (out.split("\t") + [""] * 6)[:6]
            artist, title, album, pos_s, len_s, url = parts

            def _us(v):
                try:
                    return float(v) / 1e6
                except (TypeError, ValueError):
                    return 0.0

            path = None
            if url.startswith("file://"):
                from urllib.parse import unquote
                path = unquote(url[len("file://"):])
            with self._lock:
                self.source = "mpris"
                self.artist, self.title, self.album = artist, title, album
                self._track_pos = _us(pos_s)
                self._track_dur = _us(len_s)
                self._stamp = time.monotonic()
                self.paused = (status == "Paused")
                self.path = path
                # O índice de faixa e a lista de reprodução são do MPV.
                # Sob MPRIS não existe lista — o playerctl entrega o arquivo
                # e mais nada — e deixar o número velho aqui é pior do que
                # não ter número: album_time soma o início de uma faixa que
                # não é esta, e o braço vai parar no lado errado do disco.
                # Quem consegue descobrir a faixa certa é quem tem o álbum
                # na mão, casando o caminho: RitualScene._track_index.
                self.playlist = []
                self.track_index = 0
            return True
        except subprocess.TimeoutExpired:
            # Uma consulta lenta não é "não há nada tocando". Mantém o último
            # estado bom: o braço continua onde estava até a próxima resposta,
            # que é muito melhor do que o disco sumir da tela por um segundo.
            return False
        except Exception:
            with self._lock:
                self.source = "none"
            return False


# ═══════════════════════════════════════════════════════════════════════════
# The album on disk: running order, sides, loudness, words
# ═══════════════════════════════════════════════════════════════════════════

_LRC_LINE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]\s*(.*)")


def parse_lrc(path):
    """.lrc -> [(seconds, text)] sorted. Blank lines are kept on purpose:
    they are the instrumental stretches, and dropping them leaves the last
    sung line hanging on screen through a two-minute outro."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LRC_LINE.match(line.strip())
                if not m:
                    continue
                mm, ss, text = m.groups()
                out.append((int(mm) * 60 + float(ss.replace(":", ".")), text.strip()))
    except Exception:
        return []
    out.sort(key=lambda x: x[0])
    return out


def _probe_duration(path):
    """A duração de uma faixa, do jeito mais barato que funcionar.

    O mutagen primeiro, o ffprobe depois. Não é micro-otimização: o deck mede
    TODA faixa do lado ao abrir, e um álbum de vinte faixas custava vinte
    processos ffprobe antes de a agulha descer — meio segundo de nada numa
    máquina rápida, um susto numa lenta. O mutagen lê o cabeçalho no mesmo
    processo, é dependência declarada (python-mutagen), e ainda faz o deck
    abrir sem o ffprobe instalado. O ffprobe fica como rede de segurança para
    o formato exótico que o mutagen não conhece.
    """
    try:
        import mutagen
        f = mutagen.File(path)
        if f is not None and f.info and f.info.length:
            return float(f.info.length)
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _track_sort_key(name):
    """Running order is the whole point of a record, so file order has to be
    right. Leading track numbers win; everything else falls back to name."""
    m = re.match(r"\s*(\d+)", os.path.basename(name))
    return (int(m.group(1)) if m else 10_000, os.path.basename(name).lower())


def track_paths(folder):
    """Os arquivos de áudio da pasta, na ordem do disco.

    É a MESMA lista que Album._scan usa, exposta para o lançador poder
    montar a lista do mpv com ela. Isso importa porque o índice de faixa que
    o mpv devolve é usado como índice em Album.tracks: se as duas listas não
    forem a mesma, o braço aponta para a faixa errada. Dando a PASTA ao mpv
    era o que acontecia — ele enfileira tudo, cover.jpg incluído, e ao chegar
    nela no fim do disco desiste e fecha, tendo antes reportado um índice que
    não existe em Album.tracks.

    Devolve [] se não houver áudio direto na pasta (álbum em Disc 01/Disc 02,
    que Album._scan também não lê), e aí quem chama volta a dar a pasta.
    """
    try:
        names = sorted((n for n in os.listdir(folder)
                        if n.lower().endswith(AUDIO_EXT)), key=_track_sort_key)
    except OSError:
        return []
    
    if names:
        return [os.path.join(folder, n) for n in names]
    
    # Sem áudio direto: procura em subdirs (Disc 01/Disc 02, por exemplo)
    # Coleta TODOS os áudios de TODOS os subdirs, na ordem de nome de subdir
    # e depois de arquivo. Assim Disc 1 vem antes de Disc 2, e as faixas estão
    # em ordem dentro de cada disco. Isto faz a lista do mpv bater com a do
    # Album._scan: ambos fazem a mesma varredura.
    try:
        subdirs = sorted(os.listdir(folder))
    except OSError:
        return []
    
    out = []
    for d in subdirs:
        subdir_path = os.path.join(folder, d)
        if not os.path.isdir(subdir_path):
            continue
        try:
            sub_names = sorted((n for n in os.listdir(subdir_path)
                               if n.lower().endswith(AUDIO_EXT)), 
                              key=_track_sort_key)
            out.extend(os.path.join(subdir_path, n) for n in sub_names)
        except OSError:
            continue
    
    return out


# ═══════════════════════════════════════════════════════════════════════════
# A memória do disco
# ═══════════════════════════════════════════════════════════════════════════
# Uma coleção de verdade tem memória. Você lembra vagamente que não põe
# aquele disco há muito tempo, e é essa lembrança que faz você tirá-lo da
# estante — um tocador digital não lembra de nada e por isso oferece sempre
# as mesmas dez coisas. O arquivo abaixo é essa memória: uma linha por vez
# que um ÁLBUM foi posto. Quem escreve são duas fontes de propósito — o
# módulo `album` da barra (que anota mesmo com o visualizador fechado) e,
# desde agora, a própria cerimônia quando a agulha desce (que anota mesmo
# com a barra fora do ar). A janela de cooldown é o que impede a mesma
# colocação de virar duas linhas.

PLAYS_TSV = os.path.join(STATE_DIR, "plays.tsv")
PLAY_COOLDOWN = 600.0


def _play_rows():
    try:
        with open(PLAYS_TSV, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 4:
                    try:
                        yield float(parts[0]), parts[3]
                    except ValueError:
                        continue
    except OSError:
        return


def play_history(folder):
    """(quantas vezes este disco foi posto, a primeira vez, a última)."""
    want = os.path.normpath(folder or "\0")
    stamps = [ts for ts, fold in _play_rows() if os.path.normpath(fold) == want]
    if not stamps:
        return 0, 0.0, 0.0
    return len(stamps), min(stamps), max(stamps)


def log_play(folder, artist="", album="", cooldown=PLAY_COOLDOWN):
    """Anota que este disco foi posto agora; devolve a contagem já com esta.

    Deduplica pela janela `cooldown` porque as duas fontes anotam a MESMA
    colocação com segundos de diferença: a barra quando o álbum muda, a
    cerimônia quando a agulha desce. Sem isso todo disco posto com a barra
    no ar contaria dobrado, e uma contagem que mente é pior do que contagem
    nenhuma — o `stylus record` sorteia puxando para os esquecidos, e
    um número inflado esconderia justamente o disco que ele deveria achar.
    """
    n, _first, last = play_history(folder)
    if n and (time.time() - last) < cooldown:
        return n
    try:
        os.makedirs(os.path.dirname(PLAYS_TSV), exist_ok=True)
        with open(PLAYS_TSV, "a", encoding="utf-8") as fh:
            fh.write(f"{int(time.time())}\t{artist}\t{album}\t{folder}\n")
    except OSError:
        return max(n, 1)
    return n + 1


_MESES = ("jan", "fev", "mar", "abr", "mai", "jun",
          "jul", "ago", "set", "out", "nov", "dez")


def play_banner(plays, first_played, fallback=""):
    """(esquerda, direita) para o canto no instante em que a agulha desce.

    Por extenso na primeira vez porque "1ª VEZ" é uma contagem e "PRIMEIRA
    VEZ" é um acontecimento — e é a segunda coisa que é verdade quando um
    disco entra na coleção. Da segunda em diante o que interessa não é o
    número sozinho, é há quanto tempo ele está com você.
    """
    if plays <= 1:
        return "PRIMEIRA VEZ", fallback
    dias = (time.time() - first_played) / 86400.0 if first_played else 0.0
    if dias < 1.0:
        return f"{plays}ª VEZ", fallback
    d = time.localtime(first_played)
    return f"{plays}ª VEZ", f"desde {d.tm_mday} de {_MESES[d.tm_mon - 1]}"


# ── a estante ──────────────────────────────────────────────────────────────
# A mesma noção de "o que conta como um DISCO" que o `stylus record` usa.
# Estava só lá dentro; mora aqui porque a cerimônia também precisa dela — o
# fim de um disco é exatamente o momento em que a pergunta "e agora qual?"
# aparece, e responder a ela é metade do que uma estante serve para fazer.

SHELF_MIN_TRACKS = 6
# Pasta de bootleg/show começa com data. São ótimas e não são "pôr um disco";
# misturá-las no sorteio faz sair mais fita de show do que álbum.
_DATED_FOLDER = re.compile(r"^\d{4}[-.]\d{2}")


def best_root(candidatos=None, profundidade=3):
    """Adivinha QUAL pasta é a estante, contando discos e não arquivos.

    O problema real: a coleção quase nunca está na raiz que a gente
    chutaria. Aqui ela está em ~/Músicas/Fortnite Balls/Artista/Álbum, então
    apontar para ~/Músicas encontra 19 discos e apontar um nível abaixo
    encontra 260. Um sistema de música que abre mostrando 19 de 260 discos
    parece quebrado e a pessoa não tem como saber por quê.

    O que conta como acerto é PASTA-FOLHA COM ÁUDIO DENTRO, que é a definição
    de disco usada em todo o resto — não arquivo solto, senão uma pasta de
    downloads plana ganha de uma coleção organizada.
    """
    if candidatos is None:
        candidatos = []
        for raiz in music_roots():
            if not os.path.isdir(raiz):
                continue
            candidatos.append(raiz)
            try:
                for n in sorted(os.listdir(raiz))[:40]:
                    p = os.path.join(raiz, n)
                    if os.path.isdir(p):
                        candidatos.append(p)
            except OSError:
                pass
    melhor, melhor_n = None, 0
    for c in candidatos:
        n = len(shelf(root=c, min_tracks=1))
        if n > melhor_n:
            melhor, melhor_n = c, n
    return melhor, melhor_n


def folder_names(folder):
    """(artista, disco) a partir do caminho — a mesma leitura que o Album faz."""
    folder = folder.rstrip(os.sep)
    return os.path.basename(os.path.dirname(folder)), os.path.basename(folder)


def shelf(root=None, artist=None, min_tracks=SHELF_MIN_TRACKS):
    """As pastas que contam como disco na estante.

    Sem `root`, varre TODAS as estantes configuradas — a local e a do celular
    montada pelo `stylus webdav`, por exemplo. Com `root`, varre só aquela,
    que é como as ferramentas que trabalham numa pasta específica chamam.
    """
    if root is None:
        raizes = library_roots()
        if len(raizes) != 1:
            out = []
            for r in raizes:
                out.extend(_shelf_one(r, artist, min_tracks))
            return out
        root = raizes[0]
    return _shelf_one(root, artist, min_tracks)


def _shelf_one(root, artist=None, min_tracks=SHELF_MIN_TRACKS):
    base = os.path.join(root, artist) if artist else root
    if not os.path.isdir(base):
        return []
    try:
        tops = [base] if artist else [os.path.join(root, d)
                                      for d in sorted(os.listdir(root))]
    except OSError:
        return []
    out = []
    for t in tops:
        if not os.path.isdir(t):
            continue
        try:
            entries = sorted(os.listdir(t))
        except OSError:
            continue
        for d in entries:
            p = os.path.join(t, d)
            if not os.path.isdir(p) or _DATED_FOLDER.match(d):
                continue
            try:
                n = sum(1 for f in os.listdir(p) if f.lower().endswith(AUDIO_EXT))
            except OSError:
                continue
            if n >= min_tracks:
                out.append(p)
    return out


def last_played():
    """{pasta: quando} — a última vez de cada disco, do registro."""
    out = {}
    for ts, fold in _play_rows():
        k = os.path.normpath(fold)
        if ts > out.get(k, 0.0):
            out[k] = ts
    return out


def draw_record(candidates=None, exclude=(), rng=None):
    """Sorteia um disco puxando para o que faz mais tempo que não toca.

    Não é "o mais esquecido de todos", é sorteio COM PESO: um disco novo na
    estante tem que ter chance de sair, e um que você ouviu ontem também — só
    bem menos. Sorteio puro devolve sempre o mesmo punhado de coisas e a
    estante inteira vira enfeite; "sempre o mais antigo" vira lista de
    tarefas. O meio-termo é o que parece escolher.
    """
    cands = list(candidates if candidates is not None else shelf())
    fora = {os.path.normpath(e) for e in exclude}
    cands = [c for c in cands if os.path.normpath(c) not in fora]
    if not cands:
        return None
    vistos = last_played()
    agora = time.time()
    pesos = []
    for d in cands:
        quando = vistos.get(os.path.normpath(d))
        dias = 400.0 if quando is None else max(0.0, (agora - quando) / 86400.0)
        pesos.append(1.0 + dias * dias)     # quadrático: o esquecimento pesa
    return (rng or random).choices(cands, weights=pesos, k=1)[0]


def record_seed(folder):
    """Um número estável por disco, para que cada um tenha as SUAS marcas.

    Com a semente fixa que estava aqui antes, a coleção inteira carregava os
    mesmos nove arranhões nos mesmos nove lugares — o oposto exato de ter
    objetos. Derivando do caminho da pasta, o risco que o seu Kid A tem
    perto da borda continua lá amanhã, e é dele.
    """
    h = hashlib.blake2s(os.path.normpath(folder or "?").encode("utf-8", "replace"),
                        digest_size=4).digest()
    return int.from_bytes(h, "big")


class Album:
    """One record: its running order, its sides, and its loudness.

    The envelope scan runs on a background thread because it decodes the
    whole album (about 0.15s per FLAC, so a couple of seconds for an LP) and
    the deck has to be on screen and spinning immediately. Until it lands the
    grooves are drawn flat, then they fill in with the real shape of the
    record. Cached per folder afterwards, so it only ever happens once.
    """

    def __init__(self, folder, envelope=True):
        """envelope=False lê só a estrutura (ordem, durações, lados, capa).

        A varredura de intensidade decodifica o álbum inteiro. Quem só quer
        saber "que lado é este e quanto falta para virar" — a barra do
        desktop, por exemplo — não precisa disso e não deve pagar por isso.
        """
        self.folder = folder
        self.artist, self.name = folder_names(folder)
        self.tracks = []        # [{path, title, duration, start}]
        self.total = 0.0
        self.sides = []         # [{label, start, end, tracks:[idx...]}]
        self.cover = None
        self.envelope = None    # (M,) float32 RMS at ENV_HZ, or None until ready
        self.env_ready = False
        self.year = ""
        # A história deste disco, lida uma vez na abertura: o desenho usa a
        # contagem para o desgaste e a semente para as marcas serem DELE.
        self.seed = record_seed(folder)
        self.plays, self.first_played, self.last_played = play_history(folder)
        self._lock = threading.Lock()
        self._scan()
        if envelope:
            threading.Thread(target=self._load_envelope, daemon=True).start()
        else:
            # A ESTRUTURA não é parte do envelope, embora o carregamento do
            # envelope a construísse de passagem. Sem isto, envelope=False
            # devolvia um álbum com faixas e total=0 e nenhum lado — inútil
            # justamente para quem só quer a estrutura. Custa um ffprobe por
            # faixa, não a decodificação do disco inteiro.
            self._measure_durations()
            self._build_sides()

    # -- structure ---------------------------------------------------------
    def _scan(self):
        try:
            names = sorted(
                (n for n in os.listdir(self.folder) if n.lower().endswith(AUDIO_EXT)),
                key=_track_sort_key)
        except Exception:
            names = []
        
        for n in names:
            p = os.path.join(self.folder, n)
            title = re.sub(r"^\s*\d+\s*[-._)]\s*", "", os.path.splitext(n)[0]).strip()
            self.tracks.append({"path": p, "title": title, "duration": 0.0, "start": 0.0})
        
        # Sem áudio direto: procura em subdirs (Disc 01/Disc 02)
        if not self.tracks:
            try:
                subdirs = sorted(os.listdir(self.folder))
            except OSError:
                subdirs = []
            
            for d in subdirs:
                subdir_path = os.path.join(self.folder, d)
                if not os.path.isdir(subdir_path):
                    continue
                try:
                    sub_names = sorted(
                        (n for n in os.listdir(subdir_path) 
                         if n.lower().endswith(AUDIO_EXT)),
                        key=_track_sort_key)
                    for n in sub_names:
                        p = os.path.join(subdir_path, n)
                        title = re.sub(r"^\s*\d+\s*[-._)]\s*", "", 
                                     os.path.splitext(n)[0]).strip()
                        self.tracks.append({"path": p, "title": title, 
                                          "duration": 0.0, "start": 0.0})
                except OSError:
                    continue
        
        for cand in ("cover.jpg", "cover.png", "folder.jpg", "front.jpg", "cover.jpeg"):
            p = os.path.join(self.folder, cand)
            if os.path.isfile(p):
                self.cover = p
                break
        if self.tracks:
            self._read_tags(self.tracks[0]["path"])

    def _read_tags(self, path):
        # mutagen primeiro, mesma razão de _probe_duration: um processo a menos
        # no caminho até a agulha descer, e o deck abre sem ffprobe.
        try:
            import mutagen
            f = mutagen.File(path, easy=True)
            t = getattr(f, "tags", None) or {}

            def first(*chaves):
                for c in chaves:
                    v = t.get(c)
                    if v:
                        return v[0] if isinstance(v, list) else v
                return ""
            nome = first("album")
            artista = first("albumartist", "album artist", "artist")
            ano = first("date", "year", "originaldate")
            if nome or artista or ano:
                self.name = nome or self.name
                self.artist = artista or self.artist
                self.year = str(ano)[:4]
                return
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format_tags=album,artist,album_artist,date", "-of", "json", path],
                capture_output=True, text=True, timeout=10)
            tags = {k.lower(): v for k, v in
                    (json.loads(r.stdout).get("format", {}).get("tags", {}) or {}).items()}
            self.name = tags.get("album") or self.name
            self.artist = tags.get("album_artist") or tags.get("artist") or self.artist
            self.year = (tags.get("date") or "")[:4]
        except Exception:
            pass

    def _measure_durations(self):
        t = 0.0
        for tr in self.tracks:
            tr["start"] = t
            tr["duration"] = _probe_duration(tr["path"])
            t += tr["duration"]
        self.total = t

    def _build_sides(self):
        """Pack the running order into <=22-minute sides at real track
        boundaries — a side never cuts a song in half, which is exactly the
        constraint that decided the running order of every album pressed to
        vinyl. Aims for even sides rather than filling A to the brim and
        leaving B with two songs on it."""
        if not self.tracks or self.total <= 0:
            self.sides = []
            return
        n_sides = max(1, math.ceil(self.total / SIDE_MAX_SECONDS))
        target = self.total / n_sides
        sides, cur, cur_start = [], [], 0.0
        for i, tr in enumerate(self.tracks):
            cur.append(i)
            end = tr["start"] + tr["duration"]
            remaining_sides = n_sides - len(sides)
            # Close this side when it has passed its share AND there is still
            # material left for every side after it.
            if (remaining_sides > 1
                    and (end - cur_start) >= target * 0.86
                    and (len(self.tracks) - i - 1) >= (remaining_sides - 1)):
                sides.append({"start": cur_start, "end": end, "tracks": cur})
                cur, cur_start = [], end
        if cur:
            sides.append({"start": cur_start, "end": self.total, "tracks": cur})
        for i, s in enumerate(sides):
            s["label"] = "SIDE " + chr(ord("A") + i)
        self.sides = sides

    def side_for(self, t):
        for i, s in enumerate(self.sides):
            if t < s["end"] - 1e-6:
                return i, s
        if self.sides:
            return len(self.sides) - 1, self.sides[-1]
        return 0, {"label": "SIDE A", "start": 0.0, "end": max(1.0, self.total), "tracks": []}

    def track_for(self, t):
        for i, tr in enumerate(self.tracks):
            if t < tr["start"] + tr["duration"] - 1e-6:
                return i
        return max(0, len(self.tracks) - 1)

    def album_time(self, track_index, track_pos):
        if 0 <= track_index < len(self.tracks):
            return self.tracks[track_index]["start"] + track_pos
        return track_pos

    # -- loudness ----------------------------------------------------------
    def _cache_key(self):
        h = hashlib.sha1()
        h.update(self.folder.encode("utf-8", "replace"))
        for tr in self.tracks:
            try:
                st = os.stat(tr["path"])
                h.update(f"{tr['path']}:{st.st_size}:{int(st.st_mtime)}".encode("utf-8", "replace"))
            except OSError:
                pass
        return h.hexdigest()[:16]

    def _load_envelope(self):
        try:
            self._measure_durations()
            self._build_sides()
            if not self.tracks:
                return
            os.makedirs(CACHE_DIR, exist_ok=True)
            cache = os.path.join(CACHE_DIR, self._cache_key() + ".npy")
            if os.path.isfile(cache):
                env = np.load(cache)
            else:
                env = self._scan_envelope()
                if env is not None and len(env):
                    try:
                        np.save(cache, env)
                    except Exception:
                        pass
            with self._lock:
                self.envelope = env
                self.env_ready = env is not None and len(env) > 0
        except Exception:
            with self._lock:
                self.env_ready = False

    def _scan_envelope(self):
        """RMS of the whole record at ENV_HZ, tracks laid end to end.

        Decoding to mono at ENV_HZ*64 and reducing in numpy is enough: this
        is a picture of where the loud parts are, not a mastering tool. A
        whole album costs a couple of seconds because FLAC decode is fast and
        the resample throws away almost everything.
        """
        rate = ENV_HZ * 64
        chunks = []
        for tr in self.tracks:
            try:
                r = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", tr["path"], "-ac", "1",
                     "-ar", str(rate), "-f", "f32le", "-"],
                    capture_output=True, timeout=120)
                x = np.frombuffer(r.stdout, dtype=np.float32)
            except Exception:
                x = np.zeros(0, dtype=np.float32)
            n_out = max(1, int(round(tr["duration"] * ENV_HZ)) if tr["duration"] else len(x) // 64)
            if len(x) < n_out * 64:
                x = np.pad(x, (0, n_out * 64 - len(x)))
            block = x[: n_out * 64].reshape(n_out, 64)
            chunks.append(np.sqrt((block.astype(np.float64) ** 2).mean(axis=1)).astype(np.float32))
        if not chunks:
            return None
        env = np.concatenate(chunks)
        peak = float(np.percentile(env, 99.5)) or 1.0
        return np.clip(env / peak, 0.0, 1.4).astype(np.float32)

    def envelope_snapshot(self):
        with self._lock:
            return self.envelope if self.env_ready else None

    # -- words -------------------------------------------------------------
    def lyrics_for(self, track_index):
        if not (0 <= track_index < len(self.tracks)):
            return []
        tr = self.tracks[track_index]
        if "lrc" not in tr:
            base = os.path.splitext(tr["path"])[0]
            tr["lrc"] = parse_lrc(base + ".lrc") if os.path.isfile(base + ".lrc") else []
        return tr["lrc"]


def track_index_for(album, snap, cache=None):
    """Qual faixa do ÁLBUM está tocando agora.

    Com o mpv o número já vem certo: o lançador monta a lista com a mesma
    track_paths() que o Album lê, então os dois índices são o mesmo por
    construção. Sob MPRIS não existe lista nenhuma — o playerctl entrega o
    arquivo e o Session não tem como numerá-lo.

    O que havia ali antes era o índice VELHO deixado por uma sessão de mpv
    anterior. Efeito prático no Strawberry, que é o tocador que ele usa de
    verdade: album_time somava o começo de uma faixa que não era esta, então
    o braço apontava para outro ponto do disco e a letra na tela era de outra
    música. Casar o caminho contra as faixas resolve exatamente, e é o que
    faz o modo ritual ser exato fora do mpv.

    `cache` é uma lista de dois [caminho, índice] para não varrer as faixas a
    cada quadro; a busca em si é barata, mas 60 vezes por segundo não é.
    """
    idx = snap.get("track_index", 0) or 0
    if album is None or snap.get("source") == "mpv":
        return idx
    p = snap.get("path") or ""
    if p:
        if cache is not None and cache[0] == p:
            return cache[1]
        want = os.path.normpath(p)
        for i, t in enumerate(album.tracks):
            if os.path.normpath(t.get("path", "")) == want:
                if cache is not None:
                    cache[0], cache[1] = p, i
                return i
    return idx if 0 <= idx < len(album.tracks) else 0


def resolve_album(path=None, artist="", album=""):
    """Find the folder this record lives in.

    A local file answers it outright — the folder containing the track IS the
    album, which is how the library is laid out. Otherwise (Spotify, a
    browser) fall back to matching artist/album names against the library, so
    a streamed record still gets its real running order and loudness if the
    files happen to be owned too.
    """
    if path and os.path.isfile(path):
        folder = os.path.dirname(os.path.abspath(path))
        if any(n.lower().endswith(AUDIO_EXT) for n in os.listdir(folder)):
            return folder
    if not album:
        return None
    want_a, want_al = _norm(artist), _norm(album)
    for root in MUSIC_ROOTS:
        if not os.path.isdir(root):
            continue
        try:
            for artist_dir in os.listdir(root):
                ap = os.path.join(root, artist_dir)
                if not os.path.isdir(ap):
                    continue
                if want_a and _norm(artist_dir) != want_a and want_a not in _norm(artist_dir):
                    continue
                for album_dir in os.listdir(ap):
                    if _norm(album_dir) == want_al:
                        return os.path.join(ap, album_dir)
        except OSError:
            continue
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ═══════════════════════════════════════════════════════════════════════════
# Geometry — everything below is pure numpy, returns NDC ready for
# build_ribbon_strip, and is unit-testable without a window.
# ═══════════════════════════════════════════════════════════════════════════

def _polar(cx, cy, r, theta, iso):
    """Record space -> NDC. `r` is in units of the record's outer radius,
    `theta` is measured clockwise from 12 o'clock, because that is the
    direction a record turns and it makes every angle in this file read the
    same way as the thing it draws."""
    a = np.pi / 2.0 - theta
    return np.stack([cx + np.cos(a) * r * iso[0],
                     cy + np.sin(a) * r * iso[1]], axis=-1).astype(np.float32)


def sheen_gain(theta, light_angle, strength=1.0):
    """Two soft highlight lobes 180 degrees apart, fixed in SCREEN space.

    A glossy black disc lit by one broad source shows exactly this: two
    opposed sheens, and they stay put while the record turns under them.
    Getting that right is most of why the disc reads as a physical object and
    not as a flat circle — a uniformly shaded disc looks like a hole.
    """
    d = (theta - light_angle + np.pi) % (2.0 * np.pi) - np.pi
    d2 = (theta - light_angle + np.pi / 2.0) % np.pi - np.pi / 2.0
    del d
    return 1.0 + strength * np.exp(-(d2 ** 2) / 0.075)


def disc_body(cx, cy, radius, iso, light_angle, n=256, rings=(0.0, 0.34, 0.62, 0.86, 1.0)):
    """The black plastic. Concentric annuli as triangle strips.

    Returned in the same 7-float vertex layout build_ribbon_strip emits
    ([x, y, r, g, b, a, edge]) with edge pinned to 0, which RIBBON_FS reads
    as "dead centre of the stroke" and therefore renders at full, flat
    colour — so filled areas and strokes can share one shader and one buffer
    without adding a second pipeline.
    """
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=True)
    gain = sheen_gain(theta, light_angle)
    out = []
    for r0, r1 in zip(rings[:-1], rings[1:]):
        p0 = _polar(cx, cy, r0 * radius, theta, iso)
        p1 = _polar(cx, cy, r1 * radius, theta, iso)
        c0 = np.array(_lerp(VINYL_CORE, VINYL_RIM, r0), dtype=np.float32)
        c1 = np.array(_lerp(VINYL_CORE, VINYL_RIM, r1), dtype=np.float32)
        # sheen only really shows on the outer half, like it does on a record
        s0 = np.array(SHEEN, dtype=np.float32) * max(0.0, r0 - 0.25) / 0.75
        s1 = np.array(SHEEN, dtype=np.float32) * max(0.0, r1 - 0.25) / 0.75
        v = np.empty((2 * n, 7), dtype=np.float32)
        v[0::2, 0:2] = p0
        v[1::2, 0:2] = p1
        v[0::2, 2:5] = c0[None, :] + s0[None, :] * (gain[:, None] - 1.0)
        v[1::2, 2:5] = c1[None, :] + s1[None, :] * (gain[:, None] - 1.0)
        v[:, 5] = 1.0
        v[:, 6] = 0.0
        out.append(v)
    return out


def _ring_time(i, n_rings, side_start, side_end):
    """Ring index -> moment of the side. Outermost ring is the start, exactly
    as the needle finds it."""
    f = i / max(1, n_rings - 1)
    return side_start + f * (side_end - side_start)


def groove_rings(cx, cy, radius, iso, side, envelope, tracks, light_angle,
                 n_rings=N_RINGS, played_ring=-1, half_width=0.85):
    """The record's face: radius is time, brightness is loudness.

    Each ring covers a slice of the side and is shaded by the real measured
    RMS over that slice (peak-weighted, so a short loud passage is not
    averaged into invisibility). A ring whose slice contains a track boundary
    is drawn as the near-silent lead-out spiral instead — bright and thin —
    which is what lets you count the songs on the disc by eye.

    played_ring is the outermost ring the needle has NOT yet reached; rings
    outside it are lit, rings inside it are still cold slate. Progress
    therefore advances groove by groove rather than as a sliding bar, which
    is both what a record does and, deliberately, not a number.
    """
    strips = []
    s_start, s_end = side["start"], side["end"]
    span = max(1e-6, (s_end - s_start) / max(1, n_rings - 1))
    boundaries = [t["start"] for t in tracks[1:]] if tracks else []
    for i in range(n_rings):
        f = i / max(1, n_rings - 1)
        r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
        t = _ring_time(i, n_rings, s_start, s_end)
        is_gap = any(abs(b - t) <= span * 0.5 for b in boundaries)

        loud = 0.55
        if envelope is not None and len(envelope):
            lo = int(max(0, (t - span * 0.5) * ENV_HZ))
            hi = int(min(len(envelope), (t + span * 0.5) * ENV_HZ + 1))
            if hi > lo:
                seg = envelope[lo:hi]
                loud = float(0.45 * seg.mean() + 0.55 * seg.max())
        # sqrt keeps quiet-but-present music visible instead of crushing it
        # to black, the same reason meters are not linear.
        shade = 0.28 + 0.85 * math.sqrt(max(0.0, min(1.4, loud)))

        played = i < played_ring
        base = GROOVE_PLAYED if played else GROOVE_UNPLAYED
        if is_gap:
            base = GROOVE_GAP
            # Mais brilho que qualquer outra faixa: a separação precisa ser
            # vista de longe para que se possa contar as faixas de olho,
            # especialmente a 33⅓ numa tela distante.
            shade = 1.3

        n = int(np.clip(radius * r * 900, 96, 384))
        theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=True)
        pts = _polar(cx, cy, r * radius, theta, iso)
        gain = sheen_gain(theta, light_angle, strength=0.55)
        cols = np.empty((n, 4), dtype=np.float32)
        cols[:, 0:3] = np.array(base, dtype=np.float32)[None, :] * (shade * gain)[:, None]
        cols[:, 3] = 1.0
        # Faixa de separação entre faixas: fina e clara, como a espiral
        # muda-na-cauda de um disco real. No mundo real a agulha pula de
        # um sulco para o outro aqui; na tela isto é o que permite CONTAR
        # as faixas de olho.
        w = 0.18 if is_gap else half_width * (0.75 + 0.45 * min(1.0, loud))
        strips.append((pts, cols, w))
    return strips


def boundary_ring(cx, cy, radius, iso, side, envelope, frac, light_angle,
                  n_rings=N_RINGS, half_width=0.85):
    """The one ring the needle is inside right now, lit only as far around as
    the record has actually turned since it entered this groove. Without it
    progress jumps a whole ring at a time (~14 seconds) and the disc reads as
    a stepped gauge instead of a moving object."""
    i = int(np.clip(frac * (n_rings - 1), 0, n_rings - 1))
    sub = frac * (n_rings - 1) - i
    f = i / max(1, n_rings - 1)
    r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
    n = int(np.clip(radius * r * 900, 96, 384))
    cut = int(np.clip(sub, 0.0, 1.0) * (n - 1))
    if cut < 2:
        return None
    theta = np.linspace(0.0, 2.0 * np.pi * (cut / (n - 1)), cut)
    pts = _polar(cx, cy, r * radius, theta, iso)
    gain = sheen_gain(theta, light_angle, strength=0.55)
    cols = np.empty((cut, 4), dtype=np.float32)
    cols[:, 0:3] = np.array(GROOVE_PLAYED, dtype=np.float32)[None, :] * gain[:, None]
    cols[:, 3] = 1.0
    return pts, cols, half_width * 1.05


def live_groove(cx, cy, radius, iso, frac, mid, side_signal, rotation,
                n_rings=N_RINGS, arc=2.6, half_width=1.05, depth=0.0048):
    """The groove being read RIGHT NOW, modulated by the live waveform.

    This is where the oscilloscope actually lives in ritual mode, and it is
    not a decoration bolted onto a record — it is the same measurement, drawn
    in the record's own coordinates. A stereo groove is cut with the two
    channels on walls at +/-45 degrees, which means the SUM of the channels
    moves the cutting head sideways (the groove wanders in radius) and the
    DIFFERENCE moves it up and down (the groove gets deeper and shallower,
    which on a played record shows as the wall catching more or less light).

    So: mid displaces the arc radially, side brightens it. Both are real; a
    mono passage draws a steady bright wander, a wide stereo one shimmers.
    The arc trails behind the stylus over roughly the last half revolution
    and fades out, because that is how far back you can still see the groove
    the needle just came out of.
    """
    if mid is None or len(mid) < 8:
        return None
    i = frac * (n_rings - 1)
    f = i / max(1, n_rings - 1)
    r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
    n = len(mid)
    # theta runs backwards from the stylus: the newest sample sits under the
    # needle and older ones trail away in the direction the disc came from.
    theta = rotation + np.linspace(0.0, arc, n)[::-1]
    m = np.asarray(mid, dtype=np.float32)
    s = np.asarray(side_signal, dtype=np.float32) if side_signal is not None else np.zeros(n, np.float32)
    peak = float(np.max(np.abs(m))) or 1e-6
    m = m / max(peak, 0.08)
    s_peak = float(np.max(np.abs(s))) or 1e-6
    s_norm = np.clip(np.abs(s) / max(s_peak, 0.08), 0.0, 1.0)
    m_abs = np.clip(np.abs(m), 0.0, 1.0)
    # groove wanders with the MUSIC (signed), stereo widens the excursion
    # depth 0.0048 is ~50% more visible than original 0.0032 but not cartoonish
    rr = (r + m * depth * (1.0 + 0.28 * s_norm)) * radius
    pts = _polar(cx, cy, rr, theta, iso)
    fade = np.linspace(1.0, 0.04, n) ** 1.65
    # brightness: trail fades, stereo shimmers, loudness gives a subtle pulse
    bright = fade * (0.48 + 0.72 * s_norm) * (0.82 + 0.18 * m_abs)
    cols = np.empty((n, 4), dtype=np.float32)
    cols[:, 0:3] = np.array(STYLUS_HOT, dtype=np.float32)[None, :] * bright[:, None]
    cols[:, 3] = 1.0
    widths = half_width * (0.32 + 0.68 * fade)
    return pts, cols, widths


def edge_and_label_rings(cx, cy, radius, iso, light_angle, n=384):
    """The disc's outer edge and the label's edge — the two hard lines that
    tell you where the object stops."""
    out = []
    for r, col, w in ((R_OUTER, EDGE_RING, 1.5),
                      (R_LEADIN, EDGE_RING, 0.7),
                      (R_RUNOUT, EDGE_RING, 0.7),
                      (R_LABEL, EDGE_RING, 1.0)):
        theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=True)
        pts = _polar(cx, cy, r * radius, theta, iso)
        gain = sheen_gain(theta, light_angle, strength=0.8)
        cols = np.empty((n, 4), dtype=np.float32)
        cols[:, 0:3] = np.array(col, dtype=np.float32)[None, :] * gain[:, None]
        cols[:, 3] = 1.0
        out.append((pts, cols, w))
    return out


def wear_counts(plays):
    """Quantas marcas um disco carrega depois de ser posto `plays` vezes.

    Logarítmico e não linear porque é assim que desgaste é percebido: a
    diferença entre nunca ter tocado e ter tocado três vezes é enorme, entre
    trinta e quarenta não existe. E o piso nunca é zero — disco lacrado
    também tem poeira, e uma superfície perfeitamente limpa não lê como
    nova, lê como renderizada.
    """
    k = math.log2(1.0 + max(0, int(plays)))
    return (int(min(14, round(2 + 3.2 * k))),
            int(min(120, round(22 + 14.0 * k))))


def wear_marks(cx, cy, radius, iso, rotation, seed=7, n_scratch=None,
               n_dust=None, plays=0, crackle=0.0):
    """Scratches and dust, fixed to the disc so they turn with it.

    Two jobs. Honest one: a record that has been played has marks on it, and
    imperfection is most of what separates an object you own from a rendered
    circle. Practical one: a perfect circle rotating looks completely static,
    so without something asymmetric on the face there is no visual evidence
    the platter is turning at all.

    `seed` é a IDENTIDADE do disco (ver record_seed) e `plays` é a sua
    HISTÓRIA (ver play_history). Antes as duas eram constantes, e o efeito
    era que a coleção inteira tinha a mesma cara: os mesmos nove arranhões
    nos mesmos nove lugares em todo disco, novo ou surrado. Agora o disco que
    você põe toda semana acumula marcas, o que ficou na estante não, e as de
    cada um são só dele — que é a diferença entre uma pilha de arquivos e uma
    coleção com objetos dentro.

    `crackle` (0..1) é o estalo da agulha encostando. O campo já existia no
    Deck, era zerado e decaído todo quadro e NINGUÉM o desenhava. Vale
    mostrar porque é a única parte do ritual que acontece antes da música: o
    meio segundo de ruído de superfície entre a agulha tocar o disco e a
    primeira nota sair.
    """
    auto_scratch, auto_dust = wear_counts(plays)
    n_scratch = auto_scratch if n_scratch is None else n_scratch
    n_dust = auto_dust if n_dust is None else n_dust
    rng = np.random.default_rng(seed)
    glow = 1.0 + 2.2 * crackle
    segs, cols = [], []
    for _ in range(n_scratch):
        r0 = rng.uniform(R_RUNOUT + 0.02, R_OUTER - 0.02)
        a0 = rng.uniform(0, 2 * np.pi)
        span = rng.uniform(0.05, 0.30)
        k = 12
        theta = rotation + a0 + np.linspace(0, span, k)
        rr = r0 + rng.uniform(-0.004, 0.004) * np.linspace(0, 1, k)
        p = _polar(cx, cy, rr * radius, theta, iso)
        b = rng.uniform(0.35, 1.0) * glow
        for j in range(k - 1):
            segs.append(p[j])
            segs.append(p[j + 1])
            cols.append([DUST[0] * b, DUST[1] * b, DUST[2] * b, 1.0])
    for _ in range(n_dust):
        r0 = rng.uniform(R_SPINDLE, R_OUTER)
        a0 = rng.uniform(0, 2 * np.pi)
        theta = rotation + a0 + np.array([0.0, 0.006])
        p = _polar(cx, cy, r0 * radius, theta, iso)
        b = rng.uniform(0.15, 0.6) * glow
        segs.append(p[0])
        segs.append(p[1])
        cols.append([DUST[0] * b, DUST[1] * b, DUST[2] * b, 1.0])
    # A rajada do estalo, na cor da agulha porque é ruído DELA. Sorteada de
    # novo a cada quadro de propósito: ruído de superfície que não cintila
    # não é estalo, é sujeira desenhada. Fica na faixa de entrada, que é
    # onde a agulha acabou de encostar.
    if crackle > 0.02:
        pop = np.random.default_rng()
        for _ in range(int(90 * crackle)):
            r0 = pop.uniform(R_PROG_OUT - 0.03, R_OUTER)
            a0 = pop.uniform(0.0, 2.0 * np.pi)
            theta = rotation + a0 + np.array([0.0, 0.010])
            p = _polar(cx, cy, r0 * radius, theta, iso)
            b = pop.uniform(0.4, 1.4) * crackle
            segs.append(p[0])
            segs.append(p[1])
            cols.append([STYLUS_HOT[0] * b, STYLUS_HOT[1] * b,
                         STYLUS_HOT[2] * b, 1.0])
    if not segs:
        return None
    return np.array(segs, dtype=np.float32), np.array(cols, dtype=np.float32)


# ── tonearm ────────────────────────────────────────────────────────────────
# Real 9-inch arm geometry, in units of the record's outer radius (152mm):
# effective length pivot->stylus 230mm, mounting distance spindle->pivot
# 212mm (the 18mm difference is the overhang that makes the stylus reach
# past the spindle, which is why a tonearm can track all the way to the
# run-out). Using the real numbers rather than guessed ones is what gives the
# arm its correct, slightly awkward sweep — a made-up pivot makes it swing
# like a windscreen wiper.
ARM_LENGTH = 230.0 / 152.0
ARM_MOUNT = 212.0 / 152.0
ARM_PIVOT_ANGLE = math.radians(42.0)   # clockwise from 12 o'clock: rear right
# Onde a agulha para quando o braço está no alto.
#
# A nota antiga aqui dizia que o conserto certo seria trocar de ramo do
# triângulo ao estacionar. MEDIDO, e é falso: com este pivô (212mm, 42° a
# partir das 12h) o outro ramo estaciona a agulha em theta 116°, do outro
# lado do eixo, e QUALQUER caminho contínuo entre os dois ramos passa por
# s=0 — o braço apontando direto para o eixo, com a cabeça em cima do
# RÓTULO. Não existe caminho não-cruzante entre os dois; a única saída pelo
# ramo de tocar seria r>=1.5, e aí a cabeça sai por cima do quadro.
#
# Então o descanso continua neste ramo, mas mais para fora do que estava
# (era R_OUTER+0.07). Dois motivos, e o segundo é o que importa: a 1.07 a
# agulha parada ficava a 3 GRAUS da faixa de entrada, então o CUE — 1,7s de
# cerimônia inteiros — era um tremor invisível. A 1.26 são ~8°, e a saída
# do braço até o disco vira um movimento que dá para ver. O primeiro motivo
# é que 26% além da borda lê como fora do disco, e 7% lê como quase caindo
# dentro dele.
#
# O que faz isso parar de ser "pairando sem explicação" é o berço desenhado
# em arm_rest(): um toca-discos tem um descanso, e agora este tem.
ARM_REST_RADIUS = 1.26


def arm_angle_for_radius(r):
    """Solve for the arm's swing so the stylus lands at radius r.

    Plain version of the maths: the spindle, the arm's pivot, and the stylus
    make a triangle whose three side lengths we know — spindle-to-pivot is
    fixed by where the arm is bolted down, pivot-to-stylus is the arm's own
    length, and spindle-to-stylus is the radius we want. Knowing all three
    sides fixes every angle in the triangle (law of cosines), so there is
    exactly one way the arm can be pointing. That is the whole calculation.
    """
    r = max(0.02, min(r, ARM_MOUNT + ARM_LENGTH - 0.02))
    cosang = (ARM_MOUNT ** 2 + ARM_LENGTH ** 2 - r ** 2) / (2.0 * ARM_MOUNT * ARM_LENGTH)
    return math.acos(max(-1.0, min(1.0, cosang)))


def stylus_xy(cx, cy, radius, iso, stylus_radius, lift=0.0):
    """(pivô, ponta da agulha) em NDC, para o raio pedido.

    Separado do tonearm porque o berço precisa saber exatamente onde o braço
    para, e a única resposta que não mente é a mesma conta que desenha o
    braço. Duplicar a fórmula seria pedir para o berço sair de lugar na
    primeira vez que a geometria mudasse.
    """
    pv = _polar(cx, cy, ARM_MOUNT * radius, np.array([ARM_PIVOT_ANGLE]), iso)[0]
    ang = arm_angle_for_radius(stylus_radius)
    # Direction from the pivot back toward the spindle, then swung out by the
    # angle solved above. Sign chosen so the arm sweeps inward (toward the
    # label) as the record plays, which is the direction a real one goes.
    base = math.atan2(cy - pv[1], (cx - pv[0]) / max(1e-6, iso[0]) * iso[1])
    swing = base - ang
    sx = pv[0] + math.cos(swing) * ARM_LENGTH * radius * iso[0]
    sy = pv[1] + math.sin(swing) * ARM_LENGTH * radius * iso[1]
    push = 1.0 + lift * 0.045
    return pv, (pv[0] + (sx - pv[0]) * push, pv[1] + (sy - pv[1]) * push)


def arm_rest(cx, cy, radius, iso):
    """O berço em que o braço pousa quando não está tocando.

    Um braço levantado e parado no ar, sem nada embaixo, lê como um defeito
    de desenho — foi assim que a virada de lado apareceu na primeira vez.
    Com o berço no ponto onde ele realmente para (mesma stylus_xy que
    desenha o braço, então os dois não têm como divergir), a mesma pose
    passa a ler como pousado. É também mais um objeto no deck, que é o
    ponto: o ritual mora nos objetos.
    """
    pv, s = stylus_xy(cx, cy, radius, iso, ARM_REST_RADIUS, lift=1.0)
    ux, uy = s[0] - pv[0], s[1] - pv[1]
    ln = math.hypot(ux, uy) or 1.0
    ux, uy = ux / ln, uy / ln
    nx, ny = -uy, ux
    dim = tuple(v * 0.95 for v in ARM_METAL)
    hi = tuple(v * 0.95 for v in ARM_HIGHLIGHT)
    segs, cols = [], []

    def seg(a, b, color):
        segs.append(np.array(a, dtype=np.float32))
        segs.append(np.array(b, dtype=np.float32))
        cols.append([color[0], color[1], color[2], 1.0])

    # Uma forquilha em U que ABRE para o lado do pivô: as duas hastes
    # ladeiam a cabeça e a travessa é onde ela encosta. A primeira versão
    # tinha as hastes para o outro lado e o U ficava inteiro além da ponta
    # do braço, sem nada dentro — de fora lia como uma caixinha solta
    # flutuando, não como um descanso segurando alguma coisa.
    w = 0.050 * radius            # meia-largura, folgada em volta da cabeça
    d = 0.085 * radius            # o quanto as hastes recuam ladeando o braço
    c = (s[0] + ux * 0.030 * radius, s[1] + uy * 0.030 * radius)
    a1 = (c[0] + nx * w, c[1] + ny * w)
    a2 = (c[0] - nx * w, c[1] - ny * w)
    seg(a1, a2, hi)                                       # a travessa
    seg(a1, (a1[0] - ux * d, a1[1] - uy * d), dim)        # as hastes
    seg(a2, (a2[0] - ux * d, a2[1] - uy * d), dim)
    # o pé, visto de cima: fora do U, do lado de fora da travessa
    th = np.linspace(0.0, 2.0 * np.pi, 13)
    foot = (c[0] + ux * 0.034 * radius, c[1] + uy * 0.034 * radius)
    pc = _polar(foot[0], foot[1], 0.019 * radius, th, iso)
    for j in range(len(th) - 1):
        seg(pc[j], pc[j + 1], dim)
    seg(c, foot, dim)
    return np.array(segs, dtype=np.float32), np.array(cols, dtype=np.float32)


def tonearm(cx, cy, radius, iso, stylus_radius, lift=0.0):
    """Arm tube, headshell, counterweight, pivot — as disconnected segments.

    lift in [0,1] raises the arm off the record. There is no third dimension
    here, so the cue is done the way a shadow-less top-down view can do it:
    the arm brightens and shifts very slightly outward, the way something
    lifting toward the light does, and the stylus contact point goes out.
    """
    pv, (sx, sy) = stylus_xy(cx, cy, radius, iso, stylus_radius, lift)

    segs, cols = [], []

    def seg(a, b, color, reps=1):
        for _ in range(reps):
            segs.append(np.array(a, dtype=np.float32))
            segs.append(np.array(b, dtype=np.float32))
            cols.append([color[0], color[1], color[2], 1.0])

    bright = 1.0 + lift * 0.6
    metal = tuple(c * bright for c in ARM_METAL)
    hi = tuple(c * bright for c in ARM_HIGHLIGHT)

    # Counterweight stub, behind the pivot. It needs an actual weight on the
    # end: a bare stub reads as the arm continuing off the frame forever
    # instead of terminating, which is what it looked like before — a stray
    # line across the corner, not a tonearm. A real counterweight is a short
    # fat barrel, and its mass is most of what makes the arm read as balanced
    # rather than as a pointer.
    back = (pv[0] - (sx - pv[0]) * 0.22, pv[1] - (sy - pv[1]) * 0.22)
    seg(pv, back, metal)
    bux, buy = (back[0] - pv[0]), (back[1] - pv[1])
    bln = math.hypot(bux, buy) or 1.0
    bnx, bny = -buy / bln, bux / bln
    cw_half = 0.052 * radius       # how far the barrel stands off the axis
    cw_len = 0.055 * radius        # how long it is along the axis
    for t in np.linspace(-1.0, 1.0, 41):
        ax = back[0] + (bux / bln) * cw_len * t
        ay = back[1] + (buy / bln) * cw_len * t
        # ends of the barrel are narrower, so it reads as round, not as a slab
        w = cw_half * math.sqrt(max(0.0, 1.0 - t * t * 0.55))
        seg((ax - bnx * w, ay - bny * w), (ax + bnx * w, ay + bny * w),
            hi if abs(t) < 0.2 else metal)
    # the tube: drawn as several parallel copies so it has real thickness
    # without needing a second, wider shader path
    ux, uy = (sx - pv[0]), (sy - pv[1])
    ln = math.hypot(ux, uy) or 1.0
    nx, ny = -uy / ln, ux / ln
    # The tube has to out-weigh the beam trace visually or the arm reads as
    # another signal line. Real aluminium tube on a 152mm record is about
    # 10mm across; this is that, in NDC, as parallel copies.
    tube = (-0.0060, -0.0045, -0.0030, -0.0015, 0.0, 0.0015, 0.0030, 0.0045, 0.0060)
    for k, off in enumerate(tube):
        c = hi if k == 4 else metal
        seg((pv[0] + nx * off, pv[1] + ny * off), (sx + nx * off, sy + ny * off), c)
    # headshell: a short block canted at the standard offset angle
    off_ang = math.radians(23.0)
    hl = 0.085 * radius
    hdx = (ux / ln) * math.cos(off_ang) - (uy / ln) * math.sin(off_ang)
    hdy = (ux / ln) * math.sin(off_ang) + (uy / ln) * math.cos(off_ang)
    for off in (-0.010, -0.006, -0.002, 0.002, 0.006, 0.010):
        seg((sx + nx * off - hdx * hl, sy + ny * off - hdy * hl),
            (sx + nx * off + hdx * hl * 0.25, sy + ny * off + hdy * hl * 0.25), hi)
    # pivot gimbal
    th = np.linspace(0, 2 * np.pi, 17)
    pr = 0.035 * radius
    # iso, like every other element here. Passing (1,1) drew the one part of
    # the arm that is supposed to be a circle as a 1.6:1 ellipse on a 16:10
    # screen — the same aspect bug the geometric modes in scope.py already had.
    pc = _polar(pv[0], pv[1], pr, th, iso)
    for j in range(len(th) - 1):
        seg(pc[j], pc[j + 1], hi)
    return np.array(segs, dtype=np.float32), np.array(cols, dtype=np.float32), (sx, sy)


# ═══════════════════════════════════════════════════════════════════════════
# The ceremony
# ═══════════════════════════════════════════════════════════════════════════
SPINUP, CUE, DROP, PLAY, LIFT, BREAK, RETURN, STOP = range(8)

SPINUP_T = 2.0    # platter reaching 33 1/3 — a real one takes about this
CUE_T    = 1.7    # arm swinging out over the lead-in
DROP_T   = 0.9    # stylus descending
LIFT_T   = 1.1
RETURN_T = 1.6
# Quanto o braço leva para ser LEVADO do ponto em que subiu até o berço.
# Antes não existia: o quadro em que o LIFT vencia jogava a agulha do meio
# do disco para fora da borda de uma vez. Era a única parte da cerimônia que
# acontecia instantaneamente — justamente o contrário do que a cerimônia é.
TRAVEL_T = 1.3


class Deck:
    """Needle down, needle up, and the pause between sides.

    Every phase here exists because a turntable makes you wait through it,
    and waiting is the part that turns pressing play into an act. The spin-up
    is not decoration: it is the two seconds where you have already committed
    and the music has not started.
    """

    def __init__(self):
        self.phase = SPINUP
        self.t0 = time.monotonic()
        self.rotation = 0.0
        self.speed = 0.0          # revolutions per second, ramped
        self.crackle = 0.0
        self.side_index = 0
        self.pending_side = None
        self.message = None
        # Para onde este levantar vai dar. BREAK é a virada de lado (o prato
        # continua girando, esperando você virar o disco); STOP é o fim do
        # disco. Quem sabe a diferença é o RitualScene, que é quem enxerga o
        # álbum inteiro — o Deck só executa.
        self.after_lift = BREAK
        # Onde a agulha estava quando o braço subiu, para o trajeto até o
        # berço sair de onde ele realmente estava.
        self.lift_radius = ARM_REST_RADIUS
        # A alavanca de cue: 0 encostada, 1 no alto. Independente da fase
        # porque pausar não é mudar de fase — o prato continua girando, o
        # sulco continua embaixo, só a agulha sai dele. Ver update().
        self.cue_ramp = 0.0

    def elapsed(self):
        return time.monotonic() - self.t0

    def go(self, phase):
        self.phase = phase
        self.t0 = time.monotonic()

    def spinning(self):
        return self.phase not in (STOP,)

    def stylus_down(self):
        return self.phase in (PLAY,)

    def update(self, dt, playing):
        # A ALAVANCA DE CUE. `playing` chegava aqui e não era lido por
        # ninguém: pausar deixava a agulha encostada num sulco parado, que é
        # a única coisa que um toca-discos não faz. Num deck de verdade
        # pausar É levantar o braço — o prato continua girando, a agulha sai
        # do sulco e fica pairando exatamente sobre onde parou, e voltar é
        # baixá-la de novo no mesmo lugar. É o gesto mais frequente do
        # aparelho e era o único que não existia aqui.
        #
        # Fora da fase de propósito: PLAY continua sendo PLAY com a música
        # pausada, e o raio não precisa ser congelado porque a posição não
        # anda enquanto está pausado — a agulha já fica onde estava.
        e = self.elapsed()
        alvo = 0.0 if playing else 1.0
        self.cue_ramp += (alvo - self.cue_ramp) * min(1.0, dt * 3.2)
        if self.phase == SPINUP:
            # ease toward speed, like a belt taking up
            self.speed += (REV_PER_SEC - self.speed) * min(1.0, dt * 2.2)
            if e >= SPINUP_T:
                self.go(CUE)
        elif self.phase == STOP:
            self.speed *= max(0.0, 1.0 - dt * 1.1)
        else:
            self.speed += (REV_PER_SEC - self.speed) * min(1.0, dt * 3.0)
        # Relê o cronômetro: um go() logo acima acabou de zerá-lo, e usar o
        # `e` velho aqui faz a fase recém-entrada já vencer o próprio prazo
        # no MESMO quadro. Era o que acontecia: no quadro em que o prato
        # terminava de subir (e >= 2.0s), o go(CUE) zerava o t0 e a linha
        # abaixo, ainda olhando e = 2.0 contra CUE_T = 1.7, mandava direto
        # para o DROP. O CUE nunca acontecia - o braço nunca era visto
        # saindo para cima da faixa de entrada, a agulha só aparecia já
        # descendo. Achado pelo tools/test_ritual.py, não a olho.
        e = self.elapsed()
        if self.phase == CUE and e >= CUE_T:
            self.go(DROP)
        elif self.phase == DROP and e >= DROP_T:
            self.crackle = 1.0
            self.go(PLAY)
        elif self.phase == LIFT and e >= LIFT_T:
            self.go(self.after_lift)
        elif self.phase == RETURN and e >= RETURN_T:
            self.go(CUE)
        self.rotation = (self.rotation + self.speed * dt * 2.0 * math.pi) % (2.0 * math.pi)
        self.crackle *= max(0.0, 1.0 - dt * 2.5)
        return self.phase

    def arm_target_radius(self, play_radius):
        """Where the stylus should be right now, including the swing."""
        e = self.elapsed()
        if self.phase == SPINUP:
            return ARM_REST_RADIUS
        if self.phase == CUE:
            k = _ease(min(1.0, e / CUE_T))
            return ARM_REST_RADIUS + (R_LEADIN - ARM_REST_RADIUS) * k
        if self.phase == DROP:
            return R_LEADIN
        if self.phase == LIFT:
            # Guardar aqui, e não no go(LIFT), porque é aqui que o raio de
            # agora chega — é o quadro que sabe onde a agulha está. É o que
            # a alavanca de cue faz de verdade: segura o braço onde estava.
            self.lift_radius = play_radius
            return play_radius
        if self.phase in (BREAK, STOP):
            k = _ease(min(1.0, e / TRAVEL_T))
            return self.lift_radius + (ARM_REST_RADIUS - self.lift_radius) * k
        if self.phase == RETURN:
            # O braço já está no berço; o RETURN é a batida de espera antes
            # de cuear de novo, e o CUE é quem o traz de volta ao disco.
            return ARM_REST_RADIUS
        return play_radius

    def arm_lift(self):
        """0 encostada, 1 no alto — o maior entre a fase e a alavanca de cue.

        As duas coisas levantam o braço por motivos diferentes (a cerimônia e
        a mão da pessoa) e o maior é o que vale: durante o DROP com a música
        pausada a agulha não pode descer só porque a fase mandou.
        """
        e = self.elapsed()
        if self.phase in (SPINUP, CUE, BREAK, RETURN, STOP):
            return 1.0
        if self.phase == DROP:
            fase = max(0.0, 1.0 - _ease(min(1.0, e / DROP_T)))
        elif self.phase == LIFT:
            fase = _ease(min(1.0, e / LIFT_T))
        else:
            fase = 0.0
        return max(fase, self.cue_ramp)


def _ease(t):
    """Smootherstep. Mechanical things do not start and stop instantly."""
    return t * t * t * (t * (t * 6 - 15) + 10)
