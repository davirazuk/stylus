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
              pygame.K_HOME, pygame.K_END,
              # `d` baixa na loja do Qobuz e `c` abre o formulário de conta.
              # Só entraram na lista depois que o Job e o `rodar` viraram de
              # mentira: antes, apertar `d` aqui teria começado um download de
              # verdade, e `c` seguido de ENTER teria falado com o servidor.
              pygame.K_d, pygame.K_c]

    secao("cada seção desenha e aguenta o teclado")
    # Nada aqui pode lançar processo de verdade. A varredura aperta ENTER em
    # TODAS as telas — e a de JOGOS, no ENTER, abre Steam em Big Picture:
    # quatro rodadas deste teste chegaram a descompactar ~13 GB de Steam
    # dentro da pasta de mentira até estourar a cota do /tmp. E as teclas
    # novas da AGORA falam com playerctl/pamixer da sessão REAL. Gravar os
    # comandos em vez de executá-los mantém a cobertura e torna o teste
    # hermético.
    spawn_reais = []
    # Sem guardar o original de propósito: a troca vale pelo processo inteiro.
    # O resto do teste continua desenhando e apertando tecla depois daqui, e
    # devolver o de verdade no meio abriria de novo a porta que acabamos de
    # fechar.
    A.spawn = lambda cmd, *a, **k: spawn_reais.append(cmd)

    # O Job também, e pelo mesmo motivo do spawn.
    #
    # O spawn estava grampeado desde a lição do Steam, mas o Job NÃO — e três
    # seções lançam comando de verdade por ele no ENTER: OFICINA (`stylus
    # check`, `stylus covers --apply`, `stylus rip`…), CELULAR (`stylus-phone
    # sync --apply`) e AJUSTES. A varredura aperta ENTER em todas as telas.
    # Hoje escapa por acidente de ordenação — a primeira ação de cada lista é
    # de só-leitura — e no dia em que alguém reordenar a lista da OFICINA para
    # pôr "pôr cover.jpg onde falta" na frente, este teste passa a ESCREVER
    # na coleção de verdade, que não tem cópia em lugar nenhum.
    #
    # Um teste que aperta tudo precisa interceptar tudo que lança processo.
    class JobDeMentira:
        def __init__(self, cmd, title):
            self.cmd, self.title = cmd, title
            self.lines, self.done, self.rc = ["(gravado, não executado)"], True, 0
            spawn_reais.append(cmd)

    A.Job = JobDeMentira

    # E o `rodar`, que é por onde o formulário de conta chama o comando que
    # autentica. Sem grampeá-lo, a varredura de teclas — que aperta `c` e
    # depois ENTER em todas as telas — chegaria a rodar `stylus-qobuz entrar`
    # de verdade contra o servidor do Qobuz.
    class _Resposta:
        def __init__(self, out): self.stdout, self.stderr, self.returncode = out, "", 0
    A.rodar = lambda cmd, **k: (spawn_reais.append(cmd),
                                _Resposta('{"ok": true}'))[1]
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

    # Uma tela que lança processo e NÃO passa por aqui é uma tela que o teste
    # não protege. Se nenhuma passar, a interceptação parou de morder.
    esperados = {"stylus check", "stylus-phone status"}
    vistos = {" ".join(c) if isinstance(c, list) else str(c)
              for c in spawn_reais}
    if esperados & vistos:
        ok(f"o Job foi interceptado ({len(esperados & vistos)} de "
           f"{len(esperados)} conhecidos)")
    else:
        bad("o ENTER não chegou a nenhum Job conhecido — "
            "a interceptação pode ter parado de morder")

    secao("entrar numa conta sem sair da tela")
    try:
        enviados = []

        class _R:
            stdout, stderr, returncode = '{"ok": true, "assinatura": "Studio"}', "", 0

        A.rodar = lambda cmd, **k: (enviados.append((cmd, k.get("input", ""))), _R())[1]
        loja = next(x for x in app.screens if x.name == "QOBUZ")
        app._goto(app.screens.index(loja))
        # A varredura anterior deixou a tela em modo de busca (ela aperta
        # `/`), e ali `c` é letra, não atalho — que é o certo. Zera antes.
        loja.entrada, loja.searching, loja.query = None, False, ""
        loja.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c, unicode="c", mod=0))
        if loja.entrada is None:
            bad("o [c] não abriu o formulário")
        else:
            ok("o [c] abre o formulário")
            for ch in "eu@exemplo.com":
                loja.key(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=ch, mod=0))
            loja.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, unicode="", mod=0))
            for ch in "segredo":
                loja.key(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=ch, mod=0))
            # A tela de trás não pode reagir: o formulário é modal, e uma
            # tecla que escape dali mexe na grade que está atrás dele.
            if loja.query:
                bad(f"a tela de trás recebeu o que foi digitado: {loja.query!r}")
            else:
                ok("o que se digita fica no formulário, não vaza para a tela")
            loja.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))
            for _ in range(40):
                if enviados:
                    break
                time.sleep(0.05)
            if not enviados:
                bad("o ENTER não enviou nada")
            else:
                cmd, entrada = enviados[-1]
                if "senha" in " ".join(cmd) or "segredo" in " ".join(cmd):
                    bad(f"a senha foi por ARGUMENTO, visível no ps: {cmd}")
                elif "segredo" not in entrada:
                    bad("a senha não chegou pelo stdin")
                else:
                    ok("a senha vai pelo stdin, nunca por argumento")
        # e desenhar com o formulário aberto não pode estourar
        loja.draw(app.surf, corpo)
        ok("desenha com o formulário aberto")

        # O dígito, vindo pela rota DE VERDADE (o App._key global, não o
        # key() da tela): era o atalho 1-9 de trocar de seção que comia o
        # número antes do formulário ver. Com o formulário aberto, o 7 tem
        # que cair no campo de senha e não mexer na seção.
        loja.entrada = A.Formulario("t", [("a", "", False), ("b", "", True)],
                                    ["x"], ao_terminar=lambda *_: None)
        cur_antes = app.cur
        app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_8, unicode="8", mod=0))
        if app.cur != cur_antes:
            bad("o dígito mudou de seção durante o formulário")
        elif not loja.entrada.valores[loja.sel].endswith("8"):
            bad("o dígito não chegou ao campo do formulário")
        else:
            ok("o dígito fica no formulário, não troca de seção")
        app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0))
        if loja.entrada is not None:
            bad("o ESC não fechou o formulário")
        else:
            ok("o ESC fecha o formulário")

        loja.entrada = None
    except Exception:                                       # noqa: BLE001
        bad("formulário de conta", traceback.format_exc())

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
            # Os campos todos, não só os que o teste do lado usa: este objeto
            # fica no app.playing pelo resto da rodada, e QUALQUER seção que
            # desenhe depois vai perguntar por eles. Um fake incompleto vira
            # AttributeError num teste que não tem nada a ver com este.
            folder = "/mentira/Artista/Disco"
            artist = "Artista"
            name = "Disco"
            total = 2400.0
            cover = None
            year = 1969
            duration = 2400.0
            plays = 0
            last_played = 0.0
            tracks = []
            sides = [{"label": "SIDE A", "start": 0, "end": 1200},
                     {"label": "SIDE B", "start": 1200, "end": 2400}]

            def lyrics_for(self, *a, **k):
                return None

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

    secao("colchete em nome de disco não vira tecla")
    # **Sintoma:** a linha de dicas monta "[enter] põe  [s] empilha…" e o
    # `[X]` vira um quadradinho de tecla. A estante montava a linha inteira
    # numa f-string, com o nome do disco junto — e disco baixado se chama
    # "Radiohead - Live From The Basement [FLAC]". O [FLAC] do NOME DO
    # ARQUIVO virava tecla no meio da frase.
    #
    # A regra que isto guarda: marcação só vale em texto que o repositório
    # escreveu. Dado de usuário entra pelo `contexto=`, que nunca é lido.
    try:
        import theme as _T
        original_tec = _T.tecla
        teclas_vistas = []
        _T.tecla = lambda surf, letra, pos, size=18, anchor="topleft", \
            cor=None: (teclas_vistas.append(str(letra)),
                       original_tec(surf, letra, pos, size, anchor, cor))[1]
        teclas_vistas.clear()
        app.hint(app.surf, corpo, "[enter] põe   [s] empilha",
                 contexto="Radiohead - Live From The Basement [FLAC] [2008]")
        _T.tecla = original_tec
        intrusas = [t for t in teclas_vistas if t.lower() not in ("enter", "s")]
        if intrusas:
            bad("o nome do disco virou tecla", ", ".join(intrusas))
        else:
            ok(f"[FLAC] e [2008] ficaram texto; só {teclas_vistas} viraram tecla")
    except Exception:                                       # noqa: BLE001
        bad("colchete em nome de disco", traceback.format_exc())

    secao("nenhum rótulo de ação cortado")
    # As listas de ação da OFICINA e do CELULAR são frases curtas e fixas —
    # cabem, ou o layout está errado. **Sintoma:** a coluna tinha 470 px
    # fixos e três rótulos viravam "pôr a coleção do celular na es…", com o
    # painel de saída ao lado ocupando 760 px e vazio.
    #
    # Nome de disco cortado é outra coisa e é correto; por isso a conferência
    # é só destas duas telas, cujo texto o repositório escolheu.
    try:
        import theme as _T
        original = _T.text
        cortados = []

        def espiao_corte(surf, txt, pos, size=20, colour=_T.TEXT, bold=False,
                         anchor="topleft", maxw=None):
            if maxw and _T.font(size, bold).size(str(txt))[0] > maxw:
                cortados.append(str(txt))
            return original(surf, txt, pos, size, colour, bold, anchor, maxw)

        _T.text = espiao_corte
        for i, tela in enumerate(app.screens):
            if tela.name not in ("OFICINA", "CELULAR"):
                continue
            # Só os rótulos que o repositório escreveu. O painel de saída ao
            # lado mostra o que o comando imprimiu, e ali cortar é o certo:
            # linha de saída de programa não tem tamanho previsível.
            rotulos = {a[0] for a in tela.ACOES}
            app._goto(i)
            cortados.clear()
            # Em TODA largura de tela que o sistema pode encontrar: a de
            # notebook é onde a coluna aperta primeiro.
            for larg in (1280, 1600, 1920, 3840):
                corpo_l = pygame.Rect(230, 0, larg - 230, 800)
                app.screens[i].draw(app.surf, corpo_l)
            cortados[:] = [c for c in cortados if c in rotulos]
            if cortados:
                bad(f"{tela.name}: {len(cortados)} rótulos cortados",
                    "\n".join(sorted(set(cortados))[:4]))
            else:
                ok(f"{tela.name}: nada cortado de 1280 a 3840 px")
        _T.text = original
    except Exception:                                       # noqa: BLE001
        bad("conferência de corte", traceback.format_exc())

    secao("nenhum texto por cima de outro texto")
    # POR QUE ISTO EXISTE
    # -------------------
    # Na tela SINAL, o nome do conversor entrava por cima do "pode trocar de
    # taxa": a folga entre o texto da esquerda e o valor encostado à direita
    # era um número fixo, e o valor mais largo passava dele. Colisão de texto
    # não estoura, não vira traceback, não aparece em teste nenhum — ela só
    # fica FEIA, e só na máquina de quem tem o nome de placa comprido.
    #
    # Então em vez de conferir uma tela, confere-se a CLASSE: espiona todo
    # T.text de todas as seções e reclama de dois retângulos que se cruzam.
    try:
        import theme as _T
        original = _T.text
        caixas = []

        def espiao(surf, txt, pos, size=20, colour=_T.TEXT, bold=False,
                   anchor="topleft", maxw=None):
            r = original(surf, txt, pos, size, colour, bold, anchor, maxw)
            if str(txt).strip():
                caixas.append((r.copy(), str(txt)))
            return r

        _T.text = espiao
        # Um conversor de nome comprido, que é o caso que quebrava. Sem forçar
        # isto o teste roda com o "—" de máquina sem áudio e não mede nada.
        for tela in app.screens:
            if tela.name == "SINAL":
                tela.info = {"file": "faixa.flac", "frate": 44100,
                             "graph": 48000, "fbits": 24, "codec": "FLAC",
                             "dev": "Meteor Lake-P HD Audio Controller Speaker",
                             "multi": True}
        batidas, vazados = [], []
        # Em QUATRO tamanhos de tela. O layout do diário era uma altura fixa
        # de 104 px numa posição fixa: numa tela de 720 o calendário entrava
        # na lista, e nada disso aparece medindo só a resolução do
        # desenvolvedor. Da tela de notebook barato à de 4K.
        for larg, alt in ((1280, 720), (1366, 768), (1920, 1080), (3840, 2160)):
            quadro = pygame.Rect(230, 0, larg - 230, alt)
            for i, tela in enumerate(app.screens):
                app._goto(i)
                caixas.clear()
                app.screens[i].draw(app.surf, quadro)
                for a in range(len(caixas)):
                    for b in range(a + 1, len(caixas)):
                        ra, sa = caixas[a]
                        rb, sb = caixas[b]
                        cruz = ra.clip(rb)
                        # Precisa cruzar de verdade: alguns px de sobra são
                        # só acento de letra encostando na linha de cima.
                        if cruz.w > 3 and cruz.h > ra.h * 0.4:
                            batidas.append(f"{larg}x{alt} {tela.name}: "
                                           f"{sa[:26]!r} x {sb[:26]!r}")
                # E nada pode ser desenhado fora da tela — que é como um
                # layout apertado falha antes de chegar a se sobrepor.
                for rr, ss in caixas:
                    if rr.bottom > alt + 2 or rr.y < -2:
                        vazados.append(f"{larg}x{alt} {tela.name}: {ss[:26]!r}")
        _T.text = original
        if batidas:
            bad(f"{len(batidas)} textos se cruzam", "\n".join(batidas[:5]))
        else:
            ok(f"{len(app.screens)} seções × 4 resoluções, nada por cima de nada")
        if vazados:
            bad(f"{len(vazados)} textos fora da tela", "\n".join(vazados[:5]))
        else:
            ok("nada desenhado fora da tela")
    except Exception:                                       # noqa: BLE001
        bad("conferência de colisão", traceback.format_exc())

    # ── outros alfabetos ──────────────────────────────────────────────────
    secao("outros alfabetos")
    try:
        import theme as _T
        principal = _T._arquivo_principal()
        caixinhas, trocas = [], []
        for amostra, nome in (("Kid A", "latino"), ("Привет", "cirílico"),
                              ("Ελληνικά", "grego"), ("日本語のアルバム", "japonês"),
                              ("한국어", "coreano"), ("中文專輯", "chinês"),
                              ("עברית", "hebraico"), ("ไทย", "tailandês")):
            f = _T.fonte_para(amostra, 22)
            # A pergunta que importa não é "escolheu outra fonte", é "o que
            # sai na tela é o nome do disco ou é o retângulo vazio". Um disco
            # japonês virava uma fileira de caixinhas, e o nome é a única
            # coisa que a grade tem para dizer qual disco é.
            if _T._assinatura(f, amostra[0]) == _T._assinatura(f, _T._NADA):
                caixinhas.append("%s (%s)" % (nome, amostra))
            arq = [k for k, v in _T._cache.items() if v is f]
            if arq and arq[0][0] != principal:
                trocas.append(nome)
        if caixinhas:
            bad(f"{len(caixinhas)} alfabetos saem como caixinha",
                ", ".join(caixinhas))
        else:
            ok("oito alfabetos desenham de verdade")
        # E o latino/cirílico/grego NÃO podem trocar de fonte: a nossa os tem,
        # e trocar por trocar mudaria o desenho da tela inteira.
        if "latino" in trocas or "cirílico" in trocas or "grego" in trocas:
            bad("trocou de fonte onde não precisava", ", ".join(trocas))
        else:
            ok("só troca de fonte quem precisa (%s)"
               % (", ".join(trocas) or "ninguém"))
        # E o custo tem que caber num quadro: isto roda por texto desenhado.
        t0 = time.time()
        for _ in range(20000):
            _T.fonte_para("Radiohead — Kid A", 22)
        gasto = time.time() - t0
        if gasto > 0.5:
            bad("escolher fonte custa caro", f"20 mil chamadas em {gasto:.2f}s")
        else:
            ok(f"20 mil escolhas de fonte em {gasto*1000:.0f} ms")
    except Exception:                                       # noqa: BLE001
        bad("conferência de alfabetos", traceback.format_exc())

    # ── o custo de um quadro ──────────────────────────────────────────────
    secao("o custo de um quadro")
    try:
        import theme as _T
        # 1. Superfície em cache com alfa-de-superfície 255 é o caminho lento
        #    do SDL: ele multiplica o 255 em cada pixel em vez de pular.
        #    Medido num halo de 1040 px: 1,09 ms contra 0,30 ms no mesmo blit.
        #    É invisível na leitura e são três quartos do custo.
        lentas = []
        for nome, sup2 in (("halo", _T.halo(300, forca=192)),
                           ("disco", _T.disco(300))):
            if sup2.get_alpha() is not None:
                lentas.append("%s (alpha=%s)" % (nome, sup2.get_alpha()))
        if lentas:
            bad("superfície em cache no caminho lento do SDL", ", ".join(lentas))
        else:
            ok("as superfícies em cache saem do caminho lento")

        # 2. O cache do halo tem que caber os degraus de força. Se não couber,
        #    ele se limpa a cada respiração e cada quadro redesenha um halo do
        #    zero — 7,7 ms, mais caro do que o set_alpha que se veio tirar.
        _T._halo_cache.clear()
        for _ in range(3):
            for nivel in (90, 150, 210, 255):
                _T.halo(300, forca=nivel)
        if len(_T._halo_cache) < 3:
            bad("o cache do halo se esvaziou", f"{len(_T._halo_cache)} entradas")
        else:
            ok(f"os {len(_T._halo_cache)} degraus de brilho ficam em cache")

        # 3. E o quadro inteiro tem que caber em 60 fps com folga.
        t0 = time.time()
        for k in range(200):
            _T.halo(300, forca=90 + (k % 4) * 55)
            _T.disco(300)
        gasto = (time.time() - t0) / 200 * 1000
        if gasto > 1.0:
            bad("halo e disco custam caro", f"{gasto:.2f} ms/quadro")
        else:
            ok(f"halo e disco em cache: {gasto*1000:.0f} µs/quadro")
    except Exception:                                       # noqa: BLE001
        bad("conferência de custo", traceback.format_exc())

    # ── o rato ────────────────────────────────────────────────────────────
    secao("o rato")
    try:
        # 1. Um clique só ESCOLHE; o segundo, no mesmo lugar, é que abre.
        #    Num sistema em que abrir significa pôr um disco, clique único que
        #    já toca é alto demais para quem só estava mirando.
        app.cur = 0
        app.alvos = [(pygame.Rect(10, 10, 40, 40), 3)]
        app._alvos_do_trilho = []
        tela = app.screens[0]
        antes = getattr(tela, "sel", 0)
        tela.sel = 0
        pygame.event.clear()
        app._clique(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20),
                                       button=1))
        if tela.sel != 3:
            bad("clique não escolhe", f"sel ficou {tela.sel}, esperado 3")
        elif [e for e in pygame.event.get() if e.type == pygame.KEYDOWN]:
            bad("clique único já abriu", "devia só escolher")
        else:
            ok("um clique escolhe, sem abrir")
        pygame.event.clear()
        app._clique(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20),
                                       button=1))
        teclas = [e.key for e in pygame.event.get() if e.type == pygame.KEYDOWN]
        if pygame.K_RETURN in teclas:
            ok("o segundo clique abre")
        else:
            bad("segundo clique não abriu", str(teclas))
        tela.sel = antes

        # 2. O botão da direita é o ESC — a mesma volta, sem inventar outra.
        pygame.event.clear()
        app._clique(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20),
                                       button=3))
        teclas = [e.key for e in pygame.event.get() if e.type == pygame.KEYDOWN]
        if pygame.K_ESCAPE in teclas:
            ok("botão direito volta")
        else:
            bad("botão direito não voltou", str(teclas))

        # 3. Clique fora de qualquer alvo não faz nada. Um clique no vazio que
        #    abre o último item escolhido é o pior tipo de surpresa.
        pygame.event.clear()
        app.alvos = [(pygame.Rect(10, 10, 40, 40), 3)]
        app._clique(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(900, 900),
                                       button=1))
        if [e for e in pygame.event.get() if e.type == pygame.KEYDOWN]:
            bad("clique no vazio fez alguma coisa")
        else:
            ok("clique no vazio não faz nada")

        # 4. O cursor acende ao mexer e some sozinho. Ele nascia escondido
        #    PARA SEMPRE, e numa mesa isso se lê como a tela travada.
        app._rato_visivel = False
        app._rato_mexeu((100, 100))
        acendeu = app._rato_visivel
        app._rato_t -= app.RATO_SOME + 1
        app._rato_pisca()
        if acendeu and not app._rato_visivel:
            ok("o cursor acende ao mexer e some parado")
        else:
            bad("o cursor não acende ou não some",
                f"acendeu={acendeu} visível={app._rato_visivel}")

        # 5. Toda tela que desenha grade tem que ANOTAR os alvos, senão o
        #    clique cai no vazio e o rato "não funciona" só naquela seção.
        sem_alvo = []
        for i, tela in enumerate(app.screens):
            app.cur = i
            app.alvos = []
            app._alvos_do_trilho = []
            try:
                tela.draw(app.surf, pygame.Rect(240, 0, 1280 - 240, 800))
            except Exception:                               # noqa: BLE001
                continue
            # Só cobra de quem TEM o que clicar agora: a loja desenhada sem
            # conta e a pilha vazia não têm item nenhum na tela, e exigir
            # alvo delas seria uma conferência que reprova o estado correto.
            itens = 0
            for campo in ("results", "ACOES", "items", "rows"):
                v = getattr(tela, campo, None)
                if isinstance(v, (list, tuple)):
                    itens = max(itens, len(v))
            if hasattr(tela, "sel") and itens and not app.alvos:
                sem_alvo.append(tela.name)
        if sem_alvo:
            bad(f"{len(sem_alvo)} seções com seleção e sem alvo de rato",
                ", ".join(sem_alvo))
        else:
            ok("toda seção com seleção responde ao clique")
    except Exception:                                       # noqa: BLE001
        bad("conferência do rato", traceback.format_exc())

    pygame.quit()
    print()
    if FAIL:
        print(f"  {G}{PASS} passaram{Z}, {R}{FAIL} falharam{Z}\n")
    else:
        print(f"  {G}{PASS} passaram{Z}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
