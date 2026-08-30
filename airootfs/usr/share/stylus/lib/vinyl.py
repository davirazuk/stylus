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

# Quanto cabe num lado de 12" a 33⅓ antes de o sulco ficar apertado demais.
#
# Eram 22 minutos, e 22 é o lado CONFORTÁVEL, não o teto. Abbey Road tem
# 23min30 no lado A; a maioria dos LPs de rock dos anos 70 passa dos 22 sem
# cerimônia — o nível cai um pouco e é isso. Com o teto em 22, um disco de 45
# minutos (que é o objeto mais comum que existe) não cabia em dois lados e
# virava TRÊS, o que não existe.
SIDE_MAX_SECONDS = 26 * 60

# E o teto FÍSICO, que é outra coisa. Um lado de 12" a 33⅓ aguenta uns 30
# minutos com o nível um pouco abaixo — é o que se faz num disco que não se
# deixa repartir de outro jeito, e é o que a prensagem de verdade faz.
#
# **Sintoma:** um disco de 50 minutos em doze faixas saía como DISCO DUPLO,
# com quatro lados. Não é erro de conta: com o teto em 26, nenhum corte em
# dois lados cabia — as somas parciais pulam de 21,8 para 26,1 minutos, e
# 26,1 passa por SEIS SEGUNDOS. Seis segundos transformavam um LP em dois.
#
# Então: o teto de cima decide QUANTOS lados planejar (é o lado confortável)
# e este só entra quando o plano não fecha — na ordem certa, que é preferir
# o disco simples ao duplo, e não o contrário.
SIDE_HARD_SECONDS = 30 * 60

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
# O socket IPC do mpv que o `stylus-deck` sobe, e o PID dele. Os dois nomes
# moram AQUI e não em cada script porque três lugares já os escreviam à mão
# (o stylus-deck, o stylus-qobuz e este arquivo) — e o dia em que um deles
# mudar sozinho é o dia em que a barra mostra um disco e sai o som de outro,
# sem erro nenhum em lugar nenhum.
SOCKET_PATH = os.path.join(STATE_DIR, "deck.sock")
MPV_PIDFILE = os.path.join(STATE_DIR, "deck.mpv.pid")
# O recado para o lançador que JÁ está aberto. Ele é instância única: um
# `stylus deck` num terminal não pode abrir uma segunda tela cheia por cima
# da primeira, então deixa aqui o que quer que ela faça e ela lê no próximo
# quadro. Uma linha, apagada depois de lida.
UI_CMD = os.path.join(STATE_DIR, "ui.cmd")
SESSION_FILE = os.path.join(STATE_DIR, "session-memory.json")
_USER_LIBRARY_CONF = os.path.expanduser("~/.config/stylus/library")
_SYSTEM_LIBRARY_CONF = "/etc/stylus/library"
_FALLBACK_ROOTS = ("~/Music", "~/Músicas", "~/Musica", "~/Musique", "/srv/music")


def plural(n, um, muitos=None):
    """"1 disco", "2 discos" — a regra do plural, UMA vez.

    **Sintoma:** "1 faixas", "1 discos", "posto há 1 meses", "1 lado(s)",
    "3 problema(s) claro(s)". Não derruba nada e não aparece em teste
    nenhum; só faz o sistema parecer traduzido por máquina, e o texto que a
    pessoa vê é a única parte dele que ela lê inteira.

    Ela já morava no `ui/model.py`, e o `model` é da INTERFACE: as
    ferramentas de linha de comando não o importam, então elas escreviam a
    regra à mão de novo — e o "(s)" é o que se escreve quando se desiste de
    escrevê-la. Aqui é onde os dois lados alcançam.
    """
    muitos = muitos or (um + "s")
    return "%d %s" % (n, um if abs(n) == 1 else muitos)


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
# O que conta como arquivo de música — a lista CANÔNICA. As ferramentas de
# `tools/` a pegam pelo `_raiz.audio_ext()`; havia QUATRO listas diferentes
# espalhadas por elas, e duas paravam em .flac e .mp3 — numa coleção em
# ALAC ou Opus, `stylus covers`, `stylus suggest` e o gerador de playlist
# não achavam faixa nenhuma e diziam que estava tudo bem.
#
# O .shn (Shorten) veio das listas do check_library/discover e o .ape
# (Monkey's Audio) da do stylus-audio: os dois são formatos sem perda de
# coleção antiga, e nenhum dos dois estava aqui.
AUDIO_EXT = (".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".aac",
             ".wma", ".shn", ".ape")

# ── a PLAYLIST em arquivo ─────────────────────────────────────────────────
# **Sintoma:** este sistema ESCREVIA playlists e não sabia tocar nenhuma. O
# `stylus suggest`, o `make_new_playlist` e o `integrate_album` põem .m3u na
# raiz da coleção há muito tempo — "Shoegaze & Dreampop.m3u", "Novidades
# 2026-08-30.m3u", "coleção.m3u" — e não havia caminho nenhum daqui até o
# tocador. Arquivos que o sistema cria e o sistema não abre.
#
# Uma playlist NÃO é um disco, e a diferença importa: ela entra como um lado
# só e contínuo (`continuo`), sem "vire o disco" — o aviso que é a tese deste
# projeto é verdade sobre um objeto que tem dois lados, e numa lista de 200
# faixas viraria um alarme a cada vinte minutos. É a mesma decisão que a
# playlist do Qobuz já tomava.
PLAYLIST_EXT = (".m3u", ".m3u8")


def ler_m3u(caminho):
    """[(caminho ou endereço, título, duração)] de um .m3u, na ordem dele.

    O que um .m3u tem de traiçoeiro, e por que cada linha abaixo existe:

      · caminho RELATIVO é o normal, e é relativo à pasta do .m3u — não à
        pasta de onde alguém rodou o comando.
      · barra invertida: playlist escrita no Windows. Um acervo que veio de
        lá tem `Artista\Album\01.flac` e nada abre.
      · `#EXTINF:213,Artista - Título` traz duração e nome de graça; sem ele
        o nome sai do arquivo. Ler o EXTINF é o que evita um ffprobe por
        faixa numa lista de trezentas.
      · endereço http(s): playlist de rádio, e o mpv toca. Não é para virar
        caminho de arquivo.
      · `#EXTM3U` e o resto dos comentários não são faixas.
    """
    base = os.path.dirname(os.path.abspath(caminho))
    saida, titulo, dur = [], "", 0.0
    try:
        with open(caminho, encoding="utf-8", errors="replace") as fh:
            linhas = fh.read().splitlines()
    except OSError:
        return []
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("#"):
            if ln.upper().startswith("#EXTINF:"):
                resto = ln.split(":", 1)[1]
                seg, _sep, nome = resto.partition(",")
                try:
                    d = float(seg.split(",")[0])
                    dur = d if d > 0 else 0.0
                except ValueError:
                    dur = 0.0
                titulo = nome.strip()
            continue
        if ln.startswith(("http://", "https://")):
            saida.append((ln, titulo, dur))
        else:
            alvo = ln.replace("\\", "/")
            alvo = os.path.expanduser(alvo)
            if not os.path.isabs(alvo):
                alvo = os.path.normpath(os.path.join(base, alvo))
            saida.append((alvo, titulo, dur))
        titulo, dur = "", 0.0
    return saida


