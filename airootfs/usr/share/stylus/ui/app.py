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
import random
import re
import subprocess
import sys
import threading
import time

import pygame

sys.path.insert(0, "/usr/share/stylus/deck")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vinyl                                            # noqa: E402
import theme as T                                       # noqa: E402
import audio_live                                       # noqa: E402
from model import (THUMB_HI, Playing, Shelf, Thumbs,     # noqa: E402
                   ha_quanto, humano, plural, relogio)

FPS = 60


# ═══════════════════════════════════════════════════════════════════════════
# Infraestrutura
# ═══════════════════════════════════════════════════════════════════════════
# Todo lançamento de processo desta interface passa por um destes três nomes
# — `spawn`, `Job` e `rodar` — de propósito. O teste (`ui/tools/test_ui.py`)
# aperta TODAS as teclas em TODAS as telas, e uma tecla que chegue a um
# subprocess.run direto executa de verdade lá dentro. Já custou 13 GB de
# Steam descompactado dentro de uma pasta temporária; o `rodar` é o terceiro
# nome porque o formulário de conta precisa da SAÍDA do comando, que nem o
# spawn nem o Job devolvem.
rodar = subprocess.run


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
_fav_cache = None

def _lados_de(faixas):
    """(lados, duração total, discos) de uma lista de faixas do Qobuz.

    Pelo `vinyl.Album._build_sides` e não por uma conta nova aqui: é a MESMA
    regra que decide os lados de um disco da estante — teto de 26 min, corte
    em fronteira de faixa, lados equilibrados, número de DISCOS arredondado
    porque um disco tem dois lados sempre. Uma segunda implementação diria
    "2 lados" na loja e "4" depois de baixar, sobre o mesmo disco.

    O `__new__` sem `__init__` é de propósito: o construtor do Album vai ao
    disco procurar arquivo, e aqui não há arquivo nenhum — o disco está do
    outro lado da assinatura.
    """
    al = vinyl.Album.__new__(vinyl.Album)
    al.tracks, al.continuo, t = [], False, 0.0
    for f in faixas:
        dur = float(f.get("duration") or 0)
        al.tracks.append({"title": f.get("title") or "?", "duration": dur,
                          "start": t, "path": ""})
        t += dur
    al.total = t
    al.sides, al.discos = [], 1
    try:
        al._build_sides()
    except Exception:                     # noqa: BLE001 — a loja não cai por isso
        al.sides, al.discos = [], 1
    return al.sides, t, getattr(al, "discos", 1)


def _load_favorites():
    global _fav_cache
    if _fav_cache is not None:
        return _fav_cache
    try:
        with open(_FAV_FILE) as f:
            _fav_cache = set(json.load(f))
    except (OSError, json.JSONDecodeError):
        _fav_cache = set()
    return _fav_cache

def _save_favorites(favs):
    global _fav_cache
    os.makedirs(os.path.dirname(_FAV_FILE), exist_ok=True)
    try:
        with open(_FAV_FILE, "w") as f:
            json.dump(sorted(favs), f)
        _fav_cache = set(favs)
    except OSError:
        pass

def _toggle_favorite(folder):
    global _fav_cache
    favs = _load_favorites()
    key = os.path.normpath(folder)
    if key in favs:
        favs.discard(key)
    else:
        favs.add(key)
    _fav_cache = favs
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


