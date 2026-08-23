#!/usr/bin/env python3
"""STYLUS — a tela cheia. Tudo o que o sistema faz com música, num lugar só.

POR QUE ISTO EXISTE
-------------------
As ferramentas de linha de comando deste sistema são boas e eu não vou tirar
nenhuma. Mas "qual disco eu ponho agora" não é uma pergunta de terminal. É
uma pergunta que se responde passando o olho por uma prateleira, e a resposta
vem de uma capa te chamando — não de uma lista de nomes, que é um índice, e a
resposta honesta a um índice sempre acaba sendo "embaralha".

Então isto é uma estante antes de ser um menu. A grade de capas é a tela
principal e todo o resto é secundário a ela.

COMO SE MEXE
------------
    setas / hjkl      andar          enter    pôr o disco
    tab / q           voltar         esc      sair
    1-9               ir direto para uma seção
    /                 procurar
    barra de espaço   pausa
    controle          d-pad anda, A põe, B volta

NAVEGAÇÃO POR CONTROLE É REQUISITO, NÃO ENFEITE: metade do valor de uma tela
cheia de música é poder usá-la do outro lado do quarto.
"""
import math
import os
import subprocess
import sys
import threading
import time

import pygame

sys.path.insert(0, "/usr/share/stylus/deck")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vinyl                                            # noqa: E402
import theme as T                                       # noqa: E402
from model import (Playing, Shelf, Thumbs, ha_quanto,    # noqa: E402
                   humano, relogio)

FPS = 60


# ═══════════════════════════════════════════════════════════════════════════
# Infraestrutura
# ═══════════════════════════════════════════════════════════════════════════
def spawn(cmd):
    """Roda uma coisa e esquece dela.

    start_new_session porque o filho tem que sobreviver a esta janela: pôr um
    disco e depois fechar a tela cheia não pode parar a música.
    """
    try:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


class Job:
    """Um comando cuja saída aparece na tela enquanto ele roda.

    A alternativa era abrir um terminal, e abrir um terminal é exatamente o
    que esta tela existe para evitar.
    """

    def __init__(self, cmd, title):
        self.cmd = cmd
        self.title = title
        self.lines = []
        self.done = False
        self.rc = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            p = subprocess.Popen(self.cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 bufsize=1, errors="replace")
            for line in p.stdout:
                # Sem limite, um `check` de coleção grande vira centenas de
                # milhares de linhas na memória de um programa que só mostra
                # as últimas trinta.
                self.lines.append(line.rstrip("\n"))
                del self.lines[:-400]
            p.wait()
            self.rc = p.returncode
        except OSError as e:
            self.lines.append(f"não deu para rodar: {e}")
            self.rc = 127
        finally:
            self.done = True


class Screen:
    """Uma seção. Desenha, recebe tecla, e sabe o próprio nome."""
    name = "?"
    icon = ""
    key_hint = ""

    def __init__(self, app):
        self.app = app

    def enter(self):
        pass

    def key(self, ev):
        return False

    def draw(self, s, r):
        pass


# ═══════════════════════════════════════════════════════════════════════════
# AGORA — o disco que está tocando
# ═══════════════════════════════════════════════════════════════════════════
class NowScreen(Screen):
    name = "AGORA"
    icon = "󰲸"

    def key(self, ev):
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            # Abre O DECK no disco que JÁ está tocando, sem reiniciar nada: o
            # scope acha a posição sozinho pelo socket do mpv ou pelo MPRIS.
            # Reabrir o arquivo aqui recomeçaria a faixa, que é o oposto do
            # que "ver o disco" deveria custar.
            self.app.open_deck()
            return True
        if ev.key == pygame.K_SPACE:
            spawn(["playerctl", "play-pause"])
            return True
        if ev.key == pygame.K_n:
            spawn(["playerctl", "next"])
            return True
        if ev.key == pygame.K_p:
            spawn(["playerctl", "previous"])
            return True
        return False

    def draw(self, s, r):
        snap, al, track, side, t_abs, frac = self.app.playing.where()
        if al is None:
            self._nothing(s, r)
            return

        # ── a capa, grande, à esquerda. É o objeto; ela manda na tela. ─────
        size = min(r.h - 220, 460)
        cov = self.app.thumbs.get(al.cover) if al.cover else None
        cr = pygame.Rect(r.x + 40, r.y + 40, size, size)
        T.shadow_card(s, cr, radius=8)
        if cov:
            s.blit(pygame.transform.smoothscale(cov, (size, size)), cr)
        else:
            T.panel(s, cr, T.INK_LIFT, radius=8)
            T.text(s, "sem capa", cr.center, 18, T.TEXT_FAINT, anchor="center")

        x = cr.right + 44
        w = r.right - x - 40
        T.text(s, al.artist.upper(), (x, r.y + 46), 22, T.TEXT_DIM, maxw=w)
        T.text(s, al.name, (x, r.y + 78), 40, T.TEXT, bold=True, maxw=w)
        if al.year:
            T.text(s, str(al.year), (x, r.y + 130), 20, T.TEXT_FAINT)

        # ── onde no LADO. o número que um disco te dá e um tocador não. ────
        y = r.y + 186
        if side:
            resta = max(0.0, side["end"] - t_abs)
            ultimo = side is al.sides[-1]
            rotulo = side["label"].replace("SIDE", "LADO")
            T.text(s, rotulo, (x, y), 26, T.BLUE, bold=True)
            T.text(s, ("acaba em " if ultimo else "vira em ") + humano(resta),
                   (x + 130, y + 4), 20, T.TEXT_DIM)
            self._groove(s, pygame.Rect(x, y + 44, w, 10), frac)
            y += 76

        if track:
            n = (al.tracks.index(track) + 1) if track in al.tracks else 0
            T.text(s, f"{n:02d}  {track.get('title') or ''}", (x, y), 26,
                   T.TEXT, maxw=w)
            y += 40

        # ── a letra do momento. a metade encarte do ritual. ────────────────
        line = self.app.current_lyric(al, track)
        if line:
            T.text(s, line, (x, y + 8), 24, T.LAV, maxw=w)
        y += 56

        hist = f"{al.plays}ª vez" if al.plays else "primeira vez"
        T.text(s, f"{hist}  ·  {len(al.tracks)} faixas  ·  "
                  f"{humano(al.total)}  ·  {ha_quanto(al.last_played)}",
               (x, r.bottom - 92), 18, T.TEXT_FAINT, maxw=w)
        self.app.hint(s, r, "enter abrir o deck   espaço pausa   n/p faixa")

    def _groove(self, s, rect, frac):
        """A barra de progresso desenhada como um sulco, não como um tubo.

        A diferença não é decorativa: um sulco tem começo na borda e fim no
        centro, e é isso que a barra está representando.
        """
        pygame.draw.rect(s, T.LINE, rect, border_radius=5)
        f = pygame.Rect(rect.x, rect.y, int(rect.w * frac), rect.h)
        pygame.draw.rect(s, T.BLUE, f, border_radius=5)
        pygame.draw.circle(s, T.TEXT, (f.right, rect.centery), 7)

    def _nothing(self, s, r):
        cx, cy = r.centerx, r.centery
        t = time.time()
        # um disco parado, girando devagar, só para a tela não estar morta
        for i in range(7):
            rr = 60 + i * 26
            pygame.draw.circle(s, T.lerp(T.INK_SOFT, T.LINE, 0.4 + i * 0.08),
                               (cx, cy - 40), rr, 1)
        ang = (t * 0.35) % (2 * math.pi)
        pygame.draw.line(s, T.LINE, (cx, cy - 40),
                         (cx + math.cos(ang) * 180, cy - 40 + math.sin(ang) * 180), 1)
        T.text(s, "nada tocando", (cx, cy + 190), 30, T.TEXT_DIM, anchor="center")
        T.text(s, "vá para a ESTANTE e escolha um disco",
               (cx, cy + 228), 20, T.TEXT_FAINT, anchor="center")