def e_playlist(caminho):
    """Este caminho é um arquivo de playlist?"""
    return bool(caminho) and str(caminho).lower().endswith(PLAYLIST_EXT)


def playlists(raizes=None):
    """As playlists da coleção, ordenadas por nome.

    Só o primeiro nível de cada raiz, de propósito: playlist mora ao lado da
    coleção, não dentro de um disco — e um `lista.m3u` de dentro de uma pasta
    de álbum (que é o que o Qobuz escreve no cache) não é uma playlist da
    pessoa, é encanamento.
    """
    achadas = []
    for raiz in (raizes if raizes is not None else library_roots()):
        try:
            for n in sorted(os.listdir(raiz)):
                if n.lower().endswith(PLAYLIST_EXT) and not n.startswith("."):
                    achadas.append(os.path.join(raiz, n))
        except OSError:
            continue
    vistas, saida = set(), []
    for p in achadas:
        real = os.path.realpath(p)
        if real in vistas:
            continue
        vistas.add(real)
        saida.append(p)
    return sorted(saida, key=lambda p: os.path.basename(p).lower())


# A CAPA. Mesma história das extensões de áudio: havia QUATRO listas de nome
# de capa espalhadas (aqui, no model da interface, no extract_covers e no
# embed_metadata) e elas discordavam — duas tinham `folder.png`, as outras
# duas `cover.jpeg`.
#
# Pior que a discordância: aqui e no model a comparação era pelo nome EXATO,
# com maiúscula e tudo. Uma coleção passada por um Windows guarda `Folder.jpg`
# (o Windows Media Player escreve assim há vinte anos) e `Cover.jpg` — e nesse
# caso o deck ficava SEM capa nenhuma, e a estante caía no "primeira imagem em
# ordem alfabética", que numa pasta dessas costuma ser `AlbumArtSmall.jpg` ou
# `Back.jpg`. Meia coleção com a contracapa na estante, sem erro nenhum.
COVER_NAMES = ("cover", "folder", "front", "capa", "albumart", "album")
COVER_EXT = (".jpg", ".jpeg", ".png")
# O que é imagem de disco mas NÃO é a capa. Só vale para o palpite do fim,
# quando nenhum nome conhecido apareceu: melhor não ter capa do que pôr a
# contracapa ou a bolacha do CD no lugar dela.
_NAO_E_CAPA = ("back", "verso", "contra", "disc", "cd1", "cd2", "inlay",
               "booklet", "tray", "matrix", "label", "small", "thumb")


def taxa_do_grafo(padrao=48000):
    """A taxa em que o grafo do PipeWire está rodando AGORA.

    A RESPOSTA CANÔNICA, porque havia duas — o `detect_graph_rate` do
    scope.py (que a lia certo) e o monitor da tela cheia (que abria a captura
    em 48000 escrito à mão). A segunda custava a tese da máquina: uma captura
    pedindo 48k em cima de um disco de 44,1k é um segundo fluxo em outra
    taxa, e aí o grafo REAMOSTRA a música — a tela que desenha o som
    desfazendo a promessa do sistema, com a tela SINAL ao lado mostrando o
    resultado sem saber a causa.

    Lê o RELÓGIO DO GRAFO e não o formato de um dispositivo: os dois podem
    divergir legitimamente (medido: o DAC por USB negociado em 96k com o
    grafo em 48k no mesmo instante), e é o do grafo que decide se houve
    conversão.
    """
    try:
        out = subprocess.run(["pw-metadata", "-n", "settings"],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"key:'clock\.rate'\s+value:'(\d+)'", out)
        if m:
            return int(m.group(1))
        # O formato da saída do pw-metadata já mudou entre versões; a busca
        # frouxa é a reserva, não a regra.
        m = re.search(r"clock\.rate.*?(\d{4,6})", out)
        if m:
            return int(m.group(1))
    except Exception:                     # noqa: BLE001
        pass
    return padrao


def find_cover(folder, entries=None):
    """A capa desta pasta, ou None. Sem olhar maiúscula.

    `entries` existe para quem já listou a pasta (a varredura da estante lista
    centenas): passar a lista pronta evita um os.listdir por disco.
    """
    if entries is None:
        try:
            entries = os.listdir(folder)
        except OSError:
            return None
    imagens = [e for e in entries if e.lower().endswith(COVER_EXT)]
    if not imagens:
        return None
    porordem = {}
    for e in imagens:
        porordem.setdefault(e.lower(), e)
    for nome in COVER_NAMES:
        for ext in COVER_EXT:
            achou = porordem.get(nome + ext)
            if achou:
                return os.path.join(folder, achou)
    resto = [e for e in sorted(imagens)
             if not any(x in e.lower() for x in _NAO_E_CAPA)]
    return os.path.join(folder, resto[0]) if resto else None


# ═══════════════════════════════════════════════════════════════════════════
# A PALETA DO DISCO SAIU DAQUI
# ═══════════════════════════════════════════════════════════════════════════
# Eram quinze cores em ponto flutuante para o OpenGL do deck — o corpo, o
# aro, o brilho, os dois sulcos, o intervalo, a agulha, o facho do braço. Só
# o deck as lia, e o deck não existe mais.
#
# A lei que elas escreviam (CLAUDE.md §5.5: corpo preto FRIO, âmbar como
# única cor viva) não saiu com elas — ela mudou de casa para onde o disco é
# desenhado hoje: o `ui/theme.py` (AMBER/AMBER_DIM sobre INK, ver `disco()`)
# e o `VinylRenderer.kt` do celular. As duas conferências do `check.sh` que
# medem a lei em números apontam para lá.


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


# ── memória de sessão ────────────────────────────────────────────────────
# Salva o estado de reprodução para restaurar após reinício.
# Guarda: disco, faixa, posição, timestamp. Não guarda estado de pause —
# se o sistema reiniciou, assume que quer continuar de onde parou.