class Formulario:
    """Entrar numa conta sem sair da tela cheia.

    POR QUE ISTO EXISTE
    -------------------
    Para usar o Qobuz aqui, a máquina mandava abrir um navegador numa
    interface web, entrar lá, e voltar — e o único motivo daquele navegador
    existir era guardar um token num arquivo. Para o Spotify era pior: um
    client_id e um client_secret escritos à mão num arquivo cujo caminho a
    tela mostrava e mais nada. Num sistema feito para ser usado do sofá, com
    um controle, "abra o navegador e edite um .conf" é o mesmo que "não dá
    para fazer daqui".

    O envio roda numa thread e recebe os valores pelo STDIN do programa que
    autentica — nunca por argumento. Argumento de processo aparece no `ps`
    para qualquer usuário da máquina.
    """

    def __init__(self, titulo, campos, comando, ao_terminar=None, rodape=""):
        # campos: [(rótulo, dica, oculto), ...]
        self.titulo = titulo
        self.campos = campos
        self.comando = comando
        self.ao_terminar = ao_terminar
        self.rodape = rodape
        self.valores = ["" for _ in campos]
        self.sel = 0
        self.enviando = False
        self.erro = None

    # ── teclado ────────────────────────────────────────────────────────────
    def key(self, ev):
        """True quando a tecla foi consumida. Sempre consome: é um formulário
        modal, e uma tecla que escapa daqui vai mexer na tela de trás."""
        if self.enviando:
            return True
        if ev.key == pygame.K_TAB or ev.key == pygame.K_DOWN:
            self.sel = (self.sel + 1) % len(self.campos)
        elif ev.key == pygame.K_UP:
            self.sel = (self.sel - 1) % len(self.campos)
        elif ev.key == pygame.K_BACKSPACE:
            self.valores[self.sel] = self.valores[self.sel][:-1]
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.sel < len(self.campos) - 1:
                self.sel += 1          # enter no meio anda, não envia
            else:
                self.enviar()
        elif ev.unicode and ev.unicode.isprintable():
            # Teto por campo: um segredo do Spotify tem 32 caracteres e um
            # e-mail raramente passa de 60. Sem teto, uma tecla presa enche a
            # memória e o desenho sai da caixa.
            if len(self.valores[self.sel]) < 200:
                self.valores[self.sel] += ev.unicode
        return True

    def enviar(self):
        if any(not v.strip() for v in self.valores):
            self.erro = "preencha os dois campos"
            return
        self.enviando = True
        self.erro = None

        def _vai():
            try:
                r = rodar(
                    self.comando,
                    input="\n".join(self.valores) + "\n",
                    capture_output=True, text=True, timeout=90)
                saida = (r.stdout or "").strip().splitlines()
                dado = json.loads(saida[-1]) if saida else {}
            except subprocess.TimeoutExpired:
                dado = {"erro": "o serviço não respondeu a tempo"}
            except Exception as e:                        # noqa: BLE001
                dado = {"erro": str(e)}
            if dado.get("ok"):
                # Os valores não ficam na memória depois de servirem.
                self.valores = ["" for _ in self.campos]
                if self.ao_terminar:
                    self.ao_terminar(True, dado)
            else:
                self.erro = dado.get("erro") or "não deu certo"
                if self.ao_terminar:
                    self.ao_terminar(False, dado)
            self.enviando = False

        threading.Thread(target=_vai, daemon=True).start()

    # ── desenho ────────────────────────────────────────────────────────────
    def draw(self, s, r):
        dim = pygame.Surface(r.size)
        dim.fill(T.INK)
        dim.set_alpha(226)
        s.blit(dim, r.topleft)

        pw = min(560, r.w - 120)
        ph = 150 + len(self.campos) * 74 + (28 if self.erro else 0) \
            + (26 if self.rodape else 0)
        caixa = pygame.Rect(0, 0, pw, ph)
        caixa.center = r.center
        T.panel(s, caixa, T.INK_SOFT, radius=16, border=T.LINE)

        x = caixa.x + 30
        corpo = pw - 60
        y = caixa.y + 26
        T.text(s, self.titulo, (x, y), 24, T.TEXT, bold=True, maxw=corpo)
        y += 46

        for i, (rotulo, dica, oculto) in enumerate(self.campos):
            aceso = i == self.sel and not self.enviando
            T.text(s, rotulo, (x, y), 14, T.AMBER if aceso else T.TEXT_FAINT)
            cr = pygame.Rect(x, y + 20, corpo, 38)
            T.panel(s, cr, T.INK_LIFT if aceso else T.INK, radius=6,
                    border=T.BLUE_BRIGHT if aceso else T.LINE)
            v = self.valores[i]
            # Oculto vira bolinha por caractere: alguém pode estar olhando a
            # tela de longe, que é o modo normal de usar esta interface.
            mostra = ("•" * len(v)) if oculto else v
            if not v and not aceso:
                T.text(s, dica, (cr.x + 12, cr.y + 9), 17, T.TEXT_FAINT,
                       maxw=corpo - 24)
            else:
                # Mostra o FIM do texto quando ele não cabe: quem está
                # digitando quer ver o que acabou de escrever.
                while mostra and T.largura(mostra, 17) > corpo - 30:
                    mostra = mostra[1:]
                T.text(s, mostra, (cr.x + 12, cr.y + 9), 17, T.TEXT,
                       maxw=corpo - 24)
                if aceso and int(time.time() * 2) % 2 == 0:
                    cx = cr.x + 12 + T.largura(mostra, 17) + 2
                    pygame.draw.line(s, T.AMBER, (cx, cr.y + 9),
                                     (cx, cr.y + 29), 2)
            y += 74

        if self.erro:
            T.text(s, self.erro, (x, y), 16, T.RED, maxw=corpo)
            y += 28
        if self.rodape:
            T.text(s, self.rodape, (x, y), 14, T.TEXT_FAINT, maxw=corpo)
            y += 24

        pe = caixa.bottom - 40
        if self.enviando:
            T.text(s, "entrando…", (x, pe), 17, T.AMBER)
        else:
            # Curto porque tem que CABER: a versão longa encostava na borda
            # direita do painel e o "desiste" saía por fora.
            T.frase_com_teclas(s, "[tab] campo   ·   [enter] entra   ·   [esc] sai",
                               (x, pe), 15, T.TEXT_FAINT)
        return caixa


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

    def __init__(self, app):
        super().__init__(app)
        # A volta do disco, acumulada. Ver o desenho: pausar pára o disco, e
        # para parar é preciso guardar onde ele estava.
        self._ang = None
        # A retenção de picos do espectro (ver `_spectrum`): por faixa, o
        # máximo recente. Se ficar aqui como atributo de classe, dois testes
        # de tela dividem o mesmo estado e os picos "vazam" de um desenho
        # para o outro.
        self._spec_pico = None
        # O DISCO ocupando a tela toda, sem trilho e sem coluna de texto.
        # Ver `_cheia`: é o deck, dentro do lançador.
        self.tela_cheia = False

    def key(self, ev):
        # ── a tela cheia do disco ─────────────────────────────────────────
        # `f` liga e desliga; ESC também desliga, porque ESC é "volta" no
        # sistema inteiro e uma tela sem trilho precisa de uma saída óbvia.
        if ev.key == pygame.K_f:
            self.tela_cheia = not self.tela_cheia
            return True
        if ev.key == pygame.K_ESCAPE and self.tela_cheia:
            self.tela_cheia = False
            return True
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
        # Repeat toggle: R (shift+r) — checked BEFORE unshifted r
        if ev.key == pygame.K_r and (ev.mod & pygame.KMOD_SHIFT):
            self.app.toggle_repeat()
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
            self.app._save_player_prefs()
            self.app.toast("deck sozinho: LIGADO" if self.app.auto_deck
                           else "deck sozinho: DESLIGADO (fica na AGORA)")
            return True
        return False

    def _nome_do_disco(self, s, nome, pos, w):
        """O nome do disco, no maior corpo que couber. Devolve a altura.

        **Sintoma:** "Lift Your Skinny Fists Like Antennas to Heaven" saía
        como "Lift Your Ski…" em corpo 56 — o nome do disco, que é a coisa
        que esta tela existe para dizer, virava três palavras e reticências
        enquanto sobrava coluna embaixo. Nome comprido é comum: todo álbum
        duplo, toda edição de aniversário, toda gravação ao vivo com data no
        título.

        Duas linhas no máximo. Três empurrariam o LADO e o "vira em" para
        fora do bloco, e o nome deixaria de ser um título para virar um
        parágrafo.

        A escada pára em 30: abaixo disso o nome deixa de ser o texto mais
        importante da tela, e aí cortar é mais honesto do que espremer.
        """
        x, y = pos
        for tam in (56, 48, 41, 35, 30):
            larg = T.largura(nome, tam, True)
            if larg <= w:
                T.text(s, nome, (x, y), tam, T.TEXT, bold=True)
                return int(tam * 1.15)
            # Cabe em duas? Só quando NENHUMA palavra sozinha estoura a
            # coluna — o `paragrafo` quebra no espaço e não corta, então uma
            # palavra maior que a coluna sairia desenhada para fora dela.
            if (larg <= w * 1.9
                    and all(T.largura(p, tam, True) <= w
                            for p in nome.split())):
                return T.paragrafo(s, nome, (x, y), tam, T.TEXT, maxw=w,
                                   bold=True, entrelinha=1.12, limite=2)
        T.text(s, nome, (x, y), 30, T.TEXT, bold=True, maxw=w)
        return 34

    def draw(self, s, r):
        snap, al, track, side, t_abs, frac = self.app.playing.where()
        if al is None:
            # Sem disco não há tela cheia do disco: sair dela sozinha é
            # melhor do que deixar a pessoa num quadro preto sem trilho.
            self.tela_cheia = False
            self._nothing(s, r)
            return
        if self.tela_cheia:
            self._cheia(s, r, snap, al, track, side, t_abs, frac)
            return

        # ── a capa vaza para a sala: fundo desfocado na cor do disco ──────
        fundo = self.app.backdrop(al, r.size)
        if fundo is not None:
            s.blit(fundo, r.topleft)
            # vinheta suave nas bordas — profundidade
            T.vignette(s)

        # ── o disco SAINDO da capa, e a coluna de texto ao lado ───────────
        # O vinil era um aro simétrico atrás da capa: um pouco maior que ela
        # em todos os lados, o que na tela lê como um prato, ou como uma
        # sombra redonda — não como um disco. Um disco de verdade só aparece
        # assim quando está DENTRO da capa, e aí não se vê nada dele.
        #
        # O que se vê de verdade, e é a imagem que todo mundo tem na cabeça,
        # é o disco meio PUXADO para fora: a bolacha e a beirada do sulco de
        # fora, girando, e o resto ainda na capa. Então é isso — ele sai pela
        # esquerda, que é onde a composição tem espaço (a coluna de texto
        # está à direita), e a capa fica por cima, como fica.
        #
        # O bloco inteiro (o quanto o disco sai + a capa + a coluna) é que se
        # centra. Sem contar a saliência, a capa ficava no meio e o disco
        # saía por baixo do trilho.
        margem, gap, txt_teto, txt_min = 64, 72, 620, 180
        avail = max(320, r.w - margem * 2)
        # 0.36 e não 0.44: a saliência do disco pede a diferença.
        size = min(int(r.h * 0.62), int(avail * 0.36), 720)
        # O bloco inteiro é `sai + size + gap + txt_w`, e o `sai` é 0,425 do
        # tamanho do disco (ver as duas linhas abaixo) — ou seja, o bloco
        # mede 1,425×size + gap + a coluna de texto.
        #
        # **Sintoma:** os dois pisos — 260 para o disco e 180 para a coluna —
        # somam mais do que a largura de uma tela de 800, e o bloco era
        # desenhado para FORA dela: o nome do artista, o do disco, o LADO e o
        # "vira em X" todos com o fim cortado pela borda. Um piso que não
        # cabe não é piso, é overflow com nome bonito.
        #
        # Quem cede é o DISCO, porque ele é desenho e a coluna é informação.
        size = max(110, min(size, int((avail - gap - txt_min) / 1.425)))
        # O disco é um pouco MENOR que a capa (12" contra 12⅜"), e sai o
        # bastante para a bolacha aparecer — é ela que diz que ele é um
        # disco, e não uma sombra.
        #
        # 0,44 e não 0,56. Com 0,56 o CENTRO do disco ficava para fora da
        # capa: o selo inteiro do lado de fora e mais da metade da bolacha
        # à mostra, o que na tela lê como duas coisas — um disco E um
        # quadrado, lado a lado — em vez de um disco sendo puxado de dentro
        # da capa. Com 0,44 o selo encosta na beirada da capa e sobra um
        # terço do disco para fora: é a imagem que se tem na cabeça, e é o
        # ponto em que a capa e o disco leem como UM objeto.
        rm = int(size * 0.485)
        desl = int(size * 0.44)
        sai = max(0, desl + rm - size // 2)
        txt_w = min(txt_teto, max(120, avail - sai - size - gap))
        total = sai + size + gap + txt_w

        # AGORA usa 640px — 320 esticado ficava borrado (audit A-N1)
        cov = self.app.thumbs_hi.get(al.cover) if al.cover else None
        if cov is None and al.cover:
            cov = self.app.thumbs.get(al.cover)
        cr = pygame.Rect(r.x + sai + max(0, (r.w - total) // 2),
                         r.y + (r.h - size) // 2, size, size)
        # O centro do DISCO, que é de onde sai toda a luz desta tela. Preso à
        # borda esquerda do corpo: numa tela estreita ele sairia por baixo do
        # trilho, e meio disco desenhado atrás do menu não é meio disco, é um
        # corte reto no meio da imagem.
        dx = max(r.x + 20 + rm, cr.centerx - desl)
        dy = cr.centery
        # O som do momento em quatro números — esta tela inteira é desenhada
        # a partir deles, e o monitor (audio_live) já os calculou no fundo.
        # O `pulse` é o transiente (o ritmo) e o `level` é a energia
        # carregada (o volume): brilho que empurra na batida em vez de só
        # seguir o volume médio.
        level, wave, spec, pulse = self.app.audio_now()

        # ── o halo, no disco ───────────────────────────────────────────────
        # O T.halo, e não um círculo CHEIO de alfa uniforme como era antes.
        # Aquilo não é um brilho, é um disco âmbar chapado atrás da capa, com
        # aresta dura no raio — a coisa exata que a §5.5 chama de app de um
        # dólar. O halo é forte na borda do disco e cai para fora, que é onde
        # a luz de um objeto realmente está. Em cache, e a força vem assada
        # nele (ver T.halo).
        # O piso é alto de propósito: agora que o disco SAI da capa, ele é
        # metade da imagem, e um disco preto sobre um fundo quase preto lê
        # como buraco. A luz é o que faz dele um objeto (§5.5) — o áudio
        # empurra a partir daí, não a partir do escuro.
        hal = T.halo(int(rm * 1.06),
                     forca=int(150 + (level * 0.75 + pulse * 0.25) * 105))
        s.blit(hal, (dx - hal.get_width() // 2, dy - hal.get_height() // 2))

        # ── o disco, girando ───────────────────────────────────────────────
        # Fora do `if spec`: o disco é o OBJETO, não um efeito de áudio. Numa
        # máquina sem PortAudio o `spec` é None o tempo todo, e o vinil
        # simplesmente não era desenhado — a AGORA ficava só com a capa
        # flutuando, e nada explicando por quê.
        d = T.disco(rm)
        s.blit(d, (dx - rm, dy - rm))
        # O reflexo que passa: o vinil é simétrico, e sem ele não se vê que
        # está girando. A velocidade dança com o som (e adormece na pausa); a
        # fase anda com o lado, para o reflexo não cair sempre no mesmo sulco.
        # O ângulo ANDA; não é lido do relógio. Pausar tem que PARAR o
        # disco — um toca-discos parado é a coisa mais visível que existe — e
        # um ângulo calculado de `time.time()` não pára: ele salta para onde
        # estaria quando a música volta, como se o disco tivesse girado
        # sozinho no escuro. A fase inicial vem do `frac` para o reflexo não
        # nascer sempre no mesmo sulco.
        parado = bool((snap or {}).get("paused"))
        # A cerimônia vale nas DUAS telas. Ela é o ritual, não um enfeite da
        # tela cheia: quem está na AGORA normal também acabou de pôr o disco.
        fase, fcer = self._cerimonia()
        giro = fcer ** 1.6 if fase == "spinup" else 1.0
        if self._ang is None:
            self._ang = (frac * 5.0) % (2 * math.pi)
        if not parado:
            dt_g = min(0.1, self.app.clock.get_time() / 1000.0)
            self._ang = (self._ang
                         + dt_g * (0.6 + level * 1.8) * giro) % (2 * math.pi)
        ang = self._ang
        # Reaproveitada, não alocada. Não é mais rápido — está medido no
        # T.rascunho — mas deixa de fazer quatro megabytes de lixo por quadro
        # para desenhar 46 linhas.
        bril = T.rascunho(rm * 2, rm * 2, "reflexo")
        n, arco = 46, math.radians(40)
        r0, r1 = rm * 0.93, rm * T.GROOVE_O
        for i in range(n):
            f = i / (n - 1)
            aa = ang + (f - 0.5) * arco
            # Reflete o SINAL, não o volume médio: o pulso é o que passa no
            # reflexo quando a batida chega — sem ele o brilho sobe junto com
            # o nível e o reflexo só muda de claro para mais claro.
            a = int((26 + (level * 0.7 + pulse * 0.3) * 44)
                    * math.sin(f * math.pi) ** 2)
            if a <= 0:
                continue
            pygame.draw.line(
                bril, (*T.AMBER_GLOW, a),
                (rm + math.cos(aa) * r0, rm + math.sin(aa) * r0),
                (rm + math.cos(aa) * r1, rm + math.sin(aa) * r1), 2)
        s.blit(bril, (dx - rm, dy - rm))

        # ── onde a agulha está, no próprio disco ───────────────────────────
        # O raio É o tempo — é a frase da §5.5 e a única coisa que um disco
        # diz de longe: dá para ver quanto falta olhando onde a agulha está.
        # A tela tinha isso escrito em minutos ("vira em 6min") e não tinha
        # no objeto, que é onde a pessoa olha.
        #
        # Marca à ESQUERDA, a 180°, porque é a metade que fica de fora da
        # capa: o resto do sulco está atrás dela, e uma luz desenhada ali
        # seria luz desenhada para ninguém.
        # No `spinup` o braço ainda está no descanso; no `cue` a agulha fica
        # suspensa FORA da borda, e no `drop` desce dali até o sulco. Ver
        # `_cerimonia`.
        rr_cue = rm * 1.09
        if fase == "spinup":
            pass
        elif side and (frac > 0.0 or fase in ("cue", "drop")):
            rr = rm * (T.GROOVE_O - (T.GROOVE_O - T.GROOVE_I) * min(1.0, frac))
            brilho, pousada = 1.0, True
            if fase == "cue":
                rr, brilho, pousada = rr_cue, 0.45, False
            elif fase == "drop":
                d = 1.0 - (1.0 - fcer) ** 2
                rr = rr_cue + (rr - rr_cue) * d
                brilho, pousada = 0.45 + 0.55 * d, d > 0.75
            ax, ay = dx - rr, dy
            # A parte JÁ TOCADA, do sulco de fora até onde a agulha está: um
            # arco fino e fraco no que sobra à vista. É o mesmo que a barra
            # de progresso diz, dito pelo disco.
            tocado = T.rascunho(rm * 2, rm * 2, "tocado")
            if pousada and rr < rm * T.GROOVE_O - 1:
                pygame.draw.arc(tocado, (*T.AMBER_DIM, 95),
                                pygame.Rect(int(rm - rm * T.GROOVE_O),
                                            int(rm - rm * T.GROOVE_O),
                                            int(rm * T.GROOVE_O * 2),
                                            int(rm * T.GROOVE_O * 2)),
                                math.radians(120), math.radians(240), 2)
            s.blit(tocado, (dx - rm, dy - rm))
            # Apertada e quente, não uma bolha grande e fraca: cinco
            # círculos de alfa baixo sobre o disco escuro somam um disco
            # ACINZENTADO com aresta, que é o contrário de um ponto de luz.
            # Respira no PULSO (o transiente, a batida) e não no nível
            # médio: é a batida que deve piscar aqui. Na pausa o pulso
            # escorre e sobra a base — o "ainda há música".
            fr = max(5, int(rm * 0.055))
            faisca = T.rascunho(fr * 2, fr * 2, "agulha")
            for k in range(4, 0, -1):
                pygame.draw.circle(
                    faisca,
                    (*T.AMBER_GLOW, int((30 + pulse * 40) * brilho * k / 4)),
                    (fr, fr), int(fr * k / 4))
            s.blit(faisca, (ax - fr, ay - fr))
            pygame.draw.circle(s, T.lerp(T.AMBER_DIM, T.AMBER, brilho),
                               (int(ax), int(ay)), max(2, int(rm * 0.018)))

        # ── o som, no aro do disco ─────────────────────────────────────────
        if spec is not None:
            self._spectrum(s, (dx, dy), spec, level, rm)

        # Lombada à DIREITA: a borda fechada da capa é a do outro lado de
        # onde o disco sai. Com ela à esquerda, o disco estava saindo por
        # dentro da própria costura.
        T.sleeve(s, cr, cov, lombada="dir")
        if not cov:
            T.text(s, "sem capa", cr.center, 24, T.TEXT_FAINT, anchor="center")

        x = cr.right + gap
        w = txt_w
        y_text = cr.y + 8

        # Artista mais sutil, álbum com mais peso — quem olha de longe
        # quer saber QUAL disco é, não quem fez.
        T.text(s, al.artist.upper(), (x, y_text), 22, T.TEXT_FAINT, maxw=w)
        alt_nome = self._nome_do_disco(s, al.name, (x, y_text + 34), w)
        y_ab = y_text + 34 + alt_nome + 8
        if al.year:
            T.text(s, str(al.year), (x, y_ab), 22, T.TEXT_DIM)
            y_ab += 32

        # ── onde no LADO. ────
        # A partir do fim do NOME, e não de um `y_text + 145` fixo: com o
        # nome em duas linhas, o "DISCO 2 · LADO C" era desenhado por cima da
        # segunda.
        y = max(y_text + 145, y_ab + 8)
        if side:
            resta = max(0.0, side["end"] - t_abs)
            ultimo = side is al.sides[-1]
            # `.get` e não `[...]`: um lado sem etiqueta derrubava a tela
            # inteira (era o caso das playlists do Qobuz). Dado que falta
            # pode virar "LADO"; não pode virar tela de erro.
            rotulo = side.get("label", "LADO").replace("SIDE", "LADO")
            # Numa caixa de quatro lados, "LADO C" não diz QUAL disco está no
            # prato — e é o disco que a pessoa tem na mão. Lados vêm aos
            # pares, então o disco é o índice do lado dividido por dois.
            if getattr(al, "discos", 1) > 1:
                try:
                    i_lado = al.sides.index(side)
                except ValueError:
                    i_lado = 0
                rotulo = "DISCO %d · %s" % (i_lado // 2 + 1, rotulo)
            # cor do lado respira com o áudio
            side_alpha = int(180 + level * 75) if level > 0.01 else 180
            side_cor = T.lerp(T.AMBER, (255, 255, 255), (side_alpha - 180) / 75)
            # MEDIDO, não `x + 150`: "DISCO 2 · LADO C" é o dobro da largura
            # de "LADO A", e com a folga fixa o "vira em 6min" era desenhado
            # por cima dele. É a mesma lição do nome do conversor na tela
            # SINAL, e ela vale toda vez que dois textos dividem uma linha.
            #
            # E quando os dois não cabem na mesma linha, o "vira em" DESCE —
            # o mesmo que o `job_panel` faz com o estado da tarefa. Antes o
            # rótulo ia sem `maxw` nenhum e o "vira em" recebia uma folga que
            # podia ser NEGATIVA: numa tela de 800 os dois eram desenhados
            # para fora da borda. E é o "vira em" que não pode ser cortado:
            # é a informação que só um disco dá.
            resta_txt = ("acaba em " if ultimo else "vira em ") + humano(resta)
            larg_resta = T.largura(resta_txt, 22)
            if T.largura(rotulo, 30) + 24 + larg_resta <= w:
                r_lado = T.text(s, rotulo, (x, y), 30, side_cor, bold=True)
                T.text(s, resta_txt, (r_lado.right + 24, y + 5), 22, T.TEXT_DIM,
                       maxw=max(1, w - (r_lado.width + 24)))
                y_sulco = y + 48
            else:
                T.text(s, rotulo, (x, y), 30, side_cor, bold=True, maxw=w)
                T.text(s, resta_txt, (x, y + 34), 22, T.TEXT_DIM, maxw=w)
                y_sulco = y + 66
            self._groove(s, pygame.Rect(x, y_sulco, w, 14), frac, wave, pulse)
            y = y_sulco + 36

        if track:
            n = (al.tracks.index(track) + 1) if track in al.tracks else 0
            T.text(s, f"{n:02d}  {track.get('title') or ''}", (x, y), 30,
                   T.TEXT, maxw=w)
            y += 48

        # Informativos no rodapé
        #
        # A posição era amarrada só à CAPA (`cr.bottom + 20`), como se a
        # coluna de texto ao lado nunca passasse dela. Numa tela baixa e
        # estreita ela passa — o LADO desce para duas linhas, o nome da faixa
        # quebra — e a linha do rodapé era desenhada POR CIMA do "LADO A".
        # Ela vem depois do texto, então tem que ceder ao texto.
        hist = f"{al.plays}ª vez" if al.plays else "primeira vez"
        y_rodape = min(max(cr.bottom + 20, y + 12), r.bottom - 60)
        # Os ícones de embaralhar/repetir/soneca são desenhados lá embaixo,
        # encostados à direita e quase na mesma linha que esta. Montados
        # AQUI para poder MEDIR: numa tela estreita a linha do rodapé
        # chegava neles e os dois textos se cruzavam. Mesma lição da folga
        # fixa, e ela vale toda vez que dois textos dividem uma linha.
        icones = []
        if self.app.shuffle:
            icones.append(T.icon("󰒟"))  # nf-md-shuffle
        if self.app.repeat == 1:
            icones.append(T.icon("󰑙"))  # nf-md-repeat_once
        elif self.app.repeat == 2:
            icones.append(T.icon("󰑖"))  # nf-md-repeat
        if self.app._sleep_minutes > 0:
            faltam_min = max(0, int((self.app._sleep_end - time.time()) / 60))
            icones.append(f"{T.icon('󰅐')}{faltam_min}m")  # nf-md-timer
        txt_icones = "  ".join(icones)
        larg_icones = (T.largura(txt_icones, 20) + 28) if icones else 0
        T.text(s, f"{hist}  ·  {plural(len(al.tracks), 'faixa')}  ·  "
                  f"{humano(al.total)}  ·  {ha_quanto(al.last_played)}",
               (x, y_rodape), 19, T.TEXT_FAINT,
               maxw=max(60, w - larg_icones))

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

        # Embaralhar / repetir / soneca — montados lá em cima, junto do
        # rodapé, para o rodapé poder medi-los.
        if icones:
            T.text(s, txt_icones, (r.right - 20, r.bottom - 50), 20,
                   T.AMBER, anchor="bottomright")

        self.app.hint(s, r, "[f] o disco na tela toda   [enter] abre o deck   "
                            "[space] pausa   "
                            "[n]/[p] faixa   [←]/[→] busca   [v]/[b] lado   "
                            "[+]/[-] volume   "
                            + ("[d] deck sozinho: ligado" if self.app.auto_deck
                               else "[d] deck sozinho: desligado"))

    # A cerimônia, em segundos, VINDA DO DECK. O prato leva um tempo para
    # chegar aos 33 (SPIN), a agulha fica suspensa sobre a borda (CUE) e
    # então desce (DROP) — pouco mais de dois segundos ao todo: é uma
    # cerimônia, não uma espera.
    #
    # Os números são os do `vinyl.py` de propósito, e não uns parecidos
    # escritos aqui. É a MESMA cerimônia do mesmo sistema; duas cópias à mão
    # do mesmo ritual derivam, e aí pôr um disco no deck e pôr um disco no
    # lançador passam a ser dois gestos com durações diferentes — que é a
    # deriva da paleta outra vez, em segundos em vez de hexadecimais.
    CER_SPIN = getattr(vinyl, "SPINUP_T", 1.1)
    CER_CUE = getattr(vinyl, "CUE_T", 1.05)
    CER_DROP = getattr(vinyl, "DROP_T", 0.55)

    def _cerimonia(self):
        """(fase, f) — em que ponto da cerimônia estamos, e quanto dela já foi.

        POR QUE ISTO EXISTE
        -------------------
        O deck é um programa à parte, com OpenGL e venv, e a única coisa que
        ele tinha de próprio depois que a tela cheia do disco nasceu era
        esta: a CERIMÔNIA. O CLAUDE.md §5.5 chama de sagrado, e com razão —
        ela é o que separa "pôr um disco" de "dar play". Sem ela, a tela
        cheia é uma foto bonita de um disco que já está tocando.

        Fora da cerimônia devolve (None, 1.0), que é o estado normal: o
        chamador multiplica o giro por 1.0 e desenha a agulha onde ela está.
        """
        t0 = getattr(self.app, "cerimonia_t0", 0.0)
        if not t0:
            return (None, 1.0)
        dt = time.monotonic() - t0
        if dt < self.CER_SPIN:
            return ("spinup", dt / self.CER_SPIN)
        dt -= self.CER_SPIN
        if dt < self.CER_CUE:
            return ("cue", dt / self.CER_CUE)
        dt -= self.CER_CUE
        if dt < self.CER_DROP:
            return ("drop", dt / self.CER_DROP)
        return (None, 1.0)

    def _cheia(self, s, r, snap, al, track, side, t_abs, frac):
        """O DISCO ocupando a tela — o deck, dentro do lançador.

        POR QUE ISTO EXISTE
        -------------------
        O deck é um programa à parte: OpenGL, um venv com PyOpenGL, PortAudio,
        uma janela própria e uma cerimônia inteira. Tudo isso para mostrar um
        disco girando — que é o que esta tela já desenha, com a mesma
        geometria do vinyl.py, sem GL nenhum.

        Aqui o disco vem para o CENTRO e cresce até o que a altura der; o
        trilho e a coluna de texto saem (o laço principal olha o
        `tela_cheia`), e o que sobra de escrito é o que se lê de longe: o
        disco, o lado, e quanto falta. É a mesma leitura do deck sem o custo
        dele — e é a resposta honesta a "por que não tudo no lançador".

        E a CERIMÔNIA está aqui (ver `_cerimonia`): disco novo, o prato sai
        do zero, a agulha aparece suspensa fora da borda e desce até o sulco.
        Era a única coisa que o deck tinha de próprio depois que esta tela
        nasceu — o CLAUDE.md §5.5 chama o ritual de sagrado, e sem ele isto
        aqui era uma foto bonita de um disco que já está tocando.

        O que o deck ainda tem e isto não: o composto CRT (barril,
        varredura, grão), o acumulador aditivo com bloom, o osciloscópio do
        sinal e as marcas de uso lidas do envelope do áudio. É desenho de
        GPU; nada disso é o ritual.
        """
        fundo = self.app.backdrop(al, r.size)
        if fundo is not None:
            s.blit(fundo, r.topleft)
            T.vignette(s)

        level, wave, spec, pulse = self.app.audio_now()
        # O texto é MEDIDO, não chutado: quatro linhas (artista, disco, lado,
        # faixa) mais o respiro e a linha de dicas. Com o disco em 40% da
        # altura o nome da faixa caía FORA da tela em 1080p — e o que se
        # perdia era justamente a informação, não a decoração.
        txt_h = 28 + 26 + 56 + 40 + 30 + 46
        topo = r.y + max(16, int(r.h * 0.03))
        rm = int(min((r.bottom - txt_h - topo) / 2, r.w * 0.30))
        rm = max(120, rm)
        dx, dy = r.centerx, topo + rm

        hal = T.halo(int(rm * 1.06),
                     forca=int(150 + (level * 0.75 + pulse * 0.25) * 105))
        s.blit(hal, (dx - hal.get_width() // 2, dy - hal.get_height() // 2))
        s.blit(T.disco(rm), (dx - rm, dy - rm))

        parado = bool((snap or {}).get("paused"))
        fase, fcer = self._cerimonia()
        # O prato sai do zero: ao pôr o disco ele acelera até a rotação, e
        # essa aceleração é metade do que faz a coisa parecer um objeto. O
        # expoente é o que dá o peso — velocidade proporcional ao tempo lê
        # como interpolação, não como massa.
        giro = fcer ** 1.6 if fase == "spinup" else 1.0
        if self._ang is None:
            self._ang = (frac * 5.0) % (2 * math.pi)
        if not parado:
            self._ang = (self._ang
                         + min(0.1, self.app.clock.get_time() / 1000.0)
                         * (0.6 + level * 1.8) * giro) % (2 * math.pi)
        bril = T.rascunho(rm * 2, rm * 2, "reflexo")
        n, arco = 46, math.radians(40)
        r0, r1 = rm * 0.93, rm * T.GROOVE_O
        for i in range(n):
            f = i / (n - 1)
            aa = self._ang + (f - 0.5) * arco
            a = int((26 + (level * 0.7 + pulse * 0.3) * 44)
                    * math.sin(f * math.pi) ** 2)
            if a > 0:
                pygame.draw.line(
                    bril, (*T.AMBER_GLOW, a),
                    (rm + math.cos(aa) * r0, rm + math.sin(aa) * r0),
                    (rm + math.cos(aa) * r1, rm + math.sin(aa) * r1), 2)
        s.blit(bril, (dx - rm, dy - rm))

        # A capa NA BOLACHA, que é onde ela está num disco de verdade — e
        # aqui ela cabe, porque o disco é grande. Recortada em círculo pelo
        # T.bolacha; quadrada no meio de um disco redondo seria um adesivo.
        cov = self.app.thumbs_hi.get(al.cover) if al.cover else None
        if cov is None and al.cover:
            cov = self.app.thumbs.get(al.cover)
        if cov is not None:
            lr = int(rm * T.LABEL_R)
            s.blit(T.bolacha(cov, lr, al.cover), (dx - lr, dy - lr))

        # A agulha, no sulco em que ela está — e o SULCO ACESO com ela.
        #
        # Sozinho, o ponto da agulha era um pingo âmbar solto no meio de um
        # disco de meio metro: não dizia onde estava porque não havia com o
        # que comparar. O que diz é o sulco inteiro em que ele anda, aceso
        # fraco: aí o raio vira o tempo à vista, que é a tese do deck.
        # A agulha é a mesma cruz curta e quente do vinyl.py — luz, não peça.
        #
        # Na CERIMÔNIA ela não está no sulco ainda: no `spinup` não existe
        # (o braço está no descanso), no `cue` fica suspensa FORA da borda
        # sem sulco aceso, e no `drop` desce dali até o sulco de verdade,
        # acendendo. É a mesma coreografia do deck, sem OpenGL nenhum.
        rr_cue = rm * 1.09
        if fase == "spinup":
            pass                       # o braço ainda está no descanso
        elif side and (frac > 0.0 or fase in ("cue", "drop")):
            rr = rm * (T.GROOVE_O - (T.GROOVE_O - T.GROOVE_I) * min(1.0, frac))
            if fase == "cue":
                rr, brilho, sulco_vivo = rr_cue, 0.45, False
            elif fase == "drop":
                # desce com desaceleração: a agulha ENCOSTA, não aterrissa
                d = 1.0 - (1.0 - fcer) ** 2
                rr, brilho, sulco_vivo = (rr_cue + (rr - rr_cue) * d,
                                          0.45 + 0.55 * d, d > 0.75)
            else:
                brilho, sulco_vivo = 1.0, True
            lado_s = int(rr * 2) + 8
            sul = T.rascunho(lado_s, lado_s, "sulco-vivo")
            cs = lado_s // 2
            if sulco_vivo:
                pygame.draw.circle(sul, (*T.AMBER, 46), (cs, cs), int(rr), 1)
            # O rastro: o pedaço de sulco que ACABOU de passar pela agulha,
            # apagando para trás. Em SEGMENTOS e não em pontos — pontos com
            # o espaçamento do arco viram linha pontilhada, que lê como
            # tracejado de desenho técnico e não como luz que some.
            passos, arco = 40, math.radians(-72)
            gr = max(1, int(rm * 0.009))
            ant = None
            for k in range(passos + 1 if sulco_vivo else 0):
                f = k / float(passos)
                a = math.pi + f * arco
                pt = (cs + math.cos(a) * rr, cs + math.sin(a) * rr)
                if ant is not None:
                    pygame.draw.line(sul, (*T.AMBER_GLOW,
                                           int(120 * (1.0 - f) ** 2)),
                                     ant, pt, gr)
                ant = pt
            s.blit(sul, (dx - cs, dy - cs))
            # À esquerda, como na tela pequena: aqui nada esconde o disco,
            # mas as duas telas contam a mesma história sobre o mesmo disco.
            ax, ay = dx - rr, dy
            fr = max(8, int(rm * 0.07))
            faisca = T.rascunho(fr * 2, fr * 2, "agulha")
            for k in range(5, 0, -1):
                pygame.draw.circle(
                    faisca,
                    (*T.AMBER_GLOW, int((26 + pulse * 44) * brilho * k / 5)),
                    (fr, fr), int(fr * k / 5))
            s.blit(faisca, (ax - fr, ay - fr))
            braco = max(5, int(rm * 0.045))
            gros = max(2, int(rm * 0.010))
            cor_h = T.lerp(T.AMBER_DIM, T.AMBER_GLOW, brilho)
            cor_v = T.lerp(T.AMBER_DIM, T.AMBER, brilho)
            pygame.draw.line(s, cor_h, (ax - braco, ay), (ax + braco, ay), gros)
            pygame.draw.line(s, cor_v, (ax, ay - braco // 2),
                             (ax, ay + braco // 2), gros)
        if spec is not None:
            self._spectrum(s, (dx, dy), spec, level, rm)

        # ── o que se lê de longe ──────────────────────────────────────────
        larg = min(r.w - 120, 1100)
        y = dy + rm + 26
        T.text(s, al.artist.upper(), (r.centerx, y), 20, T.TEXT_FAINT,
               anchor="midtop", maxw=larg)
        T.text(s, al.name, (r.centerx, y + 28), 42, T.TEXT, bold=True,
               anchor="midtop", maxw=larg)
        y += 84
        if side:
            resta = max(0.0, side["end"] - t_abs)
            ultimo = side is al.sides[-1]
            rot = side.get("label", "LADO").replace("SIDE", "LADO")
            if getattr(al, "discos", 1) > 1:
                try:
                    rot = "DISCO %d · %s" % (al.sides.index(side) // 2 + 1, rot)
                except ValueError:
                    pass
            frase = "%s   %s%s" % (rot, "acaba em " if ultimo else "vira em ",
                                   humano(resta))
            T.text(s, frase, (r.centerx, y), 24, T.AMBER, bold=True,
                   anchor="midtop", maxw=larg)
            y += 40
        if track:
            n_t = (al.tracks.index(track) + 1) if track in al.tracks else 0
            T.text(s, "%02d  %s" % (n_t, track.get("title") or ""),
                   (r.centerx, y), 22, T.TEXT_DIM, anchor="midtop", maxw=larg)
        self.app.hint(s, r, "[f] ou [esc] volta ao lançador   [space] pausa   "
                            "[n]/[p] faixa   [v] vira o lado")

    def _spectrum(self, s, centro, spec, level, rm):
        """O som desenhado no ARO do disco — um anel que ondula com a música.

        ── o que havia antes, e por que saiu ──────────────────────────────
        Uma coluna de retângulos âmbar de canto vivo, colada na beirada
        esquerda da capa: vinte e quatro caixinhas empilhadas, uma por faixa
        de frequência, com o resto da tela sem nenhuma. Era um GRÁFICO
        pendurado ao lado do disco — a única peça da AGORA que não era nem
        luz nem objeto, e a §5.5 do CLAUDE.md diz o que fazer com isso: mais
        vida, mais reação ao som, mais luz com propósito.

        O disco já está ali, girando atrás da capa, e o que se vê dele é o
        aro em volta — quatro fatias, porque a capa é quadrada e o disco é
        redondo. Então o som mora nesse aro: um anel fechado cujo RAIO é o
        espectro, grave no alto, agudo embaixo, espelhado à esquerda e à
        direita para ler como objeto e não como leitura de instrumento.
        Parado, ele é uma circunferência; com música, ele ondula.

        Um traço só, fechado — não vinte e quatro peças —, o que também o
        torna mais barato do que a coluna que ele substitui.

        E ele tem RETENÇÃO: um segundo anel, mais fraco, no máximo recente de
        cada faixa, descendo aos poucos. Sem ele o espectro desaba junto com a
        nota e o aro inteiro "lê" igual; o pico é o eco da energia que passou,
        e é a peça que fecha a ilusão de um instrumento. (É a mesma ideia do
        acento no topo das barras da coluna que este anel substituiu — mudou
        a forma, não o que ela diz.)
        """
        if level < 0.015 or spec is None or len(spec) == 0:
            return
        nb = len(spec)
        # A retenção, por faixa: sobe com a banda e desce 3% por quadro.
        pico = self._spec_pico
        if pico is None or len(pico) != nb:
            pico = self._spec_pico = [0.0] * nb
        for i in range(nb):
            pico[i] = max(float(spec[i]), pico[i] - 0.03)
        n = 96                      # pontos do anel: liso a 60 fps, e barato
        # Colado no aro, não flutuando em volta: a onda é pequena de
        # propósito. Com muita amplitude o anel perde a circunferência e o
        # disco deixa de ter silhueta — vira uma mancha com contorno. E o
        # TETO é em pixels, não em fração do raio: na tela cheia o disco tem
        # 430 px de raio, e 7,5% dele são 32 px de ondulação — o anel
        # descolava da borda e lia como uma curva de nível solta em volta.
        ganho = min(0.075, 22.0 / max(1.0, rm)) * (0.45 + 0.55 * min(1.0, level))
        lado = int(rm * 2.4)
        aro = T.rascunho(lado, lado, "espectro")
        c = lado // 2
        cx_d, cy_d = centro
        pts, pts_pico = [], []
        for k in range(n):
            a = -math.pi / 2 + 2 * math.pi * k / n
            # A distância ao TOPO, de 0 (12 h) a 1 (6 h), igual dos dois
            # lados: é o espelhamento que faz o anel ler como um objeto
            # respirando em vez de um gráfico enrolado num círculo.
            t = abs(((2 * math.pi * k / n) + math.pi) % (2 * math.pi)
                    - math.pi) / math.pi
            f = t * (nb - 1)
            i0 = int(f)
            i1 = min(nb - 1, i0 + 1)
            v = float(spec[i0]) + (float(spec[i1]) - float(spec[i0])) * (f - i0)
            vp = pico[i0] + (pico[i1] - pico[i0]) * (f - i0)
            r = rm * (0.99 + ganho * v)
            pts.append((c + math.cos(a) * r, c + math.sin(a) * r))
            rp = rm * (0.99 + ganho * vp)
            pts_pico.append((c + math.cos(a) * rp, c + math.sin(a) * rp))
        # Três passadas: larga e fraca por fora, fina e forte no meio. É o
        # jeito barato de um traço virar LUZ em vez de contorno vetorial —
        # sem desfoque, que a esta altura custaria o quadro inteiro.
        base = min(1.0, level)
        # O eco primeiro, por baixo: um traço fino e apagado por onde a
        # energia passou.
        pygame.draw.lines(aro, (*T.TEXT, int(60 * (0.35 + 0.65 * base))),
                          True, pts_pico, 1)
        for larg, alfa in ((5, 22), (3, 55), (1, 150)):
            pygame.draw.lines(aro, (*T.AMBER, int(alfa * (0.35 + 0.65 * base))),
                              True, pts, larg)
        s.blit(aro, (cx_d - c, cy_d - c))

    def _groove(self, s, rect, frac, wave=None, pulse=0.0):
        """Barra de progresso como sulco — e o sulco desenha a música.

        O traço âmbar é a própria onda dos últimos ~21 ms, lida do monitor do
        PipeWire (audio_live) — o sulco é onde o som está, é justo que o som
        o desenhe. Sem monitor (máquina sem PortAudio, teste de tela sem
        áudio) a barra volta ao traço clássico: nenhum desenho pode depender
        de um hardware que não existe. A ponta da reprodução pulsa com o
        `pulse` (o transiente) por cima do traço parado — a batida passa
        aqui, na marca exata onde o prato está agora."""
        pygame.draw.rect(s, T.LINE, rect, border_radius=6)
        if wave is not None and len(wave) >= 2:
            y0 = rect.centery
            pts = []
            salto = (len(wave) - 1) / float(max(1, rect.w - 1))
            for xi in range(rect.w):
                v = float(wave[int(xi * salto)]) * rect.h * 0.42
                pts.append((rect.x + xi, int(y0 - v)))
            pygame.draw.lines(s, T.AMBER, False, pts)
        # ponta luminosa na posição atual
        if frac > 0.01:
            glow = T.rascunho(18, rect.h + 6, "sulco")
            pygame.draw.circle(glow, (*T.AMBER_GLOW, 60), (9, rect.h // 2 + 3), 8)
            s.blit(glow, (rect.x + int(rect.w * frac) - 9, rect.y - 3))
            pygame.draw.circle(s, T.TEXT,
                               (rect.x + int(rect.w * frac), rect.centery),
                               6 + int(3 * (pulse or 0.0)))

    def _nothing(self, s, r):
        """Nada tocando: o disco parado no escuro, e onde a agulha cairia.

        ── Por que o braço saiu daqui ────────────────────────────────────────
        Antes havia um braço inteiro: haste cinza, pivô, CONTRAPESO atrás do
        pivô, cabeçote, e um descanso feito de poste vertical com um berço em
        U e um pé. A lei do desenho (CLAUDE.md §5.5) proíbe isso pelo nome —
        "braço de metal com contrapeso desenhado" — e o motivo aparece na
        tela: era a única peça em cinza frio num quadro cujo assunto é âmbar
        no escuro, e ela puxava o olho para uma peça de móvel em vez de para
        o disco. Toda vez que alguém tentou desenhar isto "como um toca-discos
        de verdade", o resultado foi reprovado na hora.

        O que ficou é só luz, e cada peça diz alguma coisa:

            o halo    assenta o disco no escuro sem inventar mesa nem sombra
            o brilho  passa uma vez a cada volta: a tela não congelou
            o eixo    pulsa devagar — o "ligado" da máquina
            a faísca  onde a agulha cairia, respirando. É um convite, e é a
                      única coisa que precisava do braço para ser dita.
        """
        t = time.time()
        # O disco ocupa o que a tela der, com espaço para o texto embaixo.
        R = int(max(120, min(r.w * 0.20, (r.h - 220) * 0.42)))
        cx, cy = r.centerx, r.centery - 30

        # ── o halo, respirando ────────────────────────────────────────────
        # Sem ele o disco fica recortado no nada. Respira em contratempo com
        # o eixo (fases diferentes) para as duas pulsações não baterem juntas
        # e virarem um piscar só.
        # A respiração vai no `forca`, ASSADA na superfície em cache, e não
        # num `set_alpha` por quadro. Duas razões, as duas medidas:
        # o set_alpha custa 4,2 ms contra 0,4 ms num halo de 938 px (um quarto
        # do quadro para desenhar uma luz parada, nesta que é a tela que fica
        # ligada a noite inteira); e ele mexia na superfície do CACHE, ou
        # seja, na luz de todo mundo que pedisse o mesmo halo depois.
        folga = int(R * 0.30)
        h = T.halo(R, folga, forca=int(190 + 65 * math.sin(t * 0.55)))
        s.blit(h, (cx - R - folga, cy - R - folga))

        d = T.disco(R)
        s.blit(d, (cx - R, cy - R))

        # O brilho que passa: é ele que diz que o disco está ali, parado, e
        # não que a tela congelou. A intensidade sobe e desce ao longo do
        # arco. Com a queda só de um lado — como estava — o começo do brilho
        # era um corte reto, e o que aparecia no disco era um quadrilátero
        # claro, não um reflexo.
        ang = (t * 0.7) % (2 * math.pi)
        bril = T.rascunho(R * 2, R * 2, "bril")
        n, arco = 40, math.radians(34)
        r0, r1 = R * T.GROOVE_I, R * T.GROOVE_O
        for i in range(n):
            f = i / (n - 1)
            aa = ang + (f - 0.5) * arco
            a = int(20 * math.sin(f * math.pi) ** 2)
            if a <= 0:
                continue
            pygame.draw.line(
                bril, (*T.AMBER_GLOW, a),
                (R + math.cos(aa) * r0, R + math.sin(aa) * r0),
                (R + math.cos(aa) * r1, R + math.sin(aa) * r1), 2)
        s.blit(bril, (cx - R, cy - R))

        # O eixo, pulsando devagar — o "ligado" da máquina.
        pulse = 0.7 + 0.3 * math.sin(t * 1.5)
        gr = int(R * 0.10)
        glow = T.rascunho(gr * 2, gr * 2, "glow")
        pygame.draw.circle(glow, (*T.AMBER_GLOW, int(26 * pulse)),
                           (gr, gr), gr)
        s.blit(glow, (cx - gr, cy - gr))
        pygame.draw.circle(s, T.AMBER, (cx, cy), max(3, int(R * 0.022)))

        # ── a faísca da queda ─────────────────────────────────────────────
        # Onde a agulha encosta: o começo do primeiro sulco, no alto à
        # direita. O ângulo é o mesmo pivô de 42° que o deck usa (vinyl.py),
        # para as duas telas não contarem histórias diferentes sobre o mesmo
        # disco — só que aqui ele vira um ponto de luz em vez de uma haste.
        qa = math.radians(42.0) - math.pi / 2
        qr = R * (T.GROOVE_O - 0.015)
        qx, qy = cx + math.cos(qa) * qr, cy + math.sin(qa) * qr
        resp = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 1.1 + 1.6))
        fr = max(10, int(R * 0.12))
        faisca = T.rascunho(fr * 2, fr * 2, "faisca")
        for k in range(6, 0, -1):
            pygame.draw.circle(faisca, (*T.AMBER_GLOW, int(20 * resp)),
                               (fr, fr), int(fr * k / 6))
        s.blit(faisca, (qx - fr, qy - fr))
        pygame.draw.circle(s, T.AMBER, (int(qx), int(qy)),
                           max(2, int(R * 0.016)))

        # ── o texto ──────────────────────────────────────────────────────
        # As teclas viram teclas: é a mesma linguagem do resto da interface,
        # e "pressione r" escrito por extenso era o único lugar que ainda
        # explicava um atalho com uma frase.
        ty = cy + R + 56
        T.text(s, "nada tocando", (cx, ty), 32, T.TEXT_DIM, anchor="center")
        T.text(s, "vá para a ESTANTE e escolha um disco",
               (cx, ty + 42), 20, T.TEXT_FAINT, anchor="center")
        T.frase_com_teclas(s, "ou [r] sorteia um por você",
                           (cx, ty + 76), 17, T.TEXT_FAINT, anchor="center")


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
        # 78 e não 58: a contagem ("14 discos") é escrita em 22 px a partir
        # de r.y+18, ou seja termina em r.y+46 — com o corte da grade em 58 a
        # primeira fileira de capas encostava nela, e uma parede de capas
        # encostada no título lê como se tivesse sido cortada pela borda.
        head = 78

        if not self.app.shelf.ready:
            T.text(s, "lendo a estante…", (r.centerx, r.centery), 26,
                   T.TEXT_DIM, anchor="center")
            return
        if not its:
            # Vazio por QUATRO motivos diferentes, e o recado errado manda a
            # pessoa consertar o que não está quebrado: com a ordem em
            # "favoritos" e nenhum favorito, ou com um filtro de artista sem
            # resultado, a tela dizia "a estante está vazia" e mandava rodar
            # `stylus library` — numa coleção de trezentos discos.
            if self.query:
                msg = 'nada com "%s"' % self.query
                saida = "[esc] limpa a busca"
            elif self.order == "favoritos":
                msg = "nenhum disco favoritado ainda"
                saida = ("[f] marca o disco escolhido   ·   "
                         "[o] volta para a estante inteira")
            elif self.artist:
                msg = "nada de %s por aqui" % self.artist
                saida = "[a] tira o filtro de artista"
            else:
                msg = "a estante está vazia"
                saida = "`stylus library ~/Music` diz onde ela fica"
            T.text(s, msg, (r.centerx, r.centery), 26, T.TEXT_DIM,
                   anchor="center", maxw=r.w - 80)
            T.frase_com_teclas(s, saida, (r.centerx, r.centery + 36), 19,
                               T.TEXT_FAINT, anchor="center")
            return

        # ── cabeçalho: contagem, ordem, busca ──────────────────────────────
        if self.picking:
            self._picker(s, r)
            return
        if self.searching or self.query:
            T.text(s, "/ " + self.query + ("▌" if self.searching else ""),
                   (r.x + pad, r.y + 16), 24, T.AMBER)
        else:
            rotulo = plural(len(its), "disco")
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

        # ── qual destes está tocando ───────────────────────────────────────
        # A grade não dizia. Havia a tarja no rodapé com o nome da faixa, mas
        # numa parede de capas a pergunta é "qual delas", e a resposta estava
        # escrita em letra de dez pixels do outro lado da tela. O disco que
        # está no prato ganha o mesmo halo da AGORA — a luz que aquela tela
        # já usa para dizer "é este" — e ela respira com o som.
        al_tocando = self.app.playing.album
        pasta_tocando = (os.path.normpath(al_tocando.folder)
                         if al_tocando is not None and al_tocando.folder
                         else None)
        i_tocando = None
        if pasta_tocando:
            for i, it in enumerate(its):
                if (it["folder"] == pasta_tocando
                        or os.path.normpath(it["folder"]) == pasta_tocando):
                    i_tocando = i
                    break

        clip = pygame.Rect(r.x, r.y + head, r.w, view_h)
        old = s.get_clip()
        s.set_clip(clip)
        # O halo vem ANTES de todas as capas, e não junto com a sua.
        # Desenhado no meio do laço, ele passava por cima da capa do vizinho
        # da esquerda — a luz do disco que toca tingindo de âmbar a arte de
        # outro disco. Luz atrás é atrás de TODAS.
        if i_tocando is not None:
            cx = r.x + pad + (i_tocando % self.COLS) * (cw + gap)
            cy = r.y + head + (i_tocando // self.COLS) * ch - int(self.scroll)
            nivel = min(1.0, self.app.audio_level())
            # O piso de 110 é para a marca não sumir no silêncio: numa máquina
            # sem PortAudio o nível é zero o tempo todo, e um disco tocando
            # sem marca nenhuma é pior do que não ter marca.
            hal = T.halo(int(cw * 0.62), forca=int(110 + nivel * 145))
            s.blit(hal, (cx + cw // 2 - hal.get_width() // 2,
                         cy + cw // 2 - hal.get_height() // 2))
        for i, it in enumerate(its):
            cx = r.x + pad + (i % self.COLS) * (cw + gap)
            cy = r.y + head + (i // self.COLS) * ch - int(self.scroll)
            if cy > clip.bottom or cy + ch < clip.top:
                continue
            # O alvo do rato é a capa MAIS a legenda: clicar no nome do
            # disco é clicar no disco, e um alvo do tamanho exato da capa
            # falha justamente onde o olho mira quando o disco é escuro.
            self.app.alvos.append(
                (pygame.Rect(cx, cy, cw, cw + 44).clip(clip), i))
            self._card(s, pygame.Rect(cx, cy, cw, cw), it, i == self.sel)
            # favorito: estrela âmbar no canto superior direito
            if os.path.normpath(it["folder"]) in favs:
                T.text(s, "★", (cx + cw - 8, cy + 4), 18, T.AMBER, anchor="topright")
            # 14 e não 8: o disco selecionado levanta 6px para cada lado, e
            # com a legenda colada nela mesma ela encostava na capa levantada.
            ty = cy + cw + 14
            # O nome do que está tocando vai em âmbar. O halo atrás da capa
            # some entre as capas do meio da grade — sobram os 18 px de folga
            # para ele aparecer — e o âmbar é a palavra que este sistema usa
            # para "é aqui" (ver o cabeçalho do theme.py). As duas coisas
            # juntas dizem qual disco está no prato de qualquer distância.
            T.text(s, it["name"], (cx, ty), 17,
                   T.AMBER if i == i_tocando else
                   (T.TEXT if i == self.sel else T.TEXT_DIM), maxw=cw)
            T.text(s, it["artist"], (cx, ty + 22), 15, T.TEXT_FAINT, maxw=cw)
        # O aviso de que a grade continua. Sem ele, a fileira cortada ao meio
        # se lê como fileira com defeito e não como "tem mais aqui embaixo".
        total_h = ((len(its) + self.COLS - 1) // self.COLS) * ch
        T.borda_rolagem(s, clip,
                        acima=self.scroll > 2,
                        abaixo=self.scroll + view_h < total_h - 2)
        s.set_clip(old)

        # ── a tarja de "tocando agora" saiu daqui ─────────────────────────
        # Havia uma faixa âmbar atravessando o rodapé com "▶ artista —
        # faixa" e, à direita, "enter = ver o disco".
        #
        # Duas coisas erradas com ela. A primeira é que ENTER na estante PÕE
        # o disco escolhido — a linha de dicas logo abaixo diz isso com todas
        # as letras — então a tarja anunciava um atalho que faz outra coisa,
        # a dois centímetros de quem diz a verdade. A segunda é que ela virou
        # a QUARTA resposta para a mesma pergunta na mesma tela: o trilho tem
        # o cartão TOCANDO com capa, nome, artista e progresso; a grade tem o
        # halo âmbar atrás da capa e o nome em âmbar. Um sistema que responde
        # quatro vezes à mesma pergunta não está informando, está enchendo.
        # A estante revarre numa thread enquanto a grade desenha: entre o
        # `items()` do começo deste quadro e aqui, a lista pode ter
        # encolhido. Um índice velho vira IndexError e a tela cai.
        self.sel = max(0, min(self.sel, len(its) - 1))
        sel = its[self.sel]
        self.app.hint(
            s, r,
            # O [r] e o [f] existiam desde sempre e não eram anunciados em
            # lugar nenhum: sortear um disco da prateleira e marcar favorito
            # são duas coisas que a estante FAZ e que ninguém tinha como
            # descobrir. (É o mesmo defeito do i3 ao contrário: lá a tela
            # prometia comando que não existia; aqui ela escondia o que
            # existe.) A linha ficou longa, e tudo bem: quando não couber,
            # o `hint` derruba a dica inteira do fim, nunca corta um atalho
            # pela metade.
            "[enter] põe   [s] empilha   [r] sorteia   [f] favorito   "
            "[a] artista   [o] ordem   [/] procura",
            contexto=f"{sel['artist']} — {sel['name']}   ·   "
                     f"{ha_quanto(sel['last'])}")

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
        self.app.hint(s, r, "[enter] escolhe   ·   [↑][↓] anda   ·   "
                            "[esc] desiste")

    def _card(self, s, rect, it, selected):
        # O selecionado é puxado meio palmo para fora da prateleira: cresce e
        # ganha um halo âmbar por trás. O halo é desenhado antes da capa
        # porque é o que sobra visível ao redor dela.
        if selected:
            rect = rect.inflate(10, 10)
            pygame.draw.rect(s, T.lerp(T.INK, T.AMBER, 0.30), rect.inflate(14, 14),
                             border_radius=6)
        cov = self.app.thumbs.get(it["cover"])
        # A capa com lombada, luz e contato — o T.sleeve explica por quê. A
        # sombra que estava aqui desenhava preto sobre um fundo quase
        # preto: custava blits e não mudava pixel nenhum.
        T.sleeve(s, rect, cov, selected)
        if not cov:
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
        elif ev.key == pygame.K_e:
            # Embaralhar a PILHA é a coisa física: você tira os discos do
            # móvel e reencosta em outra ordem. Não toca em nada nem começa
            # nada — a pilha continua sendo um compromisso que se cumpre um
            # disco de cada vez, e a ordem é a única coisa que muda.
            #
            # Não é o [s] da AGORA: aquele embaralha as FAIXAS do que já está
            # tocando, e este a ordem dos DISCOS que ainda não foram postos.
            if len(st) > 1:
                antes = [i["folder"] for i in st]
                for _ in range(8):
                    random.shuffle(st)
                    if [i["folder"] for i in st] != antes:
                        break
                self.sel = 0
                self.app.stack_save()
                self.app.toast("pilha embaralhada")
            else:
                self.app.toast("um disco só: não há o que embaralhar")
        elif ev.key in (pygame.K_LEFT, pygame.K_h, pygame.K_RIGHT,
                        pygame.K_l):
            # Sobe e desce o disco na pilha. A ordem da pilha é a ordem da
            # noite, e mudá-la era coisa de esvaziar e empilhar de novo.
            sobe = ev.key in (pygame.K_LEFT, pygame.K_h)
            novo_i = self.sel - 1 if sobe else self.sel + 1
            if 0 <= novo_i < len(st):
                st[self.sel], st[novo_i] = st[novo_i], st[self.sel]
                self.sel = novo_i
                self.app.stack_save()
        else:
            return False
        return True

    def draw(self, s, r):
        st = self.app.stack
        if not st:
            T.vazio(s, r, T.fantasma_pilha, "a pilha está vazia", [
                # Minúsculas: é assim que o resto do sistema escreve tecla,
                # e o `frase_com_teclas` desenha a letra dentro de uma
                # tampinha — um [S] ali se lê como Shift+S, que não é a
                # tecla. As duas são as mesmas do rodapé da estante.
                "na estante, [s] empilha o disco escolhido",
                "ou [t] monta uma noite inteira daqui",
            ])
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
            T.sleeve(s, cr, cov)
            T.text(s, f"{i + 1}", (row.x - 18, row.y + 30), 22,
                   T.AMBER if sel else T.TEXT_FAINT, anchor="topright")
            T.text(s, it["name"], (cr.right + 20, row.y + 14), 24,
                   T.TEXT if sel else T.TEXT_DIM, maxw=row.w - 140)
            T.text(s, it["artist"], (cr.right + 20, row.y + 46), 18,
                   T.TEXT_FAINT, maxw=row.w - 140)
            # O que este disco É, encostado à direita: a pilha é um
            # compromisso, e um compromisso se mede. A linha inteira à
            # direita da capa estava vazia — mil e duzentos pixels sem nada.
            partes = []
            if it.get("mins"):
                partes.append("%d min" % it["mins"])
            if it.get("lados"):
                partes.append("%d lado%s" % (it["lados"],
                                             "s" if it["lados"] > 1 else ""))
            if it.get("discos", 1) > 1:
                partes.append(plural(it["discos"], "disco"))
            if partes:
                T.text(s, "  ·  ".join(partes), (row.right - 8, row.y + 20),
                       19, T.TEXT_DIM if sel else T.TEXT_FAINT,
                       anchor="topright")
            if it.get("last"):
                T.text(s, ha_quanto(it["last"]), (row.right - 8, row.y + 48),
                       16, T.TEXT_FAINT, anchor="topright")
            total += it.get("mins", 0)
            y += 104
        if total:
            T.text(s, f"{int(total)} min de disco encostado no móvel",
                   (x, y + 8), 19, T.TEXT_FAINT)
        self.app.hint(s, r, "[enter] põe este e tira da pilha   [x] descarta   "
                            "[e] embaralha   [←][→] muda de lugar   "
                            "[t] monta uma noite")


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

        # A coluna tem largura máxima (linha comprida demais não se lê a três
        # metros) e por isso sobrava meia tela vazia à direita, com tudo
        # grudado na borda esquerda. Centrada, o vazio fica dos dois lados e
        # a tela passa a ter composição em vez de encosto.
        bw = min(r.w - 88, 900)
        bx = r.x + max(44, (r.w - bw) // 2)

        y = r.y + 60
        T.text(s, "o caminho do sinal", (bx, y), 30, T.TEXT, bold=True)
        T.text(s, "medido agora, não prometido na caixa",
               (bx, y + 40), 19, T.TEXT_FAINT)

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
        by = y + 96
        # O passo e a altura dos quadros vêm da ALTURA que sobra. Eram 132 e
        # 104 fixos: três quadros mais o cabeçalho somam 552 px, e numa tela
        # de 600 o veredito ("reamostrado 44,1 → 48 kHz", que é a frase que
        # esta tela existe para dizer) era desenhado por cima da linha de
        # dicas. Os 136 px reservados são o veredito (34), a explicação de
        # duas linhas (44) e a linha de dicas (34), com folga.
        disp = max(210, r.bottom - 136 - by)
        passo = min(132, max(76, disp // 3))
        alt_box = max(62, passo - 28)
        # As letras encolhem junto: num quadro de 62 px o valor em 26 pt
        # transborda por baixo dele.
        fs_val = 26 if alt_box >= 90 else 20
        fs_nome = 24 if alt_box >= 90 else 19
        y_tit = int(alt_box * 0.17)
        y_val = int(alt_box * 0.42)
        for n, (titulo, nome, val) in enumerate(elos):
            box = pygame.Rect(bx, by + n * passo, bw, alt_box)
            T.panel(s, box, T.INK_SOFT, radius=12, border=T.LINE)
            T.text(s, titulo, (box.x + 24, box.y + y_tit), 16, T.TEXT_FAINT)
            # O nome do aparelho para onde o valor começa, MEDIDO. Ver
            # T.largura: com folga fixa, o nome do conversor entrava por cima
            # do "pode trocar de taxa" — e só em quem tem placa de nome
            # comprido, que é sempre a máquina de outra pessoa.
            folga = T.largura(str(val), fs_val, bold=True) + 40
            T.text(s, str(nome), (box.x + 24, box.y + y_val), fs_nome, T.TEXT,
                   maxw=max(120, bw - 48 - folga))
            T.text(s, str(val), (box.right - 24, box.y + y_val), fs_val,
                   cor if n < 2 else (T.GREEN if i.get("multi") else T.AMBER),
                   bold=True, anchor="topright")
            if n < len(elos) - 1:
                mx = box.centerx
                pygame.draw.line(s, cor, (mx, box.bottom + 4),
                                 (mx, box.bottom + 24), 3)
                pygame.draw.polygon(s, cor, [(mx - 7, box.bottom + 22),
                                             (mx + 7, box.bottom + 22),
                                             (mx, box.bottom + 30)])

        # O veredito fica dentro da MESMA coluna dos três quadros — as três
        # linhas daqui para baixo não tinham largura nenhuma, e a explicação
        # do reamostrado ("algo mais está segurando o grafo nessa taxa…") tem
        # 84 caracteres: numa tela de 1024 ela terminava fora do monitor,
        # justo a frase que existe para dizer o que fazer quando o caminho do
        # som está errado.
        vy = by + 3 * passo + 12
        if not frate:
            T.text(s, "ponha um disco para medir o caminho inteiro",
                   (bx, vy), 21, T.TEXT_FAINT, maxw=bw)
        elif clean:
            T.text(s, "▸ sem conversão: o arquivo chega como foi gravado",
                   (bx, vy), 24, T.GREEN, bold=True, maxw=bw)
        else:
            T.text(s, f"▸ reamostrado {frate / 1000:g} → {graph / 1000:g} kHz",
                   (bx, vy), 24, T.RED, bold=True, maxw=bw)
            # Em parágrafo, não cortada: uma explicação com reticências no
            # meio não explica nada.
            # Uma linha em vez de duas quando não há espaço para duas: a
            # explicação cortada ao meio é melhor do que a explicação por
            # cima da linha de dicas.
            T.paragrafo(s, "algo mais está segurando o grafo nessa taxa, ou o "
                           "conversor ainda não soltou a anterior",
                        (bx, vy + 34), 18, T.TEXT_FAINT, maxw=bw,
                        limite=2 if r.bottom - (vy + 34) > 96 else 1)
        self.app.hint(s, r, "atualiza sozinho   ·   [enter] força agora")


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
        # Quantas vezes cada disco foi posto, contado DAQUI — do mesmo
        # registro que a lista está lendo, numa passada só.
        #
        # **Sintoma:** o `Nx` de cada linha vinha do `plays` da ESTANTE, que é
        # contado uma vez, na varredura. O diário lia o registro fresco e
        # mostrava a escuta de dois minutos atrás — com um número ao lado que
        # não a incluía, e que só mudava quando a estante fosse varrida de
        # novo. A linha mais nova da tela com o número mais velho dela.
        vezes = {}
        postos = set()
        for _ts, f in rows:
            k = os.path.normpath(f)
            postos.add(k)
            vezes[k] = vezes.get(k, 0) + 1
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
                        "plays": vezes.get(k, 1)})
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
            T.vazio(s, r, T.fantasma_diario, "nada anotado ainda", [
                "o sistema anota sozinho toda vez que você põe um disco",
                "não precisa fazer nada — é só ouvir",
            ])
            return
        x, y = r.x + 44, r.y + 30
        total = sum(self.by_day.values())
        T.text(s, f"{plural(len(self.rows), 'disco')}  ·  {plural(total, 'vez', 'vezes')}",
               (x, y), 24,
               T.TEXT_DIM)
        y += 46
        # Quantas linhas cabem, em vez de sete sempre. Sete linhas de 84 px
        # mais o cabeçalho passam de 660 px: numa tela de 720 elas comiam o
        # calendário e a linha de dicas. Três é o piso — abaixo disso a
        # seção deixa de ser uma lista.
        cabem = max(3, min(7, (r.h - 240) // 84))
        for i, it in enumerate(self.rows[self.scroll:self.scroll + cabem]):
            sel = i == 0
            row = pygame.Rect(x, y, r.w - 88, 78)
            if sel:
                T.panel(s, row.inflate(16, 6), T.INK_LIFT, radius=10)
            cr = pygame.Rect(row.x, row.y, 66, 66)
            # A mesma capa-objeto do resto do sistema. Aqui ela ainda era
            # colada chapada, e era a última lista que destoava.
            T.sleeve(s, cr, self.app.thumbs.get(it["cover"]))
            # As três colunas dividem a linha por MEDIDA. Eram dois números
            # fixos — `row.w - 380` para o nome e `row.right - 150` para a
            # data — e "posto há 11 meses" mede mais do que os 150
            # reservados: o fim do nome do disco ficava por baixo do começo
            # da data. Numa tela de 800 acontecia até com "Abbey Road".
            quando = ha_quanto(it["ts"])
            vezes = f"{it['plays']}x"
            x_vezes = row.right - 20
            x_quando = x_vezes - T.largura(vezes, 21) - 16
            maxw = max(60, x_quando - T.largura(quando, 19) - 16
                       - (cr.right + 18))
            T.text(s, it["name"], (cr.right + 18, row.y + 8), 22,
                   T.TEXT if sel else T.TEXT_DIM, maxw=maxw)
            T.text(s, it["artist"], (cr.right + 18, row.y + 38), 17,
                   T.TEXT_FAINT, maxw=maxw)
            T.text(s, quando, (x_quando, row.y + 20), 19,
                   T.TEXT_DIM, anchor="topright")
            T.text(s, vezes, (x_vezes, row.y + 20), 21,
                   T.PINK, anchor="topright")
            y += 84
        # O calendário fica ENTRE o fim da lista e a linha de dicas, e fica
        # com o que sobrar. Antes era altura fixa de 104 px numa posição
        # fixa: numa tela grande sobrava espaço vazio debaixo da lista e o
        # quadro ficava apertado do mesmo jeito, e numa tela pequena ele
        # entrava por cima da lista. O -70 reserva a legenda dele e a linha
        # de dicas, que foi o defeito que a posição fixa existia para evitar.
        topo = y + 18
        alt = min(240, r.bottom - topo - 70)
        if alt >= 60:
            self._calendar(s, pygame.Rect(x, topo, r.w - 88, alt))
        self.app.hint(s, r, "[enter] põe de novo   ·   [↑][↓] anda   ·   [s] o formato")

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
            T.sleeve(s, cr, cov)
            if not cov:
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
            T.text(s, f"{self.nunca} dos {plural(self.total_estante, 'disco')} da estante "
                      f"nunca foram postos  ·  o SORTEIO puxa para eles",
                   (x, r.bottom - rodape + 4), 17,
                   T.AMBER if self.nunca else T.GREEN)
        self.app.hint(s, r, "[s] volta para a lista")

    def _calendar(self, s, rect):
        """Um ano em quadradinhos: uma coluna por semana, um por dia.

        Vale mais do que parece. Ver as semanas vazias é a única forma
        honesta de perceber que você passou um mês sem sentar para ouvir
        nada — o que é exatamente o hábito que este sistema existe para
        recuperar.
        """
        hoje = time.localtime()
        gap = 2
        # Quantos dias mostrar. O ano inteiro é o objetivo — mas só depois de
        # existir um ano de diário.
        #
        # **Sintoma:** numa máquina com oito dias de uso, o desenho eram 363
        # quadradinhos vazios e seis pintados. Isso não diz "você passou meses
        # sem ouvir nada", que é a leitura que o desenho propõe; diz "o sistema
        # não estava instalado". Para quem acabou de instalar — o primeiro
        # público desta tela — é uma tela inteira de fracasso que nunca
        # aconteceu.
        #
        # Então o quadro começa no primeiro dia ANOTADO, e cresce sozinho até
        # o ano. A partir daí, semana vazia volta a querer dizer o que o
        # docstring acima diz que quer dizer.
        dias = 364
        if self.by_day:
            try:
                primeiro = min(time.mktime(time.strptime(k, "%Y-%m-%d"))
                               for k in self.by_day)
                idade = int((time.time() - primeiro) // 86400)
                # Um mês de piso: menos que isso e o desenho fica estreito
                # demais para se ler como calendário.
                dias = max(27, min(364, idade + 6))
            except ValueError:
                pass
        # O quadradinho vem da largura E da altura disponíveis. Só da largura,
        # ele ficava preso em 10 px numa tela de 1600 e o ano inteiro ocupava
        # metade do espaço que tinha, lendo como um enfeite pequeno em vez de
        # como o gráfico que é.
        # O quadradinho cabe nas SEMANAS QUE EXISTEM, não nas 53 de um ano:
        # com o divisor fixo, um diário de quatro semanas desenhava quatro
        # colunas minúsculas encolhidas para um ano que ainda não aconteceu.
        # E ele ocupa a LARGURA que tem. O teto era 22 px por quadradinho:
        # num ano inteiro isso são 53×24 = 1272 px dentro de um retângulo de
        # 1600, e o ano terminava trezentos pixels antes da lista de discos
        # que ele acompanha — lendo como um enfeite solto no canto em vez de
        # como o resumo da página. O teto que sobrou (30) existe só para um
        # diário de quatro semanas não virar oito quadrados gigantes.
        semanas = dias // 7 + 1
        cell = max(4, min(30, rect.w // semanas - gap, rect.h // 7 - gap))
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
        # A legenda diz o período de VERDADE. "um ano" num quadro de cinco
        # semanas seria a mesma mentira em texto.
        desde = time.strftime("%d/%m", time.localtime(base))
        quanto = "um ano" if dias >= 364 else f"desde {desde}"
        T.text(s, f"{quanto}  ·  até {time.strftime('%d/%m', hoje)}",
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
        self.app.lista_com_saida(
            s, r, "o celular",
            "a coleção é a mesma nos dois lados; a parte difícil é manter "
            "os dois honestos sobre qual cópia é a melhor",
            self.ACOES, self.sel, self.job,
            "[enter] roda   ·   nada aqui mexe no celular sem você mandar",
            size=21)


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
        # Havia aqui um "baixar do Qobuz e arquivar" que abria um terminal
        # com a interface WEB do qobuz-dl. Saiu: a seção QOBUZ faz a mesma
        # coisa sem navegador nenhum, procura, toca sem baixar e agora até
        # entra na conta — e mandar alguém para um terminal e um navegador
        # para fazer o que a tela ao lado faz melhor é o oposto do que esta
        # interface existe para ser.
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
        self.app.lista_com_saida(
            s, r, "a oficina",
            "as mesmas ferramentas do terminal, sem o terminal",
            self.ACOES, self.sel, self.job,
            "[enter] roda   ·   a saída aparece do lado")


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
        self.examing = None
        self.job = None
        self._montagem = None
        self.entrada = None           # o formulário de login, quando aberto
        self.favoritos = False        # a grade mostra os seus favoritos?
        # A ordem de cada disco já examinado, por id. Guardada porque olhar o
        # mesmo disco duas vezes é o que se faz numa loja, e pedir de novo ao
        # Qobuz por isso seria dois segundos de espera por olhada.
        self._faixas = {}

    def enter(self):
        self._olhar()
        # A loja abria vazia, com um "[/] procura um disco" e mais nada. A
        # coisa mais óbvia de se querer ver ao abrir a loja da SUA assinatura
        # é o que você já marcou lá dentro — dezenas de discos que já estavam
        # do outro lado da conta, sem caminho nenhum até eles daqui.
        if not self.results and not self.query:
            self._favoritos()

    def _favoritos(self):
        """Os discos marcados na sua conta do Qobuz, na abertura da loja."""
        if self.loading:
            return
        self.loading = True
        self.error = None

        def _do():
            try:
                r = rodar(["stylus-qobuz", "favoritos"],
                          capture_output=True, text=True, timeout=30)
                dados = json.loads((r.stdout or "").strip() or "{}")
                # Sem conta ainda não é ERRO: é o estado normal de quem
                # acabou de instalar. Um vermelho no meio da tela para dizer
                # "você ainda não entrou" é assustar sem motivo — o cartão de
                # instalação já diz isso com calma, e é ele que aparece.
                if dados.get("results"):
                    self.results = dados["results"]
                    self.sel, self.scroll, self.target = 0, 0.0, 0.0
                    self.favoritos = True
            except Exception:             # noqa: BLE001
                pass
            finally:
                self.loading = False

        threading.Thread(target=_do, daemon=True).start()

    def _listas(self):
        """As SUAS playlists do Qobuz, na mesma grade dos discos.

        Uma assinatura é a coleção de discos e as playlists que você montou, e
        a loja só sabia da metade: as três playlists desta conta — uma delas
        com 853 faixas — não tinham caminho nenhum daqui. Elas entram como
        item da grade, com o mosaico das quatro primeiras capas no lugar da
        capa, e tocam por `playlist:ID`, que o qobuz_stream entende.
        """
        if self.loading:
            return
        self.loading, self.error = True, None

        def _do():
            try:
                r = rodar(["stylus-qobuz", "listas"],
                          capture_output=True, text=True, timeout=90)
                itens = []
                for ln in (r.stdout or "").splitlines():
                    campos = ln.split("\t")
                    if len(campos) != 4 or not campos[3].startswith("qobuz-lista:"):
                        continue
                    dono, nome, capa, alvo = campos
                    ident = alvo.split(":", 1)[1]
                    itens.append({
                        "id": ident, "display_title": nome,
                        "display_subtitle": dono, "release_year": "",
                        "tracks": 0, "quality": "playlist", "hires": False,
                        "cover": capa, "lista": True,
                        "url": "https://play.qobuz.com/playlist/%s" % ident})
                self.results, self.sel = itens, 0
                if not itens:
                    self.error = "nenhuma playlist nesta conta"
            except Exception as e:                       # noqa: BLE001
                self.error = str(e)
            finally:
                self.loading = False

        threading.Thread(target=_do, daemon=True).start()

    def _entrar(self):
        """Abre o formulário de conta. Ver a classe Formulario."""
        def _pronto(deu, dado):
            if deu:
                self.app.toast("entrou no Qobuz (%s)"
                               % (dado.get("assinatura") or "conta"))
                self.entrada = None
                self._olhar()
        self.entrada = Formulario(
            "entrar no Qobuz",
            [("e-mail", "a conta da sua assinatura", False),
             ("senha", "", True)],
            ["stylus-qobuz", "entrar", "--json"],
            ao_terminar=_pronto,
            rodape="fica guardado só nesta máquina, em ~/.config/qobuz-dl")

    def _olhar(self):
        """O que a tela precisa saber para trabalhar, fora do fio do desenho.

        Não sonda mais a interface web. Ela sondava a porta 8765 fixa — uma
        das cinco que o `stylus-qobuz` procura — e usava a resposta para
        decidir se `d` podia baixar. Agora `d` baixa pela linha de comando,
        que não precisa de interface nenhuma no ar, e a sonda virou uma
        conexão de dois segundos cuja resposta ninguém lia.
        """
        def _ler():
            self._montagem = self._ler_montagem()
        threading.Thread(target=_ler, daemon=True).start()

    def _ler_montagem(self):
        """O que falta para a loja funcionar: o qobuz-dl e a conta.

        Nenhum dos dois tem a ver com a interface web — ela é opcional e é o
        que se quer evitar num sofá. Ver o cabeçalho do draw.
        """
        # Há DOIS jeitos de estar autenticado, e antes só um contava.
        #
        # Quem entra pela interface web (qobuz-dl-gui) — que é como quase
        # todo mundo entra — autentica por token: o config.ini fica com
        # user_id e user_auth_token preenchidos e e-mail e senha VAZIOS.
        # Exigir e-mail e senha fazia esta tela dizer "a loja ainda não está
        # ligada" para sempre numa máquina perfeitamente logada, com o cartão
        # de instalação mandando fazer de novo o que já estava feito.
        cfg = os.path.expanduser("~/.config/qobuz-dl/config.ini")
        cred = False
        if os.path.exists(cfg):
            try:
                import configparser
                cp = configparser.ConfigParser()
                cp.read(cfg, encoding="utf-8")
                for sec in cp.sections() + ["DEFAULT"]:
                    d = cp[sec]
                    tem = (lambda k: bool(d.get(k, "").strip()))
                    if ((tem("user_id") and tem("user_auth_token"))
                            or (tem("email") and tem("password"))):
                        cred = True
                        break
            except Exception:             # noqa: BLE001
                cred = False
        venv = os.path.expanduser("~/.local/share/stylus/venv/bin/python3")
        lib = False
        for py in (venv, "python3"):
            try:
                lib = subprocess.run([py, "-c", "import qobuz_dl"],
                                     capture_output=True, timeout=8).returncode == 0
                if lib:
                    break
            except Exception:             # noqa: BLE001
                pass
        return {"lib": lib, "cred": cred}

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
                self.favoritos = False
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

    def _pedir_faixas(self, item):
        """A ordem do disco, do Qobuz, sem baixar nem assinar nada.

        O `[enter]` se chama "examina" e mostrava capa, ano e qualidade —
        tudo que já estava no quadradinho da grade. O que se examina num
        disco é o que tem DENTRO: as faixas, quanto dura, e em quantos LADOS
        ele cabe, que é a pergunta que este sistema inteiro existe para
        responder. O Qobuz manda isso de graça; era só ninguém pedir.
        """
        ident = str(item.get("id") or "").strip()
        if not ident or item.get("lista") or ident in self._faixas:
            return
        self._faixas[ident] = {"estado": "lendo"}

        def _do():
            try:
                r = rodar(["stylus-qobuz", "faixas", ident],
                          capture_output=True, text=True, timeout=40)
                dados = json.loads((r.stdout or "").strip() or "{}")
                fx = dados.get("results") or []
                if not fx:
                    self._faixas[ident] = {
                        "estado": "erro",
                        "msg": dados.get("error") or "esse disco veio sem faixas"}
                    return
                lados, total, discos = _lados_de(fx)
                self._faixas[ident] = {"estado": "ok", "faixas": fx,
                                       "lados": lados, "total": total,
                                       "discos": discos}
            except Exception as e:                       # noqa: BLE001
                self._faixas[ident] = {"estado": "erro", "msg": str(e)}

        threading.Thread(target=_do, daemon=True).start()

    def _download(self, item):
        """Baixa direto para a estante. Sem navegador, sem interface no ar.

        Antes esta função recusava o trabalho quando a interface web não
        estava de pé — e a interface web é exatamente o que não se quer num
        sofá, sem teclado, a três metros da tela. O caminho de linha de
        comando (`stylus qobuz baixar ID`) não precisa de nada no ar e põe o
        disco em Artista/Álbum, que é o desenho que a estante lê. Apertar `d`
        e receber "a interface não está no ar" era a tela mandando abrir um
        navegador para fazer o que ela já sabia fazer sozinha.
        """
        if self.job and not self.job.done:
            self.app.toast("já tem download rodando")
            return
        ident = str(item.get("id") or "").strip() or item.get("url", "")
        artist = item.get("display_subtitle", "")
        title = item.get("display_title", "")
        if not ident:
            self.app.toast("esse disco veio sem id")
            return
        self.job = Job(
            ["stylus-qobuz", "baixar", ident],
            f"baixando: {artist} — {title}"
        )
        self.examing = None
        self.app.toast(f"baixando: {artist} — {title}")

    def _tocar(self, item, sortear=False):
        """Toca agora, sem baixar. A assinatura usada como assinatura.

        Ouvir um disco que você ainda não sabe se quer guardar exigia gastar
        quatro gigabytes e depois apagar — ou abrir o site num navegador, que
        é sair do sistema inteiro para fazer a única coisa que ele existe
        para fazer.
        """
        ident = str(item.get("id") or "").strip() or item.get("url", "")
        if not ident:
            self.app.toast("esse disco veio sem id")
            return
        # `playlist:` é o que separa os dois: um id cru não diz sozinho se é
        # disco ou playlist, e pedir o disco de id 67931032 devolve "não achei
        # esse disco" para uma playlist que existe.
        if item.get("lista"):
            ident = "playlist:%s" % ident
        elif sortear:
            # Um disco tem a ordem que quem o fez escolheu. Recusar aqui é
            # mais honesto do que sortear em silêncio — e o [s] da AGORA
            # embaralha o que já está tocando, para quem quiser mesmo.
            self.app.toast("um disco não se sorteia: a ordem é dele. "
                           "([s] na AGORA embaralha o que está tocando)",
                           secs=6.0)
            return
        artist = item.get("display_subtitle", "")
        title = item.get("display_title", "")
        # --deck: a cerimônia, igual à da estante. Um disco que veio pela
        # assinatura não é menos disco — agora que o vinyl sabe ler o
        # disco.json, ele gira na tela como qualquer outro.
        cmd = ["stylus-qobuz", "tocar", "--deck"]
        if sortear:
            cmd.append("--sortear")
        if spawn(cmd + [ident]):
            self.examing = None
            self.app.toast(("sorteando: " if sortear else "pondo pela rede: ")
                           + f"{artist} — {title}", secs=8.0)
        else:
            self.app.toast("não deu para chamar o stylus-qobuz")

    def key(self, ev):
        # O formulário primeiro: enquanto ele está aberto, ele é a tela.
        if self.entrada:
            if ev.key == pygame.K_ESCAPE:
                self.entrada = None
                return True
            return self.entrada.key(ev)

        # ── overlay de exame ────────────────────────────────────────────────
        if self.examing:
            if ev.key == pygame.K_ESCAPE:
                self.examing = None
            elif ev.key == pygame.K_p:
                self._tocar(self.examing)
            elif ev.key == pygame.K_s:
                self._tocar(self.examing, sortear=True)
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
                # Sair da busca sem ter procurado nada volta para os
                # favoritos, e não para uma grade vazia.
                self.searching, self.query = False, ""
                if not self.results:
                    self._favoritos()
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
        # As playlists sao Shift+L, e esta linha tem de vir ANTES da navegacao.
        # O `l` sozinho ja e "direita" no par vim logo abaixo, e num if/elif
        # quem chega primeiro leva: enquanto isto estava la embaixo, apertar
        # `l` andava um disco para o lado e a chamada de _listas() nunca rodava
        # — codigo morto, com a linha de dica prometendo playlists e a tela
        # respondendo com o cursor mexendo. Se algum dia mover isto para baixo
        # da grade, o defeito volta inteiro e de novo sem recado nenhum.
        elif ev.key == pygame.K_l and (ev.mod & pygame.KMOD_SHIFT):
            self._listas()
        # Numa GRADE, para baixo é uma FILEIRA e para o lado é um disco. Estava
        # trocado: ↓ andava um disco para a direita e → pulava cinco. Com o
        # cursor no meio da grade, apertar → mandava o foco para a linha de
        # baixo e apertar ↓ para o vizinho da direita — o olho segue a seta e
        # a seleção vai para outro lugar, que é a definição de controle
        # quebrado. E o par vim é h/l para o lado, j/k para cima e para baixo.
        elif ev.key in (pygame.K_RIGHT, pygame.K_l):
            if n:
                self.sel = min(n - 1, self.sel + 1)
        elif ev.key in (pygame.K_LEFT, pygame.K_h):
            if n:
                self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            if n:
                # Da última fileira, ↓ vai para o fim: uma grade que tem 23
                # discos e 5 colunas deixava os três últimos inalcançáveis
                # pela seta, porque sel+5 passava de n-1 e o min() prendia.
                self.sel = min(n - 1, self.sel + self.COLS)
        elif ev.key in (pygame.K_UP, pygame.K_k):
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
                self._pedir_faixas(self.examing)
        elif ev.key == pygame.K_p:
            if n:
                self._tocar(self.results[self.sel])
        elif ev.key == pygame.K_s:
            # Sortear a playlist. Não é o mesmo que embaralhar depois de
            # posta: com teto de 200 faixas, "as primeiras 200" de uma lista
            # de 853 são sempre as MESMAS — 653 faixas que este sistema nunca
            # tocaria. O sorteio acontece ANTES do corte, lá no
            # qobuz_stream.py, então cada vez que se põe vem outra amostra.
            if n:
                self._tocar(self.results[self.sel], sortear=True)
        elif ev.key == pygame.K_d:
            # `d` baixa aqui também. A linha de dicas prometia "[d] baixa" na
            # grade inteira e só o overlay de exame respondia — apertar `d` em
            # cima de um disco não fazia rigorosamente nada, sem recado.
            if n:
                self._download(self.results[self.sel])
        elif ev.key == pygame.K_c:
            self._entrar()
        elif ev.key == pygame.K_f:
            # De volta aos favoritos. Sem esta, quem apertasse [L] ficava
            # preso nas playlists até reiniciar a tela.
            self.query = ""
            self._favoritos()
        elif ev.key == pygame.K_r:
            self._olhar()
            if self.query:
                self._search()
            elif any(i.get("lista") for i in self.results):
                self._listas()
            else:
                self._favoritos()
        else:
            return False
        return True

    # ── desenho ─────────────────────────────────────────────────────────────

    def _card(self, s, rect, item, sel):
        """Um disco na loja, desenhado como um disco na estante.

        Antes era um painel cinza com o mesmo ícone de disco em todos —
        vinte e cinco quadrados iguais, do lado de uma ESTANTE que mostra as
        capas de verdade. O Qobuz manda a capa junto com o resultado da
        busca; era só ninguém estar pedindo. Pelo mesmo `T.sleeve` da
        estante, para a mesma capa não ter duas aparências dependendo da
        tela em que aparece.
        """
        cov = self.app.thumbs.get(item.get("cover") or "")
        if cov is None:
            # Enquanto a capa não chega da rede: um painel, não um ícone.
            T.panel(s, rect, T.INK_LIFT if sel else T.INK_SOFT, radius=3)
            T.text(s, (item.get("display_title") or "?")[:2].upper(),
                   (rect.centerx, rect.centery), max(16, rect.w // 6),
                   T.TEXT_FAINT, anchor="center")
            if sel:
                pygame.draw.rect(s, T.AMBER, rect.inflate(4, 4), width=2,
                                 border_radius=2)
        else:
            T.sleeve(s, rect, cov, sel)

        # hi-res: um ponto de luz no canto. É a única informação que vale um
        # marcador próprio numa máquina cuja tese é não reamostrar.
        quality = item.get("quality", "")
        if item.get("hires"):
            pygame.draw.circle(s, T.AMBER, (rect.right - 9, rect.y + 9), 3)

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
            info_parts.append(plural(tracks, "faixa"))
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

        # O painel cresceu porque passou a ter o que mostrar: a ORDEM DO
        # DISCO. Ele acompanha a tela em vez de ser 620x330 fixo — numa tela
        # de 800 o de antes já ocupava quase tudo, e numa de 1920 sobrava
        # metade da tela ao lado de um cartão com quatro linhas.
        pw = max(520, min(940, r.w - 80))
        info = self._faixas.get(str(item.get("id") or ""))
        pronto = bool(info and info.get("estado") == "ok")
        # A ALTURA SAI DO CONTEÚDO. Com altura fixa, um single de quatro
        # faixas deixava metade do cartão vazia e um disco de vinte cortava a
        # lista — as duas coisas com o mesmo número escrito no código.
        alt_lista = 0
        if pronto and info["lados"]:
            n_col, por_col = self._colunas_de(info, pw - 64)
            alt_lista = 24 + por_col * 21 + 8
        ph = max(300, min(620, r.h - 60, 246 + alt_lista + 136))
        px = r.x + (r.w - pw) // 2
        py = r.y + (r.h - ph) // 2
        T.panel(s, pygame.Rect(px, py, pw, ph), T.INK_LIFT, radius=16,
                border=T.LINE)

        # a capa, do tamanho de segurar na mão
        title = item.get("display_title", "?")
        artist = item.get("display_subtitle", "?")
        year = item.get("release_year", "")
        tracks = item.get("tracks", 0)
        quality = item.get("quality", "")

        cap = pygame.Rect(px + 32, py + 32, 152, 152)
        cov = self.app.thumbs_hi.get(item.get("cover") or "")
        if cov is None:
            cov = self.app.thumbs.get(item.get("cover") or "")
        if cov is not None:
            T.sleeve(s, cap, cov)
        else:
            T.panel(s, cap, T.INK_SOFT, radius=3)
            T.text(s, title[:2].upper(), cap.center, 34, T.TEXT_FAINT,
                   anchor="center")

        tx = cap.right + 24
        tw = px + pw - 32 - tx
        T.text(s, title, (tx, cap.y + 6), 24, T.TEXT, bold=True, maxw=tw)
        T.text(s, artist, (tx, cap.y + 42), 20, T.AMBER, maxw=tw)

        # Detalhes em duas linhas, e sem os rótulos. Numa linha só eles não
        # cabiam nos 456 px do painel e a última palavra saía como
        # "qualidade…" — o rótulo sobrevivia e o valor, que é a informação,
        # sumia.
        n_faixas = len(info["faixas"]) if pronto else tracks
        if year or n_faixas:
            partes = ([str(year)] if year else []) + \
                     ([plural(n_faixas, "faixa")] if n_faixas else [])
            T.text(s, "  ·  ".join(partes), (tx, cap.y + 78), 16, T.TEXT_DIM,
                   maxw=tw)
        if quality:
            T.text(s, quality, (tx, cap.y + 102), 16,
                   T.AMBER if item.get("hires") else T.TEXT_DIM, maxw=tw)
        # O QUE ESTE DISCO É, em duração e em lados — a pergunta que este
        # sistema existe para responder, e que a loja não respondia: "45 min
        # · 2 lados" diz se cabe antes do jantar melhor do que "10 faixas".
        if pronto and info["lados"]:
            n_l = len(info["lados"])
            frase = "%s  ·  %s" % (humano(info["total"]), plural(n_l, "lado"))
            if info.get("discos", 1) > 1:
                frase += "  ·  %s" % plural(info["discos"], "disco")
            T.text(s, frase, (tx, cap.y + 126), 17, T.AMBER, maxw=tw)

        # ── a ordem do disco ───────────────────────────────────────────────
        ly = cap.bottom + 22
        # As ações moram no rodapé do painel; a lista vai até onde elas
        # começam, e nem um pixel além.
        y_acoes = py + ph - 96
        if item.get("lista"):
            pass                       # uma playlist não tem ordem para ver
        elif info is None or info.get("estado") == "lendo":
            T.text(s, "lendo a ordem do disco…", (px + 32, ly), 16,
                   T.TEXT_FAINT)
        elif info.get("estado") == "erro":
            T.text(s, info.get("msg", "não deu para ler as faixas"),
                   (px + 32, ly), 15, T.RED, maxw=pw - 64)
        elif pronto:
            self._draw_lados(s, pygame.Rect(px + 32, ly, pw - 64,
                                            max(40, y_acoes - ly - 8)), info)

        # as duas coisas que dá para fazer com um disco que não é seu
        y = y_acoes
        if item.get("lista"):
            # Uma playlist não é um disco, e as duas linhas que valem para
            # ela são outras: pôr na ordem dela, ou sorteada. Sem esta, o
            # [s] existia na tecla e não existia em lugar nenhum da tela.
            T.frase_com_teclas(s, "[p] põe a playlist — na ordem dela",
                               (px + 32, y), 16, T.GREEN)
            T.frase_com_teclas(s, "[s] põe SORTEADA — amostra de tudo, "
                                  "outra a cada vez",
                               (px + 32, y - 24), 16, T.AMBER)
        else:
            T.frase_com_teclas(s, "[p] põe o disco — sem ocupar disco",
                               (px + 32, y), 16, T.GREEN)
        if self.job and not self.job.done:
            T.text(s, "já tem um disco baixando", (px + 32, y + 26), 16, T.AMBER)
        elif item.get("hires"):
            T.frase_com_teclas(s, "[d] guarda na estante — hi-res, sem reamostrar",
                               (px + 32, y + 26), 16, T.TEXT_DIM)
        else:
            T.frase_com_teclas(s, "[d] guarda na estante",
                               (px + 32, y + 26), 16, T.TEXT_DIM)

        # ações
        y = py + ph - 40
        T.frase_com_teclas(s, "[i] copia a URL   ·   [esc] volta",
                           (px + 32, y), 15, T.TEXT_FAINT)

    def _colunas_de(self, info, larg):
        """(quantas colunas, quantas LINHAS a mais alta tem).

        Uma conta só, usada pela altura do cartão e pelo desenho: se as duas
        divergirem, o cartão fica alto demais ou corta a lista — e é sempre a
        segunda que se vê.
        """
        lados = info["lados"] or []
        n = max(1, len(lados))
        col_w = (larg - 22 * (n - 1)) // n
        if col_w < 210 and n > 1:
            n = 1
        if n == 1:
            linhas = sum(1 + len(ld.get("tracks", [])) for ld in lados)
        else:
            linhas = max((1 + len(ld.get("tracks", [])) for ld in lados),
                         default=1)
        return n, linhas

    def _draw_lados(self, s, caixa, info):
        """As faixas, em colunas — uma por LADO.

        Uma coluna por lado e não uma lista corrida: o que se quer saber
        olhando um disco que ainda não é seu é onde ele te faz levantar. Num
        LP são duas colunas, num duplo são quatro, e a quebra entre elas É a
        informação.
        """
        lados, faixas = info["lados"], info["faixas"]
        gap = 22
        # A MESMA conta que decidiu a altura do cartão (ver `_colunas_de`):
        # estreito demais para caber "01 Título 4:32" e a divisão por lado
        # vira ruído — melhor uma coluna só, com os lados anunciados no meio
        # da lista.
        n, _linhas = self._colunas_de(info, caixa.w)
        col_w = (caixa.w - gap * (n - 1)) // n
        passo = 21
        for c in range(n):
            cx = caixa.x + c * (col_w + gap)
            y = caixa.y
            grupos = ([lados[c]] if n > 1 else lados)
            for ld in grupos:
                if y + passo > caixa.bottom:
                    break
                rot = (ld.get("label") or "LADO").replace("SIDE", "LADO")
                dur = humano(max(0.0, ld["end"] - ld["start"]))
                T.text(s, rot, (cx, y), 15, T.AMBER, bold=True)
                T.text(s, dur, (cx + col_w, y), 14, T.TEXT_FAINT,
                       anchor="topright")
                y += 24
                for i in ld.get("tracks", []):
                    if i >= len(faixas):
                        continue
                    if y + passo > caixa.bottom:
                        T.text(s, "…", (cx, y), 15, T.TEXT_FAINT)
                        y += passo
                        break
                    f = faixas[i]
                    t_dur = relogio(f.get("duration") or 0)
                    larg_dur = T.largura(t_dur, 14) + 12
                    T.text(s, "%2d" % (i + 1), (cx, y + 1), 13, T.TEXT_FAINT)
                    T.text(s, f.get("title") or "?", (cx + 26, y), 15,
                           T.TEXT_DIM, maxw=col_w - 26 - larg_dur)
                    T.text(s, t_dur, (cx + col_w, y + 1), 14, T.TEXT_FAINT,
                           anchor="topright")
                    y += passo
                y += 8

    def draw(self, s, r):
        """O corpo primeiro, o formulário por cima — sempre.

        O desenho do formulário estava espalhado pelos vários `return` do
        corpo, e faltava justamente no que mais importa: a tela vazia, que é
        onde alguém que ainda não entrou está quando aperta [c]. Apertar a
        tecla não fazia nada visível. Com um invólucro não há saída do corpo
        por onde o formulário possa escapar.
        """
        self._corpo(s, r)
        if self.entrada:
            self.entrada.draw(s, r)

    def _corpo(self, s, r):
        pad, gap = 30, 14
        # 70 e não 58: o cabeçalho vai até 64 (o "12 que você marcou" começa
        # em 46 e tem 18 de altura), e a grade era recortada a partir de 58 —
        # seis pixels em que a legenda de um disco rolando para cima passava
        # por baixo do número. Reserva quem escreve, não quem desenha depois.
        head = 70
        self.COLS = max(3, min(8, r.w // 200))

        # ── header ──────────────────────────────────────────────────────────
        # O estado que importa é "dá para procurar e baixar", não "a interface
        # web está de pé": a web é opcional e é justamente o que não se quer
        # num sofá. Antes dizia "busca direta (interface off)" em cinza, o que
        # parecia defeito e era o modo NORMAL de usar.
        m = self._montagem
        pronto = bool(m and m["lib"] and m["cred"])
        T.text(s, "a loja", (r.x + pad, r.y + 18), 30, T.TEXT, bold=True)
        T.text(s, "pronto" if pronto else "ainda não ligada",
               (r.right - pad, r.y + 24), 15,
               T.GREEN if pronto else T.TEXT_FAINT, anchor="topright")

        if self.searching or self.query:
            T.text(s, "/ " + self.query + ("▌" if self.searching else ""),
                   (r.x + pad, r.y + 52), 24, T.AMBER)
            # E a busca também empurra a grade: ela é escrita em corpo 24 e
            # a primeira fileira começava por baixo dela.
            head = 92

        if self.loading:
            T.text(s, "buscando…", (r.centerx, r.centery), 22,
                   T.AMBER, anchor="center")
            return

        if self.error:
            # Em várias linhas: a mensagem que diz onde pôr as credenciais
            # do Spotify não cabe numa, e cortada não ensina nada.
            larg = min(760, r.w - 120)
            h = T.paragrafo(s, self.error, (r.centerx, r.centery - 40), 20,
                            T.RED, maxw=larg, anchor="center")
            T.text(s, "/ procura de novo", (r.centerx, r.centery - 40 + h + 14),
                   17, T.TEXT_FAINT, anchor="midtop")
            return

        if not self.results and self.query:
            T.text(s, f'nenhum disco com "{self.query}"',
                   (r.centerx, r.centery), 22, T.TEXT_DIM, anchor="center")
            T.text(s, "/ procura de novo",
                   (r.centerx, r.centery + 30), 17, T.TEXT_FAINT, anchor="center")
            return
        if not self.results and not self.query:
            if m and not pronto:
                T.passos(
                    s, r, "a loja ainda não está ligada",
                    "duas coisas, uma vez só — e depois qualquer disco do "
                    "catálogo toca aqui na hora, sem baixar",
                    [(m["lib"], "o qobuz-dl, que procura, toca e baixa",
                      None if m["lib"] else "stylus qobuz instalar"),
                     (m["cred"], "a sua conta do Qobuz",
                      None if m["cred"] else "[c] entra aqui mesmo")],
                    rodape="precisa de assinatura Qobuz. tocar não ocupa "
                           "disco nenhum; o que você guardar vira arquivo "
                           "seu, na sua pasta, e aparece na estante junto "
                           "com o resto.")
                return
            T.vazio(s, r, T.fantasma_busca, "a loja", [
                "[/] procura um disco",
                "[p] toca agora  ·  [d] guarda na estante",
                "[L] as suas playlists  ·  [s] põe uma sorteada",
                "[f] os seus favoritos",
            ])
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
            # Ver a estante: o alvo do rato pega a capa e a legenda.
            self.app.alvos.append(
                (pygame.Rect(cx, cy, cw, cw + 44).clip(clip), i))
            self._card(s, pygame.Rect(cx, cy, cw, cw), item, i == self.sel)
        # O mesmo aviso que a estante já tinha e a loja não: sem ele a fileira
        # cortada ao meio se lê como fileira com defeito, e o que sobrava aqui
        # era pior — a fileira seguinte entrava por um fio de um pixel, uma
        # tira de cor viva atravessando a linha de legendas.
        total_h = ((len(self.results) + self.COLS - 1) // self.COLS) * ch
        T.borda_rolagem(s, clip,
                        acima=self.scroll > 2,
                        abaixo=self.scroll + view_h < total_h - 2)
        s.set_clip(old)

        # Sob o estado, não em cima dele: os dois eram desenhados no mesmo
        # canto superior direito, um em y+20 e o outro em y+24, e "pronto"
        # saía escrito por dentro de "25 discos".
        T.text(s, (f"{len(self.results)} que você marcou" if self.favoritos
                   else plural(len(self.results), "disco")),
               (r.right - pad, r.y + 46), 15, T.TEXT_FAINT, anchor="topright")

        if self.results:
            item = self.results[self.sel]
            self.app.hint(
                s, r, "[/] procura  [enter] examina  [p] toca  "
                      + ("[s] sorteada  " if item.get("lista") else "")
                      + "[d] baixa  [L] playlists  [f] favoritos  [c] conta",
                contexto=f"{item.get('display_subtitle', '')} — "
                         f"{item.get('display_title', '')}")

        if self.job:
            self.app.job_panel(s, pygame.Rect(r.right - 380, r.y + head + 8,
                                              360, 160), self.job)

        if self.examing:
            self._draw_examing(s, r)


# ═══════════════════════════════════════════════════════════════════════════
# SPOTIFY — procurar e tocar
# ═══════════════════════════════════════════════════════════════════════════
class SpotifyScreen(Screen):
    name = "SPOTIFY"
    icon = "󰓇"
    COLS = 5

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
        self.job = None
        self._daemon_ok = None
        self._daemon = None          # ausente | parado | ok
        self.entrada = None          # o formulário de credenciais
        self._now_playing = None
        self._np_t = 0.0
        self._setup = None

    def enter(self):
        self._check_daemon_threaded()
        self._refresh_now_playing()

    def _entrar(self):
        """As credenciais do app, aqui mesmo. Ver a classe Formulario.

        Antes a tela mostrava o CAMINHO de um arquivo e mais nada — quem
        estava no sofá com um controle não tinha como escrever nele. E
        credencial errada não dizia nada: a busca só não achava disco
        nenhum, para sempre.
        """
        def _pronto(deu, _dado):
            if deu:
                self.app.toast("credenciais do Spotify guardadas")
                self.entrada = None
                self._check_daemon_threaded()
        self.entrada = Formulario(
            "as credenciais do Spotify",
            [("client_id", "de developer.spotify.com", False),
             ("client_secret", "", True)],
            ["stylus-spotify", "entrar", "--json"],
            ao_terminar=_pronto,
            rodape="criar um app em developer.spotify.com é de graça")

    def _check_daemon_threaded(self):
        def _probe():
            # Três estados, não dois. "Não está tocando" e "não está
            # instalado" pediam coisas diferentes, e a tela dizia a mesma para
            # os dois: `systemctl --user enable --now spotifyd`. Numa máquina
            # sem o spotifyd — que não está nos repositórios do Arch, está no
            # AUR — esse comando falha com "Unit not found", e quem fez
            # exatamente o que a tela mandou fica sem saída nenhuma.
            self._daemon = "ausente"
            try:
                r = subprocess.run(["stylus-spotify", "daemon"],
                                   capture_output=True, text=True, timeout=6)
                saida = (r.stdout or "").strip()
                if saida in ("ok", "parado", "ausente"):
                    self._daemon = saida
            except Exception:             # noqa: BLE001
                pass
            self._daemon_ok = self._daemon == "ok"
            self._setup = self._ler_montagem()
        threading.Thread(target=_probe, daemon=True).start()

    def _ler_montagem(self):
        """Quais dos três passos do Spotify já estão de pé.

        São três e são independentes: o spotifyd (que toca), o spotipy (que
        procura) e as credenciais (que autorizam procurar). Faltando qualquer
        um a seção não funciona, e antes disto a tela dizia só "spotifyd não
        encontrado" — que é, dos três, o que menos costuma ser o problema.
        """
        conf = os.path.expanduser("~/.config/stylus/spotify.conf")
        cred = False
        if os.path.exists(conf):
            try:
                import configparser
                cp = configparser.ConfigParser()
                cp.read(conf, encoding="utf-8")
                sec = cp["spotify"] if cp.has_section("spotify") else cp["DEFAULT"]
                cred = bool(sec.get("client_id", "").strip()
                            and sec.get("client_secret", "").strip())
            except Exception:             # noqa: BLE001
                cred = False
        venv = os.path.expanduser("~/.local/share/stylus/venv/bin/python3")
        lib = False
        for py in (venv, "python3"):
            try:
                lib = subprocess.run([py, "-c", "import spotipy"],
                                     capture_output=True, timeout=6).returncode == 0
                if lib:
                    break
            except Exception:             # noqa: BLE001
                pass
        return {"daemon": bool(self._daemon_ok), "spotipy": lib, "cred": cred}

    def _refresh_now_playing(self):
        def _get():
            try:
                r = subprocess.run(
                    ["playerctl", "-p", "spotifyd", "metadata",
                     "--format", "{{title}}\n{{artist}}\n{{album}}\n{{duration(m)}}\n{{position(m)}}"],
                    capture_output=True, text=True, timeout=3)
                if r.returncode == 0 and r.stdout.strip():
                    lines = r.stdout.strip().split("\n")
                    if len(lines) >= 2:
                        self._now_playing = {
                            "title": lines[0],
                            "artist": lines[1],
                            "album": lines[2] if len(lines) > 2 else "",
                            "duration": lines[3] if len(lines) > 3 else "?",
                            "position": lines[4] if len(lines) > 4 else "0",
                        }
                        return
                self._now_playing = None
            except Exception:
                self._now_playing = None
        self._np_t = time.time()
        threading.Thread(target=_get, daemon=True).start()

    def _search(self):
        if not self.query.strip():
            return
        self.searching = False
        self.loading = True
        self.error = None

        def _do():
            try:
                r = subprocess.run(
                    ["stylus-spotify", "search", self.query.strip()],
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
                self.results = data.get("tracks", [])
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

    def _play(self, item):
        uri = item.get("uri", "")
        if not uri:
            self.app.toast("sem URI para tocar")
            return
        try:
            subprocess.run(["playerctl", "-p", "spotifyd", "open", uri],
                           timeout=5)
            self.app.toast(f"tocando: {item.get('name', '?')}")
            self._refresh_now_playing()
        except Exception as e:
            self.app.toast(f"erro: {e}", kind="erro")

    def _toggle_play(self):
        try:
            subprocess.run(["playerctl", "-p", "spotifyd", "play-pause"],
                           timeout=3)
            self._refresh_now_playing()
        except Exception:
            pass

    def _next(self):
        try:
            subprocess.run(["playerctl", "-p", "spotifyd", "next"], timeout=3)
            time.sleep(0.3)
            self._refresh_now_playing()
        except Exception:
            pass

    def _prev(self):
        try:
            subprocess.run(["playerctl", "-p", "spotifyd", "previous"],
                           timeout=3)
            time.sleep(0.3)
            self._refresh_now_playing()
        except Exception:
            pass

    def key(self, ev):
        # O formulário primeiro: enquanto ele está aberto, ele é a tela.
        if self.entrada:
            if ev.key == pygame.K_ESCAPE:
                self.entrada = None
                return True
            return self.entrada.key(ev)

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

        n = len(self.results)
        if ev.key == pygame.K_c:
            self._entrar()
        elif ev.key == pygame.K_SLASH:
            self.searching, self.query = True, ""
        # Numa GRADE, para baixo é uma FILEIRA e para o lado é um disco. Estava
        # trocado: ↓ andava um disco para a direita e → pulava cinco. Com o
        # cursor no meio da grade, apertar → mandava o foco para a linha de
        # baixo e apertar ↓ para o vizinho da direita — o olho segue a seta e
        # a seleção vai para outro lugar, que é a definição de controle
        # quebrado. E o par vim é h/l para o lado, j/k para cima e para baixo.
        elif ev.key in (pygame.K_RIGHT, pygame.K_l):
            if n:
                self.sel = min(n - 1, self.sel + 1)
        elif ev.key in (pygame.K_LEFT, pygame.K_h):
            if n:
                self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            if n:
                # Da última fileira, ↓ vai para o fim: uma grade que tem 23
                # discos e 5 colunas deixava os três últimos inalcançáveis
                # pela seta, porque sel+5 passava de n-1 e o min() prendia.
                self.sel = min(n - 1, self.sel + self.COLS)
        elif ev.key in (pygame.K_UP, pygame.K_k):
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
                self._play(self.results[self.sel])
        elif ev.key == pygame.K_SPACE:
            self._toggle_play()
        elif ev.key == pygame.K_n:
            self._next()
        elif ev.key == pygame.K_p:
            self._prev()
        elif ev.key == pygame.K_r:
            self._check_daemon_threaded()
            self._refresh_now_playing()
            if self.query:
                self._search()
        else:
            return False
        return True

    def _draw_track(self, s, rect, item, sel):
        if sel:
            T.panel(s, rect, T.INK_LIFT, radius=10, border=T.LINE)
        else:
            T.panel(s, rect, T.INK_SOFT, radius=10, border=T.LINE)

        T.text(s, "󰓇", (rect.centerx, rect.centery - 4), 38,
               T.AMBER if sel else T.TEXT_FAINT, anchor="center")

        ty = rect.bottom + 8
        name = item.get("name", "?")
        artist = item.get("artist", "?")
        album = item.get("album", "")
        duration = item.get("duration", "")

        T.text(s, name, (rect.x, ty), 15,
               T.TEXT if sel else T.TEXT_DIM, maxw=rect.w)
        T.text(s, artist, (rect.x, ty + 20), 13, T.TEXT_FAINT, maxw=rect.w)
        # A duração é MEDIDA e descontada do nome do disco. Os dois eram
        # desenhados na mesma linha, o disco com a largura inteira do quadro
        # e a duração encostada à direita por cima dele — e como a grade
        # nunca era medida com disco dentro (sem rede, `results` fica vazia),
        # ninguém tinha visto. Ver a lição da folga fixa no CLAUDE.md §4.
        larg_dur = (T.largura(duration, 12) + 10) if duration else 0
        if album:
            T.text(s, album, (rect.x, ty + 36), 12, T.TEXT_FAINT,
                   maxw=max(24, rect.w - larg_dur))
        if duration:
            T.text(s, duration, (rect.right - 4, ty + 36), 12,
                   T.TEXT_FAINT, anchor="topright")

    def draw(self, s, r):
        """O corpo primeiro, o formulário por cima — sempre.

        O desenho do formulário estava espalhado pelos vários `return` do
        corpo, e faltava justamente no que mais importa: a tela vazia, que é
        onde alguém que ainda não entrou está quando aperta [c]. Apertar a
        tecla não fazia nada visível. Com um invólucro não há saída do corpo
        por onde o formulário possa escapar.
        """
        self._corpo(s, r)
        if self.entrada:
            self.entrada.draw(s, r)

    def _corpo(self, s, r):
        pad, gap = 30, 14
        # 70 e não 58, pelo mesmo motivo da loja do Qobuz: a contagem no
        # canto começa em 46 e tem 18 de altura, e a grade era recortada a
        # partir de 58 — a legenda de uma faixa rolando para cima passava por
        # baixo do número.
        head = 70
        self.COLS = max(3, min(8, r.w // 200))

        status = {"ok": "pronto", "parado": "spotifyd instalado, parado",
                  "ausente": "sem o spotifyd"}.get(self._daemon,
                                                   "olhando…")
        T.text(s, "spotify", (r.x + pad, r.y + 18), 30, T.TEXT, bold=True)
        T.text(s, status, (r.right - pad, r.y + 24), 15,
               T.GREEN if self._daemon_ok else T.TEXT_FAINT, anchor="topright")

        # now playing bar
        if time.time() - self._np_t > 5.0:
            self._refresh_now_playing()
        np = self._now_playing
        if np:
            np_rect = pygame.Rect(r.x + pad, r.y + 50, r.w - pad * 2, 52)
            T.panel(s, np_rect, T.INK_LIFT, radius=10, border=T.LINE)
            T.text(s, "󰓇", (np_rect.x + 14, np_rect.y + 14), 24, T.AMBER)
            pos = np.get('position', '0')
            dur = np.get('duration', '?')
            relogio = f"{pos}/{dur}"
            # O relógio fica à direita na MESMA faixa de linhas do nome e do
            # disco: os três precisam dividir a largura por medida, não pelo
            # `- 60` fixo que valia para os dois da esquerda como se o
            # terceiro não existisse.
            larg_rel = T.largura(relogio, 13) + 24
            T.text(s, f"{np['artist']} — {np['title']}",
                   (np_rect.x + 46, np_rect.y + 10), 17, T.TEXT,
                   maxw=max(40, np_rect.w - 60 - larg_rel))
            T.text(s, np['album'], (np_rect.x + 46, np_rect.y + 32), 13,
                   T.TEXT_FAINT, maxw=max(40, np_rect.w - 60 - larg_rel))
            T.text(s, relogio, (np_rect.right - 14, np_rect.y + 18),
                   13, T.TEXT_FAINT, anchor="topright")
            head = 116

        if self.searching or self.query:
            T.text(s, "/ " + self.query + ("▌" if self.searching else ""),
                   (r.x + pad, r.y + head + 4), 24, T.AMBER)
            head += 38          # a grade começa DEPOIS da linha de busca

        if self.loading:
            T.text(s, "buscando…", (r.centerx, r.centery), 22,
                   T.AMBER, anchor="center")
            return

        if self.error:
            # Em várias linhas: a mensagem que diz onde pôr as credenciais
            # do Spotify não cabe numa, e cortada não ensina nada.
            larg = min(760, r.w - 120)
            h = T.paragrafo(s, self.error, (r.centerx, r.centery - 40), 20,
                            T.RED, maxw=larg, anchor="center")
            T.text(s, "/ procura de novo", (r.centerx, r.centery - 40 + h + 14),
                   17, T.TEXT_FAINT, anchor="midtop")
            return

        if not self.results and self.query:
            T.text(s, f'nenhuma faixa com "{self.query}"',
                   (r.centerx, r.centery), 22, T.TEXT_DIM, anchor="center")
            T.text(s, "/ procura de novo",
                   (r.centerx, r.centery + 30), 17, T.TEXT_FAINT, anchor="center")
            return
        if not self.results and not self.query:
            m = self._setup
            if m and not (m["daemon"] and m["spotipy"] and m["cred"]):
                T.passos(
                    s, r, "o Spotify ainda não está ligado",
                    "três coisas, uma vez só — depois é só procurar e tocar",
                    [(m["spotipy"], "a biblioteca que procura (spotipy)",
                      None if m["spotipy"] else "stylus spotify instalar"),
                     (m["cred"], "as credenciais da sua conta de programador",
                      None if m["cred"] else "[c] entra aqui mesmo"),
                     (m["daemon"], "o spotifyd, que é quem toca",
                      None if m["daemon"] else
                      ("systemctl --user enable --now spotifyd"
                       if self._daemon == "parado"
                       else "stylus spotify instalar --daemon"))],
                    rodape="as credenciais saem de developer.spotify.com — "
                           "criar um app ali é de graça. e tocar exige conta "
                           "Premium — o Spotify não deixa um programa de fora "
                           "tocar sem ela. o Qobuz, aqui do lado, não pede "
                           "nada disso.")
                return
            T.vazio(s, r, T.fantasma_busca, "a loja de streaming", [
                "[/] procura uma faixa",
                "[space] pausa   ·   [n] e [p] pulam",
            ])
            return

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
            # Ver a estante: o alvo do rato pega a capa e a legenda.
            self.app.alvos.append(
                (pygame.Rect(cx, cy, cw, cw + 44).clip(clip), i))
            self._draw_track(s, pygame.Rect(cx, cy, cw, cw), item, i == self.sel)

        # O mesmo aviso que a estante tem: sem ele a fileira cortada ao meio
        # se lê como fileira com defeito, e a seguinte entra por um fio de um
        # pixel atravessando a linha de legendas.
        total_h = ((len(self.results) + self.COLS - 1) // self.COLS) * ch
        T.borda_rolagem(s, clip,
                        acima=self.scroll > 2,
                        abaixo=self.scroll + view_h < total_h - 2)
        s.set_clip(old)

        # Sob o estado, não em cima dele: os dois eram desenhados no mesmo
        # canto superior direito, um em y+20 e o outro em y+24.
        T.text(s, plural(len(self.results), "faixa"), (r.right - pad, r.y + 46), 15,
               T.TEXT_FAINT, anchor="topright")

        if self.results:
            item = self.results[self.sel]
            self.app.hint(
                s, r, "[/] procura   [enter] toca   [space] pausa   "
                      "[r] atualiza   [c] conta",
                contexto=f"{item.get('artist', '')} — {item.get('name', '')}")

        if self.job:
            self.app.job_panel(s, pygame.Rect(r.right - 380, r.y + head + 8,
                                              360, 160), self.job)



# ═══════════════════════════════════════════════════════════════════════════
# JOGOS
# ═══════════════════════════════════════════════════════════════════════════
class GamesScreen(Screen):
    name = "JOGOS"
    icon = "󰊴"

    # (nome, comando, binário, ícone, controle, de-onde-vem)
    #
    # O último campo é o que fazer quando o jogo NÃO está instalado. Nove dos
    # onze quadros desta tela dizem "não encontrado" numa máquina nova, e
    # apertar ENTER em cima de qualquer um deles só devolvia um aviso
    # dizendo, de novo, "não encontrado" — a tela repetindo o que já estava
    # escrito no quadro, e nenhum caminho a partir dali.
    #
    # Onde há receita, ENTER instala. Onde não há, ele ao menos DIZ de onde
    # aquilo vem, que é a informação que faltava.
    ACOES = [
        ("Clone Hero", ["clonehero"], "clonehero", "󰝰", "controller",
         ["stylus-term", "Clone Hero", "stylus", "app", "clonehero"]),
        ("Keyboard Warriors", [os.path.expanduser(
            "~/Documentos/coiso/keyboardwarrior/keyboardwarrior")],
            "keyboardwarrior", "󰌑", "keyboard", None),
        ("StepMania", ["stepmania"], "stepmania", "󰝰", "keyboard",
         "vem do AUR:  yay -S stepmania"),
        ("Etterna", ["etterna"], "etterna", "󰝰", "keyboard",
         "vem do AUR:  yay -S etterna"),
        ("YARG", ["yarg"], "yarg", "󰝰", "controller",
         "baixe do site do YARG e ponha em /opt"),
        ("osu!", ["osu"], "osu", "󰝰", "mouse",
         "vem do AUR:  yay -S osu-lazer-bin"),
        ("Audica", ["audica"], "audica", "󰝰", "controller",
         "é um jogo de VR, comprado na Steam"),
        ("Steam", ["steam", "-bigpicture"], "steam", "󰓓", "controller",
         ["stylus-term", "Steam", "sudo", "pacman", "-S", "--needed", "steam"]),
        ("Lutris", ["lutris"], "lutris", "󰓓", "controller",
         ["stylus-term", "Lutris", "sudo", "pacman", "-S", "--needed", "lutris"]),
        ("Heroic", ["heroic"], "heroic", "󰓓", "controller",
         ["stylus-term", "Heroic", "stylus", "app", "heroic"]),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.sub = "menu"  # menu | buscar | baixadas | stats
        self.query = ""
        self.query_active = False
        self.results = []
        self.downloaded = []
        self.downloaded_ids = set()
        self.job = None
        self.page = 1
        self.total_pages = 1
        self._installed_cache = {}
        self._load_downloaded()

    def _load_downloaded(self):
        db_path = os.path.expanduser("~/.local/share/stylus/charts.json")
        try:
            with open(db_path) as f:
                db = json.load(f)
            self.downloaded = list(db.get("downloaded", {}).values())
            self.downloaded_ids = set(db.get("downloaded", {}).keys())
        except (FileNotFoundError, json.JSONDecodeError):
            self.downloaded = []
            self.downloaded_ids = set()

    def _do_search(self, page=1):
        import http.client as _http
        import ssl as _ssl
        try:
            ctx = _ssl.create_default_context()
            conn = _http.HTTPSConnection("api.enchor.us", timeout=30, context=ctx)
            data = json.dumps({"search": self.query, "page": page}).encode()
            conn.request("POST", "/search", body=data, headers={
                "Content-Type": "application/json", "User-Agent": "stylus-ch/1.0"})
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
            if resp.status in (200, 201):
                result = json.loads(raw, strict=False)
                self.results = result.get("data", [])[:30]
                total = result.get("totalPages", 1) or 1
                self.total_pages = total
                self.page = page
            else:
                self.app.toast(f"erro {resp.status} na busca", kind="erro")
        except Exception as e:
            self.app.toast(f"falha na busca: {type(e).__name__}", kind="erro")
            self.results = []

    def _delete_chart(self, chart):
        db_path = os.path.expanduser("~/.local/share/stylus/charts.json")
        cid = str(chart.get("chartId", ""))
        try:
            with open(db_path) as f:
                db = json.load(f)
            if cid in db.get("downloaded", {}):
                del db["downloaded"][cid]
                with open(db_path, "w") as f:
                    json.dump(db, f)
            self._load_downloaded()
            self.app.toast("chart removido", kind="ok")
        except Exception as e:
            self.app.toast(f"erro ao remover: {e}", kind="erro")

    def _is_installed(self, binary):
        if binary not in self._installed_cache:
            import shutil as _sh
            self._installed_cache[binary] = bool(_sh.which(binary))
        return self._installed_cache[binary]

    def key(self, ev):
        if self.sub == "buscar":
            return self._key_buscar(ev)
        elif self.sub == "baixadas":
            return self._key_baixadas(ev)
        elif self.sub == "stats":
            return self._key_stats(ev)
        return self._key_menu(ev)

    def _key_menu(self, ev):
        n_games = len(self.ACOES)
        n_ch = 4  # buscar, baixadas, sync, stats
        total = n_games + n_ch
        if ev.key in (pygame.K_RIGHT, pygame.K_l, pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % total
        elif ev.key in (pygame.K_LEFT, pygame.K_h, pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % total
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.sel < n_games:
                nome, cmd, binario, _icon, _kind, de_onde = self.ACOES[self.sel]
                if self._is_installed(binario) or os.path.isfile(cmd[0]):
                    self.app.toast(f"abrindo {nome}…")
                    spawn(cmd)
                elif isinstance(de_onde, list):
                    # Num terminal, e não num Job: instalar pede senha de sudo
                    # e leva minutos falando. Num painel de trinta linhas sem
                    # entrada de teclado, isso fica pendurado para sempre.
                    self.app.toast(f"instalando {nome} — veja o terminal",
                                   secs=6.0)
                    spawn(de_onde)
                elif de_onde:
                    self.app.toast(f"{nome}: {de_onde}", secs=8.0)
                else:
                    self.app.toast(f"{nome} não está instalado")
            elif self.sel == n_games:  # buscar
                self.sub = "buscar"
                self.query_active = True
                self.query = ""
                self.page = 1
            elif self.sel == n_games + 1:  # baixadas
                self._load_downloaded()
                self.sub = "baixadas"
                self.sel = 0
            elif self.sel == n_games + 2:  # sync
                self.app.toast("sincronizando pro celular…")
                self.job = Job(["stylus-ch", "sync"], "sync clone hero")
            else:  # stats
                self.sub = "stats"
                self.sel = 0
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
                    self._do_search(1)
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
                    self.app.toast(
                        f"baixando {chart['artist']} — {chart['name']}…")
                    self.job = Job(["stylus-ch", "baixar", cid],
                                   chart["name"])
                    self.downloaded_ids.add(cid)
                else:
                    self.app.toast("já baixado", kind="ok")
            elif ev.key == pygame.K_f:
                self.query_active = True
            elif ev.key == pygame.K_RIGHT and self.page < self.total_pages:
                self._do_search(self.page + 1)
                self.sel = 0
            elif ev.key == pygame.K_LEFT and self.page > 1:
                self._do_search(self.page - 1)
                self.sel = 0
            elif ev.key == pygame.K_d and self.results:
                chart = self.results[self.sel]
                self._delete_chart(chart)
        return True

    def _key_baixadas(self, ev):
        if ev.key == pygame.K_ESCAPE:
            self.sub = "menu"
            return True
        elif ev.key in (pygame.K_DOWN, pygame.K_j):
            self.sel = (self.sel + 1) % max(1, len(self.downloaded) * 2)
        elif ev.key in (pygame.K_UP, pygame.K_k):
            self.sel = (self.sel - 1) % max(1, len(self.downloaded) * 2)
        elif ev.key == pygame.K_d and self.downloaded:
            # sel alternates between artist headers and songs
            by_artist = {}
            for info in self.downloaded:
                by_artist.setdefault(info.get("artist", "?"), []).append(info)
            flat = []
            for artist in sorted(by_artist):
                flat.append(("artist", artist, None))
                for info in by_artist[artist]:
                    flat.append(("song", info.get("name", "?"), info))
            if self.sel < len(flat) and flat[self.sel][0] == "song":
                self._delete_chart(flat[self.sel][2])
        return True

    def _key_stats(self, ev):
        if ev.key == pygame.K_ESCAPE:
            self.sub = "menu"
            return True
        return True

    def draw(self, s, r):
        x, y = r.x + 44, r.y + 40
        T.text(s, "jogos", (x, y), 30, T.TEXT, bold=True)
        T.text(s, "porque nem tudo é disco", (x, y + 40), 18, T.TEXT_FAINT)

        if self.sub == "buscar":
            self._draw_buscar(s, r)
        elif self.sub == "baixadas":
            self._draw_baixadas(s, r)
        elif self.sub == "stats":
            self._draw_stats(s, r)
        else:
            self._draw_menu(s, r)

        # A saída só aparece quando existe. Um painel de 300x80 escrito "a
        # saída aparece aqui" pendurado no canto de baixo à direita não é
        # informação: é uma caixa vazia num canto, e ela ficava lá o tempo
        # todo. Quando há o que mostrar, ela é grande o bastante para caber
        # linha de terminal — que é o que o `stylus-ch` e o `yay` cospem.
        if self.job is not None:
            self.app.job_panel(s, pygame.Rect(r.right - 560, r.bottom - 230,
                                              516, 170), self.job)

    def _draw_menu(self, s, r):
        # O título ocupa até ~r.y+98 (30px de "jogos" + o subtítulo em y+40).
        # Começar a grade em 96 punha a primeira fileira em cima da frase.
        x, y = r.x + 44, r.y + 132
        n_games = len(self.ACOES)
        # A grade tem quatro colunas, e a LARGURA DELAS vem da tela.
        #
        # **Sintoma:** numa tela de 1024 px (máquina virtual, monitor velho,
        # televisão de 720p ligada por VGA) a quarta coluna era desenhada
        # FORA da tela: quatro quadros de 220 com 20 de folga somam 940 px, e
        # o corpo ali tem 794. Três jogos e o quadro de "estatísticas" ficavam
        # invisíveis — e como a seta continua andando por eles, a seleção
        # sumia no nada. A fileira de baixo já se ajustava (o `cw2` logo
        # adiante); metade desta tela era elástica e a outra metade não.
        # E quantas colunas vem da tela também. Eram QUATRO fixas com teto de
        # 220 px cada: numa tela de 1920 a grade somava 940 px num corpo de
        # 1645 e sobravam setecentos pixels de nada à direita, com dois dos
        # rótulos ("Keyboard Wa…", "sincronizar pro ce…") cortados dentro de
        # quadros estreitos enquanto o espaço para eles estava vazio ao lado.
        gap = 20
        # O que sobra de ALTURA para a grade e a fileira de ações. Sem esta
        # conta a grade era desenhada com passo fixo de 120 px: dez jogos em
        # três colunas são quatro fileiras, e numa tela de 1024x600 — que é
        # painel de carro, mini-PC e monitor velho — as ações caíam 60 px
        # abaixo da borda de baixo. Não estoura; some.
        livre = max(140, r.bottom - 40 - y)
        cols = max(3, min(6, (r.w - 88) // 250))
        cols = min(cols, n_games)
        # Numa tela BAIXA, mais colunas é o que faz caber: elas custam largura,
        # que é o que sobra, e economizam fileira, que é o que falta.
        # ...mas só até onde a LARGURA deixa: um quadro abaixo de 120 px não
        # cabe o nome, e o `max(120, …)` do `cw` logo abaixo não encolhe o
        # quadro — ele empurra a grade para fora da tela pela direita, que é
        # trocar um vazamento por outro.
        cols_max = max(3, min(6, (r.w - 88 + gap) // (120 + gap)))
        while (cols < min(cols_max, n_games)
               and ((n_games + cols - 1) // cols) * 120 + 80 > livre):
            cols += 1
        cw = max(120, (r.w - 88 - gap * (cols - 1)) // cols)
        linhas = (n_games + cols - 1) // cols
        # E se ainda não couber, o passo encolhe. Com piso: abaixo de 70 px
        # o quadro deixa de caber o nome e o "[enter] instala" embaixo dele.
        passo = min(120, max(70, (livre - 80) // max(1, linhas)))
        alt_card = max(52, passo - 20)
        for i, (nome, _cmd, binario, icon, kind, de_onde) in enumerate(self.ACOES):
            col = i % cols
            row = i // cols
            bx = pygame.Rect(x + col * (cw + gap), y + row * passo, cw, alt_card)
            self.app.alvos.append((bx.copy(), i))
            sel = i == self.sel
            tem = self._is_installed(binario)
            T.panel(s, bx, T.INK_LIFT if sel else T.INK_SOFT, radius=14,
                    border=T.AMBER if sel else T.LINE)
            # Quem cede é o TAMANHO DA LETRA, não o nome: "Keyboard Warri…"
            # não diz que jogo é. Mesma regra do `lista_com_saida`.
            rot = f"{icon}  {nome}"
            fs = 22
            while fs > 15 and T.largura(rot, fs) > bx.w - 24:
                fs -= 1
            T.text(s, rot, bx.center, fs,
                   T.TEXT if tem else T.TEXT_FAINT, bold=sel, anchor="center",
                   maxw=bx.w - 24)
            # kind badge
            kind_icons = {"keyboard": "󰌌", "mouse": "󰍽", "controller": "󰣌"}
            kind_colors = {"keyboard": T.BLUE, "mouse": T.LAV, "controller": T.AMBER}
            ki = kind_icons.get(kind, "")
            kc = kind_colors.get(kind, T.TEXT_DIM)
            if ki:
                T.text(s, ki, (bx.right - 14, bx.y + 10), 16, kc,
                       anchor="topright")
            if not tem:
                # "não encontrado" é o que a máquina sabe; não é o que a
                # pessoa precisa. Onde há receita, o quadro vira um convite.
                if isinstance(de_onde, list):
                    T.frase_com_teclas(s, "[enter] instala",
                                       (bx.centerx, bx.centery + 30), 15,
                                       T.AMBER, anchor="center")
                else:
                    T.text(s, "não instalado", (bx.centerx, bx.centery + 28),
                           15, T.TEXT_FAINT, anchor="center", maxw=bx.w - 24)

        # CH songs row
        # Divisão para CIMA (no `linhas`, lá em cima): com `n_games // cols + 1`
        # um número de jogos múltiplo de quatro (doze, um dia) abriria uma
        # fileira inteira de vazio entre a grade e esta linha, e empurraria a
        # linha para fora da tela de 768.
        y2 = y + linhas * passo + 10
        alt_acao = max(40, min(60, r.bottom - 40 - y2))
        ch_actions = [
            ("buscar músicas", "󰍉", "buscar"),
            (f"baixadas ({len(self.downloaded)})", "󰀙", "baixadas"),
            ("sincronizar pro celular", "󰢶", "sync"),
            ("estatísticas", "󰎛", "stats"),
        ]
        # A fileira de baixo acompanha a LARGURA da grade, não a largura de
        # um quadro dela: com `min(cw, …)` as quatro ações paravam no meio da
        # tela enquanto a grade acima ia até a borda, e duas coisas alinhadas
        # pela esquerda com fins diferentes leem como erro de layout.
        cw2 = (r.w - 88 - gap * 3) // 4
        for i, (label, icon, _sub) in enumerate(ch_actions):
            bx = pygame.Rect(x + i * (cw2 + gap), y2, cw2, alt_acao)
            sel = i + n_games == self.sel
            T.panel(s, bx, T.INK_LIFT if sel else T.INK_SOFT, radius=10,
                    border=T.AMBER if sel else T.LINE)
            T.text(s, f"{icon}  {label}", bx.center, 18,
                   T.TEXT if sel else T.TEXT_FAINT, bold=sel, anchor="center",
                   maxw=bx.w - 20)

        self.app.hint(s, r, "[enter] abre — ou instala, quando falta"
                            "   ·   [←][→] navega")

    def _draw_buscar(self, s, r):
        x, y = r.x + 44, r.y + 90

        # Search bar
        bar_w = min(600, r.w - 88)
        bar = pygame.Rect(x, y, bar_w, 44)
        border = T.AMBER if self.query_active else T.LINE
        T.panel(s, bar, T.INK_LIFT, radius=10, border=border)
        placeholder = ("digite o nome da música…" if not self.query
                       else self.query)
        T.text(s, f"󰍉  {placeholder}", (bar.x + 14, bar.y + 11), 20,
               T.TEXT if self.query else T.TEXT_FAINT)
        if self.query_active:
            cw = T.font(20).size(self.query)[0]
            pygame.draw.line(s, T.AMBER, (bar.x + 14 + cw + 2, bar.y + 10),
                             (bar.x + 14 + cw + 2, bar.y + 32), 2)

        # Page indicator
        if self.total_pages > 1:
            T.text(s, f"página {self.page}/{self.total_pages}",
                   (x + bar_w + 20, y + 12), 16, T.TEXT_FAINT)

        # Results
        y += 64
        if self.results:
            for i, c in enumerate(self.results[:20]):
                sel = i == self.sel and not self.query_active
                cid = str(c["chartId"])
                downloaded = cid in self.downloaded_ids
                name = c.get("name", "?")
                artist = c.get("artist", "?")
                charter = c.get("charter", "?")
                bg = T.INK_LIFT if sel else None
                if bg:
                    T.panel(s, pygame.Rect(x - 8, y - 2, bar_w + 80, 28),
                            bg, radius=6)
                if downloaded:
                    T.text(s, "✓", (x, y), 18, T.GREEN)
                ox = 22 if downloaded else 0
                T.text(s, artist, (x + ox, y), 18,
                       T.AMBER if sel else T.PINK)
                aw = T.font(18).size(artist + "  ")[0]
                T.text(s, f"— {name}", (x + ox + aw, y), 18,
                       T.TEXT if sel else T.TEXT_FAINT)
                # difficulty badges
                dx = x + ox + aw + T.font(18).size(f"— {name}  ")[0] + 10
                for diff_key, diff_label in [("diff_guitar", "🎸"),
                                              ("diff_bass", "🎸"),
                                              ("diff_drums", "🥁"),
                                              ("diff_vocals", "🎤")]:
                    val = c.get(diff_key)
                    if val is not None and val > 0:
                        color = (T.GREEN if val <= 3
                                 else T.AMBER if val <= 6
                                 else T.RED)
                        T.text(s, f"{diff_label}{val}", (dx, y + 2),
                               14, color)
                        dx += T.font(14).size(f"{diff_label}{val}")[0] + 6
                # charter on right
                T.text(s, charter, (r.right - 60, y), 14, T.TEXT_DIM,
                       anchor="topright")
                y += 30
        elif self.query and not self.query_active:
            T.text(s, "nenhum resultado", (x, y), 18, T.TEXT_FAINT)

        hint = "enter: baixar · f: buscar · d: remover · ←→: página · esc: voltar"
        T.text(s, hint, (x, r.bottom - 40), 16, T.TEXT_FAINT)

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
        for artist in sorted(by_artist):
            flat.append(("artist", artist, None))
            for info in by_artist[artist]:
                flat.append(("song", info.get("name", "?"), info))

        view_h = r.h - 180
        vis = max(3, view_h // 28)
        self.sel = max(0, min(self.sel, len(flat) - 1))
        ini = max(0, min(self.sel - vis // 2, len(flat) - vis))

        for i in range(ini, min(len(flat), ini + vis)):
            kind, name, info = flat[i]
            sel = i == self.sel
            if sel:
                T.panel(s, pygame.Rect(x - 8, y - 2, r.w - 88, 26),
                        T.INK_LIFT, radius=6)
            if kind == "artist":
                count = len(by_artist[name])
                T.text(s, f"{name}  ({count})", (x + 8, y), 18, T.PINK,
                       bold=True)
            else:
                T.text(s, f"  — {name}", (x + 8, y), 17,
                       T.TEXT if sel else T.TEXT_FAINT)
                # show chartId for delete reference
                cid = str(info.get("chartId", ""))
                if sel:
                    T.text(s, "d: remover", (r.right - 60, y + 2), 14,
                           T.RED, anchor="topright")
            y += 28

        T.text(s, "d: remover · esc: voltar", (x, r.bottom - 40), 16,
               T.TEXT_FAINT)

    def _draw_stats(self, s, r):
        x, y = r.x + 44, r.y + 90
        T.text(s, "estatísticas", (x, y), 24, T.TEXT, bold=True)
        y += 50

        total = len(self.downloaded)
        T.text(s, f"total de charts: {total}", (x, y), 20, T.TEXT)
        y += 36

        # by artist
        by_artist = {}
        for info in self.downloaded:
            artist = info.get("artist", "Unknown")
            by_artist.setdefault(artist, []).append(info)
        artists_sorted = sorted(by_artist.items(), key=lambda x: -len(x[1]))

        T.text(s, "por artista:", (x, y), 18, T.TEXT_FAINT)
        y += 30
        for artist, songs in artists_sorted[:15]:
            bar_w = int((len(songs) / max(1, total)) * 400)
            T.panel(s, pygame.Rect(x + 200, y, max(bar_w, 4), 18),
                    T.AMBER, radius=4)
            T.text(s, f"{artist}", (x + 195, y), 16, T.PINK,
                   anchor="topright")
            T.text(s, str(len(songs)), (x + 200 + bar_w + 8, y), 16,
                   T.TEXT_FAINT)
            y += 24

        if len(artists_sorted) > 15:
            T.text(s, f"+ {len(artists_sorted) - 15} outros", (x, y), 16,
                   T.TEXT_DIM)
            y += 24

        # total size
        total_size = sum(info.get("size", 0) for info in self.downloaded)
        if total_size > 0:
            y += 10
            mb = total_size / (1024 * 1024)
            T.text(s, f"espaço total: {mb:.1f} MB", (x, y), 18, T.TEXT_FAINT)

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
        self._lib_root = None

    def enter(self):
        self._lib_root = vinyl.library_root()
        self._disk = None  # refresh disk info

    def opcoes(self):
        return [
            (f"estante: {self._lib_root or '?'}", None),
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
            st = os.statvfs(self._lib_root or "/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            self._disk = (total, free)
        except Exception:                 # noqa: BLE001
            self._disk = (0, 0)
        return self._disk

    def _stylus_version(self):
        """A versão desta máquina, na melhor fonte que existir.

        O clone em /var/lib/stylus/repo só nasce no primeiro
        `stylus-update`: numa máquina recém-instalada ele não está lá, e
        a tela dizia "?" — a resposta menos útil possível para quem abriu
        justamente para descobrir qual versão tem.

        **Sintoma:** e depois do primeiro update ela passou a mostrar a data
        da ISO, que é mais velha ainda e parece certa. O clone é do ROOT (o
        stylus-update roda com sudo) e o git recusa ler repositório de outro
        dono desde a 2.35.6: "detected dubious ownership". O erro sai pelo
        stderr, o stdout vem vazio, e o `if v:` cai calado no plano B.

        Isso quebrava justamente o laço de trabalho do sistema — publicar,
        `stylus-update`, conferir se chegou —, porque a tela que responde
        "qual versão eu tenho" respondia sempre a mesma coisa. O
        `-c safe.directory` é o jeito que o próprio git documenta para dizer
        "eu sei de quem é, pode ler".
        """
        try:
            r = subprocess.run(["git", "-c", "safe.directory=/var/lib/stylus/repo",
                                "-C", "/var/lib/stylus/repo", "log",
                                # %h %cs: a chave curta e a DATA. Era `%h %s`,
                                # e o %s é o assunto do commit — a linha da
                                # tela virava "build: f294f8e As ferramentas
                                # paravam de falar inglês c…", cortada no
                                # meio. Uma mensagem de commit é escrita para
                                # quem lê o histórico, não para quem quer
                                # saber de quando é a máquina.
                                "-1", "--format=%h  %cs"],
                               capture_output=True, text=True, timeout=3)
            v = r.stdout.strip()
            if v:
                return v
        except Exception:                 # noqa: BLE001
            pass
        # A ISO grava a data em que foi montada; é o que a máquina tem
        # antes da primeira atualização.
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                for linha in fh:
                    if linha.startswith("IMAGE_VERSION="):
                        return linha.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return "sem versão registrada"

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
        # A coluna cede para a SAÍDA ter tamanho útil. Com `min(560, r.w-88)`
        # fixo, numa tela de 1024 sobravam 136 px para o painel — onde sai a
        # saída do atualizador, que é texto de terminal. É o mesmo piso de
        # 420 px do `lista_com_saida`, pela mesma razão.
        opt_w = min(560, max(280, r.w - 88 - 420))
        for i, (rotulo, cmd) in enumerate(self.opcoes()):
            sel = i == self.sel
            box = pygame.Rect(x, y, opt_w, 44)
            if sel:
                T.linha_escolhida(s, box)
            if sel:
                T.text(s, "▸", (box.x + 16, box.y + 11), 20, T.AMBER)
            T.text(s, rotulo, (box.x + 34, box.y + 11),
                   20, T.TEXT if sel else (T.TEXT_DIM if cmd else T.TEXT_FAINT),
                   maxw=box.w - 50)
            y += 50

        # O rodapé, com a altura de cada linha respeitada. Uma linha de 40px
        # ocupa ~48 na tela: escrever a próxima 46 abaixo é escrever em cima.
        #
        # 186 e não 152: a linha de dicas mora nos últimos 34 px da tela, e
        # com 152 a frase da agulha caía em cima dela.
        y_info = r.bottom - 186
        T.text(s, "STYLUS", (x, y_info), 40, T.AMBER, bold=True)
        # O assunto do commit é texto de tamanho livre — corta no painel.
        T.text(s, f"build: {self._stylus_version()}", (x, y_info + 54), 16,
               T.TEXT_FAINT, maxw=opt_w)
        total, free = self._disk_info()
        if total > 0:
            used_gb = (total - free) / (1024 ** 3)
            total_gb = total / (1024 ** 3)
            pct = int((total - free) / total * 100)
            disk_txt = f"disco: {used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"
            T.text(s, disk_txt, (x, y_info + 76), 16, T.TEXT_FAINT)

        # A frase fica ABAIXO do painel de saída, então tem a largura toda —
        # cortá-la na coluna das opções tirava justamente o fim dela.
        T.text(s, "a agulha é o único ponto em que um objeto vira som.",
               (x, y_info + 108), 19, T.TEXT_DIM, maxw=r.right - x - 44)
        # A saída fica com TODO o resto da linha. Era `min(340, …)`: numa tela
        # de 1920 sobravam seiscentos e sessenta pixels de nada à direita de
        # um painel estreito, e é nele que sai a saída do atualizador — texto
        # de terminal, que num painel de 340 px quebra em toda linha. O mesmo
        # raciocínio do `lista_com_saida`, que já fazia isto certo.
        jp_x = x + opt_w + 40
        jp_w = r.right - jp_x - 44
        if jp_w > 120:
            jp = pygame.Rect(jp_x, r.y + 100, jp_w, r.h - 200)
        else:
            # Numa tela estreita ele desce para baixo das opções — e ali tem
            # que parar ANTES do rodapé (o "STYLUS", o build, o disco e a
            # frase da agulha), que mora nos últimos 186 px. Sem isso ele era
            # desenhado por cima deles.
            jp = pygame.Rect(x, y + 20, opt_w,
                             max(0, (r.bottom - 190) - (y + 20)))
        if jp.h >= 60:
            self.app.job_panel(s, jp, self.job)
        # **Esta era a única seção sem linha de dicas.** Todas as outras
        # dizem o que as teclas fazem; justamente a que troca a pasta da
        # coleção, o driver de vídeo e roda o atualizador não dizia nada — e
        # duas das seis linhas dela são informação, não botão, o que torna
        # "não aconteceu nada" um resultado ainda mais confuso.
        cmd_sel = self.opcoes()[self.sel][1]
        self.app.hint(s, r, "[↑][↓] anda   " + ("[enter] faz este"
                                                if cmd_sel else
                                                "(esta linha é só informação)"))


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
            if sel:
                T.text(s, "▸", (box.x + 22, box.y + 14), 21, T.AMBER)
            T.text(s, rotulo, (box.x + 40, box.y + 14),
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

        self.app.hint(s, r, "[enter] escolhe   ·   [↑][↓] anda   ·   "
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
        # O SDL só manda MOUSEMOTION quando o ponteiro se move DENTRO da
        # janela; a posição inicial não gera evento nenhum. Guardá-la aqui
        # evita que o primeiro quadro veja um "movimento" que não houve e
        # acenda o cursor sozinho numa tela que ninguém tocou.
        try:
            self._rato_pos = pygame.mouse.get_pos()
        except Exception:                 # noqa: BLE001
            pass
        self.clock = pygame.time.Clock()

        self.shelf = Shelf()
        self.thumbs = Thumbs()
        # THUMB_HI e não 640 escrito à mão: o model.py define os dois
        # tamanhos e explica por que a AGORA precisa do grande. Dois lugares
        # com o mesmo número é um lugar a mais para eles discordarem.
        self.thumbs_hi = Thumbs(px=THUMB_HI)
        self.playing = Playing()
        self.shelf.load()

        self.screens = [NowScreen(self), ShelfScreen(self), StackScreen(self),
                        DiaryScreen(self), SignalScreen(self), PhoneScreen(self),
                        ToolsScreen(self), QobuzScreen(self), SpotifyScreen(self),
                        GamesScreen(self), SettingsScreen(self)]
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
        # ── o rato ──────────────────────────────────────────────────────
        # Esta tela nasceu para um controle e um sofá, e escondia o cursor
        # para sempre: mexer o rato não fazia NADA, nem aparecer a seta. Numa
        # mesa isso se lê como a interface travada. Agora ele aparece quando
        # se mexe e some sozinho depois de parado — a tela volta a ser só a
        # música, sem uma seta esquecida no meio dela.
        self._rato_t = 0.0
        self._rato_visivel = False
        self._rato_pos = (-1, -1)
        # A área que cada item ocupa na tela, preenchida no desenho. É o que
        # transforma "onde eu cliquei" em "qual disco" sem cada tela precisar
        # saber de rato: quem desenha grade só anota o retângulo.
        self.alvos = []
        self._alvos_do_trilho = []
        self.stack = self._stack_load()
        self._toast = ""
        self._toast_until = 0.0
        self._toast_kind = "info"
        self._toast_t = 0.0       # momento em que o toast apareceu
        # Transição entre seções: fade rápido ao trocar de tela.
        self._trans_alpha = 0.0
        # Sleep timer: minutes remaining, 0 = off
        self._sleep_minutes = 0
        self._sleep_end = 0.0
        # Shuffle/repeat state — persisted across restarts
        _prefs = _load_prefs()
        # Nasce desligado SEMPRE, e não do arquivo de gosto: embaralhar é uma
        # escolha sobre a lista que está tocando, e a lista some quando o mpv
        # sai. Restaurá-lo acendia o ícone sobre um disco na ordem.
        self.shuffle = False
        self.repeat = int(_prefs.get("repeat", 0))  # 0=off, 1=repeat side, 2=repeat album
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
        # A pasta do disco anterior, para saber quando um disco NOVO entrou:
        # o embaralhar e o repetir moram no processo do mpv, e cada disco
        # posto sobe um mpv novo. Ver _disco_novo().
        self._disco_anterior = None
        # Quando a agulha começou a descer neste disco. Zero = nenhuma
        # cerimônia em curso. Ver NowScreen._cerimonia.
        self.cerimonia_t0 = 0.0
        self.auto_deck = bool(_load_prefs().get("auto_deck", True))
        self._born = time.time()
        self.pads = []
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
        novo = dict(item)
        self.stack.append(novo)
        self.stack_save()
        self._medir_da_pilha(novo)
        self.toast(f"{item['name']} na pilha  ({len(self.stack)})")

    def _medir_da_pilha(self, it):
        """Quanto tempo e quantos lados este disco é. Numa thread.

        **Sintoma:** a PILHA soma `it.get("mins", 0)` para escrever "X min de
        disco encostado no móvel" — e o item da estante NUNCA teve `mins`. O
        índice da estante não guarda duração de propósito (ele existe para a
        grade desenhar rápido), então a soma dava zero e a linha, que só é
        desenhada quando a soma é positiva, nunca apareceu na tela. Uma frase
        escrita, um `if` que nunca foi verdade.
        
        Aqui é barato: a pilha tem três ou quatro discos, não quatrocentos, e
        a medida é feita UMA vez e vai junto no arquivo da pilha. O que ela
        responde é a pergunta da seção — com o que exatamente eu me
        comprometi para hoje à noite.
        """
        pasta = it.get("folder")
        if not pasta:
            return

        def _corre():
            try:
                al = vinyl.Album(pasta, envelope=False)
                if al.total:
                    it["mins"] = int(al.total // 60)
                    it["lados"] = len(al.sides)
                    it["discos"] = getattr(al, "discos", 1)
                    self.stack_save()
            except Exception:             # noqa: BLE001 — disco sumiu, e daí
                pass

        threading.Thread(target=_corre, daemon=True).start()

    def stack_tonight(self):
        """Monta uma noite: três discos, puxando para os esquecidos.

        Três e não dez porque uma noite tem três discos. Uma fila de dez é
        uma playlist com outro nome, e playlist é justamente a coisa que este
        sistema não quer ser.
        """
        # A estante é lida UMA vez, e não uma por disco sorteado. Sem o
        # `candidates`, cada `draw_record` varre a coleção inteira do disco
        # rígido de novo — três varreduras para escolher três discos, e o
        # botão "monta uma noite" fica parado enquanto isso.
        #
        # E ela já está lida: o `self.shelf.items` é a mesma estante que a
        # grade desenha.
        prateleira = [i["folder"] for i in (self.shelf.items or [])]
        escolhidos, fora = [], [i["folder"] for i in self.stack]
        for _ in range(3):
            d = vinyl.draw_record(prateleira or None, exclude=fora)
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
        for it in escolhidos:
            self._medir_da_pilha(it)
        self.toast("%s para hoje à noite" % plural(len(escolhidos), "disco"))

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
        """Cicla o "parar sozinho": desligado → 30m → 60m → 90m → desligado.

        Chamava-se "sleep timer" na tela, em inglês, e o celular dizia a
        mesma coisa com outra caixa alta em dois arquivos diferentes. Texto
        que o usuário lê é em português, e é o MESMO português dos dois
        lados: a coleção é a mesma nos dois, o vocabulário também tem que ser.
        """
        cycle = [0, 30, 60, 90]
        idx = cycle.index(self._sleep_minutes) if self._sleep_minutes in cycle else 0
        self._sleep_minutes = cycle[(idx + 1) % len(cycle)]
        if self._sleep_minutes > 0:
            self._sleep_end = time.time() + self._sleep_minutes * 60
            self.toast(f"para sozinho em {self._sleep_minutes} minutos")
        else:
            self.toast("não para mais sozinho")

    def _ao_tocador(self, *cmd):
        """Manda um comando ao mpv que está tocando. None se não há mpv.

        O `playerctl` cobre pausa e faixa, e não cobre isto: embaralhar e
        repetir são propriedades da LISTA, e a lista mora no mpv. O socket é
        o mesmo do deck (vinyl.SOCKET_PATH) — o `stylus-deck` e o `stylus
        qobuz tocar` os dois sobem o mpv com `--input-ipc-server` nele, de
        propósito, para que o resto do sistema possa falar com o tocador.

        Chamado da tecla, nunca do desenho: sem socket o `connect()` devolve
        falso na hora (não há espera), e com socket a resposta leva ~1 ms.
        """
        try:
            return self.playing.session.mpv.command(*cmd)
        except Exception:                     # noqa: BLE001 — tocador morto
            return None

    def _ha_tocador(self):
        """Existe um mpv nosso do outro lado do socket?

        `command()` devolve None tanto para "não deu" quanto para um comando
        que responde vazio, então quem pergunta "tem tocador?" pergunta por
        uma propriedade que sempre tem valor.
        """
        return self._ao_tocador("get_property", "playlist-count") is not None

    def toggle_shuffle(self):
        """Embaralha a lista que está tocando — de verdade.

        **Sintoma:** isto virava um `self.shuffle = not self.shuffle`, um
        toast dizendo "embaralhar: ligado" e um ícone aceso na AGORA. E mais
        nada: nenhuma linha deste arquivo, em lugar nenhum, contava ao
        tocador. A música seguia na mesma ordem, e o sistema afirmava o
        contrário com um ícone — que é pior do que não ter a tecla.

        `playlist-shuffle` e `playlist-unshuffle` são do mpv desde a 0.33, e
        o segundo devolve a ORDEM DO DISCO, não outro embaralhamento: um
        disco é uma sequência que alguém escolheu, e desfazer tem que
        devolver essa sequência.
        """
        if not self._ha_tocador():
            self.toast("não há disco tocando para embaralhar")
            return
        quer = not self.shuffle
        self._ao_tocador("playlist-shuffle" if quer else "playlist-unshuffle")
        # Confere no tocador em vez de acreditar: o `playlist-unshuffle` só
        # existe se o mpv for novo o bastante, e falhar em silêncio é como
        # este defeito começou.
        self.shuffle = quer
        self._save_player_prefs()
        self.toast("embaralhar: " + ("ligado" if quer else
                                     "desligado (ordem do disco de volta)"))

    def toggle_repeat(self):
        """Repetir: desligado → a faixa → o disco inteiro.

        Mesmo defeito do embaralhar: girava um número e acendia um ícone sem
        falar com o tocador.

        E os rótulos mentiam de outro jeito: diziam "repetir lado", que o mpv
        não sabe fazer — um lado é um pedaço da lista, e `loop-file` repete a
        FAIXA. O ícone já era o de repetir-uma (󰑙). Agora o rótulo, o ícone e
        o que acontece são a mesma coisa.
        """
        if not self._ha_tocador():
            self.toast("não há disco tocando para repetir")
            return
        labels = ["desligado", "repetir a faixa", "repetir o disco"]
        self.repeat = (self.repeat + 1) % 3
        self._ao_tocador("set_property", "loop-file",
                         "inf" if self.repeat == 1 else "no")
        self._ao_tocador("set_property", "loop-playlist",
                         "inf" if self.repeat == 2 else "no")
        self._save_player_prefs()
        self.toast("repetir: " + labels[self.repeat])

    def _save_player_prefs(self):
        _save_prefs({"auto_deck": self.auto_deck, "repeat": self.repeat})

    _volume_cache = (0, 0)
    _volume_counter = 0

    @classmethod
    def volume_pct(cls):
        """Volume atual (0-100). Throttled: 1 consulta a cada 5 chamadas.

        Contador próprio: compartilhar o do audio_level fazia as duas
        consultas caírem em frames alternados e o volume só atualizar
        de dez em dez."""
        cls._volume_counter += 1
        if cls._volume_counter % 5 != 0:
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
        """Nível de áudio real (0.0 a 1.0) para efeitos reativos.

        O audio_live mantém um monitor do PipeWire aberto numa thread e o
        nível já está calculado: ler aqui é só uma atribuição, não um
        subprocess (o wpctl de antes media o GANHO do sink, não a música, e
        pagava um processo novo a cada 5 quadros)."""
        cls._audio_level_counter += 1
        mon = audio_live.get_monitor()
        return mon.snapshot()[0] if mon is not None else 0.0

    def audio_now(self):
        """(level, wave, spectrum, pulse) do momento, prontos para desenhar.

        A AGORA precisa das quatro peças, e pedi-las por getters separados
        faria quatro snapshots no mesmo quadro. As duas matrizes são cópias
        protegidas da thread; desenhar sem ela é meio-quadro com uma faixa
        pela metade.

        O `pulse` é o transiente, a energia crua da batida — é o "ritmo", e
        o `level` é o "volume". O brilho respira nos dois: volume dá peso,
        ritmo dá vida.
        O monitor é caro de abrir e fracassa com graça: sem ele a AGORA
        desenha tudo menos o que respira com o som (os Nones).
        """
        mon = audio_live.get_monitor()
        if mon is None:
            return 0.0, None, None, 0.0
        return mon.snapshot()

    # ── desenho comum ──────────────────────────────────────────────────────
    def hint(self, s, r, teclas, contexto=""):
        """A linha de dicas do rodapé, com as teclas desenhadas como teclas.

        O `[X]` de `teclas` vira quadradinho (ver T.frase_com_teclas). Sem
        isso a linha lê "s empilha  a artista  o ordem", que parece três
        palavras faltando e não três teclas.

        **O `contexto` é separado de propósito, e nunca passa pelo `[...]`.**
        Sintoma: a estante montava a linha inteira numa `f"..."` — nome do
        disco, quando foi posto, e os atalhos, tudo junto. E disco baixado se
        chama "Radiohead - Live From The Basement [FLAC]". O `[FLAC]` do NOME
        DO ARQUIVO virava um quadradinho de tecla no meio da frase. Marcação
        só vale em texto que este repositório escreveu; dado de usuário entra
        por outra porta.

        E o contexto é o que CEDE quando falta espaço, nunca as teclas: na
        coleção de verdade um nome comprido comia a linha e a dica terminava
        em "ente…". Nome de disco cortado ainda diz qual disco é; atalho
        cortado não faz nada.
        """
        x, y = r.x + 44, r.bottom - 34
        cabe = r.w - 88
        if not teclas.strip():
            T.text(s, contexto, (x, y), 17, T.TEXT_FAINT, maxw=cabe)
            return

        larg_teclas = T.frase_largura(teclas, 17)
        if contexto:
            sobra = cabe - larg_teclas - 20
            if sobra > 80:
                rc = T.text(s, contexto, (x, y), 17, T.TEXT_FAINT, maxw=sobra)
                # A folga é somada DEPOIS de desenhar: se ela fosse parte do
                # texto, o corte por reticências a comeria junto e o nome do
                # disco ficaria colado no primeiro quadradinho.
                x = rc.right + 22
                # `sobra > 80` já garante `cabe > larg_teclas + 100`: as
                # teclas cabem inteiras no que restou.
                T.frase_com_teclas(s, teclas, (x, y), 17, T.TEXT_FAINT)
                return
        # A linha é só das dicas — e ela precisa CABER.
        #
        # **Sintoma:** a AGORA anuncia sete atalhos, e numa tela de 1280 os
        # dois últimos ("[+]/[-] volume", "[D] deck sozinho: desligado") eram
        # desenhados FORA da tela. O corte por largura existia, mas só dentro
        # do `if contexto:` — e a AGORA, a ESTANTE e a maioria das seções
        # chamam isto sem contexto nenhum, ou seja, justamente por onde não
        # havia conferência.
        cabem = self._dicas_que_cabem(teclas, cabe)
        if not cabem:
            # Nem a primeira dica cabe: sem os quadradinhos ela ainda entra.
            T.text(s, teclas.replace("[", "").replace("]", ""), (x, y), 17,
                   T.TEXT_FAINT, maxw=cabe)
            return
        T.frase_com_teclas(s, cabem, (x, y), 17, T.TEXT_FAINT)

    @staticmethod
    def _dicas_que_cabem(teclas, cabe, size=17):
        """As dicas que couberem, INTEIRAS, na largura dada.

        Cortar esta linha por reticências deixaria "…[D] deck sozinho: desl…",
        que não é um atalho, é um enigma. Uma dica ou aparece por completo ou
        não aparece: as primeiras da frase são as que mais importam, e a
        separação entre elas (dois ou mais espaços) já diz onde uma acaba.
        """
        partes = [p for p in re.split(r"\s{2,}", teclas.strip()) if p]
        if not partes:
            return ""
        sep = T.largura("   ", size)
        usado, saida = 0, []
        for p in partes:
            w = T.frase_largura(p, size) + (sep if saida else 0)
            if usado + w > cabe:
                break
            saida.append(p)
            usado += w
        # O separador de algumas linhas é um "·" sozinho entre os espaços.
        # Cortando no meio, ele sobraria pendurado no fim da frase apontando
        # para o que não está mais ali.
        while saida and not any(c.isalnum() for c in saida[-1]):
            saida.pop()
        return "   ".join(saida)

    def lista_com_saida(self, s, r, titulo, sub, acoes, sel, job, dica,
                        size=20):
        """Uma lista de ações à esquerda e a saída do que rodou à direita.

        **Sintoma:** a OFICINA e o CELULAR reservavam 470 px fixos para a
        lista, e três dos rótulos não cabiam — "pôr a coleção do celular na
        es…", "o papel de parede vira o disco de …". Ao lado, o painel de
        saída ficava com 760 px e passa quase toda a vida VAZIO. O espaço
        estava todo do lado que não tinha o que mostrar.

        Aqui a coluna é medida a partir do rótulo mais comprido: nada corta,
        e a saída ainda fica com a maior parte da tela.
        """
        x, y = r.x + 44, r.y + 34
        T.text(s, titulo, (x, y), 30, T.TEXT, bold=True)
        alt_sub = T.paragrafo(s, sub, (x, y + 40), 18, T.TEXT_FAINT,
                              maxw=r.w - 90, limite=2)
        y += 74 + alt_sub

        recuo = 34 + 14                   # o ▸ à esquerda e a folga à direita
        # A saída tem piso: abaixo de ~380 px ela não mostra uma linha de
        # terminal inteira e vira decoração. O que sobra é o teto da coluna —
        # e se o rótulo mais comprido não couber nele, quem cede é o TAMANHO
        # DA LETRA, não o texto: um rótulo uma letra menor continua legível,
        # um rótulo cortado no meio não diz mais o que a ação faz.
        # O painel fica com `r.w - larg - 128` (os 128 são as margens e o vão
        # entre as duas colunas). Invertendo: para a saída ter no mínimo 420,
        # a coluna não pode passar de r.w - 548.
        teto = max(320, r.w - 128 - 420)
        while size > 15:
            larg = max(T.largura(rot, size) for rot, *_ in acoes) + recuo
            if larg <= teto:
                break
            size -= 1
        larg = int(max(320, min(larg, teto)))

        passo = size + 30
        for i, item in enumerate(acoes):
            rotulo = item[0]
            escolhido = i == sel
            box = pygame.Rect(x, y, larg, passo - 6)
            self.alvos.append((box.copy(), i))
            if escolhido:
                T.linha_escolhida(s, box)
                T.text(s, "▸", (box.x + 16, box.y + 11), size, T.AMBER)
            T.text(s, rotulo, (box.x + 34, box.y + 11), size,
                   T.TEXT if escolhido else T.TEXT_DIM, maxw=box.w - recuo)
            y += passo

        px = x + larg + 40
        self.job_panel(s, pygame.Rect(px, r.y + 120, r.right - px - 44,
                                      r.h - 220), job)
        self.hint(s, r, dica)

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
        # A folga para o estado, MEDIDA. Era um `- 140` fixo, e "saiu com
        # 127" não cabe em 140 px — o mesmo defeito da tela SINAL.
        #
        # E quando nem assim cabe, o estado desce para a linha de baixo em
        # vez de comer o título. Num painel estreito, "ver o que está…" não
        # diz qual tarefa está rodando, que é a única coisa que este título
        # existe para dizer.
        folga = T.largura(estado, 18) + 32
        topo = rect.y + 12
        if T.largura(job.title, 19) <= rect.w - 32 - folga:
            T.text(s, job.title, (rect.x + 16, topo), 19, T.TEXT)
            T.text(s, estado, (rect.right - 16, topo), 18, cor,
                   anchor="topright")
            base = rect.y + 46
        else:
            T.text(s, job.title, (rect.x + 16, topo), 19, T.TEXT,
                   maxw=rect.w - 32)
            T.text(s, estado, (rect.x + 16, topo + 26), 18, cor)
            base = rect.y + 72
        f = T.font(15)
        lh = f.get_linesize()
        n = max(1, (rect.bottom - base - 6) // lh)
        old = s.get_clip()
        s.set_clip(rect.inflate(-8, -8))
        for i, ln in enumerate(job.lines[-n:]):
            T.text(s, ln, (rect.x + 16, base + i * lh), 15, T.TEXT_DIM,
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

            self._alvos_do_trilho.append((box.copy(), i))
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
                    T.sleeve(s, cr, mini)
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
            # elapsed / remaining do ÁLBUM (não da faixa): o disco inteiro,
            # igual à barra do ritual. O where() já trouxe o instante absoluto
            # no álbum em `_t` e o Album de verdade chama o total de `.total`,
            # não `.duration` — os dois nomes antigos não existiam e derrubavam
            # a tela na primeira faixa tocando.
            elapsed_s = int(_t)
            total_s = int(al.total)
            if total_s and total_s > 0:
                rem_s = max(0, total_s - elapsed_s)
                T.text(s, f"{elapsed_s // 60}:{elapsed_s % 60:02d}",
                       (24, ty + 74), 12, T.TEXT_FAINT)
                T.text(s, f"-{rem_s // 60}:{rem_s % 60:02d}",
                       (w - 24, ty + 74), 12, T.TEXT_FAINT, anchor="topright")
            else:
                T.text(s, f"{elapsed_s // 60}:{elapsed_s % 60:02d} / ?",
                       (24, ty + 74), 12, T.TEXT_FAINT)

    # ── virar o lado ───────────────────────────────────────────────────────
    # Meio minuto, e não sete segundos, pelo mesmo motivo do aviso da área de
    # trabalho (ESPERA_LADO no stylus-side-watch): quem está ouvindo um disco
    # é justamente quem não está na frente do computador, e um acontecimento
    # que some antes de você voltar da cozinha vira um contador de novo.
    # Qualquer tecla dispensa, então ficar mais tempo não custa nada a quem
    # está ali — e este aviso, com a tela cheia no ar, é o ÚNICO: o vigia não
    # manda notificação quando a interface está aberta.
    FLIP_DUR = 30.0

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
            # A frase do gesto vem do Album — a mesma que a notificação e o
            # deck dizem. Escrita aqui, ela perguntava "este é o último
            # lado?", e num disco DUPLO isso manda virar quando o objeto
            # pede trocar de disco.
            try:
                gesto = al.gesto_do_lado(i)
            except Exception:                              # noqa: BLE001
                gesto = "agora o %s" % (side.get("label", "LADO")
                                        .replace("SIDE", "LADO"))
            self._flip = (time.time(),
                          anterior.get("label", "LADO").replace("SIDE", "LADO"),
                          gesto, f"{al.artist} — {al.name}")
        self._lado_i = i

    def _draw_flip(self, s):
        if not self._flip:
            return
        t0, antes, gesto, disco = self._flip
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
        T.text(camada, gesto, (cx, cy + 34), 30, T.TEXT, anchor="center",
               maxw=self.W - 160)
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
        # Formulário de conta ABERTO: é modal. O ESC fecha o formulário, e
        # nenhum atalho global (trocar de tela, abrir o trilho) atravessa —
        # quem está digitando no formulário tem que poder voltar e digitar.
        em_formulario = bool(getattr(self.screens[self.cur], "entrada", None))
        if em_formulario:
            if ev.key == pygame.K_ESCAPE:
                self.screens[self.cur].entrada = None
                return None
            return self.screens[self.cur].key(ev)
        # A TELA CHEIA sai primeiro, e o ESC é o que a tira.
        #
        # **Sintoma:** com o disco na tela toda, apertar B no controle (que
        # chega aqui como ESC) parecia não fazer nada — e a partir dali NADA
        # mais respondia: o `f` não voltava, as setas não buscavam, o ENTER
        # pulava de seção. O que acontecia é que o ESC caía no bloco abaixo e
        # LIGAVA o trilho, que na tela cheia não é desenhado (`inteira` tira
        # a moldura): o programa ficava num menu invisível, comendo todas as
        # teclas seguintes. O `if ev.key == K_ESCAPE and self.tela_cheia` da
        # NowScreen nunca chegava a rodar, porque este método vem antes dela.
        tela_atual = self.screens[self.cur]
        if getattr(tela_atual, "tela_cheia", False):
            if ev.key == pygame.K_ESCAPE:
                tela_atual.tela_cheia = False
                return None
            # E qualquer coisa que ABRA o trilho tira a tela cheia junto, em
            # vez de abrir um menu por baixo de um disco que ocupa tudo.
            if ev.key in (pygame.K_TAB, pygame.K_q):
                tela_atual.tela_cheia = False
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
        # Os dígitos 1–9 trocam de tela. (Num formulário de conta aberto —
        # Qobuz/Spotify — o retorno cedo no topo deste método já repassou a
        # tecla para o formulário, então um número digitado na senha nunca
        # chega aqui para mudar de tela.)
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

    # ── o rato ─────────────────────────────────────────────────────────
    RATO_SOME = 3.0                       # segundos parado até o cursor sumir

    def _rato_mexeu(self, pos):
        """Acende o cursor. Chamado por movimento, clique e roda."""
        if pos == self._rato_pos and self._rato_visivel:
            return
        self._rato_pos = pos
        self._rato_t = time.time()
        self._ultima_entrada = self._rato_t
        if not self._rato_visivel:
            self._rato_visivel = True
            pygame.mouse.set_visible(True)

    def _rato_pisca(self):
        """Some depois de parado. Roda uma vez por quadro."""
        if self._rato_visivel and time.time() - self._rato_t > self.RATO_SOME:
            self._rato_visivel = False
            pygame.mouse.set_visible(False)

    def _clique(self, ev):
        """Um clique vira a mesma coisa que a tecla equivalente faria.

        Nada aqui inventa comportamento novo: clicar num item é escolhê-lo e
        apertar enter, clicar no trilho é ir para aquela seção, o botão da
        direita é o ESC. Duas maneiras de fazer a mesma coisa, e uma só
        implementação por baixo — que é o que impede o rato de fazer uma
        terceira coisa que ninguém previu.
        """
        if ev.button == 3:                # direito = voltar
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0))
            return None
        if ev.button != 1:
            return None
        # O trilho primeiro: ele fica por cima e é o alvo mais fácil de
        # acertar sem querer com uma grade larga do lado.
        for caixa, i in self._alvos_do_trilho:
            if caixa.collidepoint(ev.pos):
                if i >= len(self.screens):
                    self.toast("indo para a área de trabalho…")
                    pygame.display.flip()
                    spawn(["stylus-mode", "desktop"])
                else:
                    self._goto(i)
                return None
        for caixa, indice in self.alvos:
            if not caixa.collidepoint(ev.pos):
                continue
            tela = self.screens[self.cur]
            if getattr(tela, "sel", None) != indice:
                # Um clique em cima de um item que ainda não estava escolhido
                # só ESCOLHE. Abrir de primeira faz o cursor abrir coisa que a
                # pessoa só estava mirando — e num sistema em que abrir
                # significa pôr um disco, isso é alto.
                tela.sel = indice
                return None
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))
            return None
        return None

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
                elif ev.type == pygame.MOUSEMOTION:
                    self._rato_mexeu(ev.pos)
                elif ev.type == pygame.MOUSEWHEEL:
                    # A roda vira seta em vez de virar código novo em cada
                    # tela: toda tela daqui já sabe responder a ↑/↓, e uma
                    # roda que só funcionasse em três delas seria pior do que
                    # uma roda que não funciona.
                    self._rato_mexeu(pygame.mouse.get_pos())
                    tecla = pygame.K_UP if ev.y > 0 else pygame.K_DOWN
                    for _ in range(min(3, max(1, abs(ev.y)))):
                        pygame.event.post(pygame.event.Event(
                            pygame.KEYDOWN, key=tecla, unicode="", mod=0))
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    self._rato_mexeu(ev.pos)
                    if self._clique(ev) == "quit":
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
            # Uma seção pode pedir a tela INTEIRA — é o que a AGORA faz no
            # [f]. O trilho é a moldura do sistema; quando o assunto é o
            # disco e mais nada, moldura é ruído.
            # `and not self.rail`: com o trilho aberto a moldura tem que
            # aparecer. Sem isto, um caminho qualquer que ligasse o trilho com
            # a tela cheia no ar deixava o programa num menu INVISÍVEL — e um
            # menu invisível come todas as teclas seguintes.
            inteira = (getattr(self.screens[self.cur], "tela_cheia", False)
                       and not self.rail)
            body = (pygame.Rect(0, 0, self.W, self.H) if inteira else
                    pygame.Rect(rail_w, 0, self.W - rail_w, self.H))
            # Os alvos são de UM quadro: a grade muda de tamanho com a
            # janela, com o filtro e com a busca, e um retângulo guardado do
            # quadro passado clica no disco errado.
            self.alvos = []
            self._alvos_do_trilho = []
            self._rato_pisca()
            self._disco_novo()
            self._idle_deck()
            try:
                self.screens[self.cur].draw(self.surf, body)
            except Exception as e:        # noqa: BLE001
                # Uma tela com defeito não pode derrubar o sistema inteiro:
                # este programa é a cara da máquina e cair nele parece o
                # computador ter quebrado.
                T.text(self.surf, f"esta tela quebrou: {type(e).__name__}: {e}",
                       (body.x + 40, body.y + 60), 20, T.RED, maxw=body.w - 80)
            if not inteira:
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
                self.toast(f"o disco para aqui — {self._sleep_minutes} min")
                self._sleep_minutes = 0
            self.clock.tick(FPS)

    def _pasta_tocando(self):
        """A pasta do disco que está tocando — a do ÁLBUM quando ela é sabida.

        `os.path.dirname` do que o tocador diz não serve sozinho: um disco da
        rede tem endereço no lugar de caminho, e o dirname de
        `https://x.invalid/123.flac` é `https:/x.invalid` — a MESMA string
        para todas as playlists do Qobuz. Quem compara isso acha que nunca
        trocou de disco. O `Album.folder` é a pasta de cache da lista, que é
        diferente por lista.
        """
        al = self.playing.album
        if al is not None and getattr(al, "folder", ""):
            return os.path.normpath(al.folder)
        caminho = (self.playing.session.snapshot().get("path") or "")
        return os.path.dirname(caminho) if caminho else ""

    def _disco_novo(self):
        """Disco trocou: a ordem volta a ser a do disco, e o repetir vale.

        As duas coisas que o `toggle_shuffle`/`toggle_repeat` mexem moram no
        PROCESSO do mpv, e cada disco posto sobe um mpv novo. Sem isto:

          · o ícone de embaralhar continuava aceso sobre uma lista que
            nasceu na ordem — o mesmo tipo de mentira que estas duas teclas
            já contavam antes de falarem com o tocador;
          · e "repetir o disco", que é gosto e por isso fica guardado, era
            esquecido justamente na hora em que passaria a valer.

        Embaralhar NÃO se guarda de propósito: é uma escolha sobre a lista
        que está tocando, não sobre a pessoa. Disco novo, ordem do disco.
        """
        pasta = self._pasta_tocando()
        if not pasta or pasta == self._disco_anterior:
            return
        anterior = self._disco_anterior
        primeiro = anterior is None
        self._disco_anterior = pasta
        # ── a cerimônia ───────────────────────────────────────────────────
        # Disco novo, agulha desce: spinup → cue → drop. É o RITUAL, e o
        # CLAUDE.md §5.5 chama de sagrado — era a única coisa que o deck
        # tinha e a tela cheia do lançador não.
        #
        # Menos numa hipótese: a interface acabou de abrir com música já
        # tocando. Ali o disco não foi posto agora, foi encontrado no meio, e
        # encenar a descida da agulha seria mentira sobre o que aconteceu.
        if not (primeiro and time.time() - self._born < 3.0):
            self.cerimonia_t0 = time.monotonic()
        if self.shuffle:
            self.shuffle = False
        if self.repeat:
            self._ao_tocador("set_property", "loop-file",
                             "inf" if self.repeat == 1 else "no")
            self._ao_tocador("set_property", "loop-playlist",
                             "inf" if self.repeat == 2 else "no")

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
        if not (snap.get("path") or "") or snap.get("paused", True):
            return
        # Pelo ÁLBUM quando dá: ver _pasta_tocando. Com o dirname do endereço,
        # duas playlists diferentes do Qobuz eram a mesma chave, e a tela
        # chamava o disco uma vez só para as duas.
        chave = self._pasta_tocando()
        if chave and chave != self._deck_auto:
            self._deck_auto = chave
            self.open_deck()


def main():
    try:
        App().run()
    finally:
        audio_live.close_monitor()
        pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
