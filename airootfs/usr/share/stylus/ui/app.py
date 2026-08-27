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
import json
import os
import struct
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
    except Exception:
        return False


# ── favoritos ──────────────────────────────────────────────────────────────
_FAV_FILE = os.path.join(vinyl.STATE_DIR, "favorites.json")

def _load_favorites():
    try:
        with open(_FAV_FILE) as f:
            return set(json.load(f))
    except (OSError, json.JSONDecodeError):
        return set()

def _save_favorites(favs):
    os.makedirs(os.path.dirname(_FAV_FILE), exist_ok=True)
    with open(_FAV_FILE, "w") as f:
        json.dump(sorted(favs), f)

def _toggle_favorite(folder):
    favs = _load_favorites()
    key = os.path.normpath(folder)
    if key in favs:
        favs.discard(key)
    else:
        favs.add(key)
    _save_favorites(favs)
    return key in favs


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
        # r = sortear um disco aleatório (weighted random)
        if ev.key == pygame.K_r:
            d = vinyl.draw_record([i["folder"] for i in self.app.shelf.items])
            if d:
                self.app.put_on(d)
            return True
        # Virar o lado. v e b no teclado, Y no controle (que chega como "/"):
        # os ombros já pulam FAIXA, e faltava a única coisa que este sistema
        # pede que você faça com as mãos.
        if ev.key in (pygame.K_v, pygame.K_SLASH):
            self.app.toast("virando o disco…")
            spawn(["stylus-side-watch", "--virar"])
            return True
        if ev.key == pygame.K_b:
            self.app.toast("voltando um lado…")
            spawn(["stylus-side-watch", "--voltar"])
            return True
        if ev.key == pygame.K_p:
            spawn(["playerctl", "previous"])
            return True
        # Sleep timer: t cicla 30m → 60m → 90m → off
        if ev.key == pygame.K_t:
            self.app.toggle_sleep()
            return True
        # Shuffle toggle: s
        if ev.key == pygame.K_s:
            self.app.toggle_shuffle()
            return True
        # Repeat toggle: R (shift+r)
        if ev.key == pygame.K_r and (ev.mod & pygame.KMOD_SHIFT):
            self.app.toggle_repeat()
            return True
        # Busca e volume do sofá: no modo música esta tela é o controle
        # remoto. ←/→ puxam a agulha dez segundos, +/- tocam o volume — as
        # duas coisas que a pessoa quer sem levantar, e que antes só existiam
        # na barra da área de trabalho.
        if ev.key in (pygame.K_RIGHT, pygame.K_l):
            self.app.toast("avança 10s…")
            spawn(["playerctl", "position", "10+"])
            return True
        if ev.key in (pygame.K_LEFT, pygame.K_h):
            self.app.toast("volta 10s…")
            spawn(["playerctl", "position", "10-"])
            return True
        if ev.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            spawn(["pamixer", "-i", "5"])
            self.app.toast(f"volume {self.app.volume_pct()}%")
            return True
        if ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            spawn(["pamixer", "-d", "5"])
            self.app.toast(f"volume {self.app.volume_pct()}%")
            return True
        # D de deck: o protetor de tela que é o próprio deck, ligado ou não.
        # Quem sentou para CONVERSAR não quer a tela virando sozinha; quem
        # saiu do sofá quer. É uma escolha da noite, e fica guardada.
        if ev.key == pygame.K_d:
            self.app.auto_deck = not self.app.auto_deck
            _save_prefs({"auto_deck": self.app.auto_deck})
            self.app.toast("deck sozinho: LIGADO" if self.app.auto_deck
                           else "deck sozinho: DESLIGADO (fica na AGORA)")
            return True
        return False

    def draw(self, s, r):
        snap, al, track, side, t_abs, frac = self.app.playing.where()
        if al is None:
            self._nothing(s, r)
            return

        # ── a capa vaza para a sala: fundo desfocado na cor do disco ──────
        fundo = self.app.backdrop(al, r.size)
        if fundo is not None:
            s.blit(fundo, r.topleft)
            # vinheta suave nas bordas — profundidade
            T.vignette(s)

        # ── a capa e a coluna de texto formam UM bloco, centrado junto ─────
        margem, gap, txt_teto = 64, 72, 620
        avail = max(320, r.w - margem * 2)
        size = min(int(r.h * 0.62), int(avail * 0.44), 720)
        size = max(280, size)
        txt_w = min(txt_teto, avail - size - gap)
        total = size + gap + txt_w

        # AGORA usa 640px — 320 esticado ficava borrado (audit A-N1)
        cov = self.app.thumbs_hi.get(al.cover) if al.cover else None
        if cov is None and al.cover:
            cov = self.app.thumbs.get(al.cover)
        cr = pygame.Rect(r.x + (r.w - total) // 2, r.y + (r.h - size) // 2,
                         size, size)
        T.shadow_card(s, cr, radius=14)

        # ── brilho reativo ao áudio: a capa "respira" com a música ──────────
        level = self.app.audio_level()
        if level > 0.01:
            glow_r = int(size * 0.58)
            glow = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
            alpha = int(18 + level * 45)
            pygame.draw.circle(glow, (*T.AMBER, alpha),
                               (glow_r, glow_r), glow_r, 0)
            s.blit(glow, (cr.centerx - glow_r, cr.centery - glow_r))

        if cov:
            # sem smoothscale se já do tamanho certo — mais nítido
            if cov.get_width() != size or cov.get_height() != size:
                cov = pygame.transform.smoothscale(cov, (size, size))
            s.blit(cov, cr)
        else:
            T.panel(s, cr, T.INK_LIFT, radius=14)
            T.text(s, "sem capa", cr.center, 24, T.TEXT_FAINT, anchor="center")

        x = cr.right + gap
        w = txt_w
        y_text = cr.y + 8

        # Artista mais sutil, álbum com mais peso — quem olha de longe
        # quer saber QUAL disco é, não quem fez.
        T.text(s, al.artist.upper(), (x, y_text), 22, T.TEXT_FAINT, maxw=w)
        T.text(s, al.name, (x, y_text + 34), 56, T.TEXT, bold=True, maxw=w)
        if al.year:
            T.text(s, str(al.year), (x, y_text + 102), 22, T.TEXT_DIM)

        # ── onde no LADO. ────
        y = y_text + 145
        if side:
            resta = max(0.0, side["end"] - t_abs)
            ultimo = side is al.sides[-1]
            rotulo = side["label"].replace("SIDE", "LADO")
            # cor do lado respira com o áudio
            side_alpha = int(180 + level * 75) if level > 0.01 else 180
            side_cor = T.lerp(T.AMBER, (255, 255, 255), (side_alpha - 180) / 75)
            T.text(s, rotulo, (x, y), 30, side_cor, bold=True)
            T.text(s, ("acaba em " if ultimo else "vira em ") + humano(resta),
                   (x + 150, y + 5), 22, T.TEXT_DIM)
            self._groove(s, pygame.Rect(x, y + 48, w, 14), frac)
            y += 84

        if track:
            n = (al.tracks.index(track) + 1) if track in al.tracks else 0
            T.text(s, f"{n:02d}  {track.get('title') or ''}", (x, y), 30,
                   T.TEXT, maxw=w)
            y += 48

        # Informativos no rodapé
        hist = f"{al.plays}ª vez" if al.plays else "primeira vez"
        y_rodape = min(cr.bottom + 20, r.bottom - 60)
        T.text(s, f"{hist}  ·  {len(al.tracks)} faixas  ·  "
                  f"{humano(al.total)}  ·  {ha_quanto(al.last_played)}",
               (x, y_rodape), 19, T.TEXT_FAINT, maxw=w)

        # ── a letra do momento, em JANELA ────────
        est = self.app.lyric_state(al, track)
        livre = int(y_rodape - (y + 10))
        if est and livre > 70:
            lines, cur_i = est
            vis = max(3, min(6, livre // 34))
            ini = max(0, min(cur_i - 2, len(lines) - vis))
            yl = y + 8
            for k in range(ini, min(len(lines), ini + vis)):
                txt = (lines[k][1] or "").strip()
                if k == cur_i and txt:
                    T.text(s, txt, (x, yl), 26, T.LAV, bold=True, maxw=w)
                    yl += 36
                elif txt:
                    T.text(s, txt, (x, yl), 19, T.TEXT_FAINT, maxw=w)
                    yl += 26
                else:
                    yl += 12

        # Shuffle/repeat state icons — Nerd Font glyphs for consistency
        icons = []
        if self.app.shuffle:
            icons.append(T.icon("󰒟"))  # nf-md-shuffle
        if self.app.repeat == 1:
            icons.append(T.icon("󰑙"))  # nf-md-repeat_once
        elif self.app.repeat == 2:
            icons.append(T.icon("󰑖"))  # nf-md-repeat
        if self.app._sleep_minutes > 0:
            remaining = max(0, int((self.app._sleep_end - time.time()) / 60))
            icons.append(f"{T.icon('󰅐')}{remaining}m")  # nf-md-timer
        if icons:
            T.text(s, "  ".join(icons), (r.right - 20, r.bottom - 50), 20,
                   T.AMBER, anchor="bottomright")

        self.app.hint(s, r, "enter abrir o deck   espaço pausa   "
                            "n/p faixa   ←/→ busca   v/b lado   +/- volume   "
                            + ("D deck sozinho: ligado" if self.app.auto_deck
                               else "D deck sozinho: desligado"))

    def _groove(self, s, rect, frac):
        """Barra de progresso como sulco — começo na borda, fim no centro."""
        pygame.draw.rect(s, T.LINE, rect, border_radius=6)
        f = pygame.Rect(rect.x, rect.y, int(rect.w * frac), rect.h)
        pygame.draw.rect(s, T.AMBER, f, border_radius=6)
        # ponta luminosa na posição atual
        if frac > 0.01:
            glow = pygame.Surface((18, rect.h + 6), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*T.AMBER_GLOW, 60), (9, rect.h // 2 + 3), 8)
            s.blit(glow, (f.right - 9, rect.y - 3))
            pygame.draw.circle(s, T.TEXT, (f.right, rect.centery), 6)

    def _nothing(self, s, r):
        cx, cy = r.centerx, r.centery
        t = time.time()

        # disco parado, girando devagar — mas com âmbar suave
        for i in range(8):
            rr = 50 + i * 28
            alpha = 0.20 + i * 0.06
            cor = T.lerp(T.INK_SOFT, T.AMBER_DIM, alpha)
            pygame.draw.circle(s, cor, (cx, cy - 40), rr, 1)

        # agulha estática apontando para o centro
        ang = (t * 0.3) % (2 * math.pi)
        pygame.draw.line(s, T.AMBER_DIM, (cx + math.cos(ang) * 160,
                         cy - 40 + math.sin(ang) * 160),
                         (cx, cy - 40), 1)

        # centro do disco — um ponto âmbar que pulsa suavemente
        pulse = 0.7 + 0.3 * math.sin(t * 1.5)
        center_r = int(6 + pulse * 3)
        glow_s = pygame.Surface((center_r * 6, center_r * 6), pygame.SRCALPHA)
        pygame.draw.circle(glow_s, (*T.AMBER_GLOW, int(20 * pulse)),
                           (center_r * 3, center_r * 3), center_r * 3)
        s.blit(glow_s, (cx - center_r * 3, cy - 40 - center_r * 3))
        pygame.draw.circle(s, T.AMBER, (cx, cy - 40), center_r)

        # texto convidativo
        T.text(s, "nada tocando", (cx, cy + 200), 32, T.TEXT_DIM,
               anchor="center")
        T.text(s, "vá para a ESTANTE e escolha um disco",
               (cx, cy + 240), 20, T.TEXT_FAINT, anchor="center")
        T.text(s, "ou pressione r para sortear",
               (cx, cy + 270), 17, T.TEXT_FAINT, anchor="center")


# ═══════════════════════════════════════════════════════════════════════════
# ESTANTE — a grade de capas. A tela principal.
# ═══════════════════════════════════════════════════════════════════════════
class ShelfScreen(Screen):
    name = "ESTANTE"
    icon = "󰀥"

    COLS = 6  # default — recalculado no draw() conforme largura da tela

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.scroll = 0.0
        self.target = 0.0
        self.query = ""
        self.searching = False
        self.order = "artista"
        # O filtro por ARTISTA. A busca (/) acha "quem tem essa palavra no
        # nome"; isto aqui responde à pergunta de sofá — "quero ouvir esse
        # artista, qual disco dele agora?" — mostrando só a prateleira dele.
        self.artist = None
        self.picking = False
        self.a_sel = 0

    # ── quais discos, nesta ordem ──────────────────────────────────────────
    def items(self):
        its = self.app.shelf.items
        if self.artist:
            its = [i for i in its if i["artist"] == self.artist]
        if self.query:
            q = self.query.lower()
            its = [i for i in its
                   if q in i["artist"].lower() or q in i["name"].lower()]
        if self.order == "favoritos":
            favs = _load_favorites()
            its = [i for i in its if os.path.normpath(i["folder"]) in favs]
        elif self.order == "esquecidos":
            its = sorted(its, key=lambda i: i["last"])
        elif self.order == "mais postos":
            its = sorted(its, key=lambda i: -i["plays"])
        return its

    def artistas(self):
        return sorted(self.app.shelf.artists().keys(), key=str.lower)

    def key(self, ev):
        its = self.items()
        n = len(its)
        if self.picking:
            arts = self.artistas()
            if ev.key == pygame.K_ESCAPE:
                self.picking = False
            elif ev.key in (pygame.K_DOWN, pygame.K_j):
                self.a_sel = min(len(arts) - 1, self.a_sel + 1)
            elif ev.key in (pygame.K_UP, pygame.K_k):
                self.a_sel = max(0, self.a_sel - 1)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and arts:
                # Escolher o MESMO artista de novo é o gesto de tirar o
                # filtro — e custa a linha que o "a limpa" precisaria.
                self.artist = (None if arts[self.a_sel] == self.artist
                               else arts[self.a_sel])
                self.sel, self.scroll, self.target = 0, 0.0, 0.0
                self.picking = False
            return True
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
        # 'a' DEPOIS do modo de busca: dentro da busca ele é letra — "beat"
        # não pode abrir a lista de artistas no meio (foi exatamente o que
        # aconteceu, e o teste de busca pegou).
        if ev.key == pygame.K_a:
            if self.artist:
                self.artist = None          # já filtrado: 'a' limpa
                self.sel = 0
            else:
                self.picking = True
                arts = self.artistas()
                self.a_sel = (arts.index(self.artist)
                              if self.artist in arts else 0)
            return True
        if ev.key == pygame.K_SLASH:
            self.searching, self.query = True, ""
            return True
        if ev.key == pygame.K_o:
            ordens = ["artista", "esquecidos", "mais postos", "favoritos"]
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
        elif ev.key == pygame.K_f:
            folder = its[self.sel]["folder"]
            is_fav = _toggle_favorite(folder)
            self.app.toast("favorito" if is_fav else "removido dos favoritos")
        else:
            return False
        return True

    def draw(self, s, r):
        its = self.items()
        favs = _load_favorites()
        pad, gap = 30, 18
        self.COLS = max(3, min(8, r.w // 230))
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
        if self.picking:
            self._picker(s, r)
            return
        if self.searching or self.query:
            T.text(s, "/ " + self.query + ("▌" if self.searching else ""),
                   (r.x + pad, r.y + 16), 24, T.AMBER)
        else:
            rotulo = f"{len(its)} discos"
            if self.artist:
                rotulo += f"  ·  {self.artist}   (a limpa o filtro)"
            T.text(s, rotulo, (r.x + pad, r.y + 18), 22, T.TEXT_DIM)
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
        # independente de FPS — 60fps ou 30fps mesma velocidade
        dt = self.app.clock.get_time() / 1000.0
        alpha = 1.0 - pow(2.718281828, -dt * 12.0) if dt > 0 else 0.28
        self.scroll += (self.target - self.scroll) * alpha

        clip = pygame.Rect(r.x, r.y + head, r.w, view_h)
        old = s.get_clip()
        s.set_clip(clip)
        for i, it in enumerate(its):
            cx = r.x + pad + (i % self.COLS) * (cw + gap)
            cy = r.y + head + (i // self.COLS) * ch - int(self.scroll)
            if cy > clip.bottom or cy + ch < clip.top:
                continue
            self._card(s, pygame.Rect(cx, cy, cw, cw), it, i == self.sel)
            # favorito: estrela âmbar no canto superior direito
            if os.path.normpath(it["folder"]) in favs:
                T.text(s, "★", (cx + cw - 8, cy + 4), 18, T.AMBER, anchor="topright")
            # 14 e não 8: o disco selecionado levanta 6px para cada lado, e
            # com a legenda colada nela mesma ela encostava na capa levantada.
            ty = cy + cw + 14
            T.text(s, it["name"], (cx, ty), 17,
                   T.TEXT if i == self.sel else T.TEXT_DIM, maxw=cw)
            T.text(s, it["artist"], (cx, ty + 22), 15, T.TEXT_FAINT, maxw=cw)
        s.set_clip(old)

        # Now-playing bar — thin amber strip at the bottom if music is playing
        snap = self.app.playing.session.snapshot()
        if snap.get("path") or snap.get("source") != "none":
            bar_h = 36
            bar = pygame.Rect(r.x, r.bottom - bar_h - 48, r.w, bar_h)
            pygame.draw.rect(s, T.INK_LIFT, bar, border_radius=8)
            pygame.draw.rect(s, T.AMBER_DIM, bar, 1, border_radius=8)
            np_title = snap.get("title", "") or ""
            np_artist = snap.get("artist", "") or ""
            if np_title:
                label = f"▶ {np_artist} — {np_title}" if np_artist else f"▶ {np_title}"
                T.text(s, label, (bar.x + 14, bar.centery - 9), 16, T.AMBER, maxw=bar.w - 100)
            T.text(s, "enter = ver o disco", (bar.right - 14, bar.centery - 9), 14,
                   T.TEXT_FAINT, anchor="topright")

        sel = its[self.sel]
        self.app.hint(
            s, r,
            f"{sel['artist']} — {sel['name']}   ·   {ha_quanto(sel['last'])}"
            f"   ·   enter põe   s empilha   a artista   o ordem   / procura")

    def _picker(self, s, r):
        """A lista de quem está na coleção, para filtrar a estante.

        Sobre a grade escurecida e não numa seção própria: escolher artista
        é um GESTO dentro da estante — entra, escolhe, e a prateleira já é
        outra — não um lugar onde se fica.
        """
        arts = self.artistas()
        velho = s.get_clip()
        s.set_clip(r)
        dim = pygame.Surface(r.size)
        dim.fill(T.INK)
        dim.set_alpha(215)
        s.blit(dim, r.topleft)

        lw = min(560, r.w - 120)
        lh = min(len(arts) * 46 + 74, r.h - 120)
        lx, ly = r.x + (r.w - lw) // 2, r.y + (r.h - lh) // 2
        T.panel(s, pygame.Rect(lx, ly, lw, lh), T.INK_LIFT, radius=14,
                border=T.LINE)
        T.text(s, "quem?", (lx + 24, ly + 16), 22, T.TEXT, bold=True)
        T.text(s, f"{len(arts)} artistas", (lx + lw - 24, ly + 22), 16,
               T.TEXT_FAINT, anchor="topright")

        vis = max(1, (lh - 74) // 46)
        topo = max(0, min(self.a_sel - vis // 2, len(arts) - vis))
        for k, nome in enumerate(arts[topo:topo + vis]):
            i = topo + k
            ry = ly + 52 + k * 46
            atual = i == self.a_sel
            if atual:
                T.panel(s, pygame.Rect(lx + 12, ry - 4, lw - 24, 42),
                        T.INK_SOFT, radius=8)
            n_discos = len(self.app.shelf.artists().get(nome, ()))
            T.text(s, ("▸ " if atual else "  ") + nome,
                   (lx + 26, ry + 2), 20,
                   T.TEXT if atual else T.TEXT_DIM, maxw=lw - 110)
            T.text(s, str(n_discos), (lx + lw - 30, ry + 6), 16,
                   T.TEXT_FAINT, anchor="topright")
        s.set_clip(velho)
        self.app.hint(s, r, "enter escolhe   ·   ↑↓ anda   ·   "
                            "esc desiste   ·   o mesmo artista de novo limpa")

    def _card(self, s, rect, it, selected):
        if selected:
            # O disco selecionado LEVANTA: maior e com sombra mais funda.
            rect = rect.inflate(10, 10)
            glow = rect.inflate(12, 12)
            pygame.draw.rect(s, T.lerp(T.INK, T.AMBER, 0.25), glow,
                             border_radius=10)
            T.shadow_card(s, rect, radius=8)
        else:
            T.shadow_card(s, rect, radius=6)
        cov = self.app.thumbs.get(it["cover"])
        if cov:
            s.blit(pygame.transform.smoothscale(cov, rect.size), rect)
        else:
            T.panel(s, rect, T.INK_LIFT, radius=6)
            # Iniciais do artista como placeholder — mais útil que "sem capa"
            initials = "".join(w[0] for w in it["artist"].split()[:2]).upper()
            T.text(s, initials or it["name"][:2].upper(), rect.center, 36,
                   T.TEXT_FAINT, anchor="center")
        # Marcas de desgaste — menores e mais sutis
        if it["plays"]:
            n = min(5, it["plays"])
            for k in range(n):
                pygame.draw.circle(s, T.lerp(T.PINK, T.RED, 0.3),
                                   (rect.right - 10 - k * 8, rect.bottom - 10), 2)


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
                   T.AMBER if sel else T.TEXT_FAINT, anchor="topright")
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

    DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")

    def __init__(self, app):
        super().__init__(app)
        self.rows = []
        self.by_day = {}
        self.by_wd = [0] * 7
        self.by_hour = [0] * 24
        self.by_artist = {}
        self.nunca = 0
        self.total_estante = 0
        # 0 = o que você pôs (a lista). 1 = o formato (quando, quem, o parado).
        # Duas páginas e não duas seções: são a MESMA pergunta — "o que essa
        # coleção virou" — e o trilho já tem nove itens.
        self.page = 0
        self.scroll = 0

    def enter(self):
        rows = sorted(vinyl._play_rows(), key=lambda x: -x[0])
        self.by_day = {}
        self.by_wd = [0] * 7
        self.by_hour = [0] * 24
        self.by_artist = {}
        for ts, fold in rows:
            lt = time.localtime(ts)
            d = time.strftime("%Y-%m-%d", lt)
            self.by_day[d] = self.by_day.get(d, 0) + 1
            # tm_wday já é 0=segunda, que é como a semana é lida aqui.
            self.by_wd[lt.tm_wday] += 1
            self.by_hour[lt.tm_hour] += 1
            art = vinyl.folder_names(fold)[0]
            if art:
                self.by_artist[art] = self.by_artist.get(art, 0) + 1
        postos = {os.path.normpath(f) for _ts, f in rows}
        itens = self.app.shelf.items or []
        self.total_estante = len(itens)
        self.nunca = sum(1 for i in itens
                         if os.path.normpath(i["folder"]) not in postos)
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
        if ev.key == pygame.K_s:              # X no controle
            self.page = 1 - self.page
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            self.scroll = min(max(0, len(self.rows) - 8), self.scroll + 1)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.scroll = max(0, self.scroll - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.rows:
            self.app.put_on(self.rows[self.scroll]["folder"])
        else:
            return False
        return True

    def draw(self, s, r):
        if self.rows and self.page == 1:
            self._formato(s, r)
            return
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
        # 190 e não 132: com o valor antigo a legenda do calendário caía
        # exatamente em cima da linha de dicas, e as duas viravam um borrão.
        self._calendar(s, pygame.Rect(x, r.bottom - 190, r.w - 88, 104))
        self.app.hint(s, r, "enter põe de novo   ·   ↑↓ anda   ·   s o formato")

    # ── a segunda página: o formato ────────────────────────────────────────
    def _barras(self, s, rect, valores, rotulos, cor, gutter=62):
        """Barras horizontais. Um valor zero desenha a barra VAZIA e não some:
        um dia da semana em que você nunca ouve nada é um dado, e uma linha
        ausente vira um buraco que se lê como erro de desenho.

        `gutter` é a coluna do rótulo, e existe porque "seg" e "My Bloody
        Valentine" não cabem na mesma: com um valor fixo, a barra do artista
        era desenhada POR CIMA do nome dele.
        """
        maxi = max(valores) if valores and max(valores) else 1
        alt = max(14, rect.h // max(1, len(valores)) - 6)
        num_w = 44
        y = rect.y
        for rot, v in zip(rotulos, valores):
            T.text(s, rot, (rect.x, y + alt // 2 - 9), 17, T.TEXT_FAINT,
                   maxw=gutter - 10)
            trilho = pygame.Rect(rect.x + gutter, y + 2,
                                 rect.w - gutter - num_w, alt - 4)
            pygame.draw.rect(s, T.INK_SOFT, trilho, border_radius=4)
            w = int(trilho.w * v / maxi)
            if w:
                pygame.draw.rect(s, cor, (trilho.x, trilho.y, w, trilho.h),
                                 border_radius=4)
            T.text(s, str(v), (trilho.right + 12, y + alt // 2 - 9), 16,
                   T.TEXT_DIM if v else T.TEXT_FAINT)
            y += alt + 6

    def _horas(self, s, rect):
        """Vinte e quatro colunas. A do seu horário fica acesa."""
        # O `or 1` protege a divisão e ESTRAGA a busca do pico: com tudo
        # zerado, maxi vira 1 e `.index(1)` estoura com "1 is not in list".
        # São duas perguntas diferentes e precisam de dois números.
        bruto = max(self.by_hour)
        maxi = bruto or 1
        pico = self.by_hour.index(bruto) if bruto else -1
        largura = rect.w / 24.0
        for h, v in enumerate(self.by_hour):
            alt = int((rect.h - 18) * v / maxi)
            col = pygame.Rect(int(rect.x + h * largura) + 1, rect.bottom - 18 - alt,
                              max(2, int(largura) - 3), max(1, alt))
            pygame.draw.rect(s, T.AMBER if h == pico else T.lerp(T.INK_LIFT, T.AMBER, 0.4),
                             col, border_radius=2)
        for h in (0, 6, 12, 18):
            T.text(s, f"{h}h", (int(rect.x + h * largura), rect.bottom - 16),
                   14, T.TEXT_FAINT)
        if pico >= 0:
            T.text(s, f"por volta das {pico}h", (rect.right, rect.bottom - 16),
                   15, T.TEXT_DIM, anchor="topright")

    def _voltam(self, s, rect):
        """Os discos que voltam, pelas capas. Uma coluna de números diz quanto;
        uma fileira de capas diz QUAIS, que é a pergunta que se faz olhando."""
        top = sorted((it for it in self.rows if it.get("plays")),
                     key=lambda it: -it["plays"])[:8]
        if not top:
            return
        T.text(s, "OS QUE VOLTAM", (rect.x, rect.y), 16, T.GREEN, bold=True)
        # A capa cabe no que sobrou de ALTURA, não numa largura escolhida: com
        # o lado vindo só da largura, numa tela baixa a fileira passava por
        # cima da legenda, da linha de baixo e da dica, tudo junto.
        lado = min(112, (rect.w - 7 * 18) // 8, rect.h - 70)
        if lado < 40:
            return
        x = rect.x
        for it in top:
            cr = pygame.Rect(x, rect.y + 26, lado, lado)
            cov = self.app.thumbs.get(it["cover"])
            T.shadow_card(s, cr, radius=6)
            if cov:
                s.blit(pygame.transform.smoothscale(cov, cr.size), cr)
            else:
                T.panel(s, cr, T.INK_LIFT, radius=6)
                T.text(s, it["name"][:12], cr.center, 13, T.TEXT_FAINT,
                       anchor="center", maxw=lado - 12)
            T.text(s, f"{it['plays']}x", (cr.centerx, cr.bottom + 8), 17,
                   T.PINK, anchor="midtop")
            T.text(s, it["name"], (cr.centerx, cr.bottom + 30), 13,
                   T.TEXT_FAINT, anchor="midtop", maxw=lado)
            x += lado + 18

    def _formato(self, s, r):
        x, y = r.x + 44, r.y + 30
        T.text(s, "o formato", (x, y), 24, T.TEXT_DIM)
        y += 44

        meio = r.x + r.w // 2
        col_w = r.w // 2 - 70

        T.text(s, "EM QUE DIA", (x, y), 16, T.AMBER, bold=True)
        self._barras(s, pygame.Rect(x, y + 26, col_w, 190),
                     self.by_wd, self.DIAS, T.AMBER)

        T.text(s, "QUEM VOCÊ MAIS PÕE", (meio + 20, y), 16, T.PINK, bold=True)
        top = sorted(self.by_artist.items(), key=lambda kv: -kv[1])[:6]
        if top:
            # Gutter largo: nome de artista é comprido, e com a coluna estreita
            # a barra era desenhada por cima do nome.
            self._barras(s, pygame.Rect(meio + 20, y + 26, col_w, 190),
                         [n for _a, n in top], [a for a, _n in top], T.PINK,
                         gutter=150)

        y += 236
        # ── o orçamento vertical, de baixo para cima ───────────────────────
        # A dica mora no rodapé (app.hint), e a linha da prateleira parada logo
        # acima dela. O que sobra entre o fim das barras e o bloco de capas é
        # do gráfico de horas. Contado assim, e não com números soltos, porque
        # a primeira versão deu ao gráfico "tudo que sobra" e ele passou por
        # cima das capas, da legenda e da dica ao mesmo tempo.
        rodape = 68                       # dica + linha da prateleira
        bloco_capas = 176
        topo_capas = r.bottom - rodape - bloco_capas
        T.text(s, "A QUE HORAS", (x, y), 16, T.LAV, bold=True)
        self._horas(s, pygame.Rect(x, y + 24, r.w - 120,
                                   max(110, topo_capas - 20 - (y + 24))))

        self._voltam(s, pygame.Rect(x, topo_capas, r.w - 120, bloco_capas))

        if self.total_estante:
            T.text(s, f"{self.nunca} dos {self.total_estante} discos da estante "
                      f"nunca foram postos  ·  o SORTEIO puxa para eles",
                   (x, r.bottom - rodape + 4), 17,
                   T.AMBER if self.nunca else T.GREEN)
        self.app.hint(s, r, "s volta para a lista")

    def _calendar(self, s, rect):
        """Um ano em quadradinhos: uma coluna por semana, um por dia.

        Vale mais do que parece. Ver as semanas vazias é a única forma
        honesta de perceber que você passou um mês sem sentar para ouvir
        nada — o que é exatamente o hábito que este sistema existe para
        recuperar.
        """
        hoje = time.localtime()
        dias = 364
        gap = 2
        # O quadradinho vem da largura E da altura disponíveis. Só da largura,
        # ele ficava preso em 10 px numa tela de 1600 e o ano inteiro ocupava
        # metade do espaço que tinha, lendo como um enfeite pequeno em vez de
        # como o gráfico que é.
        cell = max(4, min(14, rect.w // 53 - gap, rect.h // 7 - gap))
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
                c = T.lerp(T.lerp(T.INK_LIFT, T.AMBER, 0.4), T.PINK,
                           min(1.0, (n - 1) / max(1, maxi - 1)))
            else:
                c = T.INK_SOFT
            pygame.draw.rect(s, c, (x, y, cell, cell), border_radius=2)
        # A legenda vai logo abaixo da ÚLTIMA linha desenhada, não abaixo do
        # retângulo: o retângulo é o espaço oferecido, e o desenho quase nunca
        # o preenche inteiro.
        fim = rect.y + 7 * (cell + gap)
        T.text(s, f"um ano  ·  até {time.strftime('%d/%m', hoje)}",
               (rect.x, fim + 8), 15, T.TEXT_FAINT)


# ═══════════════════════════════════════════════════════════════════════════
# CELULAR
# ═══════════════════════════════════════════════════════════════════════════
class PhoneScreen(Screen):
    name = "CELULAR"
    icon = "󰄜"

    ACOES = [
        ("ver o que está diferente", ["stylus-phone", "status"]),
        # O WebDAV não copia nada: monta o celular e os discos de lá entram
        # na estante junto com os de casa. Fica aqui, e não numa seção
        # própria, porque quem procura isso está procurando "o celular".
        ("pôr a coleção do celular na estante (WebDAV)",
         ["stylus-term", "WebDAV", "stylus-webdav", "ligar"]),
        ("tirar a coleção do celular da estante",
         ["stylus-webdav", "desligar"]),
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
            # maxw: sem ele, "pôr a coleção do celular na estante (WebDAV)"
            # era desenhado PARA FORA da caixa e entrava por baixo do painel
            # de saída, cortado no meio de uma palavra e sem reticências —
            # que se lê como texto corrompido, não como texto comprido.
            T.text(s, ("▸ " if sel else "  ") + rotulo, (box.x + 14, box.y + 12),
                   21, T.TEXT if sel else T.TEXT_DIM, maxw=box.w - 28)
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
        # As duas coisas novas que só existiam no terminal. Aqui é onde quem
        # está no sofá vai procurá-las — e a tela cheia é o modo em que a
        # máquina liga.
        ("baixar do Qobuz e arquivar",
         ["stylus-term", "Qobuz", "stylus-qobuz", "abrir"]),
        ("o papel de parede vira o disco de agora",
         ["stylus-wallpaper"]),
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
                   20, T.TEXT if sel else T.TEXT_DIM, maxw=box.w - 28)
            y += 50
        self.app.job_panel(s, pygame.Rect(x + 510, r.y + 120,
                                          r.right - x - 554, r.h - 220),
                           self.job)
        self.app.hint(s, r, "enter roda   ·   a saída aparece do lado")


# ═══════════════════════════════════════════════════════════════════════════
# QOBUZ — procurar e baixar
#
#  Busca direto pela API do Qobuz (via stylus-qobuz buscar), sem navegador.
#  Download precisa da interface qobuz-dl-gui no ar (servir antes).
# ═══════════════════════════════════════════════════════════════════════════
class QobuzScreen(Screen):
    name = "QOBUZ"
    icon = "󰝡"
    COLS = 5

    API = "http://127.0.0.1:8765/api/search"

    def __init__(self, app):
        super().__init__(app)
        self.query = ""
        self.searching = False
        self.loading = False
        self.results = []
        self.sel = 0
        self.scroll = 0.0
        self.target = 0.0
        self.error = None
        self.gui_up = False
        self.examing = None
        self.job = None
        self.error = None
        self.examing = None

    def enter(self):
        self._check_gui()

    def _check_gui(self):
        import urllib.request
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/", timeout=2)
            self.gui_up = True
        except Exception:
            self.gui_up = False

    def _search(self):
        """Busca via stylus-qobuz buscar (API direta, sem navegador).
        Roda em thread para não congelar a UI."""
        if not self.query.strip():
            return
        self.searching = False
        self.loading = True
        self.error = None

        def _do():
            try:
                r = subprocess.run(
                    ["stylus-qobuz", "buscar", self.query.strip()],
                    capture_output=True, text=True, timeout=20
                )
                out = r.stdout.strip()
                if not out:
                    self.error = r.stderr.strip() or "resposta vazia"
                    return
                data = json.loads(out)
                if "error" in data:
                    self.error = data["error"]
                    return
                self.results = data.get("results", [])
                self.sel = 0
                self.scroll = 0.0
                self.target = 0.0
            except subprocess.TimeoutExpired:
                self.error = "busca demorou demais"
            except json.JSONDecodeError as e:
                self.error = f"resposta inválida: {e}"
            except Exception as e:
                self.error = str(e)
            finally:
                self.loading = False

        threading.Thread(target=_do, daemon=True).start()

    def _download(self, item):
        """Baixa e arquiva — precisa da interface qobuz-dl-gui no ar."""
        if not self.gui_up:
            self.app.toast("interface Qobuz não está no ar — stylus qobuz servir")
            return
        if self.job and not self.job.done:
            self.app.toast("já tem download rodando")
            return
        url = item.get("url", "")
        artist = item.get("display_subtitle", "")
        title = item.get("display_title", "")
        if not url:
            self.app.toast("sem URL para baixar")
            return
        queue_file = os.path.expanduser("~/.local/share/stylus/qobuz-queue.txt")
        os.makedirs(os.path.dirname(queue_file), exist_ok=True)
        with open(queue_file, "w") as f:
            f.write(f"{url}|{artist}|{title}\n")
        self.job = Job(
            ["stylus-qobuz", "fila", queue_file],
            f"baixando: {artist} — {title}"
        )
        self.examing = None
        self.app.toast(f"na fila: {artist} — {title}")

    def key(self, ev):
        # ── overlay de exame ────────────────────────────────────────────────
        if self.examing:
            if ev.key == pygame.K_ESCAPE:
                self.examing = None
            elif ev.key == pygame.K_d:
                self._download(self.examing)
            elif ev.key == pygame.K_i:
                url = self.examing.get("url", "")
                if url:
                    subprocess.run(["xclip", "-selection", "clipboard"],
                                   input=url.encode(), timeout=3)
                    self.app.toast("URL copiada")
            return True

        # ── modo de busca ───────────────────────────────────────────────────
        if self.searching:
            if ev.key == pygame.K_ESCAPE:
                self.searching, self.query = False, ""
            elif ev.key == pygame.K_RETURN:
                self._search()
            elif ev.key == pygame.K_BACKSPACE:
                self.query = self.query[:-1]
            elif ev.unicode and ev.unicode.isprintable():
                self.query += ev.unicode
            self.sel = 0
            return True

        # ── navegação nos resultados ────────────────────────────────────────
        n = len(self.results)
        if ev.key == pygame.K_SLASH:
            self.searching, self.query = True, ""
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            if n:
                self.sel = (self.sel + 1) % n
        elif ev.key in (pygame.K_UP, pygame.K_k):
            if n:
                self.sel = (self.sel - 1) % n
        elif ev.key in (pygame.K_RIGHT, pygame.K_l):
            if n:
                self.sel = min(n - 1, self.sel + self.COLS)
        elif ev.key in (pygame.K_LEFT, pygame.K_h):
            if n:
                self.sel = max(0, self.sel - self.COLS)
        elif ev.key == pygame.K_PAGEDOWN:
            if n:
                self.sel = min(n - 1, self.sel + self.COLS * 3)
        elif ev.key == pygame.K_PAGEUP:
            if n:
                self.sel = max(0, self.sel - self.COLS * 3)
        elif ev.key == pygame.K_HOME:
            self.sel = 0
        elif ev.key == pygame.K_END:
            self.sel = max(0, n - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if n:
                self.examing = self.results[self.sel]
        elif ev.key == pygame.K_r:
            self._check_gui()
            if self.query:
                self._search()
        else:
            return False
        return True

    # ── desenho ─────────────────────────────────────────────────────────────

    def _card(self, s, rect, item, sel):
        """Um disco na prateleira."""
        if sel:
            T.panel(s, rect, T.INK_LIFT, radius=10, border=T.LINE)
        else:
            T.panel(s, rect, T.INK_SOFT, radius=10, border=T.LINE)

        # capa: silhouette de disco
        T.text(s, "󰝡", (rect.centerx, rect.centery - 4), 38,
               T.AMBER if sel else T.TEXT_FAINT, anchor="center")

        # qualidade: se hi-res, um brilho
        quality = item.get("quality", "")
        if quality and "hi" in quality.lower():
            T.text(s, "◆", (rect.right - 10, rect.y + 10), 11,
                   T.AMBER, anchor="topright")

        # informações abaixo
        ty = rect.bottom + 8
        title = item.get("display_title", "?")
        artist = item.get("display_subtitle", "?")
        year = item.get("release_year", "")
        tracks = item.get("tracks", 0)

        T.text(s, title, (rect.x, ty), 15,
               T.TEXT if sel else T.TEXT_DIM, maxw=rect.w)
        T.text(s, artist, (rect.x, ty + 20), 13, T.TEXT_FAINT, maxw=rect.w)

        # linha de info: ano · faixas · qualidade
        info_parts = []
        if year:
            info_parts.append(str(year))
        if tracks:
            info_parts.append(f"{tracks}faixas")
        if quality:
            info_parts.append(quality)
        info = "  ·  ".join(info_parts)
        if info:
            T.text(s, info, (rect.x, ty + 36), 12, T.TEXT_FAINT, maxw=rect.w)

    def _draw_examing(self, s, r):
        """Overlay de exame — segurar o disco na mão."""
        item = self.examing
        if not item:
            return

        # fundo escurecido
        dim = pygame.Surface(r.size)
        dim.fill(T.INK)
        dim.set_alpha(220)
        s.blit(dim, r.topleft)

        # painel central
        pw, ph = 520, 360
        px = r.x + (r.w - pw) // 2
        py = r.y + (r.h - ph) // 2
        T.panel(s, pygame.Rect(px, py, pw, ph), T.INK_LIFT, radius=16,
                border=T.LINE)

        # disco grande no centro
        T.text(s, "󰝡", (px + pw // 2, py + 70), 72, T.AMBER, anchor="center")

        # informações
        title = item.get("display_title", "?")
        artist = item.get("display_subtitle", "?")
        year = item.get("release_year", "")
        tracks = item.get("tracks", 0)
        quality = item.get("quality", "")

        T.text(s, title, (px + 32, py + 130), 24, T.TEXT, bold=True, maxw=pw - 64)
        T.text(s, artist, (px + 32, py + 165), 20, T.AMBER, maxw=pw - 64)

        # detalhes
        y = py + 205
        detail_parts = []
        if year:
            detail_parts.append(f"lançamento: {year}")
        if tracks:
            detail_parts.append(f"{tracks} faixas")
        if quality:
            detail_parts.append(f"qualidade: {quality}")
        detail = "  ·  ".join(detail_parts)
        if detail:
            T.text(s, detail, (px + 32, y), 16, T.TEXT_DIM, maxw=pw - 64)

        # status do download
        y = py + 250
        if self.gui_up:
            T.text(s, "d baixa para a estante", (px + 32, y), 16, T.GREEN)
        else:
            T.text(s, "interface off — stylus qobuz servir para baixar",
                   (px + 32, y), 14, T.TEXT_FAINT)

        # ações
        y = py + ph - 50
        T.text(s, "d baixa  ·  i copia URL  ·  esc volta",
               (px + 32, y), 15, T.TEXT_FAINT)

    def draw(self, s, r):
        pad, gap = 30, 14
        head = 58
        self.COLS = max(3, min(8, r.w // 200))

        # ── header ──────────────────────────────────────────────────────────
        status = "pronto" if self.gui_up else "busca direta (interface off)"
        T.text(s, "a loja", (r.x + pad, r.y + 18), 30, T.TEXT, bold=True)
        T.text(s, status, (r.right - pad, r.y + 24), 15,
               T.GREEN if self.gui_up else T.TEXT_FAINT, anchor="topright")

        if self.searching or self.query:
            T.text(s, "/ " + self.query + ("▌" if self.searching else ""),
                   (r.x + pad, r.y + 52), 24, T.AMBER)

        if self.loading:
            T.text(s, "buscando…", (r.centerx, r.centery), 22,
                   T.AMBER, anchor="center")
            return

        if self.error:
            T.text(s, self.error, (r.centerx, r.centery - 20), 20,
                   T.RED, anchor="center")
            T.text(s, "/ procura de novo", (r.centerx, r.centery + 15),
                   17, T.TEXT_FAINT, anchor="center")
            return

        if not self.results and self.query:
            T.text(s, f'nenhum disco com "{self.query}"',
                   (r.centerx, r.centery), 22, T.TEXT_DIM, anchor="center")
            T.text(s, "/ procura de novo",
                   (r.centerx, r.centery + 30), 17, T.TEXT_FAINT, anchor="center")
            return
        if not self.results and not self.query:
            T.text(s, "/ procura  ·  r atualiza",
                   (r.centerx, r.centery), 20, T.TEXT_FAINT, anchor="center")
            return

        # ── resultados ──────────────────────────────────────────────────────
        cw = (r.w - pad * 2 - gap * (self.COLS - 1)) // self.COLS
        ch = cw + 58
        view_h = r.h - head - 96
        rows_vis = max(1, view_h // ch)

        row = self.sel // self.COLS
        if row * ch < self.target:
            self.target = row * ch
        elif (row + 1) * ch > self.target + rows_vis * ch:
            self.target = (row + 1 - rows_vis) * ch
        self.target = max(0, min(self.target,
                                 max(0, (len(self.results) + self.COLS - 1)
                                     // self.COLS - rows_vis) * ch))
        dt = self.app.clock.get_time() / 1000.0
        alpha = 1.0 - pow(2.718281828, -dt * 12.0) if dt > 0 else 0.28
        self.scroll += (self.target - self.scroll) * alpha

        clip = pygame.Rect(r.x, r.y + head, r.w, view_h)
        old = s.get_clip()
        s.set_clip(clip)
        for i, item in enumerate(self.results):
            cx = r.x + pad + (i % self.COLS) * (cw + gap)
            cy = r.y + head + (i // self.COLS) * ch - int(self.scroll)
            if cy > clip.bottom or cy + ch < clip.top:
                continue
            self._card(s, pygame.Rect(cx, cy, cw, cw), item, i == self.sel)
        s.set_clip(old)

        n_found = len(self.results)
        T.text(s, f"{n_found} discos", (r.right - pad, r.y + 20), 16,
               T.TEXT_FAINT, anchor="topright")

        if self.results:
            item = self.results[self.sel]
            hint = (f"{item.get('display_subtitle', '')} — "
                    f"{item.get('display_title', '')}   ·   "
                    f"/ procura   enter examina   d baixa")
            self.app.hint(s, r, hint)

        if self.job:
            self.app.job_panel(s, pygame.Rect(r.right - 380, r.y + head + 8,
                                              360, 160), self.job)

        if self.examing:
            self._draw_examing(s, r)


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
        self.sub = "menu"  # menu | buscar | baixadas
        self.query = ""
        self.query_active = False
        self.results = []
        self.downloaded = []
        self.downloaded_ids = set()
        self.syncing = False
        self.job = None
        self._installed_cache = {}  # cache de shutil.which() por frame
        self._load_downloaded()

    def _load_downloaded(self):
        import json as _json
        db_path = os.path.expanduser("~/.local/share/stylus/charts.json")
        try:
            with open(db_path) as f:
                db = _json.load(f)
            self.downloaded = list(db.get("downloaded", {}).values())
            self.downloaded_ids = set(db.get("downloaded", {}).keys())
        except (FileNotFoundError, _json.JSONDecodeError):
            self.downloaded = []
            self.downloaded_ids = set()

    def _do_search(self):
        import http.client as _http
        import ssl as _ssl
        import json as _json
        try:
            ctx = _ssl.create_default_context()
            conn = _http.HTTPSConnection("api.enchor.us", timeout=30, context=ctx)
            data = _json.dumps({"search": self.query, "page": 1}).encode()
            conn.request("POST", "/search", body=data, headers={
                "Content-Type": "application/json", "User-Agent": "stylus-ch/1.0"})
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
            if resp.status in (200, 201):
                result = _json.loads(raw, strict=False)
                self.results = result.get("data", [])[:20]
        except Exception:
            self.results = []

    def key(self, ev):
        if self.sub == "buscar":
            return self._key_buscar(ev)
        elif self.sub == "baixadas":
            return self._key_baixadas(ev)
        return self._key_menu(ev)

    def _key_menu(self, ev):
        total = len(self.ACOES) + 3  # +3 for buscar, baixadas, sync
        if ev.key in (pygame.K_RIGHT, pygame.K_l, pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % total
        elif ev.key in (pygame.K_LEFT, pygame.K_h, pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % total
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.sel < len(self.ACOES):
                nome, cmd, binario = self.ACOES[self.sel]
                import shutil as _sh
                if _sh.which(binario):
                    self.app.toast(f"abrindo {nome}…")
                    spawn(cmd)
                else:
                    self.app.toast(f"{nome} não está instalado — "
                                   f"`stylus app {binario}` resolve")
            elif self.sel == len(self.ACOES):
                self.sub = "buscar"
                self.query_active = True
                self.query = ""
            elif self.sel == len(self.ACOES) + 1:
                self._load_downloaded()
                self.sub = "baixadas"
                self.sel = 0
            else:
                self.app.toast("sincronizando pro celular…")
                self.syncing = True
                self.job = Job(["stylus-ch", "sync"], "sync clone hero")
        else:
            return False
        return True

    def _key_buscar(self, ev):
        if self.query_active:
            if ev.key == pygame.K_ESCAPE:
                self.sub = "menu"
                self.query_active = False
                return True
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.query.strip():
                    self._do_search()
                self.query_active = False
                return True
            elif ev.key == pygame.K_BACKSPACE:
                self.query = self.query[:-1]
                return True
            elif ev.unicode and ev.unicode.isprintable():
                self.query += ev.unicode
                return True
        else:
            if ev.key == pygame.K_ESCAPE:
                self.sub = "menu"
                return True
            elif ev.key in (pygame.K_DOWN, pygame.K_j):
                self.sel = (self.sel + 1) % max(1, len(self.results))
            elif ev.key in (pygame.K_UP, pygame.K_k):
                self.sel = (self.sel - 1) % max(1, len(self.results))
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.results:
                chart = self.results[self.sel]
                cid = str(chart["chartId"])
                if cid not in self.downloaded_ids:
                    self.app.toast(f"baixando {chart['artist']} — {chart['name']}…")
                    self.job = Job(["stylus-ch", "baixar", cid], chart["name"])
                else:
                    self.app.toast("já baixado")
            elif ev.key == pygame.K_f:
                self.query_active = True
        return True

    def _key_baixadas(self, ev):
        if ev.key == pygame.K_ESCAPE:
            self.sub = "menu"
            return True
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % max(1, len(self.downloaded))
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % max(1, len(self.downloaded))
        return True

    def draw(self, s, r):
        import shutil as _sh
        x, y = r.x + 44, r.y + 40
        T.text(s, "jogos", (x, y), 30, T.TEXT, bold=True)
        T.text(s, "porque nem tudo é disco", (x, y + 40), 18, T.TEXT_FAINT)

        if self.sub == "buscar":
            self._draw_buscar(s, r)
        elif self.sub == "baixadas":
            self._draw_baixadas(s, r)
        else:
            self._draw_menu(s, r, _sh)

        self.app.job_panel(s, pygame.Rect(r.right - 340, r.bottom - 120,
                                          300, 80), self.job)

    def _draw_menu(self, s, r, _sh):
        x, y = r.x + 44, r.y + 96
        cw, gap = 240, 24
        for i, (nome, _c, binario) in enumerate(self.ACOES):
            box = pygame.Rect(x + i * (cw + gap), y, cw, 150)
            sel = i == self.sel
            if sel:
                T.shadow_card(s, box, radius=10)
            T.panel(s, box, T.INK_LIFT if sel else T.INK_SOFT, radius=14,
                    border=T.AMBER if sel else T.LINE)
            tem = bool(_sh.which(binario))
            T.text(s, nome, box.center, 26, T.TEXT if tem else T.TEXT_FAINT,
                   bold=True, anchor="center")
            if not tem:
                T.text(s, "não instalado", (box.centerx, box.centery + 34), 16,
                       T.TEXT_FAINT, anchor="center")

        # CH songs row
        y2 = y + 190
        ch_actions = [
            ("buscar músicas", "󰍉"),
            (f"baixadas ({len(self.downloaded)})", "󰀙"),
            ("sincronizar pro celular", "󰢶"),
        ]
        for i, (label, icon) in enumerate(ch_actions):
            bx = pygame.Rect(x + i * (cw + gap), y2, cw, 60)
            sel = i + len(self.ACOES) == self.sel
            if sel:
                T.shadow_card(s, bx, radius=8)
            T.panel(s, bx, T.INK_LIFT if sel else T.INK_SOFT, radius=10,
                    border=T.AMBER if sel else T.LINE)
            T.text(s, f"{icon}  {label}", bx.center, 20, T.TEXT if sel else T.TEXT_FAINT,
                   bold=sel, anchor="center")

        self.app.hint(s, r, "enter abre · ← → navega")

    def _draw_buscar(self, s, r):
        x, y = r.x + 44, r.y + 90

        # Search bar
        bar = pygame.Rect(x, y, 600, 44)
        border = T.AMBER if self.query_active else T.LINE
        T.panel(s, bar, T.INK_LIFT, radius=10, border=border)
        placeholder = "digite o nome da música…" if not self.query else self.query
        T.text(s, f"󰍉  {placeholder}", (bar.x + 14, bar.y + 11), 20,
               T.TEXT if self.query else T.TEXT_FAINT)
        if self.query_active:
            # cursor blink
            cw = T.font.size(self.query)[0]
            pygame.draw.line(s, T.AMBER, (bar.x + 14 + cw + 2, bar.y + 10),
                             (bar.x + 14 + cw + 2, bar.y + 32), 2)

        # Results
        y += 64
        if self.results:
            for i, c in enumerate(self.results[:15]):
                sel = i == self.sel and not self.query_active
                cid = str(c["chartId"])
                downloaded = cid in self.downloaded_ids
                name = c.get("name", "?")
                artist = c.get("artist", "?")
                charter = c.get("charter", "?")
                bg = T.INK_LIFT if sel else None
                if bg:
                    T.panel(s, pygame.Rect(x - 8, y - 2, 700, 28), bg, radius=6)
                if downloaded:
                    T.text(s, "✓", (x, y), 18, T.GREEN)
                T.text(s, artist, (x + (22 if downloaded else 0), y), 18,
                       T.AMBER if sel else T.PINK)
                aw = T.font.size(artist + "  ")[0]
                T.text(s, f"— {name}", (x + (22 if downloaded else 0) + aw, y), 18,
                       T.TEXT if sel else T.TEXT_FAINT)
                T.text(s, f"({charter})", (x + 500, y), 16, T.TEXT_DIM)
                y += 30
        elif self.query and not self.query_active:
            T.text(s, "nenhum resultado", (x, y), 18, T.TEXT_FAINT)

        T.text(s, "enter: baixar · f: buscar · esc: voltar",
               (x, r.bottom - 40), 16, T.TEXT_FAINT)

    def _draw_baixadas(self, s, r):
        x, y = r.x + 44, r.y + 90
        T.text(s, f"baixadas  {len(self.downloaded)} charts", (x, y), 24,
               T.TEXT, bold=True)
        y += 44

        by_artist = {}
        for info in self.downloaded:
            artist = info.get("artist", "Unknown")
            by_artist.setdefault(artist, []).append(info)

        flat = []
        for artist in sorted(by_artist.keys()):
            flat.append(("artist", artist, None))
            for info in by_artist[artist]:
                flat.append(("song", info.get("name", "?"), info))

        for i, (kind, name, info) in enumerate(flat[:20]):
            sel = i == self.sel
            if kind == "artist":
                T.text(s, name, (x + 8, y), 18, T.PINK, bold=True)
            else:
                T.text(s, f"— {name}", (x + 8, y), 17,
                       T.TEXT if sel else T.TEXT_FAINT)
            y += 26

        T.text(s, "esc: voltar", (x, r.bottom - 40), 16, T.TEXT_FAINT)


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
        self._disk = None

    def opcoes(self):
        return [
            (f"estante: {vinyl.library_root()}", None),
            ("procurar outra pasta de música", ["stylus-pickfolder"]),
            ("conferir o caminho do áudio", ["stylus-audio"]),
            ("driver de vídeo", ["stylus-gpu", "--status"]),
            ("atualizar o STYLUS", ["stylus-update"]),
            ("sobre", None),
        ]

    def _disk_info(self):
        if self._disk is not None:
            return self._disk
        try:
            st = os.statvfs(vinyl.library_root())
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            self._disk = (total, free)
        except Exception:                 # noqa: BLE001
            self._disk = (0, 0)
        return self._disk

    def _stylus_version(self):
        try:
            r = subprocess.run(["git", "-C", "/var/lib/stylus/repo", "log",
                                "-1", "--format=%h %s"],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip() or "?"
        except Exception:                 # noqa: BLE001
            return "?"

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
                   maxw=box.w - 30)
            y += 50

        # version + disk info
        y_info = r.bottom - 160
        T.text(s, "STYLUS", (x, y_info), 40, T.AMBER, bold=True)
        T.text(s, f"build: {self._stylus_version()}", (x, y_info + 46), 16,
               T.TEXT_FAINT)
        total, free = self._disk_info()
        if total > 0:
            used_gb = (total - free) / (1024 ** 3)
            total_gb = total / (1024 ** 3)
            pct = int((total - free) / total * 100)
            disk_txt = f"disco: {used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"
            T.text(s, disk_txt, (x, y_info + 68), 16, T.TEXT_FAINT)

        T.text(s, "a agulha é o único ponto em que um objeto vira som.",
               (x, r.bottom - 82), 19, T.TEXT_DIM)
        self.app.job_panel(s, pygame.Rect(x + 600, r.y + 100,
                                          r.right - x - 644, r.h - 200),
                           self.job)


# ═══════════════════════════════════════════════════════════════════════════
# INSTALAR — só no medium ao vivo
# ═══════════════════════════════════════════════════════════════════════════
def rodando_do_pendrive():
    """Estamos no medium ao vivo, e não numa máquina instalada?"""
    return os.path.isdir("/run/archiso")


class InstallScreen(Screen):
    """A porta de entrada do pendrive.

    POR QUE ISTO EXISTE: a ISO liga no MODO MÚSICA — é o que o sistema é — e
    o modo música não tinha instalador em lugar nenhum. As duas únicas
    referências a instalar no sistema inteiro chamavam `install-stylus`, um
    comando que nunca existiu (o certo é `stylus-install`). Ou seja: quem
    gravava o pendrive, ligava o computador e olhava a tela não tinha
    NENHUM caminho até o instalador, a não ser adivinhar o nome do comando
    num terminal que o modo música também não mostra.

    Por isso esta seção é a primeira do trilho quando se está no pendrive, e
    é nela que a interface abre. Numa máquina já instalada ela não existe.
    """
    name = "INSTALAR"
    icon = "󰋊"

    PASSOS = [
        ("Instalar o STYLUS neste computador",
         "as perguntas são poucas e nada é escrito no disco até você confirmar"),
        ("Só experimentar por enquanto",
         "o pendrive funciona inteiro; dá para instalar depois"),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0

    def key(self, ev):
        if ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % len(self.PASSOS)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % len(self.PASSOS)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.sel == 0:
                self.instalar()
            else:
                # Para a estante, que é o resto do sistema.
                self.app._goto(self.app.screens.index(
                    next(sc for sc in self.app.screens
                         if isinstance(sc, ShelfScreen))))
        else:
            return False
        return True

    def instalar(self):
        """Abre o instalador num terminal, por cima da tela cheia.

        Num terminal e não aqui dentro porque o instalador é um diálogo de
        verdade — ele pergunta senha, mostra o que vai fazer com o disco e
        espera você digitar SIM. Reescrever isso em pygame seria uma segunda
        versão da parte do sistema onde um erro apaga o disco de alguém.

        O i3 do modo música põe toda janela em tela cheia, então o terminal
        toma a tela e a pessoa não precisa achar nada.
        """
        self.app.toast("abrindo o instalador…")
        if not spawn(["stylus-term", "Instalar o STYLUS",
                      "sudo", "stylus-install"]):
            self.app.toast("não consegui abrir o instalador")

    def draw(self, s, r):
        x, y = r.x + 44, r.y + 44
        T.text(s, "você está rodando do pendrive", (x, y), 19, T.TEXT_FAINT)
        T.text(s, "Instalar o STYLUS", (x, y + 34), 40, T.TEXT, bold=True)
        T.text(s, "nada é escrito no disco até você ler o resumo e confirmar.",
               (x, y + 92), 20, T.TEXT_DIM, maxw=r.w - 90)

        y += 148
        for i, (rotulo, sub) in enumerate(self.PASSOS):
            sel = i == self.sel
            box = pygame.Rect(x, y, min(r.w - 90, 720), 74)
            T.panel(s, box, T.INK_LIFT if sel else T.INK_SOFT, radius=12,
                    border=T.AMBER if sel else T.LINE)
            T.text(s, ("▸ " if sel else "  ") + rotulo, (box.x + 20, box.y + 14),
                   23, T.TEXT if sel else T.TEXT_DIM, maxw=box.w - 40)
            T.text(s, sub, (box.x + 34, box.y + 44), 17, T.TEXT_FAINT,
                   maxw=box.w - 54)
            y += 86

        y += 18
        for linha in (
            "O instalador sabe instalar AO LADO do que já está no computador:",
            "ele usa só o espaço livre e não formata nada que já existe.",
        ):
            T.text(s, linha, (x, y), 18, T.TEXT_FAINT, maxw=r.w - 90)
            y += 26

        self.app.hint(s, r, "enter escolhe   ·   ↑↓ anda   ·   "
                            "o instalador abre por cima desta tela")


# ═══════════════════════════════════════════════════════════════════════════
# A casca
# ═══════════════════════════════════════════════════════════════════════════
STACK_FILE = os.path.expanduser("~/.local/share/stylus/stack.json")
UI_PREFS_FILE = os.path.expanduser("~/.local/share/stylus/ui.json")


def _load_prefs():
    try:
        import json
        with open(UI_PREFS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                 # noqa: BLE001 — sem arquivo é primeiro uso
        return {}


def _save_prefs(p):
    try:
        import json
        os.makedirs(os.path.dirname(UI_PREFS_FILE), exist_ok=True)
        with open(UI_PREFS_FILE, "w", encoding="utf-8") as fh:
            json.dump(p, fh)
    except OSError:
        pass


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
        self.thumbs_hi = Thumbs(px=640)
        self.playing = Playing()
        self.shelf.load()

        self.screens = [NowScreen(self), ShelfScreen(self), StackScreen(self),
                        DiaryScreen(self), SignalScreen(self), PhoneScreen(self),
                        ToolsScreen(self), QobuzScreen(self), GamesScreen(self),
                        SettingsScreen(self)]
        self.cur = 1                      # abre na ESTANTE, que é o assunto
        # No pendrive, INSTALAR vem primeiro e é onde a interface abre. A
        # estante de um medium ao vivo está vazia — abrir nela é a pior
        # primeira impressão possível de um sistema cujo assunto é a coleção,
        # e instalar é o que a pessoa foi ali fazer.
        if rodando_do_pendrive():
            self.screens.insert(0, InstallScreen(self))
            self.cur = 0
        self.rail = False                 # o trilho está com o foco?
        self.rail_sel = self.cur
        self.stack = self._stack_load()
        self._toast = ""
        self._toast_until = 0.0
        self._toast_kind = "info"
        self._toast_t = 0.0       # momento em que o toast apareceu
        # Transição entre seções: fade rápido ao trocar de tela.
        self._trans_alpha = 0.0
        self._trans_target = 0.0
        # Sleep timer: minutes remaining, 0 = off
        self._sleep_minutes = 0
        self._sleep_end = 0.0
        # Shuffle/repeat state
        self.shuffle = False
        self.repeat = 0  # 0=off, 1=repeat side, 2=repeat album
        # O lado em que o disco está, para saber quando ele VIRA. Ver
        # _watch_side: no modo música esta tela é a sessão inteira, e a tese
        # do sistema acontecendo num balãozinho de canto seria pouco.
        self._lado_disco = None
        self._lado_i = None
        self._lado_t = 0.0
        self._flip = None
        self._lyr_cache = (None, None)
        # Miniaturas já no tamanho do bloco TOCANDO do trilho: escalar 320px
        # para 46 a cada quadro é trabalho de GPU queimado em nada.
        self._rail_thumb = {}
        # Partículas atmosféricas — poeira âmbar no fundo
        self._particles = T.Particles(self.W, self.H, n=18)
        # O borrão de fundo da AGORA, um por capa e no tamanho da tela: gerar
        # por quadro seria smoothscale duplo a 60fps para desenhar a mesma
        # imagem. Guarda as últimas — voltar ao disco de ontem não regenera.
        self._backdrops = {}
        # Protetor de tela que é o PROPRIO deck: parado na AGORA sem tocar em
        # nada, a tela chama o disco sozinha, uma vez por álbum (ver run()).
        # Ligado/desligado pelo 'D' na AGORA — e a escolha fica guardada:
        # quem desligou uma vez não quer que a máquina "esqueça" e volte.
        self.IDLE_DECK_SECS = 240
        self._ultima_entrada = time.time()
        self._deck_auto = None
        self.auto_deck = bool(_load_prefs().get("auto_deck", True))
        self._born = time.time()
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
    def _deck_bin(self):
        # caminho absoluto é mais confiável que depender do PATH da sessão
        # gráfica (que às vezes não tem /usr/local/bin). Tenta o instalado,
        # depois o da fonte, depois o PATH.
        for cand in ("/usr/local/bin/stylus-deck",
                     "/usr/share/stylus/stylus-deck",
                     "stylus-deck"):
            if cand == "stylus-deck" or os.path.exists(cand):
                return cand
        return "stylus-deck"

    def put_on(self, folder):
        if not os.path.isdir(folder):
            self.toast(f"disco não existe: {os.path.basename(folder)}")
            return False
        self.toast(f"pondo {os.path.basename(folder)}…")
        if not spawn([self._deck_bin(), "--no-scope", folder]):
            self.toast("não consegui pôr o disco (erro ao iniciar)")
            return False
        return True

    def open_deck(self):
        """Abre o deck sem reiniciar o disco.

        Antes reiniciava o mpv inteiro (matava o tocador e criava outro)
        só para mostrar o visual — o disco recomeçava e fechar o deck
        parava a música. Agora é só view: o ritual observa o que já está
        tocando via socket/MPRIS, não toca no mpv. Fechar não para, abrir
        não reinicia. Se nada estiver tocando, sorteia um disco novo com
        cerimônia completa (agulha sobe, gira, desce e só então começa).
        """
        snap = self.playing.session.snapshot()
        has_music = bool(snap.get("path")) or snap.get("source") != "none"
        if has_music:
            self.toast("abrindo o deck…")
            if not spawn([self._deck_bin(), "--view"]):
                self.toast("não consegui abrir o deck")
        else:
            # nada tocando: põe um disco novo com cerimônia (agulha levanta,
            # disco gira, agulha desce e música começa) em vez de só mostrar
            # tela vazia — no sofá, Enter tem que sempre fazer alguma coisa.
            self.toast("nada tocando — sorteando um disco…")
            if not spawn([self._deck_bin()]):
                self.toast("não consegui abrir o deck")

    def lyric_state(self, al, track):
        """(linhas do .lrc, índice da linha de agora) — ou None.

        O par em vez de só o texto: a AGORA mostra uma JANELA de letra, e
        quem desenha precisa saber onde está o agora dentro dela. As linhas
        em branco continuam valendo (marcam trecho instrumental); aqui elas
        viram respiro, e não linha destacada vazia.
        """
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
        return lines, lo

    def backdrop(self, al, size):
        """O borrão da capa como fundo da AGORA, ou None sem capa.

        Desfocar aqui é ENCOLHER até quase nada e voltar — o smoothscale do
        pygame não tem gaussiana, e média de área em duas passadas é a mesma
        coisa que um borrão pesado, sem dependência nova. O véu de INK por
        cima é o que garante que letra legível venha antes de ambiente.
        """
        if not al.cover or not os.path.isfile(al.cover):
            return None
        hit = self._backdrops.get(al.cover)
        if hit is not None and hit.get_size() == tuple(size):
            return hit
        try:
            im = pygame.image.load(al.cover).convert()
        except Exception:                     # noqa: BLE001 — capa ruim, tela limpa
            return None
        w, h = int(size[0]), int(size[1])
        pequeno = (max(2, w // 16), max(2, h // 16))
        blur = pygame.transform.smoothscale(
            pygame.transform.smoothscale(im, pequeno), (w, h))
        blur = pygame.transform.smoothscale(
            pygame.transform.smoothscale(blur, pequeno), (w, h))
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((*T.INK, 205))
        blur.blit(veil, (0, 0))
        self._backdrops.clear()               # uma capa quente basta
        self._backdrops[al.cover] = blur
        return blur

    def toast(self, msg, secs=3.0, kind="info"):
        self._toast, self._toast_until = msg, time.time() + secs
        self._toast_t = time.time()
        self._toast_kind = kind

    def toggle_sleep(self):
        """Cicla o sleep timer: off → 30m → 60m → 90m → off."""
        cycle = [0, 30, 60, 90]
        idx = cycle.index(self._sleep_minutes) if self._sleep_minutes in cycle else 0
        self._sleep_minutes = cycle[(idx + 1) % len(cycle)]
        if self._sleep_minutes > 0:
            self._sleep_end = time.time() + self._sleep_minutes * 60
            self.toast(f"sleep timer: {self._sleep_minutes} minutos")
        else:
            self.toast("sleep timer desligado")

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.toast("embaralhar: " + ("ligado" if self.shuffle else "desligado"))

    def toggle_repeat(self):
        labels = ["desligado", "repetir lado", "repetir álbum"]
        self.repeat = (self.repeat + 1) % 3
        self.toast("repetir: " + labels[self.repeat])

    @staticmethod
    _volume_cache = (0, 0)

    @classmethod
    def volume_pct(cls):
        """Volume atual (0-100). Throttled: 1 consulta/frame no máximo."""
        cls._audio_level_counter += 1
        if cls._audio_level_counter % 5 != 0:
            return cls._volume_cache[0]
        try:
            r = subprocess.run(["pamixer", "--get-volume"],
                               capture_output=True, text=True, timeout=2)
            val = int(r.stdout.strip() or 0)
            cls._volume_cache = (val, cls._audio_level_counter)
            return val
        except Exception:                 # noqa: BLE001
            return cls._volume_cache[0]

    _audio_level_cache = (0.0, 0)
    _audio_level_counter = 0

    @classmethod
    def audio_level(cls):
        """Nível de áudio atual (0.0 a 1.0) para efeitos visuais reativos.
        Throttled: só consulta wpctl a cada 5 chamadas (~83ms a 60fps)."""
        cls._audio_level_counter += 1
        if cls._audio_level_counter % 5 != 0:
            return cls._audio_level_cache[0]
        try:
            r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                               capture_output=True, text=True, timeout=1)
            parts = r.stdout.strip().split()
            if len(parts) >= 2:
                val = float(parts[1])
                cls._audio_level_cache = (val, cls._audio_level_counter)
                return val
        except Exception:                 # noqa: BLE001
            pass
        return cls._audio_level_cache[0]

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

        # Título — âmbar, o fio que prende
        T.text(s, "STYLUS", (28, 36), 26, T.AMBER, bold=True)
        # linha fina abaixo do título
        pygame.draw.line(s, T.AMBER_DIM, (28, 70), (w - 28, 70))

        y = 100
        for i, sc in enumerate(self.screens + [_DESKTOP_ITEM]):
            atual = i == self.cur
            foco = self.rail and i == self.rail_sel
            box = pygame.Rect(12, y - 6, w - 24, 46)

            if foco:
                T.panel(s, box, T.INK_LIFT, radius=10)
            if atual:
                # barra lateral âmbar — indicador de posição
                pygame.draw.rect(s, T.AMBER, (12, y - 3, 3, 42), border_radius=2)

            cor = T.TEXT if (atual or foco) else T.TEXT_DIM
            # ícone + nome com mais espaço
            T.text(s, T.icon(sc.icon), (34, y + 4), 22, cor)
            T.text(s, sc.name, (68, y + 8), 18, cor, bold=atual)
            if i < len(self.screens):
                T.text(s, str(i + 1), (w - 22, y + 10), 15, T.TEXT_FAINT,
                       anchor="topright")
            y += 50
            if i == len(self.screens) - 1:
                pygame.draw.line(s, T.LINE, (24, y - 4), (w - 24, y - 4))
                y += 16
        snap, al, track, side, _t, frac = self.playing.where()
        if al is not None:
            # Bloco TOCANDO com painel de fundo e progresso mais largo
            ty = self.H - 120
            panel = pygame.Rect(14, ty - 8, w - 28, 100)
            T.panel(s, panel, T.INK_LIFT, radius=10, border=T.LINE)
            tx = 24
            if al.cover:
                mini = self._rail_thumb.get(al.cover)
                if mini is None:
                    full = self.thumbs.get(al.cover)
                    if full is not None:
                        mini = pygame.transform.smoothscale(full, (50, 50))
                        self._rail_thumb[al.cover] = mini
                if mini is not None:
                    cr = pygame.Rect(tx, ty + 8, 50, 50)
                    T.shadow_card(s, cr, radius=4)
                    s.blit(mini, cr)
                    tx = cr.right + 14
            T.text(s, "TOCANDO", (tx, ty - 2), 13, T.TEXT_FAINT)
            T.text(s, al.name, (tx, ty + 18), 17, T.TEXT,
                   maxw=w - tx - 24)
            T.text(s, al.artist, (tx, ty + 42), 14, T.TEXT_DIM,
                   maxw=w - tx - 24)
            bar = pygame.Rect(24, ty + 68, w - 48, 4)
            pygame.draw.rect(s, T.LINE, bar, border_radius=3)
            pygame.draw.rect(s, T.AMBER,
                             (bar.x, bar.y, int(bar.w * frac), bar.h),
                             border_radius=3)
            # elapsed / remaining
            elapsed_s = int(self.playing.time_pos())
            total_s = al.duration
            if total_s > 0:
                rem_s = max(0, total_s - elapsed_s)
                T.text(s, f"{elapsed_s // 60}:{elapsed_s % 60:02d}",
                       (24, ty + 74), 12, T.TEXT_FAINT)
                T.text(s, f"-{rem_s // 60}:{rem_s % 60:02d}",
                       (w - 24, ty + 74), 12, T.TEXT_FAINT, anchor="topright")

    # ── virar o lado ───────────────────────────────────────────────────────
    FLIP_DUR = 7.0

    def _watch_side(self):
        """Quando o LADO vira, a tela inteira diz.

        É a tese do projeto: um disco manda por vinte minutos e então PARA, e
        essa parada é o que separa ouvir um disco de ouvir uma playlist. O
        `stylus-side-watch` já avisava pelo dunst, o que serve para a área de
        trabalho; aqui a tela É o toca-discos, e um balãozinho de canto seria
        a coisa certa no tamanho errado.

        Só para frente. Arrastar a barra para trás é procurar uma faixa, não
        virar o disco — anunciar ali viraria ruído em cinco minutos.
        """
        # Duas vezes por segundo basta: o lado dura vinte minutos, e perguntar
        # a posição sessenta vezes por segundo é conversa de socket à toa em
        # toda tela, não só na AGORA.
        agora = time.time()
        if agora - self._lado_t < 0.5:
            return
        self._lado_t = agora
        try:
            _snap, al, _tr, side, t_abs, _frac = self.playing.where()
        except Exception:                 # noqa: BLE001 — nunca derrubar o laço
            return
        if al is None or side is None or not al.sides:
            self._lado_disco = self._lado_i = None
            return
        i, _s = al.side_for(t_abs)
        chave = al.folder
        if chave != self._lado_disco:     # disco novo: recomeça a contar
            self._lado_disco, self._lado_i = chave, i
            return
        if self._lado_i is not None and i > self._lado_i:
            anterior = al.sides[self._lado_i]
            ultimo = i >= len(al.sides) - 1
            self._flip = (time.time(),
                          anterior["label"].replace("SIDE", "LADO"),
                          side["label"].replace("SIDE", "LADO"),
                          f"{al.artist} — {al.name}", ultimo)
        self._lado_i = i

    def _draw_flip(self, s):
        if not self._flip:
            return
        t0, antes, agora, disco, ultimo = self._flip
        dt = time.time() - t0
        if dt > self.FLIP_DUR:
            self._flip = None
            return
        # Entra depressa e sai devagar: aparecer devagar faria a pessoa perder
        # o começo justamente do aviso que existe para ser notado.
        alpha = min(1.0, dt / 0.3)
        restante = self.FLIP_DUR - dt
        if restante < 1.2:
            alpha = min(alpha, restante / 1.2)

        camada = pygame.Surface((self.W, self.H))
        camada.fill(T.INK)
        cx, cy = self.W // 2, self.H // 2

        # Um disco, atrás do texto. Sete anéis e nada mais: é o mesmo desenho
        # que a tela "nada tocando" usa, para as duas lerem como o mesmo
        # objeto e não como duas ilustrações diferentes.
        for k in range(9):
            pygame.draw.circle(camada, T.lerp(T.INK_SOFT, T.LINE, 0.3 + k * 0.07),
                               (cx, cy), 120 + k * 34, 1)

        T.text(camada, antes, (cx, cy - 96), 26, T.TEXT_DIM, anchor="center")
        T.text(camada, "ACABOU", (cx, cy - 44), 68, T.AMBER,
               bold=True, anchor="center")
        T.text(camada, ("vire o disco para o " if ultimo else "agora é o ") + agora,
               (cx, cy + 34), 30, T.TEXT, anchor="center")
        T.text(camada, disco, (cx, cy + 84), 20, T.TEXT_FAINT,
               anchor="center", maxw=self.W - 200)

        camada.set_alpha(int(238 * alpha))
        s.blit(camada, (0, 0))

    def _draw_toast(self, s):
        now = time.time()
        if now > self._toast_until:
            return
        f = T.font(19)
        tw = f.size(self._toast)[0]
        box = pygame.Rect(self.W // 2 - tw // 2 - 22, self.H - 96,
                          tw + 44, 46)
        # slide-in: sobe 30px nos primeiros 0.2s
        age = now - self._toast_t
        if age < 0.2:
            ease = 1.0 - (1.0 - age / 0.2) ** 3
            box.y = int(box.y + 30 * (1.0 - ease))
        # fade-out: desaparece no último 0.4s
        restante = self._toast_until - now
        alpha = 255 if restante > 0.4 else int(255 * restante / 0.4)
        panel_s = pygame.Surface((box.w, box.h), pygame.SRCALPHA)
        pygame.draw.rect(panel_s, (*T.INK_LIFT, alpha), panel_s.get_rect(),
                         border_radius=23)
        # borda: cor do kind (ok=green, erro=red, info=default)
        border_cor = {"ok": T.GREEN, "erro": T.RED}.get(self._toast_kind, T.LINE)
        pygame.draw.rect(panel_s, (*border_cor, alpha), panel_s.get_rect(),
                         width=1, border_radius=23)
        s.blit(panel_s, box.topleft)
        txt_img = f.render(self._toast, True, T.TEXT)
        txt_img.set_alpha(alpha)
        s.blit(txt_img, txt_img.get_rect(centerx=box.centerx, centery=box.centery))

    # ── entrada ────────────────────────────────────────────────────────────
    def _key(self, ev):
        self._ultima_entrada = time.time()
        # O aviso de virar o lado cobre a tela; a primeira tecla tira ele e
        # não faz mais nada. Deixar a tecla ATRAVESSAR o aviso faria o botão
        # que a pessoa apertou para dispensá-lo também mudar de tela.
        if self._flip:
            self._flip = None
            return None
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
        if i != self.cur:
            self._trans_alpha = 1.0   # fade rápido ao trocar de seção
        self.cur = i
        self.rail_sel = i
        self.screens[i].enter()

    def run(self):
        rail_w = max(200, min(300, self.W // 7))
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
                    self._ultima_entrada = time.time()
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
                            6: pygame.K_TAB, 7: pygame.K_TAB,
                            8: pygame.K_2}  # L3 → estante
                    if ev.button in mapa:
                        pygame.event.post(pygame.event.Event(
                            pygame.KEYDOWN, key=mapa[ev.button], unicode="",
                            mod=0))
            self.surf.fill(T.INK)
            # Partículas atmosféricas — poeira âmbar no fundo
            dt = self.clock.get_time() / 1000.0
            self._particles.update(dt)
            self._particles.draw(self.surf)
            body = pygame.Rect(rail_w, 0, self.W - rail_w, self.H)
            self._idle_deck()
            try:
                self.screens[self.cur].draw(self.surf, body)
            except Exception as e:        # noqa: BLE001
                # Uma tela com defeito não pode derrubar o sistema inteiro:
                # este programa é a cara da máquina e cair nele parece o
                # computador ter quebrado.
                T.text(self.surf, f"esta tela quebrou: {type(e).__name__}: {e}",
                       (body.x + 40, body.y + 60), 20, T.RED, maxw=body.w - 80)
            self._draw_rail(self.surf, rail_w)
            self._watch_side()
            self._draw_flip(self.surf)
            self._draw_toast(self.surf)
            # Fade de transição: rápido e sutil, só para o corte seco entre
            # seções não parecer um engasgo.
            if self._trans_alpha > 0.01:
                fade = pygame.Surface((self.W, self.H))
                fade.fill(T.INK)
                fade.set_alpha(int(160 * self._trans_alpha))
                self.surf.blit(fade, (0, 0))
                self._trans_alpha *= 0.82
            # Subida macia: fade de abertura
            nasc = (time.time() - self._born) / 0.55
            if nasc < 1.0:
                v = pygame.Surface((self.W, self.H))
                v.fill(T.INK)
                # ease-out: começa rápido e desacelera
                ease = 1.0 - (1.0 - min(1.0, nasc)) ** 2
                v.set_alpha(int(255 * (1.0 - ease)))
                self.surf.blit(v, (0, 0))
            pygame.display.flip()
            # Sleep timer: pause when time runs out
            if self._sleep_minutes > 0 and time.time() >= self._sleep_end:
                spawn(["playerctl", "pause"])
                self.toast(f"pause — timer de {self._sleep_minutes}m expirou")
                self._sleep_minutes = 0
            self.clock.tick(FPS)

    def _idle_deck(self):
        """Parado na AGORA, a tela vira o deck sozinha. Uma vez por álbum.

        O modo música costuma estar num televisor do outro lado do quarto: a
        pessoa põe o disco, larga o controle, e a capa parada na AGORA é
        menos da metade do que o deck desenha da mesma música. Qualquer
        entrada adia; trocar de álbum rearma — e nada disso acontece na
        janela de desenvolvimento, que não é uma sala de estar.
        """
        if os.environ.get("STYLUS_UI_WINDOWED"):
            return
        if not self.auto_deck:
            return
        if not isinstance(self.screens[self.cur], NowScreen):
            return
        if time.time() - self._ultima_entrada < self.IDLE_DECK_SECS:
            return
        snap = self.playing.session.snapshot()
        path = snap.get("path") or ""
        if not path or snap.get("paused", True):
            return
        chave = os.path.dirname(path)
        if chave and chave != self._deck_auto:
            self._deck_auto = chave
            self.open_deck()


def main():
    try:
        App().run()
    finally:
        pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