def save_session(path, title, artist, album, position, duration, track_index):
    """Salva o estado atual de reprodução."""
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        data = {
            "path": path,
            "title": title,
            "artist": artist,
            "album": album,
            "position": position,
            "duration": duration,
            "track_index": track_index,
            "timestamp": time.time(),
        }
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def restore_session(max_age=3600 * 4):
    """Restaura o estado de reprodução. Retorna dict ou None.

    max_age: máxima idade em segundos — depois disso, não restaura.
    """
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        age = time.time() - data.get("timestamp", 0)
        if age > max_age:
            return None
        return data
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def clear_session():
    """Limpa a memória de sessão."""
    try:
        os.unlink(SESSION_FILE)
    except OSError:
        pass


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
        # UMA leitura antes de largar a thread.
        #
        # **Sintoma:** `stylus lado` dizia "nada tocando" com um disco
        # tocando na frente da pessoa. Quem só pergunta uma vez — os comandos
        # de terminal, um script de polybar — construía a Session, lia o
        # snapshot no instante seguinte e recebia o estado ZERADO, porque a
        # primeira volta da thread ainda não tinha acontecido. Ficava certo
        # meio segundo depois, quando o processo já tinha saído.
        #
        # Custa um round-trip no socket do mpv (milissegundos) ou um
        # playerctl (dezenas). Para quem fica de pé — o deck, a tela cheia —
        # isso é invisível na abertura; para quem pergunta uma vez, é a
        # diferença entre responder e mentir.
        if not self._poll_mpv():
            self._poll_mpris()
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
        save_counter = 0
        while not self._stop:
            if not self._poll_mpv():
                self._poll_mpris()
            # Salva a cada 10 segundos — o bastante para restaurar,
            # pouco para não matar SSD
            save_counter += 1
            if save_counter >= 20:  # 20 * 0.5s = 10s
                save_counter = 0
                self._save_state()
            time.sleep(interval)

    def _save_state(self):
        """Salva o estado para restauração futura."""
        with self._lock:
            if not self.path or self.paused:
                return
            pos, dur = self._track_pos, self._track_dur
            if not self.paused and self._stamp:
                pos += max(0.0, time.monotonic() - self._stamp)
            save_session(
                self.path, self.title, self.artist, self.album,
                min(pos, dur) if dur else pos, dur, self.track_index,
            )

    def restore(self):
        """Restaura o último estado salvo. Retorna True se restaurou."""
        data = restore_session()
        if not data or not data.get("path"):
            return False
        # Tenta retomar via mpv
        if self.mpv.connect():
            path = data["path"]
            self.mpv.command("loadfile", path)
            pos = data.get("position", 0)
            if pos > 0:
                self.mpv.command("seek", str(pos), "absolute")
            return True
        return False

    def clear(self):
        """Limpa a memória de sessão."""
        clear_session()

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

# Todos os carimbos do começo da linha, e o texto depois do último.
_LRC_CARIMBO = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")
# [offset:+500] / [offset:-250] — em MILISSEGUNDOS, e positivo quer dizer
# "a letra vem ANTES" no formato original (Lrcget, Lyricify, etc. escrevem
# assim). Ver o porquê do sinal em parse_lrc.
_LRC_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.I)


def parse_lrc(path):
    """.lrc -> [(segundos, texto)] em ordem.

    Linha em branco é guardada de propósito: é o trecho instrumental, e
    jogá-la fora deixa o último verso cantado pendurado na tela por um
    encerramento de dois minutos.

    ── Duas coisas que faltavam, e as duas se veem na tela ──────────────────

    **Carimbo REPETIDO.** O formato permite (e todo refrão usa) vários
    carimbos na mesma linha:

        [00:42.10][02:15.30][03:48.90]E o refrão volta aqui

    O regex antigo casava o PRIMEIRO e mandava o resto para o texto. Ou
    seja: o refrão aparecia uma vez só, na primeira vez que era cantado, e
    escrito como "[02:15.30][03:48.90]E o refrão volta aqui" — com os
    colchetes na cara, no meio da tela. Num arquivo bem feito isso é a maior
    parte da letra.

    **[offset:±ms].** É o conserto que quem sincronizou a letra deixou
    escrito para toda a letra de uma vez, e ele era ignorado. Meio segundo
    é o valor mais comum; meio segundo é exatamente o que separa "a linha
    certa" de "a linha errada" numa música rápida.

    O SINAL: no formato, offset positivo quer dizer "mostre mais cedo", ou
    seja SUBTRAI do carimbo. É contraintuitivo e é o que está escrito nas
    especificações do formato; inverter aqui dobraria o erro em vez de
    corrigi-lo.

    Centésimos, e não milésimos: `[01:23.45]` são 45 CENTÉSIMOS, não 45 ms.
    Por isso o texto da fração é lido pelo que ele é — `float("0." + frac)`
    — em vez de dividido por mil.
    """
    out, offset = [], 0.0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            texto = f.read()
    except Exception:
        return []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        mo = _LRC_OFFSET.match(linha)
        if mo:
            try:
                offset = int(mo.group(1)) / 1000.0
            except ValueError:
                offset = 0.0
            continue
        carimbos, fim = [], 0
        for m in _LRC_CARIMBO.finditer(linha):
            if m.start() != fim:        # o texto começou: o resto não é carimbo
                break
            mm, ss = m.groups()
            if "." in ss or ":" in ss:
                seg, frac = re.split(r"[.:]", ss, 1)
                s = int(seg) + float("0." + frac)
            else:
                s = float(ss)
            carimbos.append(int(mm) * 60 + s)
            fim = m.end()
        if not carimbos:
            continue
        corpo = linha[fim:].strip()
        for t in carimbos:
            out.append((max(0.0, t - offset), corpo))
    out.sort(key=lambda x: x[0])
    return out


def find_lrc(caminho_da_faixa):
    """O .lrc desta faixa, procurado como as coleções de verdade guardam.

    **Sintoma:** metade da coleção "não tinha letra". Só se procurava
    `faixa.lrc` ao lado do arquivo, com essa caixa exata — e um acervo que
    passou por um Windows guarda `Faixa.LRC`, e vários programas de
    sincronia guardam tudo numa subpasta `Lyrics/`. É a mesma doença das
    cinco listas de nome de capa: o arquivo está lá, o jeito de perguntar é
    que estava estreito.
    """
    if not caminho_da_faixa:
        return None
    base, _ext = os.path.splitext(caminho_da_faixa)
    direto = base + ".lrc"
    if os.path.isfile(direto):
        return direto
    pasta = os.path.dirname(caminho_da_faixa)
    querido = os.path.basename(base).lower()
    for sub in ("", "Lyrics", "lyrics", "Letras", "letras", ".lyrics"):
        d = os.path.join(pasta, sub) if sub else pasta
        try:
            entradas = os.listdir(d)
        except OSError:
            continue
        for e in entradas:
            n, ext = os.path.splitext(e)
            if ext.lower() == ".lrc" and n.lower() == querido:
                return os.path.join(d, e)
    return None


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


