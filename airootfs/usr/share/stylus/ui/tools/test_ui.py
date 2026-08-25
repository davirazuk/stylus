#!/usr/bin/env python3
"""A tela cheia, exercitada sem tela.

POR QUE ISTO EXISTE
-------------------
O deck tem `deck/tools/test_ritual.py` e por isso a cerimônia é a parte do
sistema que quebra menos. A interface de tela cheia não tinha nada — e ela é
a CARA da máquina: no modo música é a única coisa em que se pode olhar, e um
erro não tratado nela deixa o computador com um fundo preto e nenhuma saída
que não seja teclado, que é justamente o que quem está no sofá não tem.

Então isto abre a interface de verdade com o driver de vídeo "dummy" do SDL,
percorre TODAS as seções, aperta em cada uma todas as teclas que a interface
usa, e desenha de novo depois. Sem janela, sem GL, sem placa de som. É o
mesmo tipo de rede do teste do deck: roda em segundos e pega o traceback que
só apareceria com a pessoa sentada na frente.

    python3 ui/tools/test_ui.py            usa uma coleção de mentira
    python3 ui/tools/test_ui.py --lib DIR  usa uma pasta de verdade
"""
import argparse
import atexit
import os
import shutil
import sys
import tempfile
import time
import traceback

G = "\033[1;32m"; R = "\033[1;31m"; D = "\033[2m"; Z = "\033[0m"
PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"    {G}✓{Z} {msg}")


def bad(msg, detail=""):
    global FAIL
    FAIL += 1
    print(f"    {R}✗{Z} {msg}")
    for line in (detail or "").splitlines()[-6:]:
        print(f"      {line}")


def secao(nome):
    print(f"\n  {D}{nome}{Z}")