# ═══════════════════════════════════════════════════════════════════════════
# ESTANTE — a grade de capas. A tela principal.
# ═══════════════════════════════════════════════════════════════════════════
class ShelfScreen(Screen):
    name = "ESTANTE"
    icon = "󰀥"

    COLS = 6

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.scroll = 0.0
        self.target = 0.0
        self.query = ""
        self.searching = False
        self.order = "artista"

    # ── quais discos, nesta ordem ──────────────────────────────────────────
    def items(self):
        its = self.app.shelf.items
        if self.query:
            q = self.query.lower()
            its = [i for i in its
                   if q in i["artist"].lower() or q in i["name"].lower()]
        if self.order == "esquecidos":
            its = sorted(its, key=lambda i: i["last"])
        elif self.order == "mais postos":
            its = sorted(its, key=lambda i: -i["plays"])
        return its

    def key(self, ev):
        its = self.items()
        n = len(its)
        if self.searching:
            if ev.key == pygame.K_ESCAPE:
                self.searching, self.query = False, ""
            elif ev.key == pygame.K_RETURN:
                self.searching = False
            elif ev.key == pygame.K_BACKSPACE:
                self.query = self.query[:-1]
            elif ev.unicode and ev.unicode.isprintable():
                self.query += ev.unicode
            self.sel = 0
            return True
        if ev.key == pygame.K_SLASH:
            self.searching, self.query = True, ""
            return True
        if ev.key == pygame.K_o:
            ordens = ["artista", "esquecidos", "mais postos"]
            self.order = ordens[(ordens.index(self.order) + 1) % len(ordens)]
            self.sel = 0
            return True
        if not n:
            return False
        if ev.key in (pygame.K_RIGHT, pygame.K_l):
            self.sel = min(n - 1, self.sel + 1)
        elif ev.key in (pygame.K_LEFT, pygame.K_h):
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = min(n - 1, self.sel + self.COLS)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = max(0, self.sel - self.COLS)
        elif ev.key == pygame.K_PAGEDOWN:
            self.sel = min(n - 1, self.sel + self.COLS * 3)
        elif ev.key == pygame.K_PAGEUP:
            self.sel = max(0, self.sel - self.COLS * 3)
        elif ev.key == pygame.K_HOME:
            self.sel = 0
        elif ev.key == pygame.K_END:
            self.sel = n - 1
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.app.put_on(its[self.sel]["folder"])
        elif ev.key == pygame.K_s:
            self.app.stack_add(its[self.sel])
        elif ev.key == pygame.K_r:
            d = vinyl.draw_record([i["folder"] for i in its])
            if d:
                self.app.put_on(d)
        else:
            return False
        return True

    def draw(self, s, r):
        its = self.items()
        pad, gap = 30, 18
        cw = (r.w - pad * 2 - gap * (self.COLS - 1)) // self.COLS
        ch = cw + 62
        head = 58

        if not self.app.shelf.ready:
            T.text(s, "lendo a estante…", (r.centerx, r.centery), 26,
                   T.TEXT_DIM, anchor="center")
            return
        if not its:
            msg = (f'nada com "{self.query}"' if self.query
                   else "a estante está vazia")
            T.text(s, msg, (r.centerx, r.centery), 26, T.TEXT_DIM,
                   anchor="center")
            if not self.query:
                T.text(s, "`stylus library ~/Music` diz onde ela fica",
                       (r.centerx, r.centery + 36), 19, T.TEXT_FAINT,
                       anchor="center")
            return

        # ── cabeçalho: contagem, ordem, busca ──────────────────────────────
        if self.searching or self.query:
            T.text(s, "/ " + self.query + ("▌" if self.searching else ""),
                   (r.x + pad, r.y + 16), 24, T.BLUE)
        else:
            T.text(s, f"{len(its)} discos", (r.x + pad, r.y + 18), 22,
                   T.TEXT_DIM)
        T.text(s, self.order, (r.right - pad, r.y + 20), 19, T.TEXT_FAINT,
               anchor="topright")

        # ── rolagem que persegue a seleção em vez de saltar ────────────────
        row = self.sel // self.COLS
        view_h = r.h - head - 96
        rows_vis = max(1, view_h // ch)
        if row * ch < self.target:
            self.target = row * ch
        elif (row + 1) * ch > self.target + rows_vis * ch:
            self.target = (row + 1 - rows_vis) * ch
        self.target = max(0, min(self.target,
                                 max(0, (len(its) + self.COLS - 1)
                                     // self.COLS - rows_vis) * ch))
        self.scroll += (self.target - self.scroll) * 0.22

        clip = pygame.Rect(r.x, r.y + head, r.w, view_h)
        old = s.get_clip()
        s.set_clip(clip)
        for i, it in enumerate(its):
            cx = r.x + pad + (i % self.COLS) * (cw + gap)
            cy = r.y + head + (i // self.COLS) * ch - int(self.scroll)
            if cy > clip.bottom or cy + ch < clip.top:
                continue
            self._card(s, pygame.Rect(cx, cy, cw, cw), it, i == self.sel)
            ty = cy + cw + 8
            T.text(s, it["name"], (cx, ty), 17,
                   T.TEXT if i == self.sel else T.TEXT_DIM, maxw=cw)
            T.text(s, it["artist"], (cx, ty + 22), 15, T.TEXT_FAINT, maxw=cw)
        s.set_clip(old)

        sel = its[self.sel]
        self.app.hint(
            s, r,
            f"{sel['artist']} — {sel['name']}   ·   {ha_quanto(sel['last'])}"
            f"   ·   enter põe   s empilha   r sorteia   o ordem   / procura")

    def _card(self, s, rect, it, selected):
        if selected:
            glow = rect.inflate(14, 14)
            pygame.draw.rect(s, T.lerp(T.INK, T.BLUE, 0.35), glow,
                             border_radius=10)
        T.shadow_card(s, rect, radius=6)
        cov = self.app.thumbs.get(it["cover"])
        if cov:
            s.blit(pygame.transform.smoothscale(cov, rect.size), rect)
        else:
            T.panel(s, rect, T.INK_LIFT, radius=6)
            T.text(s, it["name"][:2].upper(), rect.center, 40, T.TEXT_FAINT,
                   anchor="center")
        # ── o desgaste, na própria capa ────────────────────────────────────
        # Um disco muito posto tem que PARECER muito posto quando você passa
        # o olho pela estante. É a mesma ideia das marcas no deck, trazida
        # para onde a escolha realmente acontece.
        if it["plays"]:
            n = min(5, it["plays"])
            for k in range(n):
                pygame.draw.circle(s, T.PINK,
                                   (rect.right - 12 - k * 9, rect.bottom - 12), 3)


# ═══════════════════════════════════════════════════════════════════════════
# A PILHA — os discos da noite, encostados no toca-discos
# ═══════════════════════════════════════════════════════════════════════════
class StackScreen(Screen):
    """Empilhar discos para a noite é uma coisa que só existe no mundo físico
    e que nenhum tocador digital reproduz. Uma fila de reprodução não é a
    mesma coisa: fila é uma lista de músicas que o programa consome sozinho,
    pilha é um compromisso que VOCÊ assume com três discos e depois cumpre um
    de cada vez, levantando entre eles.

    Por isso a pilha aqui não toca sozinha. Quando um disco acaba, o de cima
    fica esperando — e pôr ele é um gesto seu.
    """
    name = "A PILHA"
    icon = "󰙨"

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0

    def key(self, ev):
        st = self.app.stack
        if not st:
            if ev.key == pygame.K_t:
                self.app.stack_tonight()
                return True
            return False
        self.sel = min(self.sel, len(st) - 1)
        if ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = min(len(st) - 1, self.sel + 1)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            it = st.pop(self.sel)
            self.app.stack_save()
            self.app.put_on(it["folder"])
        elif ev.key in (pygame.K_x, pygame.K_DELETE, pygame.K_BACKSPACE):
            st.pop(self.sel)
            self.app.stack_save()
        elif ev.key == pygame.K_t:
            self.app.stack_tonight()
        else:
            return False
        return True

    def draw(self, s, r):
        st = self.app.stack
        if not st:
            T.text(s, "a pilha está vazia", (r.centerx, r.centery - 30), 30,
                   T.TEXT_DIM, anchor="center")
            T.text(s, "na estante, s empilha um disco",
                   (r.centerx, r.centery + 12), 20, T.TEXT_FAINT, anchor="center")
            T.text(s, "ou t monta uma noite inteira daqui",
                   (r.centerx, r.centery + 42), 20, T.TEXT_FAINT, anchor="center")
            return
        total = 0.0
        x, y = r.x + 40, r.y + 34
        T.text(s, "hoje à noite", (x, y), 24, T.TEXT_DIM)
        y += 46
        for i, it in enumerate(st):
            sel = i == self.sel
            row = pygame.Rect(x, y, r.w - 80, 96)
            if sel:
                T.panel(s, row.inflate(16, 8), T.INK_LIFT, radius=10)
            cr = pygame.Rect(row.x, row.y, 84, 84)
            cov = self.app.thumbs.get(it["cover"])
            T.shadow_card(s, cr, radius=4)
            if cov:
                s.blit(pygame.transform.smoothscale(cov, cr.size), cr)
            else:
                T.panel(s, cr, T.INK_LIFT, radius=4)
            T.text(s, f"{i + 1}", (row.x - 18, row.y + 30), 22,
                   T.BLUE if sel else T.TEXT_FAINT, anchor="topright")
            T.text(s, it["name"], (cr.right + 20, row.y + 14), 24,
                   T.TEXT if sel else T.TEXT_DIM, maxw=row.w - 140)
            T.text(s, it["artist"], (cr.right + 20, row.y + 46), 18,
                   T.TEXT_FAINT, maxw=row.w - 140)
            total += it.get("mins", 0)
            y += 104
        if total:
            T.text(s, f"{int(total)} min de disco encostado no móvel",
                   (x, y + 8), 19, T.TEXT_FAINT)
        self.app.hint(s, r, "enter põe este e tira da pilha   x descarta   "
                            "t monta uma noite")


# ═══════════════════════════════════════════════════════════════════════════
# SINAL — o caminho do áudio, desenhado
# ═══════════════════════════════════════════════════════════════════════════
class SignalScreen(Screen):
    """A mesma coisa que `stylus audio` responde, mas como uma corrente que
    dá para olhar de longe. Verde do começo ao fim quer dizer que o arquivo
    está chegando ao conversor como foi gravado; um elo vermelho diz onde
    ele deixou de estar."""
    name = "SINAL"
    icon = "󰓃"

    def __init__(self, app):
        super().__init__(app)
        self.info = {}
        self.t = 0.0

    def enter(self):
        self.refresh()

    def refresh(self):
        threading.Thread(target=self._probe, daemon=True).start()

    def _probe(self):
        import json as _j
        out = {}
        try:
            raw = subprocess.run(["pw-dump"], capture_output=True, text=True,
                                 timeout=10).stdout
            dump = _j.loads(raw) if raw.strip() else []
            for o in dump:
                if o.get("type", "").endswith("Core"):
                    p = (o.get("info") or {}).get("props") or {}
                    out["graph"] = int(p.get("default.clock.force-rate")
                                       or p.get("default.clock.rate") or 0)
                if o.get("type", "").endswith("Node"):
                    p = (o.get("info") or {}).get("props") or {}
                    if (p.get("media.class") == "Audio/Sink"
                            and str(p.get("node.name", "")).startswith("alsa_output")):
                        out["dev"] = p.get("node.description") or p.get("node.name")
                        out["multi"] = bool(p.get("api.alsa.multirate"))
        except Exception:                 # noqa: BLE001
            pass
        snap, al, track, _s, _t, _f = self.app.playing.where()
        path = snap.get("path") or ""
        if path and os.path.isfile(path):
            out["file"] = os.path.basename(path)
            try:
                pr = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
                     "-show_entries",
                     "stream=sample_rate,bits_per_raw_sample,codec_name",
                     "-of", "default=nw=1", path],
                    capture_output=True, text=True, timeout=10).stdout
                for ln in pr.splitlines():
                    k, _, v = ln.partition("=")
                    if k == "sample_rate" and v.isdigit():
                        out["frate"] = int(v)
                    elif k == "bits_per_raw_sample" and v.isdigit():
                        out["fbits"] = int(v)
                    elif k == "codec_name":
                        out["codec"] = v.upper()
            except Exception:             # noqa: BLE001
                pass
        self.info = out

    def key(self, ev):
        if ev.key == pygame.K_RETURN:
            self.refresh()
            return True
        return False

    def draw(self, s, r):
        self.t += 1 / FPS
        if int(self.t * 2) % 6 == 0 and self.t > 1:
            self.refresh()
            self.t += 0.6
        i = self.info
        frate, graph = i.get("frate", 0), i.get("graph", 0)
        clean = bool(frate and graph and frate == graph)
        cor = T.GREEN if clean else (T.RED if frate else T.TEXT_FAINT)

        y = r.y + 60
        T.text(s, "o caminho do sinal", (r.x + 44, y), 30, T.TEXT, bold=True)
        T.text(s, "medido agora, não prometido na caixa",
               (r.x + 44, y + 40), 19, T.TEXT_FAINT)

        elos = [
            ("O ARQUIVO", i.get("file", "—"),
             f"{i.get('frate', 0) / 1000:g} kHz"
             + (f" · {i['fbits']} bit" if i.get("fbits") else "")
             + (f" · {i['codec']}" if i.get("codec") else "") if frate else "—"),
            ("O GRAFO", "PipeWire",
             f"{graph / 1000:g} kHz" if graph else "—"),
            ("O CONVERSOR", i.get("dev", "—"),
             "pode trocar de taxa" if i.get("multi") else "taxa travada"),
        ]
        bx, by, bw = r.x + 44, y + 96, min(r.w - 88, 900)
        for n, (titulo, nome, val) in enumerate(elos):
            box = pygame.Rect(bx, by + n * 132, bw, 104)
            T.panel(s, box, T.INK_SOFT, radius=12, border=T.LINE)
            T.text(s, titulo, (box.x + 24, box.y + 18), 16, T.TEXT_FAINT)
            T.text(s, str(nome), (box.x + 24, box.y + 44), 24, T.TEXT,
                   maxw=bw - 300)
            T.text(s, str(val), (box.right - 24, box.y + 44), 26,
                   cor if n < 2 else (T.GREEN if i.get("multi") else T.AMBER),
                   bold=True, anchor="topright")
            if n < len(elos) - 1:
                mx = box.centerx
                pygame.draw.line(s, cor, (mx, box.bottom + 4),
                                 (mx, box.bottom + 24), 3)
                pygame.draw.polygon(s, cor, [(mx - 7, box.bottom + 22),
                                             (mx + 7, box.bottom + 22),
                                             (mx, box.bottom + 30)])

        vy = by + 3 * 132 + 12
        if not frate:
            T.text(s, "ponha um disco para medir o caminho inteiro",
                   (bx, vy), 21, T.TEXT_FAINT)
        elif clean:
            T.text(s, "▸ sem conversão: o arquivo chega como foi gravado",
                   (bx, vy), 24, T.GREEN, bold=True)
        else:
            T.text(s, f"▸ reamostrado {frate / 1000:g} → {graph / 1000:g} kHz",
                   (bx, vy), 24, T.RED, bold=True)
            T.text(s, "algo mais está segurando o grafo nessa taxa, ou o "
                      "conversor ainda não soltou a anterior",
                   (bx, vy + 34), 18, T.TEXT_FAINT)
        self.app.hint(s, r, "atualiza sozinho   ·   enter força agora")


# ═══════════════════════════════════════════════════════════════════════════
# DIÁRIO — o que você pôs, e quando
# ═══════════════════════════════════════════════════════════════════════════
class DiaryScreen(Screen):
    """Uma coleção com memória é o que separa uma estante de uma pasta.

    O registro já existe (a barra e a cerimônia escrevem nele); o que faltava
    era poder OLHAR para ele. O calendário de baixo é a parte que surpreende:
    dá para ver as semanas em que você não ouviu nada.
    """
    name = "DIÁRIO"
    icon = "󰃭"

    def __init__(self, app):
        super().__init__(app)
        self.rows = []
        self.by_day = {}
        self.scroll = 0

    def enter(self):
        rows = sorted(vinyl._play_rows(), key=lambda x: -x[0])
        self.by_day = {}
        for ts, fold in rows:
            d = time.strftime("%Y-%m-%d", time.localtime(ts))
            self.by_day[d] = self.by_day.get(d, 0) + 1
        idx = {os.path.normpath(i["folder"]): i for i in self.app.shelf.items}
        seen, out = set(), []
        for ts, fold in rows:
            k = os.path.normpath(fold)
            if k in seen:
                continue
            seen.add(k)
            it = idx.get(k)
            out.append({"ts": ts, "folder": fold,
                        "artist": (it or {}).get("artist")
                                  or vinyl.folder_names(fold)[0],
                        "name": (it or {}).get("name")
                                or vinyl.folder_names(fold)[1],
                        "cover": (it or {}).get("cover"),
                        "plays": (it or {}).get("plays", 1)})
        self.rows = out

    def key(self, ev):
        if ev.key in (pygame.K_DOWN, pygame.K_j):
            self.scroll = min(max(0, len(self.rows) - 8), self.scroll + 1)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.scroll = max(0, self.scroll - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.rows:
            self.app.put_on(self.rows[self.scroll]["folder"])
        else:
            return False
        return True

    def draw(self, s, r):
        if not self.rows:
            T.text(s, "nada anotado ainda", (r.centerx, r.centery), 28,
                   T.TEXT_DIM, anchor="center")
            T.text(s, "o sistema anota sozinho toda vez que você põe um disco",
                   (r.centerx, r.centery + 36), 19, T.TEXT_FAINT, anchor="center")
            return
        x, y = r.x + 44, r.y + 30
        total = sum(self.by_day.values())
        T.text(s, f"{len(self.rows)} discos  ·  {total} vezes", (x, y), 24,
               T.TEXT_DIM)
        y += 46
        for i, it in enumerate(self.rows[self.scroll:self.scroll + 7]):
            sel = i == 0
            row = pygame.Rect(x, y, r.w - 88, 78)
            if sel:
                T.panel(s, row.inflate(16, 6), T.INK_LIFT, radius=10)
            cr = pygame.Rect(row.x, row.y, 66, 66)
            cov = self.app.thumbs.get(it["cover"])
            if cov:
                s.blit(pygame.transform.smoothscale(cov, cr.size), cr)
            else:
                T.panel(s, cr, T.INK_LIFT, radius=4)
            T.text(s, it["name"], (cr.right + 18, row.y + 8), 22,
                   T.TEXT if sel else T.TEXT_DIM, maxw=row.w - 380)
            T.text(s, it["artist"], (cr.right + 18, row.y + 38), 17,
                   T.TEXT_FAINT, maxw=row.w - 380)
            T.text(s, ha_quanto(it["ts"]), (row.right - 150, row.y + 20), 19,
                   T.TEXT_DIM, anchor="topright")
            T.text(s, f"{it['plays']}x", (row.right - 20, row.y + 20), 21,
                   T.PINK, anchor="topright")
            y += 84
        self._calendar(s, pygame.Rect(x, r.bottom - 132, r.w - 88, 84))
        self.app.hint(s, r, "enter põe de novo   ·   ↑↓ anda")

    def _calendar(self, s, rect):
        """Um ano em quadradinhos: uma coluna por semana, um por dia.

        Vale mais do que parece. Ver as semanas vazias é a única forma
        honesta de perceber que você passou um mês sem sentar para ouvir
        nada — o que é exatamente o hábito que este sistema existe para
        recuperar.
        """
        hoje = time.localtime()
        dias = 364
        cell = min(10, rect.w // 53 - 1)
        gap = 2
        base = time.time() - dias * 86400
        maxi = max(self.by_day.values()) if self.by_day else 1
        for d in range(dias + 1):
            ts = base + d * 86400
            lt = time.localtime(ts)
            key = time.strftime("%Y-%m-%d", lt)
            n = self.by_day.get(key, 0)
            wk = d // 7
            wd = int(time.strftime("%w", lt))
            x = rect.x + wk * (cell + gap)
            y = rect.y + wd * (cell + gap)
            if n:
                c = T.lerp(T.lerp(T.INK_LIFT, T.BLUE, 0.45), T.PINK,
                           min(1.0, (n - 1) / max(1, maxi - 1)))
            else:
                c = T.INK_SOFT
            pygame.draw.rect(s, c, (x, y, cell, cell), border_radius=2)
        T.text(s, f"um ano  ·  até {time.strftime('%d/%m', hoje)}",
               (rect.x, rect.bottom + 6), 15, T.TEXT_FAINT)


# ═══════════════════════════════════════════════════════════════════════════
# CELULAR
# ═══════════════════════════════════════════════════════════════════════════
class PhoneScreen(Screen):
    name = "CELULAR"
    icon = "󰄜"

    ACOES = [
        ("ver o que está diferente", ["stylus-phone", "status"]),
        ("sincronizar agora", ["stylus-phone", "sync", "--apply"]),
        ("só mandar o que falta lá", ["stylus-phone", "push", "--apply"]),
        ("mandar as playlists", ["stylus-phone", "playlists", "--apply"]),
        ("juntar o que você ouviu no celular", ["stylus-phone", "scrobbles"]),
        ("ligar o sincronizar-ao-plugar", ["stylus-phone", "watch", "--enable"]),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.job = None

    def key(self, ev):
        if ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % len(self.ACOES)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % len(self.ACOES)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.job is None or self.job.done:
                self.job = Job(self.ACOES[self.sel][1], self.ACOES[self.sel][0])
        else:
            return False
        return True

    def draw(self, s, r):
        x, y = r.x + 44, r.y + 34
        T.text(s, "o celular", (x, y), 30, T.TEXT, bold=True)
        T.text(s, "a coleção é a mesma nos dois lados; a parte difícil é "
                  "manter os dois honestos sobre qual cópia é a melhor",
               (x, y + 40), 18, T.TEXT_FAINT, maxw=r.w - 90)
        y += 92
        for i, (rotulo, _cmd) in enumerate(self.ACOES):
            sel = i == self.sel
            box = pygame.Rect(x, y, 460, 46)
            if sel:
                T.panel(s, box, T.INK_LIFT, radius=9)
            T.text(s, ("▸ " if sel else "  ") + rotulo, (box.x + 14, box.y + 12),
                   21, T.TEXT if sel else T.TEXT_DIM)
            y += 52
        self.app.job_panel(s, pygame.Rect(x + 500, r.y + 120,
                                          r.right - x - 544, r.h - 220),
                           self.job)
        self.app.hint(s, r, "enter roda   ·   nada aqui mexe no celular "
                            "sem você mandar")


# ═══════════════════════════════════════════════════════════════════════════
# BIBLIOTECA — as ferramentas, sem terminal
# ═══════════════════════════════════════════════════════════════════════════
class ToolsScreen(Screen):
    name = "OFICINA"
    icon = "󰒓"

    ACOES = [
        ("o que está quebrado aí dentro", ["stylus", "check"]),
        ("pôr cover.jpg onde falta", ["stylus", "covers", "--apply"]),
        ("procurar letras dos discos sem .lrc", ["stylus", "lyrics", "--all"]),
        ("arrumar tags e capa embutida", ["stylus", "tags"]),
        ("rasgar o CD da gaveta", ["stylus", "rip"]),
        ("refazer o índice da estante", ["stylus", "reindex"]),
        ("cópia de segurança para o Drive", ["stylus", "backup"]),
        ("atualizar o sistema", ["stylus-update", "--check"]),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.job = None

    def key(self, ev):
        if ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % len(self.ACOES)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % len(self.ACOES)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.job is None or self.job.done:
                self.job = Job(self.ACOES[self.sel][1], self.ACOES[self.sel][0])
        else:
            return False
        return True

    def draw(self, s, r):
        x, y = r.x + 44, r.y + 34
        T.text(s, "a oficina", (x, y), 30, T.TEXT, bold=True)
        T.text(s, "as mesmas ferramentas do terminal, sem o terminal",
               (x, y + 40), 18, T.TEXT_FAINT)
        y += 88
        for i, (rotulo, _c) in enumerate(self.ACOES):
            sel = i == self.sel
            box = pygame.Rect(x, y, 470, 44)
            if sel:
                T.panel(s, box, T.INK_LIFT, radius=9)
            T.text(s, ("▸ " if sel else "  ") + rotulo, (box.x + 14, box.y + 11),
                   20, T.TEXT if sel else T.TEXT_DIM)
            y += 50
        self.app.job_panel(s, pygame.Rect(x + 510, r.y + 120,
                                          r.right - x - 554, r.h - 220),
                           self.job)
        self.app.hint(s, r, "enter roda   ·   a saída aparece do lado")


# ═══════════════════════════════════════════════════════════════════════════
# JOGOS
# ═══════════════════════════════════════════════════════════════════════════
class GamesScreen(Screen):
    name = "JOGOS"
    icon = "󰊴"

    ACOES = [
        ("Steam", ["steam", "-bigpicture"], "steam"),
        ("Clone Hero", ["clonehero"], "clonehero"),
        ("Lutris", ["lutris"], "lutris"),
        ("Heroic", ["heroic"], "heroic"),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0

    def key(self, ev):
        if ev.key in (pygame.K_RIGHT, pygame.K_l, pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % len(self.ACOES)
        elif ev.key in (pygame.K_LEFT, pygame.K_h, pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % len(self.ACOES)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            nome, cmd, binario = self.ACOES[self.sel]
            import shutil as _sh
            if _sh.which(binario):
                self.app.toast(f"abrindo {nome}…")
                spawn(cmd)
            else:
                self.app.toast(f"{nome} não está instalado — "
                               f"`stylus app {binario}` resolve")
        else:
            return False
        return True

    def draw(self, s, r):
        import shutil as _sh
        x, y = r.x + 44, r.y + 40
        T.text(s, "jogos", (x, y), 30, T.TEXT, bold=True)
        T.text(s, "porque nem tudo é disco", (x, y + 40), 18, T.TEXT_FAINT)
        cw, gap = 240, 24
        for i, (nome, _c, binario) in enumerate(self.ACOES):
            box = pygame.Rect(x + i * (cw + gap), y + 96, cw, 150)
            sel = i == self.sel
            T.panel(s, box, T.INK_LIFT if sel else T.INK_SOFT, radius=14,
                    border=T.BLUE if sel else T.LINE)
            tem = bool(_sh.which(binario))
            T.text(s, nome, box.center, 26, T.TEXT if tem else T.TEXT_FAINT,
                   bold=True, anchor="center")
            if not tem:
                T.text(s, "não instalado", (box.centerx, box.centery + 34), 16,
                       T.TEXT_FAINT, anchor="center")
        self.app.hint(s, r, "enter abre")


# ═══════════════════════════════════════════════════════════════════════════
# AJUSTES
# ═══════════════════════════════════════════════════════════════════════════
class SettingsScreen(Screen):
    name = "AJUSTES"
    icon = "󰢻"

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.job = None

    def opcoes(self):
        return [
            (f"estante: {vinyl.library_root()}", None),
            ("procurar outra pasta de música", ["stylus-pickfolder"]),
            ("conferir o caminho do áudio", ["stylus-audio"]),
            ("driver de vídeo", ["stylus-gpu", "--status"]),
            ("atualizar o STYLUS", ["stylus-update"]),
            ("sobre", None),
        ]

    def key(self, ev):
        ops = self.opcoes()
        if ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % len(ops)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % len(ops)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            cmd = ops[self.sel][1]
            if cmd and (self.job is None or self.job.done):
                self.job = Job(cmd, ops[self.sel][0])
        else:
            return False
        return True

    def draw(self, s, r):
        x, y = r.x + 44, r.y + 34
        T.text(s, "ajustes", (x, y), 30, T.TEXT, bold=True)
        y += 70
        for i, (rotulo, cmd) in enumerate(self.opcoes()):
            sel = i == self.sel
            box = pygame.Rect(x, y, 560, 44)
            if sel:
                T.panel(s, box, T.INK_LIFT, radius=9)
            T.text(s, ("▸ " if sel else "  ") + rotulo, (box.x + 14, box.y + 11),
                   20, T.TEXT if sel else (T.TEXT_DIM if cmd else T.TEXT_FAINT),
                   maxw=530)
            y += 50
        T.text(s, "STYLUS", (x, r.bottom - 150), 40, T.BLUE, bold=True)
        T.text(s, "a agulha é o único ponto em que um objeto vira som.",
               (x, r.bottom - 100), 19, T.TEXT_DIM)
        T.text(s, "tudo aqui existe para deixar esse ponto o mais curto e o "
                  "mais deliberado possível.", (x, r.bottom - 74), 19,
               T.TEXT_FAINT)
        self.app.job_panel(s, pygame.Rect(x + 600, r.y + 100,
                                          r.right - x - 644, r.h - 200),
                           self.job)


# ═══════════════════════════════════════════════════════════════════════════
# A casca
# ═══════════════════════════════════════════════════════════════════════════
STACK_FILE = os.path.expanduser("~/.local/share/stylus/stack.json")


class _DesktopItem:
    """O último item do trilho não é uma seção, é a porta de saída.

    Fica no trilho e não enterrado nos ajustes porque é exatamente onde a
    pessoa vai procurar por ele — é o que o Steam Deck faz, e é o que faz o
    modo música não parecer uma prisão.
    """
    name = "ÁREA DE TRABALHO"
    icon = "󰇄"


_DESKTOP_ITEM = _DesktopItem()


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("STYLUS")
        info = pygame.display.Info()
        self.W, self.H = info.current_w, info.current_h
        flags = pygame.FULLSCREEN | pygame.SCALED
        if os.environ.get("STYLUS_UI_WINDOWED"):
            self.W, self.H, flags = 1600, 950, 0
        self.surf = pygame.display.set_mode((self.W, self.H), flags)
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()

        self.shelf = Shelf()
        self.thumbs = Thumbs()
        self.playing = Playing()
        self.shelf.load()

        self.screens = [NowScreen(self), ShelfScreen(self), StackScreen(self),
                        DiaryScreen(self), SignalScreen(self), PhoneScreen(self),
                        ToolsScreen(self), GamesScreen(self), SettingsScreen(self)]
        self.cur = 1                      # abre na ESTANTE, que é o assunto
        self.rail = False                 # o trilho está com o foco?
        self.rail_sel = 1
        self.stack = self._stack_load()
        self._toast = ""
        self._toast_until = 0.0
        self._lyr_cache = (None, None)
        self.pads = []
        self._pad_ax = 0.0
        self._pad_t = 0.0
        self._init_pads()
        self.screens[self.cur].enter()

    # ── controle ───────────────────────────────────────────────────────────
    def _init_pads(self):
        pygame.joystick.init()
        self._sync_pads()

    def _sync_pads(self, announce=False):
        """(Re)lê a lista de controles conectados.

        Feito também em pleno funcionamento, não só na abertura, porque num
        sofá o controle quase sempre é ligado DEPOIS de a tela já estar de pé
        — a pessoa senta, pega o controle e aperta o botão. Sem escutar o
        evento de conexão, esse é o caminho em que "o controle não funciona"
        acontece com o controle perfeitamente bom.
        """
        antes = len(self.pads)
        for j in self.pads:
            try:
                j.quit()
            except Exception:             # noqa: BLE001
                pass
        self.pads = []
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                j.init()
                self.pads.append(j)
            except Exception:             # noqa: BLE001
                pass
        if announce and len(self.pads) != antes:
            if len(self.pads) > antes:
                self.toast("controle conectado")
            elif self.pads:
                self.toast("um controle foi desconectado")

    def _pad_poll(self):
        """D-pad e analógico viram as mesmas setas que o teclado manda.

        Traduzir para eventos de teclado em vez de tratar controle em cada
        tela é o que impede a interface de crescer dois caminhos de entrada
        que divergem — o segundo sempre esquece uma tela.
        """
        if not self.pads:
            return
        now = time.time()
        if now < self._pad_t:
            return
        for j in self.pads:
            hx = hy = 0
            if j.get_numhats():
                hx, hy = j.get_hat(0)
            ax = j.get_axis(0) if j.get_numaxes() > 0 else 0.0
            ay = j.get_axis(1) if j.get_numaxes() > 1 else 0.0
            if abs(ax) > 0.6:
                hx = 1 if ax > 0 else -1
            if abs(ay) > 0.6:
                hy = -1 if ay > 0 else 1
            k = None
            if hx > 0:
                k = pygame.K_RIGHT
            elif hx < 0:
                k = pygame.K_LEFT
            elif hy > 0:
                k = pygame.K_UP
            elif hy < 0:
                k = pygame.K_DOWN
            if k:
                self._pad_t = now + 0.16
                pygame.event.post(pygame.event.Event(
                    pygame.KEYDOWN, key=k, unicode="", mod=0))

    # ── a pilha da noite ───────────────────────────────────────────────────
    def _stack_load(self):
        try:
            import json
            with open(STACK_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return []

    def stack_save(self):
        try:
            import json
            os.makedirs(os.path.dirname(STACK_FILE), exist_ok=True)
            with open(STACK_FILE, "w", encoding="utf-8") as fh:
                json.dump(self.stack, fh)
        except OSError:
            pass

    def stack_add(self, item):
        if any(i["folder"] == item["folder"] for i in self.stack):
            self.toast("esse já está na pilha")
            return
        self.stack.append(dict(item))
        self.stack_save()
        self.toast(f"{item['name']} na pilha  ({len(self.stack)})")

    def stack_tonight(self):
        """Monta uma noite: três discos, puxando para os esquecidos.

        Três e não dez porque uma noite tem três discos. Uma fila de dez é
        uma playlist com outro nome, e playlist é justamente a coisa que este
        sistema não quer ser.
        """
        escolhidos, fora = [], [i["folder"] for i in self.stack]
        for _ in range(3):
            d = vinyl.draw_record(exclude=fora)
            if not d:
                break
            fora.append(d)
            it = next((i for i in self.shelf.items
                       if os.path.normpath(i["folder"]) == os.path.normpath(d)),
                      None)
            if it:
                escolhidos.append(dict(it))
        self.stack.extend(escolhidos)
        self.stack_save()
        self.toast(f"{len(escolhidos)} discos para hoje à noite")

    # ── ações ──────────────────────────────────────────────────────────────
    def put_on(self, folder):
        self.toast(f"pondo {os.path.basename(folder)}…")
        spawn(["stylus-deck", "--no-scope", folder])

    def open_deck(self):
        env = dict(os.environ, STYLUS_DECK_RITUAL="1")
        try:
            subprocess.Popen(
                ["/usr/share/stylus/deck/venv/bin/python3"
                 if os.path.exists("/usr/share/stylus/deck/venv/bin/python3")
                 else sys.executable,
                 "/usr/share/stylus/deck/scope.py"],
                env=env, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.toast("não consegui abrir o deck")

    def current_lyric(self, al, track):
        if al is None or track is None:
            return None
        try:
            idx = al.tracks.index(track)
        except ValueError:
            return None
        if self._lyr_cache[0] != (al.folder, idx):
            try:
                self._lyr_cache = ((al.folder, idx), al.lyrics_for(idx))
            except Exception:             # noqa: BLE001
                self._lyr_cache = ((al.folder, idx), None)
        lines = self._lyr_cache[1]
        if not lines:
            return None
        pos, _d = self.playing.session.position()
        lo, hi = 0, len(lines)
        while lo < hi:
            mid = (lo + hi) // 2
            if lines[mid][0] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return (lines[lo - 1][1] or "").strip() or None if lo else None

    def toast(self, msg, secs=3.0):
        self._toast, self._toast_until = msg, time.time() + secs

    # ── desenho comum ──────────────────────────────────────────────────────
    def hint(self, s, r, txt):
        T.text(s, txt, (r.x + 44, r.bottom - 34), 17, T.TEXT_FAINT,
               maxw=r.w - 88)

    def job_panel(self, s, rect, job):
        T.panel(s, rect, T.INK_SOFT, radius=12, border=T.LINE)
        if job is None:
            T.text(s, "a saída aparece aqui", (rect.centerx, rect.centery), 18,
                   T.TEXT_FAINT, anchor="center")
            return
        estado = ("rodando…" if not job.done
                  else ("pronto" if job.rc == 0 else f"saiu com {job.rc}"))
        cor = (T.AMBER if not job.done
               else (T.GREEN if job.rc == 0 else T.RED))
        T.text(s, job.title, (rect.x + 16, rect.y + 12), 19, T.TEXT,
               maxw=rect.w - 140)
        T.text(s, estado, (rect.right - 16, rect.y + 12), 18, cor,
               anchor="topright")
        f = T.font(15)
        lh = f.get_linesize()
        n = max(1, (rect.h - 52) // lh)
        old = s.get_clip()
        s.set_clip(rect.inflate(-8, -8))
        for i, ln in enumerate(job.lines[-n:]):
            T.text(s, ln, (rect.x + 16, rect.y + 46 + i * lh), 15, T.TEXT_DIM,
                   maxw=rect.w - 32)
        s.set_clip(old)

    def _draw_rail(self, s, w):
        pygame.draw.rect(s, T.INK_SOFT, (0, 0, w, self.H))
        pygame.draw.line(s, T.LINE, (w, 0), (w, self.H))
        T.text(s, "STYLUS", (22, 34), 24, T.BLUE, bold=True)
        y = 110
        for i, sc in enumerate(self.screens + [_DESKTOP_ITEM]):
            atual = i == self.cur
            foco = self.rail and i == self.rail_sel
            box = pygame.Rect(10, y - 8, w - 20, 44)
            if foco:
                T.panel(s, box, T.INK_LIFT, radius=9)
            if atual:
                pygame.draw.rect(s, T.BLUE, (10, y - 6, 3, 40), border_radius=2)
            cor = T.TEXT if (atual or foco) else T.TEXT_FAINT
            T.text(s, sc.icon, (30, y + 2), 22, cor)
            T.text(s, sc.name, (62, y + 6), 18, cor)
            if i < len(self.screens):
                T.text(s, str(i + 1), (w - 18, y + 8), 15, T.TEXT_FAINT,
                       anchor="topright")
            y += 48
            if i == len(self.screens) - 1:
                # A saída para a área de trabalho fica separada do resto por
                # uma linha, como no Steam Deck: não é uma seção, é sair
                # daqui.
                pygame.draw.line(s, T.LINE, (18, y - 4), (w - 18, y - 4))
                y += 12
        snap, al, track, side, _t, frac = self.playing.where()
        if al is not None:
            T.text(s, "TOCANDO", (22, self.H - 118), 14, T.TEXT_FAINT)
            T.text(s, al.name, (22, self.H - 96), 17, T.TEXT, maxw=w - 44)
            T.text(s, al.artist, (22, self.H - 72), 15, T.TEXT_DIM, maxw=w - 44)
            bar = pygame.Rect(22, self.H - 44, w - 44, 5)
            pygame.draw.rect(s, T.LINE, bar, border_radius=3)
            pygame.draw.rect(s, T.BLUE,
                             (bar.x, bar.y, int(bar.w * frac), bar.h),
                             border_radius=3)

    def _draw_toast(self, s):
        if time.time() > self._toast_until:
            return
        f = T.font(19)
        tw = f.size(self._toast)[0]
        box = pygame.Rect(self.W // 2 - tw // 2 - 22, self.H - 96,
                          tw + 44, 46)
        T.panel(s, box, T.INK_LIFT, radius=23, border=T.LINE)
        T.text(s, self._toast, box.center, 19, T.TEXT, anchor="center")

    # ── entrada ────────────────────────────────────────────────────────────
    def _key(self, ev):
        if ev.key == pygame.K_ESCAPE:
            # VOLTAR, não SAIR. No modo música esta tela é a sessão inteira, e
            # o botão B (que chega aqui como ESC) tem que se comportar como o
            # "voltar" de um videogame: abre o menu lateral, e no menu fecha o
            # menu. Sair para um vazio preto seria o oposto do que a pessoa
            # espera do B — e a saída de verdade é o item "área de trabalho"
            # no fim do trilho. Na janela de desenvolvimento, onde não há
            # supervisor para reabrir, o ESC ainda encerra por conveniência.
            if self.rail:
                self.rail = False
            elif os.environ.get("STYLUS_UI_WINDOWED"):
                return "quit"
            else:
                self.rail = True
                self.rail_sel = self.cur
            return None
        if ev.key == pygame.K_F5:
            self.shelf.rescan()
            self.toast("relendo a estante…")
            return None
        if pygame.K_1 <= ev.key <= pygame.K_9:
            i = ev.key - pygame.K_1
            if i < len(self.screens):
                self._goto(i)
            return None
        if self.rail:
            n = len(self.screens) + 1          # +1: a área de trabalho
            if ev.key in (pygame.K_DOWN, pygame.K_j):
                self.rail_sel = (self.rail_sel + 1) % n
            elif ev.key in (pygame.K_UP, pygame.K_k):
                self.rail_sel = (self.rail_sel - 1) % n
            elif ev.key in (pygame.K_RIGHT, pygame.K_l, pygame.K_RETURN,
                            pygame.K_KP_ENTER):
                if self.rail_sel >= len(self.screens):
                    self.toast("indo para a área de trabalho…")
                    pygame.display.flip()
                    spawn(["stylus-mode", "desktop"])
                else:
                    self._goto(self.rail_sel)
                self.rail = False
            elif ev.key == pygame.K_TAB:
                self.rail = False
            return None
        if self.screens[self.cur].key(ev):
            return None
        # Só cai no trilho o que a tela não quis. Assim `h` anda na grade de
        # capas em vez de abrir o menu, e continua abrindo o menu nas telas
        # que não usam h.
        if ev.key in (pygame.K_TAB, pygame.K_LEFT, pygame.K_h, pygame.K_q):
            self.rail = True
            self.rail_sel = self.cur
        return None

    def _goto(self, i):
        self.cur = i
        self.rail_sel = i
        self.screens[i].enter()

    def run(self):
        rail_w = 230
        while True:
            self._pad_poll()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type == pygame.KEYDOWN:
                    if self._key(ev) == "quit":
                        return
                elif ev.type in (pygame.JOYDEVICEADDED,
                                 pygame.JOYDEVICEREMOVED):
                    self._sync_pads(announce=True)
                elif ev.type == pygame.JOYBUTTONDOWN:
                    # Os ombros pulam faixa em QUALQUER tela, não só na AGORA:
                    # do sofá, "próxima" é a coisa que se quer poder fazer sem
                    # primeiro navegar até uma tela específica. Por isso vão
                    # direto ao playerctl em vez de virar tecla, que só a tela
                    # AGORA escuta.
                    if ev.button == 4:            # LB
                        spawn(["playerctl", "previous"]); continue
                    if ev.button == 5:            # RB
                        spawn(["playerctl", "next"]); continue
                    # A/B do padrão xbox. 0 confirma, 1 volta, 6/7 abrem o
                    # trilho — os mesmos lugares que todo mundo já conhece.
                    mapa = {0: pygame.K_RETURN, 1: pygame.K_ESCAPE,
                            2: pygame.K_s, 3: pygame.K_SLASH,
                            6: pygame.K_TAB, 7: pygame.K_TAB}
                    if ev.button in mapa:
                        pygame.event.post(pygame.event.Event(
                            pygame.KEYDOWN, key=mapa[ev.button], unicode="",
                            mod=0))
            self.surf.fill(T.INK)
            body = pygame.Rect(rail_w, 0, self.W - rail_w, self.H)
            try:
                self.screens[self.cur].draw(self.surf, body)
            except Exception as e:        # noqa: BLE001
                # Uma tela com defeito não pode derrubar o sistema inteiro:
                # este programa é a cara da máquina e cair nele parece o
                # computador ter quebrado.
                T.text(self.surf, f"esta tela quebrou: {type(e).__name__}: {e}",
                       (body.x + 40, body.y + 60), 20, T.RED, maxw=body.w - 80)
            self._draw_rail(self.surf, rail_w)
            self._draw_toast(self.surf)
            pygame.display.flip()
            self.clock.tick(FPS)


def main():
    try:
        App().run()
    finally:
        pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