def _collect_audio_recursive(folder, max_depth=4):
    """Coleta todos os áudios sob folder até max_depth, ordenado por caminho."""
    out = []
    stack = [(folder, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            continue
        # primeiro coleta áudios diretos deste nível
        for e in entries:
            p = os.path.join(cur, e)
            if os.path.isfile(p) and e.lower().endswith(AUDIO_EXT):
                out.append(p)
        if depth == max_depth:
            continue
        # depois empilha subpastas para varrer
        for e in reversed(entries):  # reversed para manter ordem com stack LIFO
            p = os.path.join(cur, e)
            if os.path.isdir(p) and not _DATED_FOLDER.match(e) and not e.startswith("."):
                # ignora pastas de arte/scans se tiverem muitas imagens mas sem áudio
                # mas ainda varre — webdav pode ter estrutura imprevisível
                stack.append((p, depth + 1))
    # ordena por caminho relativo e depois por _track_sort_key para manter ordem de disco
    out.sort(key=lambda x: (os.path.relpath(x, folder).lower(), _track_sort_key(os.path.basename(x))))
    # dedup preservando ordem
    seen = set()
    uniq = []
    for p in out:
        n = os.path.normpath(p)
        if n not in seen:
            seen.add(n)
            uniq.append(p)
    return uniq

def manifesto(folder):
    """O disco.json de uma pasta, ou None. Um disco que não tem arquivos.

    Escrito pelo `stylus qobuz tocar`: ordem, títulos, durações e endereços.
    Fica aqui, e não dentro do Album, porque o lançador do deck precisa da
    mesma lista sem construir um Album inteiro.
    """
    try:
        with open(os.path.join(folder, "disco.json"), encoding="utf-8") as fh:
            m = json.load(fh)
    except (OSError, ValueError):
        return None
    return m if m.get("tracks") else None


def track_paths(folder):
    """Os arquivos de áudio da pasta, na ordem do disco — recursivo com subpastas.

    Quando a pasta descreve um disco que vem pela rede (um disco.json, sem
    arquivo de áudio nenhum), o que sai daqui são os ENDEREÇOS, na mesma
    ordem. O mpv toca endereço, e é isso que faz o deck — a cerimônia
    inteira, com o disco girando — funcionar igual para um disco da estante e
    para um da assinatura. Sem esta linha o lançador não achava faixa nenhuma
    e entregava a PASTA ao mpv, que tentava tocar a capa.
    """
    # Uma PLAYLIST é um arquivo, não uma pasta: a ordem é a que está escrita
    # nela. Sem esta linha o `stylus deck lista.m3u` caía no os.listdir de
    # uma "pasta" que é um arquivo, achava nada, e entregava o .m3u ao mpv —
    # que até toca, mas aí o índice da faixa não é o índice do Album e o
    # LADO, a agulha e a letra falam todos da faixa errada.
    if e_playlist(folder):
        return [c for c, _t, _d in ler_m3u(folder)]
    m = manifesto(folder)
    if m:
        return [t.get("url") or "" for t in m.get("tracks") or [] if t.get("url")]
    try:
        # tenta rápido direto antes de walk (caso comum 95%%)
        names = sorted((n for n in os.listdir(folder)
                        if n.lower().endswith(AUDIO_EXT)), key=_track_sort_key)
        if names:
            direct = [os.path.join(folder, n) for n in names]
            # verifica se há também subpastas com áudio (Disc 01) — soma tudo
            rec = _collect_audio_recursive(folder)
            # se recursivo só trouxe os mesmos diretos, devolve direto (mais rápido)
            if len(rec) == len(direct) and set(rec) == set(direct):
                return direct
            # se tem mistura (ex: álbum dividido), devolve recursivo ordenado
            # que inclui diretos + subpastas na ordem correta (Disc01 antes de root? não)
            # Para manter compatibilidade, se há diretos, devolve só diretos quando
            # o álbum é simples; mas se houver subpastas com áudio adicional, devolve tudo
            # Detecta: se rec tem mais que direct, usa rec
            if len(rec) > len(direct):
                return rec
            return direct
    except OSError:
        pass
    return _collect_audio_recursive(folder)


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


# "1993-02-11 - Radiohead - Tel Aviv" → data, artista, resto.
# A data é opcional; o que importa é o " - " que separa artista de disco.
_DATA_NA_FRENTE = re.compile(r"^\s*\d{4}(?:[-.]\d{2}){0,2}\s*[-–—]\s*")


def folder_names(folder):
    """(artista, disco) a partir do caminho — a mesma leitura que o Album faz.

    O desenho normal da estante é `Artista/Álbum/faixa`, e aí a pasta de cima
    É o artista. Mas um disco pode estar SOLTO na raiz da estante, e aí a
    pasta de cima é a raiz.

    **Sintoma:** oito discos desta coleção estão soltos em `~/Músicas/Songs`,
    e a estante os mostrava como

        Songs — 1993-02-11 - Radiohead - Signal Radio Session

    com "Songs" — o nome da PASTA DA COLEÇÃO — no lugar do artista, em todos
    eles. Na grade do `stylus shelf`, que ordena por artista, os oito ficavam
    juntos no começo, todos assinados pela mesma banda inexistente. É a
    primeira tela que se vê ao apertar Mod+M.

    Quando a pasta de cima é uma raiz da estante, ela não é artista nenhum:
    o nome do disco é lido do próprio nome da pasta, que quase sempre traz o
    artista na frente ("Radiohead - Lost Treasures", "2002 - The Strokes -
    MTV $2 Dollar Bill"). Não achando, devolve artista vazio — que é honesto
    e melhor do que um nome errado.
    """
    folder = folder.rstrip(os.sep)
    nome = os.path.basename(folder)
    pai = os.path.dirname(folder)
    if not _e_raiz(pai):
        artista = os.path.basename(pai)
        # Nenhum artista se chama "2008-04-02 - Radiohead - Maida Vale Studio
        # 3, London, UK". Uma pasta com DATA na frente é um show, não um
        # artista: nesta coleção os bootlegs são Songs/<data - banda - lugar>/
        # <disco>, e a estante assinava o disco com a linha inteira, data e
        # endereço — ilegível na grade e fora de ordem alfabética, porque
        # ordena pelo ano.
        if _DATA_NA_FRENTE.match(artista):
            dentro = _DATA_NA_FRENTE.sub("", artista)
            primeiro = re.split(r"\s+[-–—]\s+", dentro, maxsplit=1)[0].strip()
            artista = primeiro or dentro.strip() or artista
        return artista, nome
    # Solto na raiz: o artista, se houver, está no próprio nome.
    resto = _DATA_NA_FRENTE.sub("", nome)
    partes = re.split(r"\s+[-–—]\s+", resto, maxsplit=1)
    if len(partes) == 2 and partes[0].strip() and partes[1].strip():
        return partes[0].strip(), partes[1].strip()
    # O nome não diz quem é. Quem sabe são as ETIQUETAS do primeiro arquivo —
    # e perguntar a elas custa uma leitura só, e só para os discos soltos que
    # também não trazem o artista no nome. Melhor uma leitura de disco do que
    # uma estante que não sabe de quem é a música.
    return _artista_das_etiquetas(folder), nome


_ARTISTA_CACHE = {}


def _artista_das_etiquetas(folder):
    if folder in _ARTISTA_CACHE:
        return _ARTISTA_CACHE[folder]
    artista = ""
    try:
        faixas = _collect_audio_recursive(folder)
        if faixas:
            from mutagen import File as _MFile
            m = _MFile(faixas[0], easy=True)
            if m:
                for chave in ("albumartist", "artist", "performer"):
                    v = m.get(chave)
                    if v:
                        artista = str(v[0]).strip()
                        break
    except Exception:                                    # noqa: BLE001
        artista = ""
    if len(_ARTISTA_CACHE) > 512:
        _ARTISTA_CACHE.clear()
    _ARTISTA_CACHE[folder] = artista
    return artista


def _e_raiz(caminho):
    """Esta pasta é uma das raízes da estante?

    Compara pelo caminho real: uma raiz montada por link (o `stylus webdav`
    faz isso) e a mesma pasta escrita direto são a mesma coisa, e comparar as
    strings diria que não.
    """
    try:
        alvo = os.path.realpath(caminho)
    except OSError:
        alvo = caminho
    for r in MUSIC_ROOTS:
        try:
            if os.path.realpath(r) == alvo:
                return True
        except OSError:
            continue
    return False


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
    # helper: conta faixas de um disco (direto + Disc 01/Disc 02 como parte do mesmo)
    disc_pat = re.compile(r'^(disc|cd|vinyl|side|part|disco)[\s._-]*\d+', re.I)
    def _album_count(p):
        try:
            direct = sum(1 for f in os.listdir(p) if f.lower().endswith(AUDIO_EXT))
            # subpastas tipo Disc 01 contam como mesmo álbum
            sub_total = 0
            has_disc_sub = False
            for sub in os.listdir(p):
                sp = os.path.join(p, sub)
                if not os.path.isdir(sp) or _DATED_FOLDER.match(sub):
                    continue
                if disc_pat.match(sub):
                    has_disc_sub = True
                    try:
                        sub_total += sum(1 for f in os.listdir(sp) if f.lower().endswith(AUDIO_EXT))
                    except OSError:
                        pass
            if has_disc_sub and direct == 0:
                return sub_total
            if has_disc_sub and direct > 0:
                return direct + sub_total
            return direct
        except OSError:
            return 0

    def _is_album(p):
        return _album_count(p) >= min_tracks

    # varre até 4 níveis, pegando folhas que são álbuns e não descendo dentro delas
    out = []
    stack = [base]
    # se artist foi passado, base já é artista — começa nele
    # senão, base é root, tops são seus filhos (artist ou flat album)
    # para walk uniforme, empilha os filhos de base quando artist is None
    if artist is None:
        try:
            tops = [os.path.join(root, d) for d in sorted(os.listdir(root))]
        except OSError:
            return []
        stack = tops

    visited = set()
    while stack:
        cur = stack.pop()
        if not os.path.isdir(cur) or cur in visited:
            continue
        visited.add(cur)
        if _is_album(cur):
            out.append(cur)
            continue  # não desce dentro de álbum (Disc 01 já contado)
        # não é álbum: desce
        try:
            for e in sorted(os.listdir(cur), reverse=True):
                p = os.path.join(cur, e)
                if os.path.isdir(p) and not _DATED_FOLDER.match(e) and not e.startswith("."):
                    # limita profundidade para não varrer coleção inteira desnecessário
                    # mas webdav pode ter Genre/Artist/Album (3 níveis) + Disc
                    rel = os.path.relpath(p, base)
                    if rel.count(os.sep) < 4:
                        stack.append(p)
        except OSError:
            continue
    # dedup e estabilidade por nome
    seen = set()
    uniq = []
    for p in sorted(set(out), key=lambda x: x.lower()):
        n = os.path.normpath(p)
        if n not in seen:
            seen.add(n)
            uniq.append(p)
    return sorted(uniq, key=lambda x: x.lower())


def last_played():
    """{pasta: quando} — a última vez de cada disco, do registro."""
    out = {}
    for ts, fold in _play_rows():
        k = os.path.normpath(fold)
        if ts > out.get(k, 0.0):
            out[k] = ts
    return out


# Quantos discos chegam à final do sorteio — ou seja, quantos ÁLBUNS são
# abertos para o empurrãozinho da hora do dia. Ver `draw_record`.
_FINALISTAS = 12


def draw_record(candidates=None, exclude=(), rng=None):
    """Sorteia um disco puxando para o que faz mais tempo que não toca,
    com um toque de consciência temporal — a manhã pede uma coisa, a noite outra.

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
    _rng = rng or random
    vistos = last_played()
    agora = time.time()

    # ── 1. o esquecimento, que não custa arquivo nenhum ───────────────────
    # Peso quadrático nos dias desde a última vez. Só o registro de escutas
    # é lido, e ele é um arquivo só.
    base = []
    for d in cands:
        quando = vistos.get(os.path.normpath(d))
        dias = 400.0 if quando is None else max(0.0, (agora - quando) / 86400.0)
        base.append(1.0 + dias * dias)

    # ── 2. a hora do dia, só entre os FINALISTAS ──────────────────────────
    # **Sintoma:** apertar [r] na estante travava a interface por segundos.
    #
    # O empurrãozinho da hora (manhã pede faixa curta, noite pede longa —
    # 15% de variação, e o comentário original diz "não é ditadura") precisa
    # da duração média das faixas, e para isso abria um `Album` de CADA
    # candidato. Numa coleção de 374 discos com uma dúzia de faixas cada,
    # isso é o mutagen abrindo quatro mil e quinhentos arquivos — e um
    # ffprobe por faixa que ele não souber ler — para aplicar um ajuste de
    # quinze por cento. O sorteio é a única coisa neste sistema que a pessoa
    # espera ser instantânea.
    #
    # Então sorteia-se primeiro pelo esquecimento, tira-se uma dúzia de
    # finalistas, e só neles se paga o preço de abrir o disco. O resultado é
    # o mesmo tipo de escolha; o custo passa de 374 leituras para 12.
    hora = time.localtime(agora).tm_hour
    if len(cands) > _FINALISTAS:
        idx = set()
        for _ in range(_FINALISTAS * 2):
            if len(idx) >= _FINALISTAS:
                break
            idx.add(_rng.choices(range(len(cands)), weights=base, k=1)[0])
        indices = sorted(idx)
    else:
        indices = list(range(len(cands)))

    finalistas, pesos = [], []
    for i in indices:
        d = cands[i]
        peso = base[i]
        try:
            alb = Album(d, envelope=False)
            total = alb.total if alb.total else 2400
            avg_track = total / max(1, len(alb.tracks))
            # manhã (6-12): médias rápidas ganham um leve bônus
            # noite (18-24): médias longas ganham um leve bônus
            # madrugada (0-6): disco comprido ganha um leve bônus
            if 6 <= hora < 12:
                if avg_track < 300:
                    peso *= 1.15
            elif 18 <= hora < 24:
                if avg_track > 360:
                    peso *= 1.15
            elif 0 <= hora < 6:
                if total > 3600:
                    peso *= 1.10
        except Exception:                                  # noqa: BLE001
            pass
        finalistas.append(d)
        pesos.append(peso)
    return _rng.choices(finalistas, weights=pesos, k=1)[0]


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
        # A história deste disco, lida uma vez na abertura. Eram quatro
        # campos: a `seed` e o `first_played` alimentavam as MARCAS DE USO
        # que o deck desenhava (quanto mais tocado, mais riscado), e saíram
        # com ele. Campo escrito e nunca lido lê como recurso que existe —
        # ver a lição no CLAUDE.md.
        self.plays, _primeira, self.last_played = play_history(folder)
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
        # Um disco que não tem arquivo nenhum: o que vem pela rede.
        #
        # O `stylus qobuz tocar` monta uma pasta em ~/.cache/stylus/qobuz com
        # a capa, a lista do mpv e um disco.json — ordem, títulos e durações,
        # que o Qobuz manda de graça junto com o álbum. Com isso este objeto
        # fica completo sem tocar em arquivo de áudio nenhum, e tudo que já
        # sabe ler um Album passa a saber ler um disco transmitido: os LADOS,
        # que é o que importa. Sem isto o aviso de virar o lado — a única
        # coisa que este sistema faz e mais nenhum faz — simplesmente não
        # acontecia para quem estava ouvindo pela assinatura.
        if self._ler_playlist():
            return
        if self._ler_manifesto():
            return
        # usa o mesmo coletor que track_paths para garantir índice idêntico
        for p in _collect_audio_recursive(self.folder):
            n = os.path.basename(p)
            title = re.sub(r"^\s*\d+\s*[-._)]\s*", "", os.path.splitext(n)[0]).strip()
            self.tracks.append({"path": p, "title": title, "duration": 0.0, "start": 0.0})
        
        self.cover = find_cover(self.folder) or self.cover
        if self.tracks:
            self._read_tags(self.tracks[0]["path"])

    def _ler_playlist(self):
        """Um .m3u no lugar de uma pasta. True quando era um.

        A `folder` de um Album normalmente é uma pasta; aqui ela é o ARQUIVO
        da playlist. Isso é de propósito e não uma gambiarra: tudo que já
        sabe ler um Album — o LADO, o "vira em X", a agulha no sulco, a letra
        no tempo — passa a valer para uma playlist sem uma segunda
        implementação de nada. É o mesmo caminho que o disco da rede usa.

        O ARTISTA sai da coleção quando dá: se todas as faixas moram sob a
        mesma pasta de artista, é o artista dela. Numa lista de vários, fica
        vazio — que é honesto. E a CAPA é a do primeiro disco que aparecer:
        uma playlist não tem capa, e a alternativa é o quadrado cinza.
        """
        if not e_playlist(self.folder) or not os.path.isfile(self.folder):
            return False
        itens = ler_m3u(self.folder)
        if not itens:
            return False
        artistas, capa = set(), None
        for caminho, titulo, dur in itens:
            nome = os.path.basename(caminho)
            if not titulo:
                titulo = re.sub(r"^\s*\d+\s*[-._)]\s*", "",
                                os.path.splitext(nome)[0]).strip()
            self.tracks.append({"path": caminho, "title": titulo,
                                "duration": float(dur or 0.0), "start": 0.0})
            if not caminho.startswith(("http://", "https://")):
                pasta = os.path.dirname(caminho)
                art, _disco = folder_names(pasta)
                if art:
                    artistas.add(art)
                if capa is None:
                    capa = find_cover(pasta)
        self.name = os.path.splitext(os.path.basename(self.folder))[0]
        self.artist = artistas.pop() if len(artistas) == 1 else ""
        self.cover = capa
        # Uma playlist não tem lado para virar. Ver o `continuo` do
        # manifesto: a mesma decisão, pelo mesmo motivo.
        self.continuo = True
        return True

    def _ler_manifesto(self):
        """disco.json no lugar dos arquivos. True quando havia um."""
        m = manifesto(self.folder)
        if not m:
            return False
        faixas = m.get("tracks") or []
        if not faixas:
            return False
        for t in faixas:
            self.tracks.append({
                "path": t.get("url") or "",
                "title": t.get("title") or "",
                # A duração vem daqui e não do ffprobe: medir um arquivo que
                # está do outro lado da internet custa uma conexão por faixa,
                # e o Qobuz já disse quanto dura cada uma.
                "duration": float(t.get("duration") or 0.0),
                "start": 0.0,
            })
        # Uma PLAYLIST não tem lado para virar. O sistema inteiro existe
        # para dizer "acabou o lado, vira o disco", e isso é verdade sobre um
        # disco; numa playlist de 274 faixas viraria um alarme a cada vinte
        # minutos, e o aviso que é a tese do projeto viraria ruído.
        self.continuo = bool(m.get("continuo"))
        self.artist = m.get("artist") or self.artist
        self.name = m.get("album") or self.name
        self.year = str(m.get("year") or "")
        capa = find_cover(self.folder)
        if capa:
            self.cover = capa
        return True

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
        for tr in self.tracks:
            # Só mede o que ainda não tem medida: um disco vindo do
            # disco.json já traz a duração de cada faixa, e o ffprobe num
            # endereço http abre uma conexão por faixa para redescobrir o que
            # já se sabe — segundos de espera antes de a tela mostrar
            # qualquer coisa.
            if not tr.get("duration"):
                tr["duration"] = _probe_duration(tr["path"])

        # ── as que não deram para medir ───────────────────────────────────
        # **Sintoma:** uma faixa que nem o mutagen nem o ffprobe sabem ler
        # entrava com duração ZERO — e zero não é "não sei", é "não dura
        # nada". Três faixas assim num disco de doze tiram um quarto do
        # total: o disco perde um LADO inteiro, o "vira em X" mente, e a
        # agulha do deck aponta para o sulco errado. Nada disso dá erro em
        # lugar nenhum; o disco simplesmente fica menor do que é.
        #
        # A MEDIANA das que deram é o palpite honesto: ela resiste a uma
        # faixa de vinte minutos no meio de onze de três, que é justamente o
        # tipo de disco em que a média estragaria tudo.
        medidas = sorted(t["duration"] for t in self.tracks if t["duration"] > 0)
        if medidas and len(medidas) < len(self.tracks):
            meio = medidas[len(medidas) // 2]
            for tr in self.tracks:
                if not tr["duration"]:
                    tr["duration"] = meio
                    # Fica marcado: quem quiser dizer "aproximado" na tela
                    # tem como saber, e quem for depurar não vai achar que a
                    # faixa media isso mesmo.
                    tr["estimada"] = True

        t = 0.0
        for tr in self.tracks:
            tr["start"] = t
            t += tr["duration"]
        self.total = t

    def _build_sides(self):
        """Reparte a ordem do disco em lados de no máximo SIDE_MAX_SECONDS
        (26 min — o comentário aqui dizia 22, de uma versão anterior), sempre
        em fronteira de faixa — a side never cuts a song in half, which is exactly the
        constraint that decided the running order of every album pressed to
        vinyl. Aims for even sides rather than filling A to the brim and
        leaving B with two songs on it."""
        if not self.tracks or self.total <= 0:
            self.sides = []
            self.discos = 0
            return
        if getattr(self, "continuo", False):
            # O rótulo NÃO é opcional. Este lado saía sem ele — a etiqueta é
            # posta no laço lá embaixo, que este `return` pula — e a AGORA
            # faz `side["label"]`: pôr uma playlist do Qobuz e ir para a
            # AGORA levantava KeyError, ou seja, a tela principal do sistema
            # quebrava para toda playlist. Não é "SIDE A": uma playlist não
            # tem lado nenhum, e é justamente essa a diferença que este
            # sistema existe para marcar.
            self.sides = [{"start": 0.0, "end": self.total, "label": "CONTÍNUO",
                           "tracks": list(range(len(self.tracks)))}]
            self.discos = 1
            return
        # ── quantos LADOS ─────────────────────────────────────────────────
        # **Sintoma:** um LP de 45 minutos — Abbey Road, Led Zeppelin IV, a
        # forma mais comum que um disco tem — saía com TRÊS lados de quinze
        # minutos. A conta era `ceil(total / teto_do_lado)`, e com o teto em
        # 22 minutos qualquer coisa acima de 44 pedia um terceiro lado; a
        # regra de equilíbrio logo abaixo então repartia tudo em três pedaços
        # parelhos. Não existe disco de três lados. Existe disco de dois e
        # disco duplo de quatro.
        #
        # A conta certa arredonda o número de DISCOS, não o de lados, porque
        # é o disco que é o objeto físico e ele tem dois lados sempre:
        #
        #     45 min  → 1 disco, 2 lados de 22min30   (era 3 de 15)
        #     53 min  → 2 discos, 4 lados de 13       (OK Computer saiu assim
        #                                              em 1997, dois LPs)
        #     74 min  → 2 discos, 4 lados de 18min30
        #     90 min  → 2 discos, 4 lados de 22min30  (era 5)
        #
        # A exceção é o que cabe INTEIRO num lado: um 12" de 21 minutos é um
        # lado só, e mandar virar no meio dele seria inventar uma cerimônia
        # que o objeto não tem.
        if self.total <= SIDE_MAX_SECONDS:
            n_sides = 1
        else:
            n_sides = 2 * math.ceil(self.total / (2.0 * SIDE_MAX_SECONDS))

        def cortar(quantos, teto=SIDE_MAX_SECONDS):
            """Reparte as faixas em `quantos` lados. Pode devolver mais.

            O teto físico (regra 1) corta quando precisa, e não pede licença
            ao plano: um disco cujas faixas não se deixam repartir em
            `quantos` pedaços abaixo do teto sai com mais lados do que se
            pediu. Quem lida com isso é o laço logo abaixo.
            """
            sides, cur, cur_start = [], [], 0.0
            for i, tr in enumerate(self.tracks):
                end = tr["start"] + tr["duration"]

                # ── 1. o teto, que é físico ───────────────────────────────
                # **Sintoma:** 69 dos 374 discos desta coleção tinham um lado
                # passando dos 22 minutos, e o cabeçalho aqui em cima promete
                # que nenhum passa. Sozinha, a regra de equilíbrio lá embaixo
                # compara com a MÉDIA e fecha o lado DEPOIS de somar a faixa
                # — então a última faixa entra inteira por cima do teto. Num
                # disco de 44 minutos a média dá 22, o lado fecha aos 19, e a
                # faixa seguinte o leva a 25.
                #
                # Importa porque um lado que não caberia num disco de verdade
                # faz o aviso de virar chegar tarde, e o `stylus lado`
                # prometer um "vira em X" de um lado que não existe.
                #
                # Fechar ANTES de pôr a faixa que estoura. Um lado vazio
                # nunca fecha: uma faixa maior que o lado inteiro fica
                # sozinha nele, que é o que acontece de verdade — não se
                # corta uma música ao meio.
                if cur and (end - cur_start) > teto:
                    sides.append({"start": cur_start, "end": tr["start"],
                                  "tracks": cur})
                    cur, cur_start = [], tr["start"]

                cur.append(i)

                # ── 2. o equilíbrio ───────────────────────────────────────
                # Lados parecidos em vez de encher o A até a boca e deixar o
                # B com duas músicas.
                #
                # O alvo é recalculado a partir do que RESTA — divida o que
                # falta pelos lados que faltam — e não fixo em
                # `total / n_lados`. Com o alvo fixo (e uma folga de 14% para
                # baixo) os lados fechavam cedo, o que sobrava não cabia no
                # último, e a regra 1 cortava de novo: um disco de 90 minutos
                # saía com CINCO lados, que é um objeto que não existe.
                faltam = max(1, quantos - len(sides))
                alvo = cur_start + (self.total - cur_start) / faltam
                if (faltam > 1
                        and end >= alvo
                        and (len(self.tracks) - i - 1) >= (faltam - 1)):
                    sides.append({"start": cur_start, "end": end,
                                  "tracks": cur})
                    cur, cur_start = [], end
            if cur:
                sides.append({"start": cur_start, "end": self.total,
                              "tracks": cur})
            return sides

        # E se o corte devolver um número ÍMPAR de lados, tente de novo
        # pedindo o par seguinte.
        #
        # **Sintoma:** 45 minutos em cinco faixas de nove saía com TRÊS
        # lados. O plano pedia dois; o teto físico não deixa três faixas de
        # nove no mesmo lado (27 > 26), então a regra 1 cortava por conta
        # própria e o resto sobrava num terceiro. Um plano maior deixa a
        # regra do equilíbrio distribuir antes de o teto precisar cortar.
        #
        # Poucas voltas, e a última resposta vale mesmo se ainda for ímpar:
        # há discos que simplesmente não se repartem em par abaixo do teto
        # (uma faixa maior que um lado, por exemplo), e inventar um lado
        # vazio para fechar a conta seria pior do que a contagem estranha.
        sides = cortar(n_sides)
        # ── o disco simples antes do duplo ────────────────────────────────
        # Quando o corte devolve MAIS lados do que o plano pedia, é porque as
        # faixas não se deixam repartir abaixo do lado confortável. Antes de
        # aceitar um disco a mais — que é a coisa mais cara que esta função
        # pode decidir —, tenta com o teto físico: 30 minutos, que é o que um
        # lado de verdade aguenta com o nível um pouco abaixo.
        if len(sides) > n_sides:
            folgado = cortar(n_sides, SIDE_HARD_SECONDS)
            if len(folgado) <= n_sides:
                sides = folgado
        for _ in range(3):
            if len(sides) <= 1 or len(sides) % 2 == 0:
                break
            n_sides = len(sides) + 1
            sides = cortar(n_sides)
        # Quantos DISCOS este álbum é — contado dos lados que EXISTEM, e não
        # dos que foram planejados.
        #
        # **Sintoma:** uma faixa única de uma hora dava "DISCO 2 · LADO A".
        # O plano pedia quatro lados (uma hora não cabe em dois), mas não se
        # corta uma música ao meio: sobra UM lado, e um lado é um disco. O
        # número vinha do plano e mentia sobre o objeto que está no prato.
        self.discos = max(1, (len(sides) + 1) // 2)
        for i, s in enumerate(sides):
            s["label"] = "SIDE " + chr(ord("A") + i)
        self.sides = sides

    # ── o que o objeto pede quando um lado começa ─────────────────────────
    # Três telas dizem esta mesma frase — a notificação do
    # `stylus-side-watch`, a legenda do deck e o aviso de tela cheia do
    # lançador — e as três a escreviam por conta própria, todas perguntando
    # "este é o último lado?". Num LP de dois lados isso acerta por
    # acidente; num DUPLO, A→B mandava "agora o LADO B" (e ali se vira o
    # disco) e B→C mandava "agora o LADO C" (e ali se TROCA de disco, que é
    # outro gesto: você levanta e vai até a estante).
    #
    # A pergunta certa é "que gesto o objeto pede?", e o objeto responde pelo
    # ÍNDICE: lado ímpar é o verso do que já está no prato; lado par é o
    # começo de outro disco. Mora aqui, junto dos lados, pelo mesmo motivo
    # que as cores moram no `palette`: uma frase escrita em três lugares
    # deriva, e derivou.

    def rotulo_do_lado(self, i):
        """LADO A, LADO B… — o vocabulário do sistema, do lado `i`."""
        lados = self.sides or ()
        if 0 <= i < len(lados):
            return (lados[i].get("label") or "LADO").replace("SIDE", "LADO")
        return "LADO"

    def gesto_do_lado(self, i):
        """"vire o disco para o LADO B" / "ponha o DISCO 2, LADO C"."""
        rot = self.rotulo_do_lado(i)
        if i % 2 == 1:
            return "vire o disco para o %s" % rot
        if i > 0 and getattr(self, "discos", 1) > 1:
            return "ponha o DISCO %d, %s" % (i // 2 + 1, rot)
        return "agora o %s" % rot

    def side_for(self, t):
        for i, s in enumerate(self.sides):
            if t < s["end"] - 1e-6:
                return i, s
        if self.sides:
            return len(self.sides) - 1, self.sides[-1]
        return 0, {"label": "SIDE A", "start": 0.0,
                   "end": max(1.0, self.total), "tracks": []}

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
            arq = find_lrc(tr.get("path"))
            tr["lrc"] = parse_lrc(arq) if arq else []
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

    ── e por que o caminho ganha do número TAMBÉM sob mpv ────────────────────
    Havia um `if album is None or snap.get("source") == "mpv": return idx`
    aqui, com a justificativa de que o lançador monta a lista com a mesma
    `track_paths()` — então índice do mpv == índice do álbum, por construção.

    Só que a lista do mpv pode ser REORDENADA depois de montada: o `[s]` da
    tela cheia manda `playlist-shuffle`. A partir daí o `playlist-pos` é a
    posição na lista embaralhada e não a faixa do disco, e tudo que se conta a
    partir dele sai errado junto — o nome da faixa na AGORA, o LADO e o "vira
    em 6 min", a agulha no sulco do deck, e o índice gravado na agulha.tsv
    para retomar depois. O caminho não tem esse problema: ele é a faixa.

    O número continua sendo a resposta quando o caminho não casa — disco que
    vem pela rede depois de reassinado (o endereço muda), tocador que não
    entrega caminho nenhum.
    """
    idx = snap.get("track_index", 0) or 0
    if album is None:
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
    if path and path.startswith(("http://", "https://")):
        f = _pasta_da_transmissao(path)
        if f:
            return f
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


CACHE_QOBUZ = os.path.expanduser("~/.cache/stylus/qobuz")


def _pasta_da_transmissao(url):
    """De um endereço tocando de volta para a pasta que o descreve.

    O `stylus qobuz tocar` guarda a lista do mpv e um disco.json numa pasta
    de cache por álbum. Aqui se procura, entre elas, a que contém ESTE
    endereço — e a partir dela um disco transmitido vira um Album igual aos
    outros, com lados e tudo.

    A busca é pelo `eid=` (o identificador da faixa dentro do endereço) e não
    pelo endereço inteiro: o resto dele carrega uma assinatura com prazo, e
    comparar a linha toda daria erro no dia em que o mpv pedisse o endereço
    de novo.
    """
    m = re.search(r"[?&]eid=(\d+)", url)
    alvo = "eid=%s" % m.group(1) if m else url
    try:
        artistas = os.listdir(CACHE_QOBUZ)
    except OSError:
        return None
    for a in artistas:
        ap = os.path.join(CACHE_QOBUZ, a)
        try:
            discos = os.listdir(ap)
        except OSError:
            continue
        for d in discos:
            dp = os.path.join(ap, d)
            lista = os.path.join(dp, "lista.m3u")
            if not os.path.isfile(lista):
                continue
            try:
                with open(lista, encoding="utf-8") as fh:
                    if alvo in fh.read():
                        return dp
            except OSError:
                continue
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ═══════════════════════════════════════════════════════════════════════════
# A GEOMETRIA DO DISCO SAIU DAQUI
# ═══════════════════════════════════════════════════════════════════════════
# Eram ~450 linhas de numpy que devolviam vértices prontos para o OpenGL: o
# corpo do disco, os sulcos, o anel do intervalo, o sulco ao vivo, as marcas
# de uso, o braço e a classe `Deck` (a cerimônia como máquina de estados).
# Quem consumia era o deck — `scope.py` e `ritual.py` —, e o deck não existe
# mais: o que ele desenhava, a tela cheia do lançador desenha melhor, com
# pygame, sem GL e sem venv (ver `NowScreen._cheia` no ui/app.py).
#
# Não ficaram aqui "por precaução". Código que ninguém chama é pior do que
# código nenhum: ele lê como um recurso que existe, e da próxima vez alguém
# liga o fio nele — foi assim com o `set_text` do deck e com os campos mortos
# do `Deck`. Está tudo no histórico do git, que é onde uma coisa que ninguém
# executa deve morar.
#
# O que FICOU, porque a tela cheia usa: os raios do disco (R_OUTER e
# companhia), a repartição em lados (`Album._build_sides`), o gesto do fim do
# lado, e os três segundos da cerimônia logo abaixo.


# ═══════════════════════════════════════════════════════════════════════════
# A cerimônia — quanto dura cada parte da descida da agulha
# ═══════════════════════════════════════════════════════════════════════════
# Três números, e eles moram AQUI porque três lugares os desenham ou esperam
# por eles: a tela cheia do lançador (`NowScreen._cerimonia`), a AGORA
# pequena, e o `stylus-deck`, que segura o som pausado até a agulha encostar.
# Cópias à mão derivam, e o sintoma dessa deriva é o som entrando antes ou
# depois do desenho — que é a única coisa que estes segundos existem para
# acertar.
#
# Os estados nomeados e as durações do LIFT/RETURN/TRAVEL saíram junto com a
# classe `Deck`: eram a máquina de estados do deck, e nada os lia mais.
SPINUP_T = 1.1    # o prato saindo do zero — honesto, não é tela de espera
CUE_T    = 1.05   # o braço indo até a faixa de entrada
DROP_T   = 0.55   # a agulha descendo — rápido, decidido


