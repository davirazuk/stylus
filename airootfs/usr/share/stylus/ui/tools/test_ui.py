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
mesmo tipo de rede do teste da biblioteca: roda em segundos e pega o traceback que
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
    """Quatro discos com capa, o suficiente para a grade ter o que desenhar.

    Os dois últimos têm nome COMPRIDO de propósito. Os dois primeiros — que
    eram a estante inteira do teste — cabem em qualquer canto, e é o
    comprimento que revela folga fixa e piso que não cabe: com eles, a
    conferência de colisão mede a estante, o diário e a pilha como se todo
    disco do mundo se chamasse "Abbey Road".
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    for artista, album in (("The Beatles", "Abbey Road"),
                           ("Radiohead", "OK Computer"),
                           ("Godspeed You! Black Emperor",
                            "Lift Your Skinny Fists Like Antennas to Heaven"),
                           ("Sigur Rós", "Ágætis byrjun (edição de aniversário)")):
        d = os.path.join(base, artista, album)
        os.makedirs(d, exist_ok=True)
        Image.new("RGB", (300, 300), (80, 120, 180)).save(
            os.path.join(d, "cover.jpg"))
        for i in range(1, 6):
            open(os.path.join(d, f"{i:02d} faixa.flac"), "wb").write(b"\0" * 32)
    # Uma PLAYLIST, com nome comprido pela mesma razão dos discos: a estante
    # passou a mostrá-las na ordem "listas", e uma tela medida sem elas é uma
    # tela não medida. Caminho relativo de propósito — é como um .m3u de
    # verdade é escrito.
    with open(os.path.join(base, "Shoegaze & Dreampop para dormir.m3u"),
              "w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for i in range(1, 4):
            fh.write(f"Radiohead/OK Computer/{i:02d} faixa.flac\n")
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
    sys.path.insert(0, os.path.join(raiz, "lib"))
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

    def encher_as_lojas(app):
        """AS DUAS LOJAS COM DISCO DENTRO.

        Elas eram exercitadas VAZIAS: sem rede, `results` fica em [] e o
        desenho para no "[/] procura um disco". A grade, que é a tela
        inteira, não era medida nem apertada por ninguém — e é onde estavam
        as duas colisões que esta chamada achou de cara (o nome do disco por
        baixo da duração, na legenda da faixa e na barra do que está
        tocando). Mesma lição da AGORA com o prato vazio.

        Nomes compridos de propósito: é o comprimento que revela folga fixa.

        Também LIMPA o que estiver aberto por cima (o painel de saída de um
        comando, o cartão de examinar, o formulário de conta) e o estado de
        "estou procurando". Isso não é arrumação: a varredura de teclado
        deixa os três abertos, e eles são desenhados POR CIMA do corpo de
        propósito — medir colisão de texto com um deles no ar acusa como
        defeito o desenho certo.

        DUAS VOLTAS, com uma pausa entre elas. Apertar `/` e depois ENTER
        numa loja começa uma busca de VERDADE, numa thread; ela falha na hora
        (não há `stylus-spotify` aqui) e, ao voltar, zera o `results` e
        acende o `error` — DEPOIS de a arrumação ter acontecido. A seção
        seguinte media então uma tela que não desenhou grade nenhuma, e só às
        vezes: uma rodada em cada três.
        """
        disco = {
            "id": "1", "display_title": "Um Disco De Nome Bastante Comprido",
            "display_subtitle": "Um Artista De Nome Também Comprido",
            "release_year": "1969", "tracks": 12, "quality": "24/192",
            "hires": True, "cover": None,
            "url": "https://play.qobuz.com/album/1"}
        faixa = {
            "name": "Uma Faixa De Nome Bastante Comprido Também",
            "artist": "Um Artista De Nome Comprido",
            "album": "Um Disco De Nome Bastante Comprido Igualmente",
            "duration": "12:34", "uri": "spotify:track:1"}
        for volta in (1, 2):
            if volta == 2:
                time.sleep(0.2)          # as threads da busca voltam aqui
            for tela in app.screens:
                for campo in ("job", "entrada", "examing", "_setup"):
                    if hasattr(tela, campo):
                        setattr(tela, campo, None)
                for campo, valor in (("loading", False), ("searching", False),
                                     ("query", ""), ("error", None)):
                    if hasattr(tela, campo):
                        setattr(tela, campo, valor)
                if tela.name == "QOBUZ":
                    tela.results = [dict(disco, id=str(i))
                                    for i in range(12)]
                    tela.favoritos = True
                if tela.name == "SPOTIFY":
                    tela.results = [dict(faixa) for _ in range(12)]
                    tela._daemon, tela._daemon_ok = "ok", True
                    tela._np_t = time.time() + 1e6   # não pergunta ao sistema
                    tela._now_playing = {
                        "artist": "Um Artista De Nome Comprido",
                        "title": "Uma Faixa De Nome Bastante Comprido",
                        "album": "Um Disco De Nome Bastante Comprido",
                        "position": "1:23", "duration": "12:34"}

    # Todas as teclas que alguma seção usa. Manda-se TODAS em TODAS: a que a
    # seção não conhece tem que ser devolvida, não estourar.
    teclas = [pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
              pygame.K_h, pygame.K_j, pygame.K_k, pygame.K_l,
              pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE,
              pygame.K_s, pygame.K_r, pygame.K_o, pygame.K_t, pygame.K_x,
              pygame.K_n, pygame.K_p, pygame.K_SLASH, pygame.K_DELETE,
              pygame.K_BACKSPACE, pygame.K_PAGEUP, pygame.K_PAGEDOWN,
              pygame.K_HOME, pygame.K_END,
              # `e` embaralha a pilha.
              pygame.K_e,
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

    secao("toda seção diz o que as teclas fazem")
    # **Sintoma:** a AJUSTES não tinha linha de dicas. Todas as outras têm, e
    # justamente a seção que troca a pasta da coleção, o driver de vídeo e
    # roda o atualizador não dizia nada — com duas das seis linhas sendo
    # informação e não botão, "não aconteceu nada" ao apertar ENTER era um
    # resultado ainda mais confuso.
    #
    # Ler não pega: nenhuma seção é obrigada a chamar o `hint`, e a falta não
    # é erro em lugar nenhum. A pergunta é sobre o RESULTADO: esta tela
    # desenhou alguma TECLA — o quadradinho do `frase_com_teclas`, que é como
    # este sistema escreve atalho — ou é uma tela vazia, que se explica
    # sozinha pelo `T.vazio`?
    try:
        import theme as _T
        original_f, original_v = _T.frase_com_teclas, _T.vazio
        visto = {"teclas": 0, "vazio": 0}

        def espia_f(*a, **k):
            visto["teclas"] += 1
            return original_f(*a, **k)

        def espia_v(*a, **k):
            visto["vazio"] += 1
            return original_v(*a, **k)

        _T.frase_com_teclas, _T.vazio = espia_f, espia_v
        quadro_h = pygame.Rect(230, 0, app.W - 230, app.H)
        mudas = []
        for i, tela in enumerate(app.screens):
            app._goto(i)
            visto["teclas"] = visto["vazio"] = 0
            tela.draw(app.surf, quadro_h)
            if not visto["teclas"] and not visto["vazio"]:
                mudas.append(tela.name)
        _T.frase_com_teclas, _T.vazio = original_f, original_v
        if mudas:
            bad("%d seções não mostram tecla nenhuma" % len(mudas),
                ", ".join(mudas))
        else:
            ok("as %d seções dizem o que as teclas fazem" % len(app.screens))
    except Exception:                                       # noqa: BLE001
        bad("linha de dicas", traceback.format_exc())

    secao("a estante anuncia tudo que ela faz")
    # **Sintoma:** o [r] (sorteia um disco da prateleira) e o [f] (favorito)
    # existiam desde sempre e não apareciam em lugar nenhum da tela. É o
    # defeito do i3 ao contrário — lá a área de trabalho prometia comando que
    # não existia; aqui a tela escondia o que existe.
    #
    # A conferência é sobre a ESTANTE porque é a seção que o teste consegue
    # encher de verdade: com discos, o rodapé dela é o de sempre. As teclas
    # do par vim (h/j/k/l) ficam de fora de propósito — quem é anunciado é a
    # seta, e anunciar as duas encheria a linha com a mesma coisa duas vezes.
    try:
        import inspect
        import re as _re
        import theme as _T
        estante = next(s for s in app.screens if s.name == "ESTANTE")
        if estante.picking or estante.searching:
            estante.key(pygame.event.Event(pygame.KEYDOWN,
                                           key=pygame.K_ESCAPE, unicode="",
                                           mod=0))
        estante.artist = None
        if not estante.items():
            ok("(estante vazia: nada para anunciar)")
        else:
            original_f, original_t = _T.frase_com_teclas, _T.text
            ditas = set()

            def _colhe(txt):
                for m in _re.finditer(r"\[([^\]]{1,6})\]", str(txt)):
                    ditas.add(m.group(1).lower())

            def _f(surf, txt, pos, size=18, colour=_T.TEXT_DIM,
                   anchor="topleft", cor_tecla=None):
                _colhe(txt)
                return original_f(surf, txt, pos, size, colour, anchor,
                                  cor_tecla)

            def _t(surf, txt, pos, size=20, colour=_T.TEXT, bold=False,
                   anchor="topleft", maxw=None):
                _colhe(txt)
                return original_t(surf, txt, pos, size, colour, bold, anchor,
                                  maxw)

            _T.frase_com_teclas, _T.text = _f, _t
            app._goto(app.screens.index(estante))
            # Numa tela larga: a linha de dicas encolhe quando não cabe, e o
            # que se confere aqui é o que ela DIZ quando cabe tudo.
            estante.draw(app.surf, pygame.Rect(230, 0, 3840 - 230, 2160))
            _T.frase_com_teclas, _T.text = original_f, original_t

            fonte = inspect.getsource(type(estante).key)
            trata = set(_re.findall(r"pygame\.K_([a-z])\b", fonte))
            vim = {"h", "j", "k", "l"}
            caladas = sorted(trata - ditas - vim)
            if caladas:
                bad("a estante faz e não anuncia: %s" % " ".join(caladas),
                    "anuncia: %s" % " ".join(sorted(ditas)))
            else:
                ok("as %d teclas da estante estão todas na tela"
                   % len(trata - vim))
    except Exception:                                       # noqa: BLE001
        bad("teclas anunciadas", traceback.format_exc())

    secao("a estante vazia diz POR QUE está vazia")
    # **Sintoma:** com a ordem em "favoritos" e nenhum disco favoritado — ou
    # com um filtro de artista sem resultado — a estante dizia "a estante
    # está vazia" e mandava rodar `stylus library ~/Music`. Numa coleção de
    # trezentos discos. O recado errado manda a pessoa consertar o que não
    # está quebrado, e o que ela precisava era de uma tecla para desfazer o
    # filtro que ela mesma pôs.
    try:
        import theme as _T
        est = next(s for s in app.screens if s.name == "ESTANTE")
        app._goto(app.screens.index(est))
        _g = (est.order, est.query, est.artist)
        vistos = []
        o_t, o_f = _T.text, _T.frase_com_teclas

        def _et(surf, txt, *a, **k):
            vistos.append(str(txt))
            return o_t(surf, txt, *a, **k)

        def _ef(surf, txt, *a, **k):
            vistos.append(str(txt))
            return o_f(surf, txt, *a, **k)

        casos = [
            ("favoritos", "", None, "favoritado", "[f]"),
            ("artista", "zzzznadaaqui", None, "zzzznadaaqui", "[esc]"),
            ("artista", "", "Ninguém Com Esse Nome", "Ninguém", "[a]"),
        ]
        ruins = []
        try:
            for ordem, busca, artista, quer, tecla in casos:
                est.order, est.query, est.artist = ordem, busca, artista
                vistos.clear()
                _T.text, _T.frase_com_teclas = _et, _ef
                est.draw(app.surf, corpo)
                _T.text, _T.frase_com_teclas = o_t, o_f
                junto = " | ".join(vistos)
                if quer not in junto or tecla not in junto:
                    ruins.append("%s/%s/%s → %s" % (ordem, busca, artista,
                                                    junto[:70]))
                if "stylus library" in junto:
                    ruins.append("%s/%s/%s manda arrumar a biblioteca"
                                 % (ordem, busca, artista))
        finally:
            _T.text, _T.frase_com_teclas = o_t, o_f
            est.order, est.query, est.artist = _g
        if ruins:
            bad("a estante vazia dá o recado errado", "\n".join(ruins[:3]))
        else:
            ok("filtro sem resultado diz qual filtro, e a tecla que o desfaz")
    except Exception:                                       # noqa: BLE001
        bad("a estante vazia", traceback.format_exc())

    secao("a pilha embaralha e muda de ordem")
    # A pilha é a ordem da NOITE, e mudá-la era coisa de esvaziar e empilhar
    # tudo de novo. Duas teclas resolvem: [e] embaralha, ←/→ sobe e desce o
    # disco. E o mesmo cuidado das outras duas teclas desta leva — a de
    # embaralhar tem que MUDAR alguma coisa, não só dizer que mudou.
    try:
        pilha = next(s for s in app.screens if s.name == "A PILHA")
        i_p = app.screens.index(pilha)
        app._goto(i_p)
        app.stack = [{"folder": "/f/%d" % i, "name": "D%d" % i,
                      "artist": "A%d" % i, "cover": "", "mins": 40}
                     for i in range(6)]
        pilha.sel = 0

        def tk(k):
            pilha.key(pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                         mod=0))

        antes = [i["folder"] for i in app.stack]
        tk(pygame.K_e)
        depois = [i["folder"] for i in app.stack]
        if sorted(depois) != sorted(antes):
            bad("embaralhar a pilha perdeu ou inventou disco",
                "%d viraram %d" % (len(antes), len(depois)))
        elif depois == antes:
            bad("[e] não mudou a ordem da pilha")
        else:
            ok("[e] embaralha os %d discos sem perder nenhum" % len(depois))

        # ←/→ trocam de lugar, e a seleção ANDA JUNTO com o disco: mover o
        # disco e ficar com o cursor parado em cima do vizinho é o tipo de
        # controle que faz a pessoa mover duas vezes sem querer.
        pilha.sel = 2
        alvo = app.stack[2]["folder"]
        tk(pygame.K_LEFT)
        if app.stack[1]["folder"] != alvo or pilha.sel != 1:
            bad("← não subiu o disco (ou o cursor não foi junto)",
                "sel=%d" % pilha.sel)
        else:
            tk(pygame.K_RIGHT)
            if app.stack[2]["folder"] != alvo or pilha.sel != 2:
                bad("→ não desceu o disco de volta")
            else:
                ok("←/→ movem o disco e levam o cursor junto")

        # Nas pontas não anda para fora — e não estoura.
        pilha.sel = 0
        tk(pygame.K_LEFT)
        pilha.sel = len(app.stack) - 1
        tk(pygame.K_RIGHT)
        if len(app.stack) != 6:
            bad("mover na ponta mexeu no tamanho da pilha")
        else:
            ok("nas pontas, ←/→ não fazem nada")
        app.stack = []
    except Exception:                                       # noqa: BLE001
        bad("a pilha", traceback.format_exc())

    secao("o disco pára quando a música pára")
    # Um toca-discos parado é a coisa mais visível que existe. O ângulo do
    # reflexo era lido de `time.time()`, e um ângulo lido do relógio não pára:
    # ele salta para onde estaria quando a música volta, como se o disco
    # tivesse girado sozinho no escuro.
    try:
        agora = next(s for s in app.screens if s.name == "AGORA")
        app._goto(app.screens.index(agora))

        class _Alb2:
            folder, artist, name, year = "/x", "A", "B", ""
            cover, plays, last_played, total = None, 1, 0, 400
            tracks = [{"title": "t", "dur": 200}]
            sides = [{"label": "SIDE A", "start": 0, "end": 400,
                      "tracks": [0]}]

        _al = _Alb2()
        _antes = app.playing.where

        def _gira(pausado, n=5):
            app.playing.where = lambda: ({"paused": pausado}, _al,
                                         _al.tracks[0], _al.sides[0],
                                         100.0, 0.25)
            vistos = []
            for _ in range(n):
                agora.draw(app.surf, corpo)
                vistos.append(agora._ang)
                app.clock.tick(60)
            return vistos

        try:
            tocando = _gira(False)
            pausado = _gira(True)
        finally:
            app.playing.where = _antes
        if tocando[0] == tocando[-1]:
            bad("o disco não gira enquanto toca")
        elif pausado[0] != pausado[-1]:
            bad("o disco continua girando com a música pausada")
        else:
            ok("gira tocando, pára pausado")
    except Exception:                                       # noqa: BLE001
        bad("a volta do disco", traceback.format_exc())

    secao("a cerimônia: o prato acelera, a agulha desce")
    # POR QUE ISTO EXISTE
    # -------------------
    # A cerimônia (spinup → cue → drop) é o RITUAL, e o CLAUDE.md §5.5 chama
    # de sagrado: é o que separa "pôr um disco" de "dar play". Era a única
    # coisa que o deck — um programa à parte, com OpenGL e venv — tinha e a
    # tela cheia do lançador não.
    #
    # Ler o código não prova nada aqui: as três fases existem, têm nome, e
    # cada uma faz alguma coisa. A pergunta é sobre o RESULTADO — o prato
    # gira MENOS no começo do que depois, e a agulha só está no sulco quando
    # ela já desceu. É a mesma lição do `[s]` que acendia o ícone e não
    # falava com o mpv.
    try:
        agora = next(s for s in app.screens if s.name == "AGORA")
        app._goto(app.screens.index(agora))

        # ── as fases, na ordem ────────────────────────────────────────────
        # Os instantes vêm das CONSTANTES, não de números escolhidos aqui:
        # as durações são as do vinyl.py (a tela cheia e o stylus-deck encenam a
        # mesma cerimônia), e um teste com o relógio escrito à mão reprova
        # quando alguém afina o ritual em vez de quando ele quebra.
        _sp, _cu, _dr = agora.CER_SPIN, agora.CER_CUE, agora.CER_DROP
        _t = time.monotonic()
        vistas = []
        for atraso in (0.0, _sp * 0.5, _sp + _cu * 0.5,
                       _sp + _cu + _dr * 0.5, _sp + _cu + _dr + 1.0):
            app.cerimonia_t0 = _t - atraso
            vistas.append(agora._cerimonia()[0])
        app.cerimonia_t0 = 0.0
        if vistas != ["spinup", "spinup", "cue", "drop", None]:
            bad("as fases da cerimônia saem fora de ordem", repr(vistas))
        else:
            ok("spinup → cue → drop → tocando, nessa ordem")
        if agora._cerimonia() != (None, 1.0):
            bad("sem cerimônia em curso a tela não volta ao normal")
        else:
            ok("sem disco novo, nenhuma cerimônia")

        # ── o prato ACELERA: o giro do começo é menor que o de regime ─────
        class _AlbCer:
            folder, artist, name, year = "/x", "A", "B", ""
            cover, plays, last_played, total = None, 1, 0, 1680
            discos = 1
            tracks = [{"title": "t", "dur": 210}]
            sides = [{"label": "SIDE A", "start": 0, "end": 840,
                      "tracks": [0]},
                     {"label": "SIDE B", "start": 840, "end": 1680,
                      "tracks": [0]}]

        _ac = _AlbCer()
        _antes = app.playing.where
        app.playing.where = lambda: ({}, _ac, _ac.tracks[0], _ac.sides[0],
                                     100.0, 0.25)

        def _quanto_girou(atraso, quadros=6):
            agora._ang = 0.0
            for _ in range(quadros):
                if atraso is not None:
                    app.cerimonia_t0 = time.monotonic() - atraso
                else:
                    app.cerimonia_t0 = 0.0
                agora.draw(app.surf, corpo)
                app.clock.tick(60)
            return agora._ang

        try:
            comeco = _quanto_girou(0.05)      # logo no início do spinup
            regime = _quanto_girou(None)      # já tocando
        finally:
            app.playing.where = _antes
            app.cerimonia_t0 = 0.0
        if not (0.0 <= comeco < regime * 0.5):
            bad("o prato não acelera: começo=%.4f, regime=%.4f"
                % (comeco, regime))
        else:
            ok("o prato sai do zero e chega à rotação (%.3f → %.3f rad)"
               % (comeco, regime))

        # ── quem DISPARA a cerimônia ──────────────────────────────────────
        # Disco novo, agulha desce. Menos numa hipótese: a interface acabou
        # de abrir com música já tocando — ali o disco não foi posto agora,
        # foi encontrado no meio, e encenar a descida seria mentira sobre o
        # que aconteceu. É a diferença entre um ritual e uma animação de
        # abertura.
        _guarda = (app._disco_anterior, app.cerimonia_t0, app._born,
                   app.playing.album, app.playing.session.snapshot)
        try:
            app.playing.album = _ac

            # a) abrindo com música tocando: nada de cerimônia
            app._disco_anterior = None
            app.cerimonia_t0 = 0.0
            app._born = time.time()
            app._disco_novo()
            recem = app.cerimonia_t0

            # b) a mesma primeira leitura, mas com a interface aberta há
            #    tempo (alguém pôs o disco de outro lugar: rofi, celular)
            app._disco_anterior = None
            app.cerimonia_t0 = 0.0
            app._born = time.time() - 600
            app._disco_novo()
            de_fora = app.cerimonia_t0

            # c) trocou de disco com a interface aberta
            app.cerimonia_t0 = 0.0
            _ac.folder = "/y"
            app._disco_novo()
            trocou = app.cerimonia_t0
        finally:
            _ac.folder = "/x"
            (app._disco_anterior, app.cerimonia_t0, app._born,
             app.playing.album, app.playing.session.snapshot) = _guarda
        if recem:
            bad("abrir a interface com música tocando encena uma cerimônia")
        elif not de_fora:
            bad("pôr um disco de fora da interface não encena nada")
        elif not trocou:
            bad("trocar de disco não começa a cerimônia")
        else:
            ok("disco novo começa; abrir com música tocando, não")
    except Exception:                                       # noqa: BLE001
        bad("a cerimônia", traceback.format_exc())

    secao("nenhuma tecla derruba a tela")
    encher_as_lojas(app)          # as lojas com disco dentro, não vazias
    # A varredura lá de cima aperta VINTE E OITO teclas escolhidas a dedo,
    # uma vez cada, e só na tela recém-aberta. Isto aperta o teclado
    # INTEIRO — as 26 letras, os 10 dígitos, ESC, TAB, as setas, as de
    # edição — duas voltas (para as teclas que alternam passarem pelos dois
    # estados) e DESENHA depois de cada uma.
    #
    # O desenho depois de cada tecla é a metade que importa. Uma tecla que
    # põe a tela num sub-estado quebrado não estoura ao ser apertada: estoura
    # no quadro seguinte, e a varredura de cima só desenha no fim de tudo —
    # onde a última tecla já desfez o estado da anterior. Foi assim que o
    # lado sem `label` de uma playlist do Qobuz chegou à máquina de quem usa.
    #
    # Custa ~2 s e cobre 11 seções × 60 teclas × 2 voltas.
    try:
        letras = [getattr(pygame, "K_" + c) for c in "abcdefghijklmnopqrstuvwxyz"]
        digitos = [getattr(pygame, "K_" + c) for c in "0123456789"]
        outras = [pygame.K_ESCAPE, pygame.K_TAB, pygame.K_UP, pygame.K_DOWN,
                  pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN,
                  pygame.K_SPACE, pygame.K_BACKSPACE, pygame.K_DELETE,
                  pygame.K_HOME, pygame.K_END, pygame.K_PAGEUP,
                  pygame.K_PAGEDOWN, pygame.K_F1, pygame.K_PLUS,
                  pygame.K_MINUS, pygame.K_EQUALS, pygame.K_SLASH,
                  pygame.K_PERIOD, pygame.K_COMMA]
        todas = letras + digitos + outras

        # E em DOIS estados, porque com nada tocando metade da AGORA nem
        # chega a ser desenhada: o `draw` sai cedo pelo `_nothing`, e o [f]
        # (a tela cheia do disco) é desligado no caminho. Uma varredura que
        # só roda com o prato vazio passa verde por cima de um traceback na
        # tela cheia — medido, com o defeito posto de propósito.
        class _AlbFuzz:
            folder, artist, name, year = "/x", "A", "B", ""
            cover, plays, last_played, total = None, 1, 0, 1680
            discos = 1
            tracks = [{"title": "t", "dur": 210, "path": "/x/01.flac"}]
            sides = [{"label": "SIDE A", "start": 0, "end": 840,
                      "tracks": [0]},
                     {"label": "SIDE B", "start": 840, "end": 1680,
                      "tracks": [0]}]

        _af = _AlbFuzz()
        _antes_w, _antes_al = app.playing.where, app.playing.album
        estados = [
            ("nada tocando", lambda: ({}, None, None, None, None, 0.0), None),
            ("com disco no prato",
             lambda: ({"status": "Playing"}, _af, _af.tracks[0], _af.sides[0],
                      430.0, 0.51), _af),
        ]
        # E a cerimônia junto, girando entre as fases a cada tecla: fora
        # dela (0), spinup, cue e drop. Custa nada e cobre o desenho nos
        # três momentos em que a agulha NÃO está onde ela normalmente
        # estaria — que é onde este código erra. (Foi assim, com o `[f]`
        # apertado no meio de um `drop`, que apareceu uma divisão por zero
        # no rastro do sulco: `passos` valia 0 e o laço dividia por ele.)
        _ns = next(s for s in app.screens if s.name == "AGORA")
        _fases_cer = (0.0, _ns.CER_SPIN * 0.4,
                      _ns.CER_SPIN + _ns.CER_CUE * 0.5,
                      _ns.CER_SPIN + _ns.CER_CUE + _ns.CER_DROP * 0.4)
        quebras = []
        try:
            for _nome_estado, _onde_esta, _album in estados:
                app.playing.where = _onde_esta
                app.playing.album = _album
                for i, tela in enumerate(app.screens):
                    app._goto(i)
                    for _volta in (1, 2):
                        for _ik, k in enumerate(todas):
                            _dt = _fases_cer[_ik % len(_fases_cer)]
                            app.cerimonia_t0 = (0.0 if not _dt
                                                else time.monotonic() - _dt)
                            onde = "tecla"
                            try:
                                tela.key(pygame.event.Event(
                                    pygame.KEYDOWN, key=k, unicode="", mod=0))
                                onde = "desenho"
                                app.alvos = []
                                tela.draw(app.surf, corpo)
                            except Exception:               # noqa: BLE001
                                quebras.append(
                                    (tela.name + " (" + _nome_estado + ")",
                                     pygame.key.name(k), onde,
                                     traceback.format_exc()
                                     .strip().splitlines()[-1]))
        finally:
            app.playing.where, app.playing.album = _antes_w, _antes_al
            app.cerimonia_t0 = 0.0
        # Sem repetir a mesma pilha vinte vezes: o que interessa é QUAIS
        # telas e por quê.
        unicas = sorted({(n, o, m) for n, _t, o, m in quebras})
        if quebras:
            bad("%d teclas derrubam alguma seção" % len(quebras),
                "\n".join("%s (no %s): %s" % u for u in unicas[:5]))
        else:
            ok("%d seções × %d teclas × 2 voltas × 2 estados × 4 fases "
               "da cerimônia, desenhando a cada uma"
               % (len(app.screens), len(todas)))
    except Exception:                                       # noqa: BLE001
        bad("a varredura de teclado", traceback.format_exc())

    secao("o disco na tela toda, dentro do lançador")
    # POR QUE ISTO EXISTE
    # -------------------
    # A pergunta era "por que não jogar fora o deck e pôr tudo no lançador?".
    # A resposta é esta tela: o disco no meio, grande, sem trilho e sem
    # coluna. E ela nasceu com o defeito clássico de layout — o disco tomava
    # 40% da altura a partir do CENTRO, o texto vinha depois, e em 1080p o
    # nome da faixa era desenhado abaixo da borda de baixo. Não estoura, não
    # vira traceback: some.
    #
    # Então mede-se o que importa numa tela sem moldura: nada desenhado fora
    # dela, em toda resolução; e não dá para ficar preso nela.
    try:
        import theme as _T
        agora = next(s for s in app.screens if s.name == "AGORA")
        app._goto(app.screens.index(agora))

        class _AlbCheia:
            folder, artist, name, year = "/x", "The Beatles", "Abbey Road", ""
            cover, plays, last_played, total = None, 2, 0, 2600
            discos = 2
            tracks = [{"title": "Uma faixa de nome comprido", "dur": 200}]
            sides = [{"label": "SIDE A", "start": 0, "end": 700, "tracks": [0]},
                     {"label": "SIDE B", "start": 700, "end": 1300,
                      "tracks": [0]},
                     {"label": "SIDE C", "start": 1300, "end": 1950,
                      "tracks": [0]},
                     {"label": "SIDE D", "start": 1950, "end": 2600,
                      "tracks": [0]}]

        _alc = _AlbCheia()
        _antes = app.playing.where
        app.playing.where = lambda: ({}, _alc, _alc.tracks[0], _alc.sides[2],
                                     1500.0, 0.42)
        # COM LETRA. Ela entra na conta da altura antes de o disco escolher o
        # raio, e é a última coisa desenhada antes da linha de dicas: medir a
        # tela sem ela é medir a metade fácil — a mesma lição do prato vazio.
        _lyr = app.lyric_state
        _linhas_lrc = [(0.0, "uma linha de letra bastante comprida para medir"),
                       (6.0, ""), (9.0, "e a seguinte, que aparece apagada")]
        app.lyric_state = lambda al, tr: (_linhas_lrc, 0)

        class _Ev:
            def __init__(self, k):
                self.key, self.mod, self.unicode = k, 0, ""

        try:
            agora.key(_Ev(pygame.K_f))
            if not agora.tela_cheia:
                bad("[f] não abre a tela cheia")
            else:
                original = _T.text
                fora = []

                def espiao_c(surf, txt, pos, size=20, colour=_T.TEXT,
                             bold=False, anchor="topleft", maxw=None):
                    rr = original(surf, txt, pos, size, colour, bold, anchor,
                                  maxw)
                    if str(txt).strip():
                        fora.append((rr.copy(), str(txt)))
                    return rr

                _T.text = espiao_c
                escapou = []
                try:
                    for larg, alt in ((1024, 768), (1280, 720), (1366, 768),
                                      (1920, 1080), (3840, 2160)):
                        quadro = pygame.Rect(0, 0, larg, alt)
                        fora.clear()
                        agora.draw(app.surf, quadro)
                        for rr, ss in fora:
                            if (rr.bottom > alt + 2 or rr.y < -2
                                    or rr.right > larg + 2 or rr.x < -2):
                                escapou.append("%dx%d: %r" % (larg, alt,
                                                              ss[:26]))
                finally:
                    _T.text = original
                if escapou:
                    bad("%d textos fora da tela cheia" % len(escapou),
                        "\n".join(escapou[:5]))
                else:
                    ok("nada desenhado fora dela, de 1024 a 3840 px")

            # ESC sai: uma tela sem trilho precisa da saída que o resto do
            # sistema usa, senão a única porta é uma tecla que ninguém contou.
            agora.tela_cheia = True
            agora.key(_Ev(pygame.K_ESCAPE))
            if agora.tela_cheia:
                bad("ESC não sai da tela cheia")
            else:
                ok("[f] abre, ESC e [f] fecham")

            # E ela não pode sobreviver ao disco: sem nada tocando, uma tela
            # cheia sem trilho é um quadro preto de onde não se sai.
            agora.tela_cheia = True
            app.playing.where = lambda: ({}, None, None, None, None, 0.0)
            agora.draw(app.surf, pygame.Rect(0, 0, 1280, 720))
            if agora.tela_cheia:
                bad("a tela cheia sobrevive ao fim do disco")
            else:
                ok("acabou o disco, ela se fecha sozinha")
        finally:
            app.playing.where = _antes
            app.lyric_state = _lyr
            agora.tela_cheia = False
    except Exception:                                       # noqa: BLE001
        bad("a tela cheia do disco", traceback.format_exc())

    secao("a pilha diz com o que você se comprometeu")
    # **Sintoma:** a PILHA soma `it.get("mins", 0)` para escrever "X min de
    # disco encostado no móvel" — e o item da estante NUNCA teve `mins`. O
    # índice da estante não guarda duração de propósito (existe para a grade
    # desenhar rápido), então a soma dava zero e a linha, que só é desenhada
    # quando a soma é positiva, nunca apareceu na tela. Uma frase escrita e um
    # `if` que nunca foi verdade.
    try:
        pilha = next(s for s in app.screens if s.name == "A PILHA")
        app.stack = []

        class _AlbFalso:
            total = 45 * 60
            sides = [{"label": "SIDE A"}, {"label": "SIDE B"}]
            discos = 1

            def __init__(self, *a, **k):
                pass

        _real_album = A.vinyl.Album
        A.vinyl.Album = _AlbFalso
        try:
            app.stack_add({"folder": "/x/disco", "name": "D", "artist": "A",
                           "cover": "", "last": 0, "plays": 0})
            for _ in range(40):
                if app.stack and app.stack[0].get("mins"):
                    break
                time.sleep(0.05)
        finally:
            A.vinyl.Album = _real_album

        it = app.stack[0] if app.stack else {}
        if it.get("mins") != 45 or it.get("lados") != 2:
            bad("empilhar não mediu o disco",
                "mins=%s lados=%s" % (it.get("mins"), it.get("lados")))
        else:
            ok("empilhar mede o disco: 45 min, 2 lados")

        # E o total do rodapé, que era a frase que nunca aparecia.
        import theme as _T3
        _orig3 = _T3.text
        ditas = []

        def _espia3(surf, txt, pos, size=20, colour=_T3.TEXT, bold=False,
                    anchor="topleft", maxw=None):
            ditas.append(str(txt))
            return _orig3(surf, txt, pos, size, colour, bold, anchor, maxw)

        _T3.text = _espia3
        app._goto(app.screens.index(pilha))
        pilha.draw(app.surf, corpo)
        _T3.text = _orig3
        if not any("encostado no móvel" in d for d in ditas):
            bad("a linha do total da pilha continua sem aparecer")
        elif not any(d.startswith("45 min") for d in ditas):
            bad("a linha do disco não diz o que ele é", str(ditas[-6:]))
        else:
            ok("e a tela diz o que cada disco é, e o total da noite")
        app.stack = []
    except Exception:                                       # noqa: BLE001
        bad("a pilha medida", traceback.format_exc())

    secao("embaralhar e repetir falam com o tocador")
    # POR QUE ISTO EXISTE
    # -------------------
    # As duas teclas viravam um `not self.shuffle`, um toast e um ícone aceso
    # na AGORA — e nenhuma linha do programa contava ao mpv. A música seguia
    # na mesma ordem e o sistema afirmava o contrário com um ícone, que é
    # pior do que não ter a tecla. Ler não pega: o método existe, tem nome
    # certo e faz alguma coisa. Então o teste põe um mpv de mentira e olha o
    # que CHEGA nele.
    try:
        agora = next(s for s in app.screens if s.name == "AGORA")
        i_ag = app.screens.index(agora)
        app._goto(i_ag)

        class MpvDeMentira:
            def __init__(self):
                self.cmds = []

            def command(self, *args):
                self.cmds.append(args)
                if args[:2] == ("get_property", "playlist-count"):
                    return 9
                return True

        falso = MpvDeMentira()
        real = app.playing.session.mpv
        app.playing.session.mpv = falso

        def tecla(k, mod=0):
            agora.key(pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                         mod=mod))

        app.shuffle = False
        tecla(pygame.K_s)
        if ("playlist-shuffle",) not in falso.cmds:
            bad("o [s] não embaralhou nada no tocador", str(falso.cmds[-3:]))
        else:
            ok("[s] manda playlist-shuffle")
        falso.cmds.clear()
        tecla(pygame.K_s)
        if ("playlist-unshuffle",) not in falso.cmds:
            bad("o [s] de volta não desembaralhou", str(falso.cmds[-3:]))
        else:
            ok("[s] de novo devolve a ordem do disco")

        # Repetir: faixa, disco, desligado — e as duas propriedades do mpv
        # coerentes em cada degrau.
        app.repeat = 0
        esperado = [("inf", "no"), ("no", "inf"), ("no", "no")]
        erros = []
        for passo, (lf, lp) in enumerate(esperado):
            falso.cmds.clear()
            tecla(pygame.K_r, mod=pygame.KMOD_SHIFT)
            props = {c[1]: c[2] for c in falso.cmds if c[0] == "set_property"}
            if props.get("loop-file") != lf or props.get("loop-playlist") != lp:
                erros.append("degrau %d: %s" % (passo, props))
        if erros:
            bad("o [R] não põe o repetir no tocador", "; ".join(erros))
        else:
            ok("[R] cicla faixa → disco → desligado no tocador")

        # Sem tocador do outro lado, ninguém acende ícone nenhum: o estado
        # tem que continuar sendo o do mpv, não uma opinião da tela.
        class MpvMorto:
            def command(self, *a):
                return None

        app.playing.session.mpv = MpvMorto()
        app.shuffle = False
        tecla(pygame.K_s)
        if app.shuffle:
            bad("sem tocador, o [s] acendeu o ícone assim mesmo")
        else:
            ok("sem tocador, nada é prometido")
        app.playing.session.mpv = real
    except Exception:                                       # noqa: BLE001
        bad("embaralhar e repetir", traceback.format_exc())

    secao("a estante diz qual disco está no prato")
    # POR QUE ISTO EXISTE
    # -------------------
    # A grade não dizia. Havia a tarja com o nome da faixa no rodapé, e numa
    # parede de capas a pergunta é "qual delas" — a resposta estava em letra
    # de dez pixels do outro lado da tela. O disco que toca ganha o halo da
    # AGORA atrás da capa e o nome em âmbar.
    try:
        import theme as _T
        estante = next(s for s in app.screens if s.name == "ESTANTE")
        if estante.picking or estante.searching:
            estante.key(pygame.event.Event(pygame.KEYDOWN,
                                           key=pygame.K_ESCAPE, unicode="",
                                           mod=0))
        estante.artist = None
        itens = estante.items()
        if not itens:
            ok("(coleção vazia: nada para marcar)")
        else:
            class _Tocando:                 # só o que o desenho pergunta
                def __init__(self, folder):
                    self.folder = folder
            alvo = itens[-1]                # o último, não o selecionado
            app.playing.album = _Tocando(alvo["folder"])

            original = _T.text
            cores = {}

            def espiao_cor(surf, txt, pos, size=20, colour=_T.TEXT,
                           bold=False, anchor="topleft", maxw=None):
                cores.setdefault(str(txt), colour)
                return original(surf, txt, pos, size, colour, bold, anchor,
                                maxw)

            _T.text = espiao_cor
            i_est = app.screens.index(estante)
            app._goto(i_est)
            estante.draw(app.surf, corpo)
            _T.text = original

            if cores.get(alvo["name"]) != _T.AMBER:
                bad("o disco que toca não vem em âmbar na estante",
                    f'{alvo["name"]}: {cores.get(alvo["name"])}')
            else:
                ok(f'"{alvo["name"]}" marcado como o que está tocando')

            # E os outros NÃO podem vir em âmbar: se tudo é o disco que toca,
            # nada é.
            outros = [n for it in itens[:-1]
                      for n in (it["name"],) if cores.get(n) == _T.AMBER]
            if outros:
                bad(f"{len(outros)} discos parados também vieram em âmbar",
                    ", ".join(outros[:3]))
            else:
                ok("os discos parados continuam apagados")

            # Sem nada tocando, ninguém é marcado — e nada estoura.
            app.playing.album = None
            _T.text = espiao_cor
            cores.clear()
            estante.draw(app.surf, corpo)
            _T.text = original
            if [n for it in itens for n in (it["name"],)
                    if cores.get(n) == _T.AMBER]:
                bad("com nada tocando ainda há disco marcado")
            else:
                ok("com nada tocando, nenhum disco é marcado")
    except Exception:                                       # noqa: BLE001
        bad("o disco no prato", traceback.format_exc())

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
        # Três escutas por disco foram escritas ali em cima; o `Nx` da linha
        # tem que dizer três. **Sintoma:** ele vinha do `plays` da ESTANTE,
        # que é contado uma vez, na varredura — o diário mostrava a escuta de
        # dois minutos atrás com um número ao lado que não a incluía, e que
        # só mudava quando a estante fosse varrida de novo.
        # E a fileira de capas "OS QUE VOLTAM" depende desse mesmo número:
        # ela filtra por `it.get("plays")`, então com todo mundo em zero ela
        # não desenhava NADA — um bloco inteiro da tela sumia sem aviso, e a
        # página parecia ter só metade do conteúdo.
        import theme as _T2
        _orig = _T2.text
        vistos = []

        def _espia(surf, txt, pos, size=20, colour=_T2.TEXT, bold=False,
                   anchor="topleft", maxw=None):
            vistos.append(str(txt))
            return _orig(surf, txt, pos, size, colour, bold, anchor, maxw)

        _T2.text = _espia
        diario.page = 1
        diario.draw(app.surf, corpo)
        diario.page = 0
        _T2.text = _orig
        if "OS QUE VOLTAM" not in vistos:
            bad("a fileira de capas dos discos que voltam não desenhou")
        else:
            ok("a fileira 'os que voltam' aparece quando há escuta")

        if diario.rows and diario.rows[0].get("plays") != 3:
            bad("o diário conta as escutas pela estante, não pelo registro",
                "esperava 3, veio %s" % diario.rows[0].get("plays"))
        elif diario.rows:
            ok("o Nx de cada linha vem do registro que a tela acabou de ler")
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
            discos = 1

            # A frase do fim do lado mora no `Album.gesto_do_lado` — as três
            # telas que a dizem (a notificação, a tela cheia e este aviso de tela
            # cheia) leem de lá. Um fake sem ela faria o aviso cair na
            # reserva, e o teste passaria por cima do caminho de verdade.
            gesto_do_lado = A.vinyl.Album.gesto_do_lado
            rotulo_do_lado = A.vinyl.Album.rotulo_do_lado

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
        app._flip = (time.time() - app.FLIP_DUR - 1, "LADO A",
                     "vire o disco para o LADO B", "x")
        app._draw_flip(app.surf)
        if app._flip:
            bad("o aviso não sumiu sozinho")
        else:
            ok("some sozinho depois de alguns segundos")

        # ── e o que ele ESCREVE ───────────────────────────────────────────
        # O aviso perguntava "este é o último lado?" para escolher entre
        # "vire o disco" e "agora é o". Num LP de dois lados acerta por
        # acidente; num DUPLO, o fim do lado B pede para TROCAR de disco e
        # ele mandava virar. A frase vem do `Album.gesto_do_lado`, que é a
        # mesma que a notificação e o vigia do lado dizem.
        disco.discos = 2
        disco.sides = [{"label": "SIDE " + c, "start": i * 600,
                        "end": (i + 1) * 600} for i, c in enumerate("ABCD")]
        frases = []
        original_t = _T.text

        def _espia_flip(surf, txt, *a, **k):
            frases.append(str(txt))
            return original_t(surf, txt, *a, **k)

        try:
            for destino in (1, 2, 3):
                app._flip = (time.time(), "LADO %s" % "ABCD"[destino - 1],
                             disco.gesto_do_lado(destino), "x")
                frases.clear()
                _T.text = _espia_flip
                app._draw_flip(app.surf)
                _T.text = original_t
                junto = " ".join(frases)
                quer = "vire o disco" if destino % 2 else "DISCO 2"
                if quer not in junto:
                    bad("o aviso do lado %s não diz %r" % ("ABCD"[destino], quer),
                        junto[:120])
                    break
            else:
                ok("num disco duplo ele manda virar, trocar e virar")
        finally:
            _T.text = original_t
            app._flip = None
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
                # O RECORTE conta. As grades (estante, as duas lojas) desenham
                # a fileira que está meio para fora e deixam o pygame cortar:
                # medir o retângulo cru acusa "desenhado fora da tela" um
                # texto que na tela não aparece — e uma conferência que grita
                # sobre o que está certo é uma que se aprende a ignorar.
                # …mas SÓ o recorte que o desenho pediu (as grades chamam
                # `set_clip` na sua janela). O retângulo da superfície
                # inteira não conta: com ele, a conferência de "fora da
                # tela" logo abaixo vira tautologia — todo retângulo, depois
                # de recortado pela tela, está dentro da tela. Medido: um
                # texto de duzentos X desenhado a partir da metade direita
                # não aparecia em acusação nenhuma.
                rec = surf.get_clip()
                interno = rec and tuple(rec) != tuple(surf.get_rect())
                vis = r.clip(rec) if interno else r.copy()
                if vis.w > 0 and vis.h > 0:
                    caixas.append((vis, str(txt)))
            return r

        _T.text = espiao
        encher_as_lojas(app)
        for tela in app.screens:
            if tela.name == "SINAL":
                tela.info = {"file": "faixa.flac", "frate": 44100,
                             "graph": 48000, "fbits": 24, "codec": "FLAC",
                             "dev": "Meteor Lake-P HD Audio Controller Speaker",
                             "multi": True}
        # E com um DISCO NO PRATO, não só com o prato vazio.
        #
        # **Sintoma:** a AGORA desenhava o artista, o disco, o LADO e o "vira
        # em X" para fora da tela em 800x600 — e este teste passava verde,
        # porque com nada tocando o `draw` sai cedo pelo `_nothing` e a
        # coluna de texto nem chega a existir. A metade da tela que mais tem
        # texto era a metade que não estava sendo medida.
        #
        # Os nomes são compridos de propósito: é o comprimento que revela
        # folga fixa e piso que não cabe, e o disco de nome curto do teste
        # antigo cabia em qualquer lugar.
        class _AlbLongo:
            folder = "/x/Um Artista/Um Disco"
            artist = "Um Artista Com Nome Bastante Comprido"
            name = "Um Disco De Nome Também Bem Comprido"
            year, cover = 1969, None
            plays, last_played, total = 3, 0, 2600
            discos = 2
            # DOZE faixas, e cada lado com as suas.
            #
            # Era UMA faixa e `"tracks": [0]` em todos os lados, e isso não
            # é um disco: é a mesma lição da estante de mentira com dois
            # discos de nome curto. A ORDEM DO LADO — a lista que a AGORA
            # desenha onde não há letra — só é desenhada a partir de duas
            # faixas, então a tela media exatamente a metade que não tem
            # lista nenhuma.
            tracks = [{"title": "Uma faixa de nome comprido também %d" % (i + 1),
                       "dur": 200, "duration": 200.0, "start": i * 200.0}
                      for i in range(12)]
            sides = [{"label": "SIDE %s" % c, "start": i * 650,
                      "end": (i + 1) * 650,
                      "tracks": list(range(i * 3, i * 3 + 3))}
                     for i, c in enumerate("ABCD")]

        _alongo = _AlbLongo()
        _surf_real = app.surf
        _guarda_w, _guarda_al = app.playing.where, app.playing.album
        estados_tela = [
            ("prato vazio", lambda: ({}, None, None, None, None, 0.0), None),
            ("disco no prato",
             lambda: ({"status": "Playing"}, _alongo, _alongo.tracks[7],
                      _alongo.sides[2], 1500.0, 0.42), _alongo),
        ]
        batidas, vazados = [], []
        # Em QUATRO tamanhos de tela. O layout do diário era uma altura fixa
        # de 104 px numa posição fixa: numa tela de 720 o calendário entrava
        # na lista, e nada disso aparece medindo só a resolução do
        # desenvolvedor. Da tela de notebook barato à de 4K.
        # A de 1024 entrou depois: é a que a máquina virtual e o monitor
        # velho dão, e foi nela que a quarta coluna dos JOGOS apareceu
        # desenhada FORA da tela.
        # A de 1024x600 entrou depois: é painel de carro, mini-PC e monitor
        # velho, e foi nela que a fileira de ações dos JOGOS era desenhada
        # sessenta pixels ABAIXO da borda de baixo. A de 800x600 é o piso do
        # que o X entrega: nela os dois pisos da AGORA — 260 px para o disco
        # e 180 para a coluna de texto — somavam mais do que a largura da
        # tela, e o bloco inteiro saía pela direita.
        for _nome_est, _onde, _album in estados_tela:
          app.playing.where, app.playing.album = _onde, _album
          for larg, alt in ((800, 600), (1024, 600), (1024, 768), (1280, 720),
                            (1366, 768), (1920, 1080), (3840, 2160)):
            # A SUPERFÍCIE tem que ter o tamanho da tela que se diz estar
            # medindo.
            #
            # **Sintoma:** o espião recorta cada texto pelo `get_clip` da
            # superfície — de propósito, porque as grades desenham a fileira
            # meio para fora e deixam o pygame cortar. Só que a superfície
            # era a que o App abriu (1600x950 aqui), e não mudava de tamanho:
            # nas duas resoluções grandes, TODO texto além de x=1600 era
            # recortado a zero e simplesmente não entrava na medição. As duas
            # últimas linhas desta lista mediam um pedaço de 1600x950 e
            # diziam "1920" e "3840". Medido com um texto de duzentos X: ele
            # não aparecia em acusação nenhuma.
            app.surf = pygame.Surface((larg, alt))
            app.W, app.H = larg, alt
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
                #
                # Os DOIS eixos. Isto conferia só o de cima e o de baixo, e
                # foi pelo lado que a tela dos JOGOS falhou: a grade tinha
                # quatro quadros de largura fixa, somando 940 px, num corpo
                # de 794 — três jogos desenhados no vazio à direita da tela,
                # com a seleção andando por eles. Passava verde: nenhum deles
                # estava alto ou baixo demais.
                for rr, ss in caixas:
                    if rr.bottom > alt + 2 or rr.y < -2:
                        vazados.append(f"{larg}x{alt} {tela.name}: {ss[:26]!r}"
                                       " (embaixo)")
                    if rr.right > larg + 2 or rr.right < quadro.x:
                        vazados.append(f"{larg}x{alt} {tela.name}: {ss[:26]!r}"
                                       " (ao lado)")
        _T.text = original
        app.surf = _surf_real
        app.W, app.H = _surf_real.get_width(), _surf_real.get_height()
        app.playing.where, app.playing.album = _guarda_w, _guarda_al
        if batidas:
            bad(f"{len(batidas)} textos se cruzam", "\n".join(batidas[:5]))
        else:
            ok(f"{len(app.screens)} seções × 7 resoluções × 2 estados, "
               "nada por cima de nada")
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
        # ── o ícone nunca decide a fonte do rótulo ────────────────────────
        # **Sintoma:** numa máquina sem o Nerd Font, "󰝰  Clone Hero" saía
        # como uma fileira de caixinhas — o NOME junto com o ícone. O
        # `fonte_para` decide por texto inteiro, e o ícone é um caractere de
        # uso privado: quem "cobre" uso privado é uma fonte de símbolos, que
        # não tem letra latina nenhuma. Escolhida por causa do ícone, ela
        # desenhava o rótulo todo.
        #
        # O atalho que evita isso existia e apontava para a área errada: só a
        # do BMP (E000–F8FF), onde este repositório não tem um ícone sequer.
        # Os 27 que ele usa são Material Design, que o Nerd Font v3 pôs no
        # plano 15.
        icones = sorted({c for tela in app.screens
                         for c in getattr(tela, "icon", "")
                         if ord(c) > 0xFFFF})
        rotulo_ruim = []
        for ic in icones + ["\U000f0770"]:
            f_ic = _T.fonte_para(f"{ic}  Clone Hero", 22)
            f_puro = _T.fonte_para("Clone Hero", 22)
            if f_ic is not f_puro:
                rotulo_ruim.append(hex(ord(ic)))
        if rotulo_ruim:
            bad(f"{len(rotulo_ruim)} ícones arrastam o rótulo para outra fonte",
                ", ".join(rotulo_ruim))
        else:
            ok(f"os {len(icones) + 1} ícones não mudam a fonte do rótulo")

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
        # 1. O halo e o disco são REDONDOS: o canto da superfície deles tem
        #    que continuar transparente ao ser blitado.
        #
        #    **Sintoma:** havia aqui uma conferência que exigia o contrário —
        #    `get_alpha() is None` nas duas — em nome de um blit 3,6x mais
        #    rápido. O `set_alpha(None)` que ela cobrava APAGA o SRCALPHA da
        #    superfície no pygame 2: o blit deixa de misturar e vira cópia
        #    crua. Era rápido porque não desenhava luz nenhuma — pintava por
        #    cima. Na tela, a AGORA ficava com um quadrado preto de meia tela
        #    (o canto (0,0,0,0) do halo) e um disco de mostarda chapado
        #    dentro dele, que é o "app de um dólar" que o CLAUDE.md §5.5
        #    proíbe pelo nome. O teste passava verde em cima disso.
        #
        #    Então a pergunta não é qual é o alfa da superfície: é o que
        #    acontece com o FUNDO quando ela é desenhada por cima.
        fundo = (40, 90, 160)
        chapados = []
        for nome, sup2 in (("halo", _T.halo(120, forca=192)),
                           ("disco", _T.disco(120))):
            prova = pygame.Surface(sup2.get_size())
            prova.fill(fundo)
            prova.blit(sup2, (0, 0))
            if prova.get_at((1, 1))[:3] != fundo:
                chapados.append("%s (canto virou %s)"
                                % (nome, prova.get_at((1, 1))[:3]))
        if chapados:
            bad("superfície em cache pinta por cima do fundo",
                ", ".join(chapados))
        else:
            ok("o halo e o disco desenham redondos, sem quadrado por baixo")

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
    secao("a loja diz quais discos você já tem")
    # Numa loja que abre nos SEUS favoritos, metade do que aparece já foi
    # baixado — e não havia nada na tela dizendo qual. "Eu já tenho esse?" é a
    # primeira pergunta que se faz numa loja, e a resposta estava do outro
    # lado de duas telas.
    try:
        loja = next(t for t in app.screens if t.name == "QOBUZ")
        app.shelf.items = [
            {"artist": "Radiohead", "name": "Kid A", "folder": "/x/1",
             "cover": None, "tracks": 10, "last": 0, "plays": 0},
            {"artist": "Sigur Rós", "name": "Ágætis byrjun",
             "folder": "/x/2", "cover": None, "tracks": 10, "last": 0,
             "plays": 0}]
        loja._tenho_n = -1
        casos = [
            # (artista da loja, disco da loja, tenho?)
            ("Radiohead", "Kid A", True),
            # a edição comemorativa é o mesmo disco para quem está decidindo
            ("Radiohead", "Kid A (Remastered)", True),
            ("SIGUR ROS", "Agaetis byrjun", True),      # sem acento, caixa alta
            ("Radiohead", "Amnesiac", False),
            ("Boards of Canada", "Kid A", False),        # mesmo nome, outro
        ]
        erros = []
        for art, alb, esperado in casos:
            deu = loja._na_estante({"display_subtitle": art,
                                    "display_title": alb})
            if deu != esperado:
                erros.append("%s — %s: %s" % (art, alb, deu))
        if erros:
            bad("%d discos com a resposta errada" % len(erros),
                ", ".join(erros))
        else:
            ok("%d casos, com acento, caixa e edição entre parênteses"
               % len(casos))
    except Exception:                                       # noqa: BLE001
        bad("já está na estante", traceback.format_exc())

    secao("o fundo desfocado não estica a capa")
    # **Sintoma:** a capa é quadrada e a tela é 16:9, e o borrão de fundo era
    # escalado direto para o tamanho da tela — quase o DOBRO da largura. Numa
    # capa com círculo ou com letra grande isso se vê na hora, mesmo desfocado
    # e por baixo do véu. É `cover`, não `stretch`: escala pelo lado que
    # precisa de mais e corta o resto.
    try:
        erros = []
        for iw, ih in ((600, 600), (1400, 1400), (500, 300), (300, 500)):
            for larg, alt in ((1920, 1080), (800, 600), (1024, 600)):
                cw, ch = A._cobre(iw, ih, larg, alt)
                if cw < larg or ch < alt:
                    erros.append("%dx%d em %dx%d não cobre" % (iw, ih, larg, alt))
                elif abs((cw / ch) - (iw / ih)) > 0.02:
                    erros.append("%dx%d em %dx%d deforma (%.3f → %.3f)"
                                 % (iw, ih, larg, alt, iw / ih, cw / ch))
        if erros:
            bad("%d casos deformam o fundo" % len(erros), ", ".join(erros[:4]))
        else:
            ok("a capa cobre a tela sem deformar, em 12 casos")
    except Exception:                                       # noqa: BLE001
        bad("fundo desfocado", traceback.format_exc())

    secao("na tela cheia do disco, as teclas continuam respondendo")
    # **Sintoma:** com o disco na tela toda, apertar B no controle (que chega
    # como ESC) parecia não fazer nada — e a partir dali NADA respondia: o [f]
    # não voltava, as setas não buscavam, o ENTER pulava de seção. O ESC caía
    # no "abre o trilho" do App._key, e o trilho não é desenhado na tela cheia:
    # o programa ficava num MENU INVISÍVEL comendo todas as teclas.
    #
    # O `if ev.key == K_ESCAPE and self.tela_cheia` da NowScreen existia e era
    # código morto — o App._key vem antes dela e nunca deixava chegar.
    try:
        agora = next(t for t in app.screens if t.name == "AGORA")
        app._goto(app.screens.index(agora))
        app.rail = False
        agora.tela_cheia = True

        def _t(k, mod=0):
            return app._key(pygame.event.Event(pygame.KEYDOWN, key=k,
                                               unicode="", mod=mod))

        _t(pygame.K_ESCAPE)
        saiu_no_esc = (not agora.tela_cheia) and not app.rail
        agora.tela_cheia = True
        _t(pygame.K_f)
        saiu_no_f = not agora.tela_cheia
        # E o trilho aberto não pode ficar invisível: com ele no ar, a tela
        # cheia cede a moldura.
        agora.tela_cheia, app.rail = True, True
        inteira = (getattr(app.screens[app.cur], "tela_cheia", False)
                   and not app.rail)
        app.rail = False
        agora.tela_cheia = False
        if not saiu_no_esc:
            bad("o ESC na tela cheia não volta (ou abre o trilho invisível)")
        elif not saiu_no_f:
            bad("o [f] não sai da tela cheia")
        elif inteira:
            bad("com o trilho aberto a tela cheia continua sem moldura")
        else:
            ok("[esc] e [f] voltam, e o trilho nunca fica invisível")
    except Exception:                                       # noqa: BLE001
        bad("tela cheia e teclas", traceback.format_exc())

    secao("com nada tocando, a tela diz O QUE pôr")
    # **Sintoma:** a tela que se vê ao chegar perto da máquina dizia "vá para
    # a ESTANTE e escolha um disco" — mandava para outro lugar sem responder
    # a única pergunta que quem chega tem, que é QUAL. E o sistema sabe: sabe
    # o que faz meses que não toca (é a única coisa que uma coleção com
    # memória responde e uma pasta de arquivos não) e sabe o que você
    # empilhou para hoje.
    try:
        agora = next(t for t in app.screens if t.name == "AGORA")
        agora._sug_cache, agora._sug_t = None, 0.0
        guardada = list(app.stack)
        app.stack = []
        # sem memória nenhuma: oferece algum
        sem_memoria = agora._sugestao()
        # com memória: o mais esquecido, e a frase tem que dizer isso
        import time as _t2
        for i, it in enumerate(app.shelf.items):
            it["last"] = _t2.time() - (100 - i) * 86400
        agora._sug_cache, agora._sug_t = None, 0.0
        esquecido = agora._sugestao()
        # com PILHA: o compromisso ganha
        app.stack = [{"folder": "/x/y", "name": "O da pilha", "artist": "Z"}]
        agora._sug_cache, agora._sug_t = None, 0.0
        da_pilha = agora._sugestao()
        app.stack = guardada
        agora._sug_cache, agora._sug_t = None, 0.0

        primeiro = app.shelf.items[0] if app.shelf.items else None
        if not sem_memoria:
            bad("com a estante cheia, não ofereceu nada")
        elif not esquecido or esquecido[0] is not primeiro:
            bad("não ofereceu o disco mais esquecido",
                str(esquecido[0]["name"] if esquecido else None))
        elif "faz tempo" not in esquecido[1]:
            bad("ofereceu sem dizer por quê", esquecido[1])
        elif not da_pilha or da_pilha[0]["name"] != "O da pilha":
            bad("a PILHA não ganhou da estante: o compromisso foi desfeito",
                str(da_pilha))
        else:
            # e o ENTER tem que PÔR o que a tela ofereceu, senão "põe este"
            # está escrito embaixo de uma tecla que faz outra coisa.
            posto = []
            real = app.put_on
            app.put_on = lambda f: (posto.append(f), True)[1]
            try:
                app.playing.session.path = ""
                app.playing.session.source = "none"
                agora._sug_cache, agora._sug_t = None, 0.0
                alvo = agora._sugestao()[0]["folder"]
                agora.key(pygame.event.Event(pygame.KEYDOWN,
                                             key=pygame.K_RETURN,
                                             unicode="", mod=0))
            finally:
                app.put_on = real
            if posto != [alvo]:
                bad("o [enter] não põe o disco oferecido", str(posto))
            else:
                ok("oferece o mais esquecido, a pilha ganha dele, e o "
                   "[enter] põe")
    except Exception:                                       # noqa: BLE001
        bad("a sugestão da AGORA", traceback.format_exc())

    secao("os sulcos do disco são as faixas DESTE disco")
    # **Sintoma:** o desenho tinha cinco anéis fixos, e o comentário deles
    # dizia "é o que faz um disco parecer um disco a três metros: dá para
    # CONTAR as músicas". Contavam sempre cinco, nos mesmos lugares, em todo
    # disco da coleção — um LP de doze faixas e um single de duas desenhavam
    # o mesmo objeto. A frase estava certa sobre o que o desenho devia
    # fazer, e o desenho não fazia.
    #
    # Ler não pega: o método existe, tem nome certo e devolve alguma coisa.
    # Este teste monta DOIS lados de tamanhos diferentes e exige que os
    # anéis sejam diferentes entre si e diferentes dos fixos.
    try:
        import theme as _T4
        agora = next(t for t in app.screens if t.name == "AGORA")
        alb = A.vinyl.Album.__new__(A.vinyl.Album)
        alb.tracks = [{"start": s * 60.0} for s in (0, 5, 11, 18, 26,
                                                    32, 38, 45, 51)]
        lado_a = {"label": "SIDE A", "start": 0.0, "end": 32 * 60.0,
                  "tracks": [0, 1, 2, 3, 4]}
        lado_b = {"label": "SIDE B", "start": 32 * 60.0, "end": 58 * 60.0,
                  "tracks": [5, 6, 7, 8]}
        a = agora._intervalos(alb, lado_a)
        b = agora._intervalos(alb, lado_b)
        sem = agora._intervalos(alb, None)
        curto = agora._intervalos(alb, {"start": 0.0, "end": 0.5,
                                        "tracks": [0, 1]})
        if not a or len(a) != 4:
            bad("o lado A tem 5 faixas: 4 sulcos entre elas", str(a))
        elif a == b:
            bad("dois lados diferentes desenharam os mesmos sulcos", str(a))
        elif tuple(a) == tuple(_T4._INTERVALOS):
            bad("caiu nos cinco fixos com um disco de verdade na mão")
        elif not all(_T4.GROOVE_I < x < _T4.GROOVE_O for x in a + b):
            bad("sulco desenhado fora da faixa de sulcos", str(a + b))
        elif sem is not None or curto is not None:
            bad("sem lado (ou com lado de meio segundo) devia cair no fixo",
                f"{sem} {curto}")
        else:
            # Uma PLAYLIST não é um disco: o lado dela é a lista inteira, e
            # numa de duzentas faixas seriam duzentos anéis — moiré, não
            # informação.
            alb.continuo = True
            lista = agora._intervalos(alb, lado_a)
            alb.continuo = False
            muitas = A.vinyl.Album.__new__(A.vinyl.Album)
            muitas.tracks = [{"start": i * 60.0} for i in range(60)]
            demais = agora._intervalos(
                muitas, {"start": 0.0, "end": 3600.0,
                         "tracks": list(range(60))})
            if lista is not None:
                bad("uma playlist desenhou um anel por faixa", str(lista[:6]))
            elif demais is not None:
                bad("sessenta anéis: contar deixou de ser possível",
                    str(len(demais)))
            # e o desenho tem que ACEITAR: o cache é por (raio, intervalos).
            d1 = _T4.disco(90, a)
            d2 = _T4.disco(90, b)
            if d1 is d2:
                bad("o cache do disco ignora os intervalos: dois lados "
                    "diferentes devolveram a MESMA superfície")
            else:
                ok(f"{len(a)} e {len(b)} sulcos, dos dois lados deste disco")
    except Exception:                                       # noqa: BLE001
        bad("os sulcos do disco", traceback.format_exc())

    secao("as playlists da coleção aparecem, e podem ser postas")
    # **Sintoma:** o sistema ESCREVIA .m3u (o `stylus suggest`, o
    # `make_new_playlist`, o `integrate_album`) e não sabia tocar nenhum: não
    # havia tela em que aparecessem nem comando que as listasse. Arquivos que
    # o sistema cria e o sistema não abre.
    try:
        estante = next(t for t in app.screens if t.name == "ESTANTE")
        app._goto(app.screens.index(estante))
        estante.order, estante.query, estante.artist = "artista", "", None
        # A estante em memória aqui é a DE MENTIRA que uma seção anterior
        # deixou (dois discos de nome comprido, para medir colisão). Esta
        # conferência é sobre a VARREDURA, então ela relê a coleção de
        # verdade — e devolve a de mentira no fim, senão as seções seguintes
        # medem outra tela.
        guardados = list(app.shelf.items)
        app.shelf.rescan()
        for _ in range(80):
            if not app.shelf.scanning:
                break
            time.sleep(0.05)
        discos = estante.items()
        entre_os_discos = [i for i in discos if i.get("playlist")]
        estante.order = "listas"
        listas = estante.items()
        estante.order = "artista"
        # e a lista tem que ser PONÍVEL: o put_on recusava arquivo.
        posto = None
        if listas:
            real = A.spawn
            A.spawn = lambda cmd, **k: posto_cmd.append(cmd) or True
            posto_cmd = []
            try:
                posto = app.put_on(listas[0]["folder"])
            finally:
                A.spawn = real
        if entre_os_discos:
            bad("uma playlist se disfarçou de disco na grade",
                str([i["name"] for i in entre_os_discos]))
        elif not listas:
            bad("a ordem 'listas' não mostrou nenhuma playlist")
        elif not posto:
            bad("o enter numa playlist não põe nada",
                "o put_on recusa arquivo (só isdir)?")
        else:
            ok(f"{len(listas)} playlist(s) fora da grade de discos, e o "
               f"enter põe")
        app.shelf.items = guardados
    except Exception:                                       # noqa: BLE001
        bad("as playlists", traceback.format_exc())

    secao("o recado do terminal espera a música chegar")
    # **A corrida:** o `stylus deck DISCO` sobe o mpv e no MESMO instante
    # deixa o recado para a tela cheia. O `Session` pesquisa o tocador de meio
    # em meio segundo numa thread própria, então o quadro que lê o recado
    # quase sempre ainda não viu música nenhuma — e a tela cheia, que só entra
    # com música, não entrava. Da poltrona isso é "às vezes funciona".
    try:
        import vinyl as _V
        agora = next(t for t in app.screens if t.name == "AGORA")
        i_agora = app.screens.index(agora)
        os.makedirs(os.path.dirname(_V.UI_CMD), exist_ok=True)
        with open(_V.UI_CMD, "w", encoding="utf-8") as fh:
            fh.write("disco\n")
        app._goto(1)
        agora.tela_cheia = False
        app.playing.session.path = ""
        app.playing.session.source = "none"
        app._recado()                       # chega sem música: só vai à AGORA
        foi = app.cur == i_agora
        cedo = agora.tela_cheia
        esperando = bool(app._esperando_disco)
        app.playing.session.path = "/x/y/01.flac"
        app.playing.session.source = "mpv"
        app._recado_tardio()                # a música chegou
        entrou = agora.tela_cheia
        # e a paciência acaba: sem música, não fica esperando para sempre
        app.playing.session.path = ""
        app.playing.session.source = "none"
        app._esperando_disco = time.time() - 1
        app._recado_tardio()
        desistiu = not app._esperando_disco
        agora.tela_cheia = False
        if not foi:
            bad("o recado não levou à AGORA")
        elif cedo:
            bad("entrou na tela cheia sem música: menu invisível")
        elif not esperando:
            bad("não ficou esperando a música chegar")
        elif not entrou:
            bad("a música chegou e a tela cheia não entrou")
        elif not desistiu:
            bad("ficaria esperando para sempre")
        else:
            ok("espera a música, entra quando ela chega, e desiste no fim")
        try:
            os.unlink(_V.UI_CMD)
        except OSError:
            pass
    except Exception:                                       # noqa: BLE001
        bad("o recado do terminal", traceback.format_exc())

    secao("ver o disco não começa a tocar sozinho")
    # **Sintoma que isto impede:** o Mod+O se chama "o disco na tela toda", e
    # ele chega aqui pelo `stylus-deck --view`, cujo cabeçalho promete "sem
    # pôr disco novo". Com nada tocando, `ver_o_disco` sorteava e PUNHA um
    # disco — uma tecla fazendo outra coisa que o nome dela não diz, e a mais
    # cara delas: começa a sair som numa casa em silêncio.
    #
    # E a tela cheia SEM música seria a tela de "nada tocando" sem trilho:
    # um menu invisível, que é o defeito que o ESC já custou uma vez.
    try:
        agora = next(t for t in app.screens if t.name == "AGORA")
        i_agora = app.screens.index(agora)
        postos = []
        real = app.put_on
        app.put_on = lambda f: (postos.append(f), True)[1]
        try:
            app._goto(1)
            agora.tela_cheia = False
            app.playing.session.path = ""
            app.playing.session.source = "none"
            app.ver_o_disco()
            foi_para_agora = app.cur == i_agora
            cheia_sem_musica = agora.tela_cheia
            app.playing.session.path = "/x/y/01.flac"
            app.playing.session.source = "mpv"
            app._goto(1)
            app.ver_o_disco()
            cheia_com_musica = agora.tela_cheia
        finally:
            app.put_on = real
            app.playing.session.path = ""
            app.playing.session.source = "none"
            agora.tela_cheia = False
        if postos:
            bad("ver o disco começou a tocar sozinho", str(postos))
        elif not foi_para_agora:
            bad("ver o disco não foi para a AGORA")
        elif cheia_sem_musica:
            bad("tela cheia com nada tocando: um menu invisível")
        elif not cheia_com_musica:
            bad("com música, não abriu a tela cheia")
        else:
            ok("vai para a AGORA, abre cheia só com música, e não põe nada")
    except Exception:                                       # noqa: BLE001
        bad("ver o disco", traceback.format_exc())

    secao('"sem capa" só quando é verdade')
    # **Sintoma:** a frase piscava no meio da capa em toda troca de disco.
    # O `Thumbs.get` devolve None em DOIS casos muito diferentes — "ainda
    # estou decodificando" e "não tem capa" — e o desenho tratava os dois
    # como o segundo. É a mesma família do "taxa travada" do SINAL: uma
    # afirmação tirada da ausência de dado.
    try:
        _agora = next(t for t in app.screens if t.name == "AGORA")
        vistos = []
        import theme as _Tm
        _orig = _Tm.text

        def _espiao(surf, txt, pos, size, *a, **k):
            vistos.append(str(txt))
            return _orig(surf, txt, pos, size, *a, **k)

        class _AlbCapa:
            folder = "/x/A/B"
            artist, name, year = "A", "B", 1969
            cover = "/x/A/B/cover.jpg"
            plays, last_played, total, discos = 1, 0, 1200, 1
            tracks = [{"title": "uma", "dur": 200}]
            sides = [{"label": "LADO A", "start": 0, "end": 1200,
                      "tracks": [0]}]

        _al = _AlbCapa()
        _guarda = (app.playing.where, app.playing.album,
                   dict(app.thumbs.mem), dict(app.thumbs_hi.mem))
        try:
            app.playing.album = _al
            app.playing.where = lambda: ({"status": "Playing"}, _al,
                                         _al.tracks[0], _al.sides[0],
                                         500.0, 0.4)
            _Tm.text = _espiao
            # a) a capa existe e ainda está sendo aberta: nada de "sem capa"
            app.thumbs.mem.pop(_al.cover, None)
            app.thumbs_hi.mem.pop(_al.cover, None)
            app.thumbs.pending.add(_al.cover)      # não deixa começar thread
            app.thumbs_hi.pending.add(_al.cover)
            vistos.clear()
            _agora.draw(app.surf, corpo)
            enquanto_carrega = any("sem capa" in v for v in vistos)
            # b) o Thumbs desistiu (capa ilegível): aí sim é verdade
            app.thumbs.pending.discard(_al.cover)
            app.thumbs_hi.pending.discard(_al.cover)
            app.thumbs.mem[_al.cover] = None
            app.thumbs_hi.mem[_al.cover] = None
            vistos.clear()
            _agora.draw(app.surf, corpo)
            quando_falha = any("sem capa" in v for v in vistos)
        finally:
            _Tm.text = _orig
            app.thumbs.pending.discard(_al.cover)
            app.thumbs_hi.pending.discard(_al.cover)
            (app.playing.where, app.playing.album) = _guarda[0], _guarda[1]
            app.thumbs.mem.clear(); app.thumbs.mem.update(_guarda[2])
            app.thumbs_hi.mem.clear(); app.thumbs_hi.mem.update(_guarda[3])
        if enquanto_carrega:
            bad('disse "sem capa" com a capa ainda sendo aberta')
        elif not quando_falha:
            bad('a capa não abriu e a tela não diz nada')
        else:
            ok("cala enquanto carrega, e fala quando não há capa mesmo")
    except Exception:                                       # noqa: BLE001
        bad("sem capa", traceback.format_exc())

    secao("PRIMEIRA VEZ: dita quando a agulha encosta, e só num disco novo")
    # POR QUE ISTO EXISTE
    # -------------------
    # É a família do `set_text` do deck: o `play_banner` — "PRIMEIRA VEZ",
    # dito no instante em que a agulha desce num disco nunca posto — existia
    # no deck e não sobreviveu à mudança para o lançador. Ler não pega: a
    # AGORA tem a frase escrita no rodapé, em cinza, no meio de outras
    # quatro informações, e isso LÊ como se o recurso estivesse lá.
    #
    # Então o teste não pergunta "a frase existe?". Ele põe um disco e olha
    # o que CHEGA na tela, e quando: nada antes de a agulha encostar, e nada
    # nenhum num disco que já foi posto — um aviso que aparece toda vez é um
    # aviso que não quer dizer nada.
    try:
        import time as _t
        salvo_itens = list(app.shelf.items)
        _ag = next(t for t in app.screens if t.name == "AGORA")
        novo_d, velho_d = "/tmp/stylus-teste/Novo", "/tmp/stylus-teste/Velho"
        app.shelf.items = [
            {"folder": novo_d, "artist": "A", "name": "Novo", "tracks": 9,
             "cover": None, "last": 0, "plays": 0},
            {"folder": velho_d, "artist": "A", "name": "Velho", "tracks": 9,
             "cover": None, "last": 0, "plays": 7},
        ]

        def _por(pasta):
            """Põe o disco como o laço principal põe: troca a pasta e roda."""
            app._pasta_tocando = lambda: pasta
            app._disco_anterior = "/tmp/stylus-teste/anterior"
            app._born = _t.time() - 60      # não é "abriu com música tocando"
            app._primeira_em = 0.0
            app._toast, app._toast_until, app._toast_kind = "", 0.0, "info"
            app._disco_novo()

        try:
            app.shuffle, app.repeat = False, 0
            _por(novo_d)
            marcou = app._primeira_em > 0.0
            # ainda girando: a agulha não encostou.
            app._primeira_vez()
            cedo, cedo_txt = bool(app._toast), app._toast
            # o momento marcado é o FIM da cerimônia, não o começo dela.
            atraso = app._primeira_em - app.cerimonia_t0
            esperado = _ag.CER_SPIN + _ag.CER_CUE + _ag.CER_DROP
            app._primeira_em = _t.monotonic() - 0.01
            app._primeira_vez()
            falou = app._toast
            kind = app._toast_kind
            # e fala UMA vez: o laço roda sessenta vezes por segundo.
            app._toast, app._toast_until = "", 0.0
            app._primeira_vez()
            repetiu = bool(app._toast)

            _por(velho_d)
            marcou_velho = app._primeira_em > 0.0

            # disco que a estante não conhece: não se afirma o que não se sabe
            _por("/tmp/stylus-teste/Desconhecido")
            marcou_estranho = app._primeira_em > 0.0

            # E o último fio: o laço principal CHAMA isto. Sem esta linha o
            # teste inteiro passa verde sobre um método que ninguém chama —
            # que é precisamente o defeito (o `set_text` do deck) que esta
            # seção existe para impedir. Medido: tirando a chamada do
            # `run()`, tudo acima continuava verde.
            import inspect as _insp
            no_laco = "self._primeira_vez()" in _insp.getsource(type(app).run)
        finally:
            app.shelf.items = salvo_itens
            app.__dict__.pop("_pasta_tocando", None)
            app._disco_anterior = None
            app._primeira_em = 0.0
            app._toast, app._toast_until, app._toast_kind = "", 0.0, "info"
            app.cerimonia_t0 = 0.0

        if not marcou:
            bad("disco nunca posto e nada foi marcado para dizer")
        elif cedo:
            bad("falou antes de a agulha encostar", cedo_txt)
        elif abs(atraso - esperado) > 0.01:
            bad("não é o instante da agulha",
                f"{atraso:.2f}s contra {esperado:.2f}s de cerimônia")
        elif "PRIMEIRA VEZ" not in (falou or ""):
            bad("a agulha encostou e não disse nada", repr(falou))
        elif kind != "primeira":
            bad("dito como recado de máquina, não como acontecimento", kind)
        elif repetiu:
            bad("repete em todo quadro")
        elif marcou_velho:
            bad("um disco já posto foi anunciado como primeira vez")
        elif marcou_estranho:
            bad("disco que a estante não conhece foi chamado de novo")
        elif not no_laco:
            bad("o laço principal não chama _primeira_vez(): ninguém vê nada")
        else:
            ok("dita na descida da agulha, uma vez, e só num disco novo")
    except Exception:                                       # noqa: BLE001
        bad("a primeira vez", traceback.format_exc())

    secao("a trava do gato engole tudo, e só a combinação destrava")
    # POR QUE ISTO EXISTE
    # -------------------
    # Uma trava que deixa passar UMA tecla não é uma trava: o gato anda por
    # cima do teclado inteiro, e a que passar é a que troca de disco. Então o
    # teste não pergunta "o `g` funciona?", ele varre o teclado inteiro
    # travado e exige que NADA tenha acontecido — nem seção trocada, nem
    # tela cheia, nem trilho aberto.
    #
    # E o destravar é por ESTADO (segurar), não por evento: quem lê só o
    # KEYDOWN destravaria com um toque, que é o que um gato dá.
    try:
        agora = next(t for t in app.screens if t.name == "AGORA")
        app._goto(app.screens.index(agora))
        app.rail = False
        agora.tela_cheia = False
        app.travar_gato(True)
        antes = (app.cur, app.rail, agora.tela_cheia)
        for k in (pygame.K_f, pygame.K_ESCAPE, pygame.K_TAB, pygame.K_RETURN,
                  pygame.K_SPACE, pygame.K_s, pygame.K_n, pygame.K_1,
                  pygame.K_q, pygame.K_RIGHT, pygame.K_g):
            app._key(pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                        mod=0))
        app._clique(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(10, 10),
                                       button=1))
        depois = (app.cur, app.rail, agora.tela_cheia)
        if depois != antes:
            bad("travado, uma tecla atravessou", f"{antes} -> {depois}")
        elif app.gato_tentativas != 12:
            bad("a contagem do gato", f"contou {app.gato_tentativas}, esperado 12")
        else:
            ok("12 tentativas contadas e nenhuma atravessou")

        # ── e o desenho ─────────────────────────────────────────────────
        app._gato_ultima = time.time()
        app._gato_segurando = time.time() - 0.5
        import theme as _T
        app.surf.fill(_T.INK)
        app._draw_gato(app.surf)
        ok("a tela travada desenha")

        # ── destravar: segurar os três ──────────────────────────────────
        pressed = {pygame.K_ESCAPE: 1}
        classe_get = pygame.key.get_pressed
        classe_mods = pygame.key.get_mods
        pygame.key.get_pressed = lambda: [pressed.get(i, 0) for i in range(600)]
        pygame.key.get_mods = lambda: pygame.KMOD_CTRL | pygame.KMOD_ALT
        try:
            app._gato_segurando = 0.0
            app._gato_destrava()                    # primeiro quadro: arma
            travado_no_toque = app.gato
            app._gato_segurando = time.time() - (app.GATO_SEGURAR + 0.1)
            app._gato_destrava()
            destravou = not app.gato
            # e um toque solto não destrava
            app.travar_gato(True)
            pygame.key.get_mods = lambda: 0
            app._gato_segurando = time.time() - 9.0
            app._gato_destrava()
            sem_mods = app.gato
        finally:
            pygame.key.get_pressed = classe_get
            pygame.key.get_mods = classe_mods
            app.travar_gato(False)
        if not travado_no_toque:
            bad("um TOQUE na combinação destravou (tem que ser segurando)")
        elif not destravou:
            bad("segurar ctrl+alt+esc não destravou")
        elif not sem_mods:
            bad("o ESC sozinho destrava — o gato faz isso deitando")
        else:
            ok("segurar destrava, tocar não, e sem os modificadores não")
    except Exception:                                       # noqa: BLE001
        bad("a trava do gato", traceback.format_exc())

    secao("a soneca esmaece e levanta a agulha")
    # **Sintoma que isto impede:** um `playerctl pause` seco no meio de uma
    # faixa. O que acorda alguém quase dormindo é o CORTE, não o silêncio.
    # E o defeito da família "tecla que muda um campo e acende um ícone": o
    # teste põe um mpv de mentira e olha o que CHEGA nele.
    try:
        recebidos = []
        real = app._ao_tocador
        app._ao_tocador = lambda *c: (recebidos.append(c),
                                      100.0 if c[:2] == ("get_property", "volume")
                                      else {"error": "success"})[1]
        try:
            # o ciclo inteiro do [t]
            app._sleep_minutes, app._sleep_lado = 0, False
            vistos = []
            for _ in range(len(app.SONECA)):
                app.toggle_sleep()
                vistos.append(-1 if app._sleep_lado else app._sleep_minutes)
            ciclo_ok = sorted(vistos) == sorted(app.SONECA)

            # esmaecimento: 20s de rampa, e no fim a agulha levanta
            app._sleep_lado = False
            app._sleep_minutes = 30
            app._sleep_end = time.time() - 1        # já passou
            app._sleep_fade = 0.0
            app._vol_antes = None
            recebidos.clear()
            app._soneca()
            app._sleep_passo = 0.0
            app._sleep_fade = time.time() - (app.ESMAECER * 0.5)
            app._soneca()
            meio = [c for c in recebidos if c[:2] == ("set_property", "volume")]
            app._sleep_passo = 0.0
            app._sleep_fade = time.time() - (app.ESMAECER + 1)
            app._soneca()
            pausou = any(c[:3] == ("set_property", "pause", True)
                         for c in recebidos)
            devolveu = recebidos[-1][:2] == ("set_property", "volume") and \
                recebidos[-1][2] == 100.0
        finally:
            app._ao_tocador = real
            app._sleep_minutes, app._sleep_lado = 0, False
            app._sleep_fade, app._vol_antes = 0.0, None
        if not ciclo_ok:
            bad("o [t] não passa por todas as sonecas", str(vistos))
        elif not meio or meio[-1][2] >= 100.0:
            bad("o volume não desceu durante o esmaecimento", str(meio[-3:]))
        elif not pausou:
            bad("a soneca não levantou a agulha no fim")
        elif not devolveu:
            bad("o volume não voltou: o disco de amanhã começa mudo",
                str(recebidos[-1]))
        else:
            ok(f"{len(app.SONECA)} sonecas, o volume desce em {app.ESMAECER:.0f}s "
               f"e volta depois")
    except Exception:                                       # noqa: BLE001
        bad("a soneca", traceback.format_exc())

    secao("a linha de dicas não promete tecla que a seção ignora")
    # A irmã da conferência do Mod+F1 no check.sh, do lado de cá: lá a lista
    # de atalhos do i3 prometia teclas ligadas a OUTRA coisa; aqui o rodapé
    # de cada seção anuncia as teclas dela. Uma tecla anunciada e não tratada
    # não estoura, não vira traceback e não aparece em teste nenhum — ela só
    # não faz nada, e quem apertou conclui que o programa travou.
    #
    # Só o `hint` (o rodapé), que fala das teclas DESTA tela. O `T.vazio` é
    # outra coisa: ele manda para outra seção ("na estante, [s] empilha"), e
    # exigir que a tela atual trate aquela tecla acusaria o texto certo.
    try:
        import re as _re2
        import theme as _T3
        anunciadas = {}
        _hint_orig = A.App.hint

        def _espia_hint(self, s_, r_, texto, contexto=None, **k):
            anunciadas.setdefault(self.screens[self.cur].name, set()).update(
                _re2.findall(r"\[([^\]]+)\]", texto))
            return _hint_orig(self, s_, r_, texto, contexto, **k)

        A.App.hint = _espia_hint
        try:
            for i, tela in enumerate(app.screens):
                app._goto(i)
                tela.draw(app.surf, corpo)
        finally:
            A.App.hint = _hint_orig

        NOMES = {"enter": pygame.K_RETURN, "space": pygame.K_SPACE,
                 "del": pygame.K_DELETE, "/": pygame.K_SLASH,
                 "↑": pygame.K_UP, "↓": pygame.K_DOWN,
                 "←": pygame.K_LEFT, "→": pygame.K_RIGHT}
        # As que o App trata por cima de todas as seções.
        GLOBAIS = {"esc", "tab", "f1", "1", "2", "3", "4", "5", "6", "7",
                   "8", "9", "0"}
        mudas = []
        for i, tela in enumerate(app.screens):
            app._goto(i)
            for rotulo in sorted(anunciadas.get(tela.name, ())):
                nome = rotulo.strip().lower()
                if nome in GLOBAIS or "+" in nome:
                    continue
                tecla = NOMES.get(nome)
                if tecla is None and len(nome) == 1 and nome.isalpha():
                    tecla = getattr(pygame, "K_" + nome, None)
                if tecla is None:
                    continue
                mod = pygame.KMOD_SHIFT if rotulo.strip().isupper() else 0
                ev = pygame.event.Event(pygame.KEYDOWN, key=tecla,
                                        unicode=nome, mod=mod)
                try:
                    if not tela.key(ev):
                        mudas.append("%s: [%s]" % (tela.name, rotulo))
                except Exception as e:                      # noqa: BLE001
                    mudas.append("%s: [%s] estourou (%s)"
                                 % (tela.name, rotulo, e))
        # Apertar as teclas deixou as lojas "procurando" e com formulário
        # aberto: quem vier depois mede uma tela que não desenha grade.
        encher_as_lojas(app)
        if mudas:
            bad("%d teclas anunciadas e não tratadas" % len(mudas),
                ", ".join(mudas[:8]))
        else:
            ok("as %d seções tratam toda tecla que o rodapé delas anuncia"
               % len(app.screens))
    except Exception:                                       # noqa: BLE001
        bad("dicas contra teclas", traceback.format_exc())

    secao("trocar de playlist do Qobuz troca o disco da AGORA")
    # **Sintoma:** o `dirname` de um ENDEREÇO é a mesma string para toda
    # playlist do Qobuz, e sob mpv o artista e o álbum do snapshot vêm
    # vazios — então a chave de "trocou de disco?" era a MESMA para todas as
    # playlists. A AGORA ficava com a lista anterior na mão: o nome da faixa,
    # o LADO, o "vira em X" e a agulha no sulco, todos da lista de antes.
    try:
        import model as _M
        URLS = {"A": "https://o-servidor.invalid/a%d.flac",
                "B": "https://o-servidor.invalid/b%d.flac"}
        pedidos = []

        class _AlbFake:
            def __init__(self, pasta):
                self.folder = pasta
                self.tracks = [{"path": URLS[pasta] % i, "title": "t%d" % i,
                                "duration": 300.0} for i in range(4)]
                self.total = 1200.0

        class _SessaoFake:
            atual = URLS["A"] % 0

            def snapshot(self):
                # como o mpv responde: sem artista e sem álbum
                return {"path": _SessaoFake.atual, "artist": "", "album": "",
                        "paused": False}

        tocando = _M.Playing.__new__(_M.Playing)
        tocando.session = _SessaoFake()
        tocando.album = None
        tocando._key = None
        tocando._resolving = False
        tocando._tentei = 0.0
        tocando._ti_cache = [None, 0]

        def _resolve_fake(snap):
            pedidos.append(snap.get("path"))
            tocando.album = _AlbFake("B" if "/b" in snap["path"] else "A")
            tocando._resolving = False

        tocando._resolve = _resolve_fake
        # sem thread: o que se quer medir é a DECISÃO de reabrir
        _antes = _M.threading.Thread
        _M.threading.Thread = lambda target=None, args=(), daemon=None: type(
            "T", (), {"start": lambda _s: target(*args)})()
        try:
            tocando.snapshot()
            primeiro = tocando.album.folder if tocando.album else None
            _SessaoFake.atual = URLS["A"] % 2          # mesma lista
            tocando.snapshot()
            meio = tocando.album.folder if tocando.album else None
            n_meio = len(pedidos)
            _SessaoFake.atual = URLS["B"] % 0          # outra lista
            tocando.snapshot()
            depois = tocando.album.folder if tocando.album else None
        finally:
            _M.threading.Thread = _antes
        if primeiro != "A":
            bad("nem o primeiro disco resolveu (%s)" % primeiro)
        elif n_meio != 1 or meio != "A":
            bad("reabriu o disco andando na MESMA playlist (%d pedidos)"
                % n_meio)
        elif depois != "B":
            bad("ficou com a playlist anterior na mão (%s)" % depois)
        else:
            ok("a lista nova entra, a faixa seguinte não reabre nada")
    except Exception:                                       # noqa: BLE001
        bad("troca de playlist", traceback.format_exc())

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
        #
        #    Com as lojas cheias e arrumadas: elas chegam aqui depois de duas
        #    varreduras de teclado, com busca começada e formulário aberto, e
        #    uma tela que sai cedo no "buscando…" não desenha alvo nenhum.
        encher_as_lojas(app)
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