def coleção_de_mentira(base):
    """Dois discos com capa, o suficiente para a grade ter o que desenhar."""
    try:
        from PIL import Image
    except ImportError:
        return None
    for artista, album in (("The Beatles", "Abbey Road"),
                           ("Radiohead", "OK Computer")):
        d = os.path.join(base, artista, album)
        os.makedirs(d, exist_ok=True)
        Image.new("RGB", (300, 300), (80, 120, 180)).save(
            os.path.join(d, "cover.jpg"))
        for i in range(1, 6):
            open(os.path.join(d, f"{i:02d} faixa.flac"), "wb").write(b"\0" * 32)
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=None)
    args = ap.parse_args()

    # Tem que vir ANTES de importar o pygame: é assim que se pede uma janela
    # que não existe. Sem isto o teste exige um X rodando.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ["STYLUS_UI_WINDOWED"] = "1"

    tmp = tempfile.mkdtemp(prefix="stylus-ui-test-")
    # A pasta de mentira some sozinha: uma rodada antiga com --lib deixou
    # para trás oito diretórios somando ~13 GB em /tmp — encheram a cota do
    # tmpfs e a conferência do branding-sync começou a falhar por falta de
    # espaço, um defeito que parecia do repositório e era do teste.
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    os.environ["HOME"] = os.path.join(tmp, "casa")
    os.makedirs(os.path.join(os.environ["HOME"], ".config", "stylus"),
                exist_ok=True)
    lib = args.lib or coleção_de_mentira(os.path.join(tmp, "estante"))
    if lib:
        with open(os.path.join(os.environ["HOME"], ".config", "stylus",
                               "library"), "w", encoding="utf-8") as fh:
            fh.write(lib + "\n")

    aqui = os.path.dirname(os.path.abspath(__file__))
    raiz = os.path.dirname(os.path.dirname(aqui))          # /usr/share/stylus
    sys.path.insert(0, os.path.join(raiz, "deck"))
    sys.path.insert(0, os.path.join(raiz, "ui"))

    try:
        import pygame
        import app as A
    except Exception as e:                                  # noqa: BLE001
        print(f"  {D}—{Z} sem pygame/numpy/Pillow aqui: {e}")
        return 0

    secao("a interface abre")
    try:
        app = A.App()
        ok("App() construiu")
    except Exception:                                       # noqa: BLE001
        bad("App() não construiu", traceback.format_exc())
        return 1

    for _ in range(60):
        if app.shelf.ready and not app.shelf.scanning:
            break
        time.sleep(0.05)
    if app.shelf.error:
        bad(f"a varredura da estante deu erro: {app.shelf.error}")
    else:
        ok(f"leu a estante ({len(app.shelf.items)} discos)")

    corpo = pygame.Rect(230, 0, app.W - 230, app.H)
    # Todas as teclas que alguma seção usa. Manda-se TODAS em TODAS: a que a
    # seção não conhece tem que ser devolvida, não estourar.
    teclas = [pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
              pygame.K_h, pygame.K_j, pygame.K_k, pygame.K_l,
              pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE,
              pygame.K_s, pygame.K_r, pygame.K_o, pygame.K_t, pygame.K_x,
              pygame.K_n, pygame.K_p, pygame.K_SLASH, pygame.K_DELETE,
              pygame.K_BACKSPACE, pygame.K_PAGEUP, pygame.K_PAGEDOWN,
              pygame.K_HOME, pygame.K_END]

    secao("cada seção desenha e aguenta o teclado")
    # Nada aqui pode lançar processo de verdade. A varredura aperta ENTER em
    # TODAS as telas — e a de JOGOS, no ENTER, abre Steam em Big Picture:
    # quatro rodadas deste teste chegaram a descompactar ~13 GB de Steam
    # dentro da pasta de mentira até estourar a cota do /tmp. E as teclas
    # novas da AGORA falam com playerctl/pamixer da sessão REAL. Gravar os
    # comandos em vez de executá-los mantém a cobertura e torna o teste
    # hermético.
    spawn_reais = []
    spawn_verdadeiro = A.spawn
    A.spawn = lambda cmd, *a, **k: spawn_reais.append(cmd)
    for i, tela in enumerate(app.screens):
        try:
            app._goto(i)
            for _ in range(3):
                app.screens[i].draw(app.surf, corpo)
            for k in teclas:
                ev = pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                        mod=0)
                tela.key(ev)
            app.screens[i].draw(app.surf, corpo)
            ok(tela.name)
        except Exception:                                   # noqa: BLE001
            bad(tela.name, traceback.format_exc())
    if spawn_reais:
        unicos = sorted({" ".join(c) if isinstance(c, list) else str(c)
                         for c in spawn_reais})
        ok(f"{len(spawn_reais)} comandos gravados em vez de executados "
           f"({', '.join(unicos[:4])})")
    else:
        ok("nenhum comando disparado pela varredura")

    secao("o trilho e o aviso")
    try:
        app._draw_rail(app.surf, 230)
        app.toast("teste")
        app._draw_toast(app.surf)
        ok("desenharam")
    except Exception:                                       # noqa: BLE001
        bad("trilho/aviso", traceback.format_exc())

    secao("procurar na estante")
    try:
        estante = next(s for s in app.screens if s.name == "ESTANTE")
        app._goto(app.screens.index(estante))

        def tecla(k, u=""):
            estante.key(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=u,
                                           mod=0))
        # A varredura de teclas acima deixa a estante DENTRO do modo de busca
        # (ela apertou a barra junto com o resto), e ali a barra é um
        # caractere, não um comando: o "/" entraria na consulta em vez de
        # zerá-la. Sair primeiro é o que faz este teste medir a busca em vez
        # de medir a sujeira que ele mesmo deixou.
        tecla(pygame.K_ESCAPE)
        tecla(pygame.K_SLASH, "/")
        if not estante.searching:
            bad("a barra não entrou no modo de busca")
        for ch in "beat":
            tecla(ord(ch), ch)
        achou = len(estante.items())
        tecla(pygame.K_RETURN)
        if estante.searching:
            bad("enter não saiu do modo de busca")
        elif lib and achou == 0 and len(app.shelf.items) > 1:
            bad("procurar por 'beat' não achou nada numa estante que tem")
        else:
            ok(f"procurou e filtrou ({achou})")
        tecla(pygame.K_ESCAPE)
    except Exception:                                       # noqa: BLE001
        bad("busca", traceback.format_exc())

    secao("filtrar por artista")
    try:
        estante = next(s for s in app.screens if s.name == "ESTANTE")

        def tk(k, u=""):
            return estante.key(pygame.event.Event(pygame.KEYDOWN, key=k,
                                                  unicode=u, mod=0))

        if estante.searching or estante.picking:
            tk(pygame.K_ESCAPE)             # herança dos testes de cima
        total = len(estante.items())
        if not estante.artistas():
            ok("(coleção sem artistas: nada para filtrar)")
        else:
            tk(pygame.K_a)
            if not estante.picking:
                bad("'a' não abriu a lista de artistas")
            else:
                # Dentro da lista 'a' é tecla qualquer: não pode aplicar
                # filtro, fechar nada, nem cair fora.
                tk(pygame.K_a)
                tk(pygame.K_DOWN)
                tk(pygame.K_UP)
                nome = estante.artistas()[estante.a_sel]
                tk(pygame.K_RETURN)
                if estante.picking or estante.artist != nome:
                    bad("enter não aplicou o filtro")
                elif total > 1 and len(estante.items()) >= total:
                    bad("o filtro não encolheu a grade")
                else:
                    ok(f"filtrou por {nome} "
                       f"({len(estante.items())} de {total})")
                tk(pygame.K_a)
                if estante.artist is not None:
                    bad("'a' não limpou o filtro")
                else:
                    ok("'a' limpou o filtro")
    except Exception:                                       # noqa: BLE001
        bad("artista", traceback.format_exc())

    secao("o botão B volta em vez de sair")
    try:
        # Sem a janela de desenvolvimento: é o modo música que interessa aqui.
        os.environ.pop("STYLUS_UI_WINDOWED", None)
        app.rail = False
        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE,
                                 unicode="", mod=0)
        r1 = app._key(esc)
        if r1 == "quit":
            bad("ESC encerrou a sessão em vez de abrir o menu")
        elif not app.rail:
            bad("ESC não abriu o menu")
        else:
            ok("ESC abre o menu")
        r2 = app._key(esc)
        if app.rail or r2 == "quit":
            bad("ESC no menu não fechou o menu")
        else:
            ok("ESC no menu fecha o menu")
        os.environ["STYLUS_UI_WINDOWED"] = "1"
    except Exception:                                       # noqa: BLE001
        bad("voltar", traceback.format_exc())

    secao("controle: ligar depois não pode ser ignorado")
    try:
        app._sync_pads()
        app._pad_poll()
        ok(f"releu os controles ({len(app.pads)} conectados)")
    except Exception:                                       # noqa: BLE001
        bad("controle", traceback.format_exc())

    secao("o DIÁRIO com registro de verdade, nas duas páginas")
    try:
        diario = next(s for s in app.screens if s.name == "DIÁRIO")
        # Sem registro a tela cai no "nada anotado" e a segunda página nunca é
        # desenhada — que é justamente onde mora todo o desenho novo.
        alvo = os.path.join(os.environ["HOME"], ".local", "share", "stylus")
        os.makedirs(alvo, exist_ok=True)
        agora = time.time()
        with open(os.path.join(alvo, "plays.tsv"), "w", encoding="utf-8") as fh:
            for i, it in enumerate(app.shelf.items or []):
                for k in range(3):
                    fh.write(f"{int(agora - (i * 5 + k) * 86400)}\t"
                             f"{it['artist']}\t{it['name']}\t{it['folder']}\n")
        diario.enter()
        if not diario.rows:
            bad("o diário não leu o registro que acabamos de escrever")
        else:
            ok(f"leu o registro ({len(diario.rows)} discos)")
            diario.page = 0
            diario.draw(app.surf, corpo)
            ok("a lista desenha")
            diario.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s,
                                          unicode="s", mod=0))
            if diario.page != 1:
                bad("o s não virou a página")
            diario.draw(app.surf, corpo)
            ok("o formato desenha")
            # Sem nenhuma hora ou dia zerado o desenho nunca exercita o caminho
            # do valor zero, que é o que costuma dividir por zero.
            diario.by_hour = [0] * 24
            diario.by_wd = [0] * 7
            diario.by_artist = {}
            diario.draw(app.surf, corpo)
            ok("o formato desenha mesmo com tudo zerado")
            diario.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s,
                                          unicode="s", mod=0))
            if diario.page != 0:
                bad("o s não voltou para a lista")
            else:
                ok("s vai e volta")
    except Exception:                                       # noqa: BLE001
        bad("diário", traceback.format_exc())

    secao("virar o lado aparece na tela, e só para frente")
    try:
        class _Disco:
            folder = "/mentira/Artista/Disco"
            artist = "Artista"
            name = "Disco"
            total = 2400.0
            sides = [{"label": "SIDE A", "start": 0, "end": 1200},
                     {"label": "SIDE B", "start": 1200, "end": 2400}]

            def side_for(self, t):
                i = 1 if t >= 1200 else 0
                return i, self.sides[i]

        disco = _Disco()
        # Um segundo disco, para conferir que trocar de disco não conta como
        # virar o lado: o lado A do próximo não é o lado B do anterior.
        outro = _Disco()
        outro.folder = "/mentira/Outro/Disco"

        estado = {"al": disco, "t": 10.0}
        app.playing.where = lambda: (
            {}, estado["al"], None,
            estado["al"].side_for(estado["t"])[1], estado["t"], 0.0)

        def olhar():
            app._lado_t = 0.0            # o vigia anda a cada meio segundo
            app._watch_side()

        app._flip = None
        olhar()                                        # lado A, primeira vez
        if app._flip:
            bad("avisou sem o lado ter virado")
        estado["t"] = 1500.0
        olhar()                                        # A -> B
        if not app._flip:
            bad("o lado virou e a tela não disse nada")
        else:
            ok("A -> B avisa")
            app._draw_flip(app.surf)
            ok("o aviso desenha")
            # a tecla dispensa o aviso e NÃO atravessa para a seção
            r = app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT,
                                            unicode="", mod=0))
            if app._flip or r == "quit":
                bad("a tecla não dispensou o aviso")
            else:
                ok("qualquer tecla dispensa")

        estado["t"] = 10.0
        olhar()                                        # voltou: procurando faixa
        if app._flip:
            bad("voltar no tempo foi tratado como virar o disco")
        else:
            ok("voltar no tempo não avisa")

        olhar(); olhar()                               # mesmo lado, de novo
        if app._flip:
            bad("o mesmo lado avisou duas vezes")
        else:
            ok("o mesmo lado não repete")

        estado["al"], estado["t"] = outro, 1500.0
        olhar()
        if app._flip:
            bad("trocar de disco contou como virar o lado")
        else:
            ok("disco novo recomeça a contar")

        # e o aviso some sozinho depois do tempo dele
        app._flip = (time.time() - app.FLIP_DUR - 1, "LADO A", "LADO B", "x", False)
        app._draw_flip(app.surf)
        if app._flip:
            bad("o aviso não sumiu sozinho")
        else:
            ok("some sozinho depois de alguns segundos")
    except Exception:                                       # noqa: BLE001
        bad("virar o lado", traceback.format_exc())

    secao("INSTALAR só existe no medium ao vivo")
    try:
        tinha = any(s.name == "INSTALAR" for s in app.screens)
        if A.rodando_do_pendrive():
            ok("estamos num medium ao vivo; a seção existe" if tinha
               else "deveria existir e não existe")
            if not tinha:
                FAIL_MARK = True          # noqa: F841
                bad("INSTALAR faltando num medium ao vivo")
        elif tinha:
            bad("INSTALAR apareceu numa máquina instalada")
        else:
            ok("máquina instalada: a seção não aparece")
        real = A.rodando_do_pendrive
        A.rodando_do_pendrive = lambda: True
        vivo = A.App()
        if vivo.screens[0].name == "INSTALAR" and vivo.cur == 0:
            ok("no pendrive ela é a primeira, e é onde a interface abre")
        else:
            bad("no pendrive a interface não abre em INSTALAR")
        vivo.screens[0].draw(vivo.surf, corpo)
        ok("INSTALAR desenha")
        A.rodando_do_pendrive = real
    except Exception:                                       # noqa: BLE001
        bad("INSTALAR", traceback.format_exc())

    pygame.quit()
    print()
    if FAIL:
        print(f"  {G}{PASS} passaram{Z}, {R}{FAIL} falharam{Z}\n")
    else:
        print(f"  {G}{PASS} passaram{Z}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
