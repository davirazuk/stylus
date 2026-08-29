"""STYLUS — a coleção, do ponto de vista da interface.

O que este arquivo resolve: a estante tem centenas de discos e a interface
tem 60 quadros por segundo. Ler tags, medir durações e decodificar capas são
todas coisas caras demais para acontecerem dentro do laço de desenho, e
esperar por elas antes de mostrar qualquer coisa faz o programa parecer
travado na abertura.

Então tudo aqui é: um índice barato lido de uma vez, um cache em disco para o
que é caro, e threads para o resto. A regra é que a interface NUNCA bloqueia
— se um dado ainda não chegou, desenha-se o lugar dele.
"""
import hashlib
import json
import os
import threading
import time

import pygame

import vinyl

CACHE = os.path.expanduser("~/.cache/stylus")
THUMBS = os.path.join(CACHE, "thumbs")
INDEX = os.path.join(CACHE, "shelf.json")
THUMB_PX = 320
THUMB_HI = 640  # AGORA — capa grande precisa ser nítida, não 320 esticado


def _key(path):
    return hashlib.blake2s(path.encode("utf-8", "replace"),
                           digest_size=16).hexdigest()


class Shelf:
    """O índice da estante: um disco por entrada, barato de montar.

    Não guarda duração nem faixas — só o que a grade precisa para desenhar
    (artista, nome, capa, quantas faixas, quando foi a última vez). Abrir um
    disco de verdade é vinyl.Album, e isso só acontece quando você escolhe um.
    """

    def __init__(self):
        self.items = []
        self.ready = False
        self.scanning = False
        self.error = None

    def load(self):
        """Mostra o índice velho na hora e revarre por trás.

        Um índice de ontem está certo em 99% das linhas e aparece
        instantaneamente; esperar a varredura para mostrar a primeira capa
        seria trocar um erro raro por uma espera garantida.
        """
        try:
            with open(INDEX, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and data:
                self.items = data
                self.ready = True
        except (OSError, ValueError):
            pass
        self.rescan()

    def rescan(self):
        if self.scanning:
            return
        self.scanning = True
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        try:
            folders = vinyl.shelf(min_tracks=1)
            seen = vinyl.last_played()
            plays = {}
            for ts, fold in vinyl._play_rows():
                k = os.path.normpath(fold)
                plays[k] = plays.get(k, 0) + 1
            out = []
            for f in folders:
                artist, name = vinyl.folder_names(f)
                # conta recursivo até 3 níveis (Disc 01/Disc 02, webdav subpastas)
                try:
                    # usa o mesmo coletor do vinyl para não divergir
                    n = len(vinyl._collect_audio_recursive(f))
                    entries = os.listdir(f)
                except OSError:
                    continue
                if n == 0:
                    try:
                        n = sum(1 for e in os.listdir(f) if e.lower().endswith(vinyl.AUDIO_EXT))
                        entries = os.listdir(f)
                    except OSError:
                        n = 0
                # Quem escolhe a capa é o vinyl, com a lista canônica e sem
                # olhar maiúscula — eram duas listas diferentes e a daqui
                # caía em "a primeira imagem em ordem alfabética", que numa
                # pasta vinda do Windows é a contracapa ou a miniatura.
                cover = vinyl.find_cover(f, entries)
                k = os.path.normpath(f)
                out.append({"folder": f, "artist": artist, "name": name,
                            "tracks": n, "cover": cover,
                            "last": seen.get(k, 0), "plays": plays.get(k, 0)})
            out.sort(key=lambda d: (d["artist"].lower(), d["name"].lower()))
            self.items = out
            self.ready = True
            try:
                os.makedirs(CACHE, exist_ok=True)
                with open(INDEX, "w", encoding="utf-8") as fh:
                    json.dump(out, fh)
            except OSError:
                pass
        except Exception as e:            # noqa: BLE001 — a grade não pode morrer
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.scanning = False

    def artists(self):
        out = {}
        for it in self.items:
            out.setdefault(it["artist"], []).append(it)
        return out


class Thumbs:
    """Capas em miniatura, decodificadas fora do laço de desenho.

    Uma capa de disco costuma ser um JPEG de 1400x1400. Decodificar trinta
    deles a 60fps é impossível e desnecessário — a grade mostra 320px. O
    cache em disco é o que faz a segunda abertura do programa ser instantânea.
    """

    def __init__(self, px=THUMB_PX):
        self.px = px
        self.mem = {}
        self.pending = set()
        self.lock = threading.Lock()

    def _thumb_path(self, cover):
        return os.path.join(THUMBS, f"{_key(cover)}-{self.px}.jpg")

    def get(self, cover):
        """A miniatura, ou None enquanto ela não existir. Nunca bloqueia."""
        if not cover:
            return None
        if cover in self.mem:
            return self.mem[cover]
        with self.lock:
            if cover in self.pending:
                return None
            self.pending.add(cover)
        threading.Thread(target=self._make, args=(cover,), daemon=True).start()
        return None

    def _baixar(self, url):
        """Uma capa que mora na internet, trazida para o cache.

        A loja do Qobuz devolve endereço, não caminho — e sem isto a única
        tela do sistema que mostra discos sem mostrar capa era justamente a
        que tem capa de sobra para mostrar. Como já é uma thread própria, a
        espera de rede não custa quadro nenhum.
        """
        import urllib.request
        alvo = os.path.join(THUMBS, f"{_key(url)}-orig")
        if os.path.isfile(alvo):
            return alvo
        os.makedirs(THUMBS, exist_ok=True)
        with urllib.request.urlopen(url, timeout=20) as r:
            dados = r.read()
        # Pelo .parcial: um download interrompido deixaria um jpeg truncado
        # no cache, e o `isfile` acima nunca mais tentaria de novo.
        with open(alvo + ".parcial", "wb") as fh:
            fh.write(dados)
        os.replace(alvo + ".parcial", alvo)
        return alvo

    def _make(self, cover):
        try:
            tp = self._thumb_path(cover)
            if not os.path.isfile(tp):
                from PIL import Image
                os.makedirs(THUMBS, exist_ok=True)
                origem = (self._baixar(cover)
                          if cover.startswith(("http://", "https://"))
                          else cover)
                im = Image.open(origem)
                im.draft("RGB", (self.px * 2, self.px * 2))   # decodifica menos
                im = im.convert("RGB")
                im.thumbnail((self.px, self.px), Image.LANCZOS)
                im.save(tp, "JPEG", quality=88)
            surf = pygame.image.load(tp)
            self.mem[cover] = surf.convert()
        except Exception:                 # noqa: BLE001 — capa ruim não derruba nada
            self.mem[cover] = None
        finally:
            with self.lock:
                self.pending.discard(cover)


class Playing:
    """O que está tocando, perguntado fora do laço de desenho.

    Reaproveita o vinyl.Session, que já resolve a parte difícil (socket do
    mpv primeiro, MPRIS depois) e já pesquisa numa thread própria. Aqui em
    cima só se acrescenta o ÁLBUM: a interface quer saber o lado e quanto
    falta, não só o nome da faixa.
    """

    def __init__(self):
        self.session = vinyl.Session()
        self.album = None
        self._key = None
        self._resolving = False
        self._tentei = 0.0
        self._ti_cache = [None, 0]

    def snapshot(self):
        snap = self.session.snapshot()
        path = snap.get("path") or ""
        folder = os.path.dirname(path) if path else ""
        key = (folder, snap.get("artist"), snap.get("album"))
        trocou = key != self._key and any(key)
        # DISCO DA REDE: o `dirname` de um ENDEREÇO é a mesma string para toda
        # playlist do Qobuz ("https:/o-servidor"), e sob mpv o artista e o
        # álbum do snapshot vêm vazios — só o MPRIS os preenche. Ou seja: a
        # chave acima é a MESMA para todas elas, e trocar de playlist deixava
        # a AGORA com o disco anterior na mão: o nome da faixa, o LADO, o
        # "vira em X" e a agulha no sulco, todos da lista de antes. O mesmo
        # defeito que o stylus-side-watch tinha.
        #
        # A pergunta certa é se o endereço que está tocando ainda é uma das
        # FAIXAS do disco que temos na mão. Com uma pausa entre tentativas,
        # porque resolver um endereço varre o cache do Qobuz.
        if not trocou and path.startswith(("http://", "https://")):
            al = self.album
            fora = al is None or not any(t.get("path") == path
                                         for t in al.tracks)
            if fora and time.time() - self._tentei > 20.0:
                self._tentei = time.time()
                trocou = True
        if trocou and not self._resolving:
            self._key = key
            self._resolving = True
            threading.Thread(target=self._resolve, args=(snap,),
                             daemon=True).start()
        return snap

    def _resolve(self, snap):
        try:
            f = vinyl.resolve_album(snap.get("path"), snap.get("artist", ""),
                                    snap.get("album", ""))
            self.album = vinyl.Album(f, envelope=False) if f else None
        except (OSError, IOError, ValueError, KeyError):
            # Erros esperados: arquivo movido, permissão negada, formato ruim
            self.album = None
        except Exception as e:
            # Erro inesperado: ao menos log para debug (não trata silenciosamente)
            import sys
            print(f"stylus: erro ao carregar álbum: {type(e).__name__}: {e}",
                  file=sys.stderr)
            self.album = None
        finally:
            self._resolving = False

    def where(self):
        """(álbum, faixa, lado, t_abs, frac_do_lado) — ou Nones."""
        snap = self.snapshot()
        al = self.album
        if al is None or not al.total:
            return snap, None, None, None, 0.0, 0.0
        idx = vinyl.track_index_for(al, snap, self._ti_cache)
        pos, _dur = self.session.position()
        t_abs = al.album_time(idx, pos)
        _i, side = al.side_for(t_abs)
        frac = 0.0
        if side:
            span = max(1e-6, side["end"] - side["start"])
            frac = min(1.0, max(0.0, (t_abs - side["start"]) / span))
        track = al.tracks[idx] if 0 <= idx < len(al.tracks) else None
        return snap, al, track, side, t_abs, frac


def plural(n, um, muitos=None):
    """"1 disco", "2 discos" — o `s` que faltava em quinze lugares.

    **Sintoma:** "1 faixas", "1 discos", "posto há 1 meses", "1 discos · 1
    vezes". Não derruba nada e não aparece em teste nenhum; só faz o sistema
    parecer traduzido por máquina, e o texto que a pessoa vê é a única parte
    dele que ela lê inteira.

    Estava escrito à mão em cada lugar (`f"{n} faixas"`), que é a mesma
    doença das cores e das listas de extensão: a regra existe uma vez e é
    copiada quinze — e basta uma cópia esquecer o caso do 1.
    """
    muitos = muitos or (um + "s")
    return "%d %s" % (n, um if abs(n) == 1 else muitos)


def humano(seg):
    seg = int(max(0, seg))
    h, m = divmod(seg // 60, 60)
    return f"{h}h{m:02d}" if h else f"{m}min"


def relogio(seg):
    seg = int(max(0, seg))
    return f"{seg // 60}:{seg % 60:02d}"


def ha_quanto(ts):
    """Quando este disco foi posto pela última vez, em português corrido.

    Devolve a frase inteira e não só o tempo. **Sintoma:** o rodapé da
    estante mostrava "Aphex Twin — Selected Ambient Works · nunca · enter
    põe…", e aquele "nunca" solto no meio não dizia nunca O QUÊ. "hoje" e
    "há 3 dias" ainda se adivinham; "nunca" sozinho é só uma palavra caída
    no meio de uma linha de atalhos.
    """
    if not ts:
        return "nunca posto"
    d = (time.time() - ts) / 86400.0
    if d < 1:
        return "posto hoje"
    if d < 2:
        return "posto ontem"
    if d < 30:
        return "posto há %s" % plural(int(d), "dia")
    if d < 365:
        return "posto há %s" % plural(int(d / 30), "mês", "meses")
    return "posto há %s" % plural(int(d / 365), "ano")
