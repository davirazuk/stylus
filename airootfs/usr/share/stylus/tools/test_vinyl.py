#!/usr/bin/env python3
"""O vinyl.py exercitado sem tela: o disco, os lados, a memória, as letras.

Por que existe: todos os defeitos da noite em que o ritual foi ligado eram
DESTE tipo — contrato de função, portão que nunca abria, formato de retorno —
e nenhum apareceu lendo o código. Apareceram olhando a tela, que é o jeito
mais caro possível de encontrar um `resolve_album()` que devolve string.

Chamava-se `test_ritual.py` e morava no deck. O deck saiu; o que ele testava
de DESENHO saiu com ele (a geometria em numpy, a cerimônia como máquina de
estados, as legendas do ritual), e o que ficou é o que sempre foi a
biblioteca: achar o disco, reparti-lo em lados, contar as colocações, casar a
faixa que o tocador diz com a faixa do álbum, ler o .lrc.

Aparência se confere olhando — hoje, no lançador:

    stylus deck "<álbum>"        e depois [f]

    python3 tools/test_vinyl.py [--album CAMINHO]
"""
import argparse
import json
import math
import os
import shutil as _shutil
import sys
import tempfile
import time

# O vinyl mora ao lado, em ../lib. Os dois caminhos: o da instalação e o
# relativo a este arquivo, que é o que serve para rodar do repositório.
_aqui = os.path.dirname(os.path.abspath(__file__))
for _p in ("/usr/share/stylus/lib", os.path.join(os.path.dirname(_aqui), "lib")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
import numpy as np
import vinyl

PASS = FAIL = 0


def check(desc, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"    \033[1;32m✓\033[0m {desc}")
    else:
        FAIL += 1
        print(f"    \033[1;31m✗\033[0m {desc}")


def case(name):
    print(f"\n  \033[2m{name}\033[0m")


def _default_album(arg):
    """Sem --album, tira um disco da estante configurada.

    O padrão antigo era a pasta de um álbum específico na casa de quem
    escreveu isto. Num sistema, o padrão tem que ser "o que houver aí".
    """
    if arg:
        return os.path.expanduser(arg)
    import vinyl as _v
    return _v.draw_record() or _v.library_root()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", default=None,
                    help="pasta do disco; sem isto, sorteia um da estante")
    args = ap.parse_args()
    folder_hint = _default_album(args.album)

    case("resolve_album devolve a PASTA, não um Album")
    # Esta era a confusão nº1: guardar o retorno como se fosse o álbum e só
    # descobrir no primeiro acesso a .total.
    audio = None
    if os.path.isdir(folder_hint):
        for n in sorted(os.listdir(folder_hint)):
            if n.lower().endswith(vinyl.AUDIO_EXT):
                audio = os.path.join(folder_hint, n)
                break
    if audio is None:
        print("    (sem álbum de teste; passe --album)")
        return 0
    got = vinyl.resolve_album(audio)
    check("devolve str", isinstance(got, str))
    check("e a str é uma pasta que existe", os.path.isdir(got or ""))
    check("sem caminho e sem álbum, devolve None", vinyl.resolve_album(None, "", "") is None)

    case("Album lê o disco")
    alb = vinyl.Album(got)
    for _ in range(150):
        if alb.envelope_snapshot() is not None:
            break
        time.sleep(0.2)
    check("achou faixas", len(alb.tracks) > 0)
    check("tem duração total", (alb.total or 0) > 0)
    check("o envelope de intensidade ficou pronto", alb.envelope_snapshot() is not None)
    check("dividiu em pelo menos um lado", len(alb.sides) >= 1)
    # Um lado de LP não passa de ~22 min; é a regra que faz o disco ser disco.
    # Um lado só pode passar dos 22 minutos quando tem UMA faixa só — não se
    # corta uma música ao meio, e uma faixa de 25 minutos ocupa o lado que
    # ela ocupa. Com mais de uma faixa é defeito de empacotamento, e era: 69
    # dos 374 discos desta coleção tinham um lado assim.
    check("nenhum lado passa do limite físico com mais de uma faixa",
          all(s["end"] - s["start"] <= vinyl.SIDE_MAX_SECONDS + 1
              or len(s["tracks"]) == 1 for s in alb.sides))
    i0, s0 = alb.side_for(0.0)
    check("o instante 0 cai no primeiro lado", i0 == 0 and s0 is not None)
    iN, sN = alb.side_for(max(0.0, (alb.total or 0) - 1.0))
    check("o último instante cai no último lado", iN == len(alb.sides) - 1)
    check("album_time soma o início da faixa",
          abs(alb.album_time(0, 5.0) - (alb.tracks[0]["start"] + 5.0)) < 1e-6)

    # (Aqui rodavam três casos sobre a classe `vinyl.Deck` — a cerimônia
    # como máquina de estados, o fim do disco com o braço voltando ao berço,
    # e o cue subindo ao pausar. O `Deck` era do deck, o deck saiu, e a
    # cerimônia que ficou é a do lançador: três durações e o desenho da
    # descida, exercitados pelo `ui/tools/test_ui.py`, que varre o teclado
    # girando entre as fases dela.)

    case("a memória do disco")
    a, b = "/x/Radiohead/Kid A", "/x/Radiohead/Amnesiac"
    # (As marcas de uso lidas do envelope — `wear_counts`/`wear_marks` — e a
    # semente por disco que as tornava DELE eram desenho do deck, e saíram
    # com ele. O que ficou é a contagem, que é memória e não desenho.)

    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".tsv")
    os.close(fd)
    os.unlink(tmp)
    real, vinyl.PLAYS_TSV = vinyl.PLAYS_TSV, tmp
    try:
        check("disco nunca posto conta zero", vinyl.play_history(a)[0] == 0)
        check("a primeira colocação conta 1", vinyl.log_play(a, "R", "Kid A") == 1)
        # A barra e a cerimônia anotam a MESMA colocação com segundos de
        # diferença. Sem a janela, todo disco contaria dobrado.
        check("a segunda dentro da janela não conta de novo",
              vinyl.log_play(a, "R", "Kid A") == 1)
        check("e não escreveu linha nova",
              sum(1 for _ in open(tmp, encoding="utf-8")) == 1)
        check("fora da janela conta", vinyl.log_play(a, "R", "Kid A", cooldown=0.0) == 2)
        check("outro disco tem a própria conta", vinyl.log_play(b, "R", "Amn") == 1)
        n, first, last = vinyl.play_history(a)
        check("play_history devolve (n, primeira, última)",
              n == 2 and first <= last and first > 0)
    finally:
        vinyl.PLAYS_TSV = real
        try:
            os.unlink(tmp)
        except OSError:
            pass

    case("achar a faixa quando o tocador não numera")
    # O defeito de verdade: o Session só numera faixa sob mpv. Sob MPRIS o
    # número que sobrava era o da sessão anterior, e o braço ia para o lado
    # errado — no Strawberry, que é o tocador que ele usa.
    if len(alb.tracks) >= 3:
        p2 = alb.tracks[2]["path"]
        mpris = {"source": "mpris", "path": p2, "track_index": 0}
        cache = [None, 0]
        check("acha a faixa pelo caminho",
              vinyl.track_index_for(alb, mpris, cache) == 2)
        check("e guarda no cache", cache == [p2, 2])
        check("o cache responde igual",
              vinyl.track_index_for(alb, mpris, cache) == 2)
        # Sob mpv o CAMINHO também ganha do número, e é isto que faz o
        # embaralhar não estragar o resto da tela: `playlist-shuffle` reordena
        # a lista, o `playlist-pos` passa a ser a posição na lista embaralhada
        # e não a faixa do disco, e tudo que se conta a partir dele sai errado
        # junto — nome da faixa, LADO, "vira em 6 min", a agulha no sulco, e o
        # índice gravado para retomar depois.
        check("sob mpv o caminho ganha do número (lista embaralhada)",
              vinyl.track_index_for(alb, {"source": "mpv", "path": p2,
                                          "track_index": 7}, None) == 2)
        # E o número continua sendo a resposta quando o caminho não casa: um
        # disco da rede reassinado tem endereço novo, e aí o índice do mpv é
        # a única coisa que sobra.
        check("sem caminho que case, o número do mpv vale",
              vinyl.track_index_for(alb, {"source": "mpv",
                                          "path": "https://x.invalid/z.flac",
                                          "track_index": 1}, None) == 1)
        check("caminho de fora do álbum não inventa faixa",
              vinyl.track_index_for(alb, {"source": "mpris", "path": "/x/y.flac",
                                          "track_index": 99}, None) == 0)
        check("sem álbum, devolve o que veio",
              vinyl.track_index_for(None, {"source": "mpris", "track_index": 4}) == 4)

    case("a lista que o mpv recebe é a mesma que o Album lê")
    # Dando a PASTA ao mpv, o cover.jpg entra na lista e o índice deixa de
    # bater com Album.tracks no fim do disco.
    paths = vinyl.track_paths(got)
    check("track_paths acha as mesmas faixas",
          [os.path.basename(p) for p in paths]
          == [os.path.basename(t["path"]) for t in alb.tracks])
    check("e nenhuma delas é imagem",
          all(p.lower().endswith(vinyl.AUDIO_EXT) for p in paths))

    case("as letras")
    idx = next((i for i in range(len(alb.tracks)) if alb.lyrics_for(i)), None)
    if idx is None:
        print("    (nenhuma faixa com .lrc neste álbum)")
    else:
        ly = alb.lyrics_for(idx)
        check("vem como (segundos, texto)",
              all(isinstance(t, (int, float)) and isinstance(x, str) for t, x in ly))
        check("em ordem de tempo", all(ly[i][0] <= ly[i + 1][0] for i in range(len(ly) - 1)))
        # As linhas em branco são guardadas de propósito: são os instrumentais,
        # e é isso que tira a última frase da tela num outro longo.
        check("guarda as linhas em branco", any(x.strip() == "" for _t, x in ly))

    if not alb.sides or not (alb.total or 0):
        # Daqui para baixo tudo mede o LADO, e sem duração não há lado: o
        # `alb.sides[0]` estourava um IndexError cru, que se lê como defeito
        # do vinyl.py e é falta de dado. E o caso comum não é álbum estranho,
        # é máquina sem ffprobe — ali TODA faixa mede zero e este arquivo
        # inteiro fica inutilizável sem dizer por quê.
        import shutil as _sh
        porque = ("" if _sh.which("ffprobe")
                  else " — não há ffprobe nesta máquina, e é ele que mede")
        print(f"\n  \033[2mo álbum de teste não tem duração{porque}:\033[0m"
              "\n  \033[2ma geometria, a cerimônia e a agulha ficam de fora"
              " desta rodada\033[0m")
        print(f"\n  \033[1;32m{PASS} passaram\033[0m"
              + (f", \033[1;31m{FAIL} falharam\033[0m" if FAIL else "") + "\n")
        return 1 if FAIL else 0

    # (Aqui rodava o caso "a geometria devolve o formato que o scope.py
    # consome": ~65 conferências sobre os vértices que o `disc_body`, o
    # `groove_rings` e o `tonearm` entregavam ao OpenGL. Saíram com eles.)

    case("um disco solto na raiz não é da banda 'Songs'")
    import tempfile as _tf
    _raiz = _tf.mkdtemp(prefix="stylus-raiz-")
    try:
        # O MUSIC_ROOTS é um _Roots, que RELÊ a configuração a cada iteração
        # — atribuir a ele não muda nada. Quem manda é o STYLUS_LIBRARY, que
        # é a primeira coisa que o _configured_roots olha.
        _antes = os.environ.get("STYLUS_LIBRARY")
        os.environ["STYLUS_LIBRARY"] = _raiz
        for _n in ("1993-02-11 - Radiohead - Tel Aviv",
                   "Radiohead - Lost Treasures", "subjectobjectnoun"):
            os.makedirs(os.path.join(_raiz, _n), exist_ok=True)
        os.makedirs(os.path.join(_raiz, "Alex G", "Rocket"), exist_ok=True)
        _a, _d = vinyl.folder_names(os.path.join(_raiz, "1993-02-11 - Radiohead - Tel Aviv"))
        check("a data na frente não vira artista", (_a, _d) == ("Radiohead", "Tel Aviv"))
        _a, _d = vinyl.folder_names(os.path.join(_raiz, "Radiohead - Lost Treasures"))
        check("'Artista - Álbum' solto na raiz se separa",
              (_a, _d) == ("Radiohead", "Lost Treasures"))
        _a, _d = vinyl.folder_names(os.path.join(_raiz, "subjectobjectnoun"))
        check("sem artista no nome e sem arquivo, devolve vazio — não o nome da raiz",
              _a == "" and _d == "subjectobjectnoun")
        _a, _d = vinyl.folder_names(os.path.join(_raiz, "Alex G", "Rocket"))
        check("e Artista/Álbum continua sendo lido como sempre",
              (_a, _d) == ("Alex G", "Rocket"))
    finally:
        if _antes is None:
            os.environ.pop("STYLUS_LIBRARY", None)
        else:
            os.environ["STYLUS_LIBRARY"] = _antes
        _shutil.rmtree(_raiz, ignore_errors=True)

    # ── o empacotamento dos lados, com medidas exatas ─────────────────────
    case("os lados nunca passam do que cabe num lado")

    class _Falso:
        """Um Album só com o que o _build_sides precisa."""
        def __init__(self, duracoes):
            self.tracks, t = [], 0.0
            for d in duracoes:
                self.tracks.append({"start": t, "duration": float(d)})
                t += d
            self.total = t
            self.sides = []
            vinyl.Album._build_sides(self)

    # O caso que quebrava, e o motivo: a regra de equilíbrio só fecha um lado
    # quando ainda FALTAM lados. O ÚLTIMO nunca era conferido — ele leva o
    # que sobrou, seja quanto for. Quatro faixas curtas e uma longa: a regra
    # nunca dispara (não há faixa sobrando para o lado seguinte), e os 26,7
    # minutos inteiros viram um lado só.
    _f = _Falso([100, 100, 100, 100, 1200])
    check("o último lado também respeita o teto",
          all(sd["end"] - sd["start"] <= vinyl.SIDE_MAX_SECONDS + 1
              or len(sd["tracks"]) == 1 for sd in _f.sides))
    check("e nenhuma faixa se perde no caminho",
          sorted(i for sd in _f.sides for i in sd["tracks"]) == list(range(5)))
    check("os lados são contíguos, sem buraco entre eles",
          all(abs(_f.sides[i]["end"] - _f.sides[i + 1]["start"]) < 1e-6
              for i in range(len(_f.sides) - 1)))
    # Uma faixa maior que o lado inteiro fica sozinha nele.
    _g = _Falso([300, 1900, 300])
    check("uma faixa longa demais fica sozinha no lado dela",
          any(len(sd["tracks"]) == 1
              and sd["end"] - sd["start"] > vinyl.SIDE_MAX_SECONDS
              for sd in _g.sides))
    # ── um disco tem DOIS lados, e um disco duplo tem quatro ──────────────
    # **Sintoma:** um LP de 45 minutos — Abbey Road, Led Zeppelin IV, a forma
    # mais comum que um disco tem — saía com TRÊS lados de quinze minutos. A
    # conta arredondava o número de LADOS para cima (`ceil(45/22)`), e não
    # existe disco de três lados: existe de dois, e disco duplo de quatro.
    for minutos, esperado, quem in ((45, 2, "um LP comum"),
                                    (74, 4, "um CD cheio, dois LPs"),
                                    (90, 4, "um disco duplo"),
                                    (113, 6, "um triplo")):
        _n = _Falso([225] * int(minutos * 60 // 225))
        if len(_n.sides) != esperado:
            check("%s (%d min) dá %d lados" % (quem, minutos, esperado), False)
        else:
            check("%s (%d min) dá %d lados — e é par"
                  % (quem, minutos, esperado), True)
    _um = _Falso([210] * 6)
    check("o que cabe num lado só continua sendo um lado só",
          len(_um.sides) == 1)

    # ── seis segundos não fazem um disco duplo ───────────────────────────
    # **Sintoma:** um LP de 50 minutos em doze faixas saía com QUATRO lados.
    # Com o teto confortável em 26 minutos, nenhum corte em dois lados cabia
    # — as somas parciais pulam de 21,8 para 26,1 — e 26,1 passa por seis
    # segundos. A prensagem de verdade resolve isso baixando um pouco o
    # nível e pondo os 26,1 no lado; a conta aqui preferia o disco duplo,
    # que é a coisa mais cara que ela pode decidir.
    _duplo = _Falso([180 + i * 11 for i in range(1, 13)])
    check("50 min em 12 faixas é UM disco, não dois", _duplo.discos == 1)
    check("e são dois lados", len(_duplo.sides) == 2)
    _longas = _Falso([600] * 5)
    check("cinco faixas de dez minutos também", _longas.discos == 1)
    # E o plano continua sendo feito com o teto CONFORTÁVEL: um disco que
    # cabe folgado em dois lados não passa a usar os trinta minutos.
    _folgado = _Falso([225] * 12)
    check("um disco de 45 min continua em dois lados de 22min30",
          len(_folgado.sides) == 2
          and abs((_folgado.sides[0]["end"] - _folgado.sides[0]["start"])
                  - 22.5 * 60) < 60)

    # ── e em TODA forma de disco, não só nas quatro escolhidas a dedo ─────
    # **Sintoma:** um disco de 90 minutos em 18 faixas de 5 saía com CINCO
    # lados. Número ímpar é um objeto que não existe — disco tem dois lados
    # sempre — e o teste acima já cobria 90 minutos e passava VERDE, porque
    # ele usa faixas de 3min45 e a granularidade mais fina escondia o
    # defeito. A causa: o alvo do equilíbrio era fixo (`total / n_lados`)
    # com folga de 14% para baixo, então os lados fechavam cedo, o resto não
    # cabia no último, e o teto físico cortava de novo.
    #
    # Uma forma escolhida a dedo prova o caso escolhido a dedo. Isto varre a
    # grade: de 20 a 130 minutos, com faixas de 2 a 9 minutos.
    impares, estouros, discos_errados = [], [], []
    for minutos in range(20, 131, 5):
        for dur_min in (2, 3, 4, 5, 7, 9):
            n = int(minutos * 60 // (dur_min * 60))
            if n < 1:
                continue
            a = _Falso([dur_min * 60.0] * n)
            forma = "%dmin em %d faixas de %d" % (minutos, n, dur_min)
            if len(a.sides) > 1 and len(a.sides) % 2:
                impares.append("%s → %d lados" % (forma, len(a.sides)))
            # O teto só vale para lado com mais de uma faixa: não se corta
            # uma música ao meio.
            for sd in a.sides:
                # Contra o teto FÍSICO (30 min) e não contra o confortável
                # (26): o confortável decide quantos lados PLANEJAR, e o
                # físico é o que um lado de 12" aguenta de verdade, com o
                # nível um pouco abaixo. Um disco de 50 minutos cujas somas
                # parciais pulam de 21,8 para 26,1 não cabe em dois lados
                # confortáveis — e virava DISCO DUPLO por seis segundos.
                if (len(sd["tracks"]) > 1
                        and sd["end"] - sd["start"] > vinyl.SIDE_HARD_SECONDS + 1):
                    estouros.append("%s → lado de %.1f min"
                                    % (forma, (sd["end"] - sd["start"]) / 60))
            if a.discos != max(1, (len(a.sides) + 1) // 2):
                discos_errados.append("%s → %d lados mas %d discos"
                                      % (forma, len(a.sides), a.discos))
    if impares:
        print("      %s" % "; ".join(impares[:3]))
    check("nenhuma forma de disco dá um número ÍMPAR de lados", not impares)
    if estouros:
        print("      %s" % "; ".join(estouros[:3]))
    check("e nenhum lado de várias faixas passa do teto físico", not estouros)
    if discos_errados:
        print("      %s" % "; ".join(discos_errados[:3]))
    check("o número de DISCOS bate com o de lados", not discos_errados)

    # Uma faixa única maior que um lado: um lado, e UM disco. O número de
    # discos vinha do plano (quatro lados para uma hora) e não do que foi
    # cortado de verdade — a tela escrevia "DISCO 2 · LADO A" de um disco
    # que tem um lado só.
    _gigante = _Falso([3600.0])
    check("uma faixa de uma hora é um lado e um disco",
          len(_gigante.sides) == 1 and _gigante.discos == 1)

    # ── faixa que não deu para medir ──────────────────────────────────────
    # **Sintoma:** uma faixa que nem o mutagen nem o ffprobe sabem ler entrava
    # com duração ZERO — e zero não é "não sei", é "não dura nada". Três
    # dessas num disco de doze tiram um quarto do total: o disco perde um LADO
    # inteiro, o "vira em X" mente, e a agulha do deck aponta para o sulco
    # errado. Sem erro nenhum em lugar nenhum.
    class _SemMedida(vinyl.Album):
        def __init__(self, duracoes):
            self.folder, self.artist, self.name = "/x", "A", "B"
            self.year, self.cover = "", None
            self.plays = self.last_played = 0
            self.total, self.sides = 0.0, []
            self.tracks = [{"path": "/x/%d" % i, "title": "F%d" % i,
                            "duration": float(d), "start": 0.0}
                           for i, d in enumerate(duracoes)]
            _real = vinyl._probe_duration
            vinyl._probe_duration = lambda _p: 0.0   # nada é mensurável aqui
            try:
                self._measure_durations()
                self._build_sides()
            finally:
                vinyl._probe_duration = _real

    _b = _SemMedida([225] * 9 + [0, 0, 0])
    check("três faixas sem medida não encolhem o disco",
          abs(_b.total - 225 * 12) < 1.0)
    check("e o disco continua com os dois lados que ele tem",
          len(_b.sides) == 2)
    check("as estimadas ficam marcadas",
          sum(1 for t in _b.tracks if t.get("estimada")) == 3)
    # A MEDIANA e não a média: ela resiste a uma faixa de vinte minutos no
    # meio de onze de três, que é onde a média estragaria tudo.
    _c = _SemMedida([180] * 10 + [1200, 0])
    check("o palpite é a mediana, não a média",
          abs(_c.tracks[-1]["duration"] - 180) < 1.0)
    # E sem NENHUMA medida não se inventa disco: zero é zero.
    check("sem medida nenhuma, não inventa duração",
          _SemMedida([0] * 6).total == 0.0)
    check("e o número de DISCOS acompanha os lados",
          _Falso([225] * 24).discos == 2 and _um.discos == 1)

    # Um disco curto continua sendo um lado só.
    _i = _Falso([330] * 8)
    check("44 min em 8 faixas dá dois lados parelhos",
          len(_i.sides) == 2 and abs((_i.sides[0]["end"] - _i.sides[0]["start"])
                                     - (_i.sides[1]["end"] - _i.sides[1]["start"])) < 60)
    _h = _Falso([200] * 5)
    check("disco curto continua com um lado só", len(_h.sides) == 1)

    # ── um disco que não tem arquivo nenhum ───────────────────────────────
    case("o disco que vem pela rede")
    # O `stylus qobuz tocar` monta uma pasta com capa, lista do mpv e um
    # disco.json. Sem o disco.json, o vinyl tentaria descobrir a ordem lendo
    # arquivos de áudio que não existem — e o aviso de virar o lado, que é a
    # única coisa que esta máquina faz e mais nenhuma faz, não acontecia para
    # quem estava ouvindo pela assinatura.
    import json as _json
    import tempfile as _tempfile
    _tmp = _tempfile.mkdtemp(prefix="stylus-stream-")
    try:
        _pasta = os.path.join(_tmp, "Alguém", "Um Disco")
        os.makedirs(_pasta)
        _url = "https://exemplo.invalid/file?uid=1&eid=%d&hmac=xyz"
        with open(os.path.join(_pasta, "disco.json"), "w", encoding="utf-8") as fh:
            _json.dump({"fonte": "qobuz", "artist": "Alguém", "album": "Um Disco",
                        "year": "1994",
                        "tracks": [{"title": "faixa %d" % i, "duration": 420,
                                    "url": _url % (600 + i)}
                                   for i in range(1, 9)]}, fh)
        with open(os.path.join(_pasta, "lista.m3u"), "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n" + "\n".join(_url % (600 + i) for i in range(1, 9)))
        _al = vinyl.Album(_pasta, envelope=False)
        check("lê o disco.json em vez de procurar arquivo", len(_al.tracks) == 8)
        check("o artista e o disco vêm do manifesto",
              _al.artist == "Alguém" and _al.name == "Um Disco")
        check("as durações vêm do manifesto, sem ffprobe",
              abs(_al.total - 8 * 420) < 1)
        # 56 minutos não cabem num lado: tem que virar mais de um.
        check("e ele TEM LADOS", len(_al.sides) >= 2)
        check("nenhum lado passa do limite de um lado de verdade",
              all(sd["end"] - sd["start"] <= vinyl.SIDE_MAX_SECONDS + 1
                  for sd in _al.sides))
        # E o caminho de volta: do endereço que está tocando para a pasta.
        _cache = vinyl.CACHE_QOBUZ
        vinyl.CACHE_QOBUZ = _tmp
        try:
            _achou = vinyl.resolve_album(_url % 604, "", "")
            check("do endereço tocando de volta para a pasta",
                  _achou == _pasta)
            check("um endereço que não é nosso não casa com nada",
                  vinyl.resolve_album("https://outro.invalid/x?eid=999", "", "")
                  is None)
        finally:
            vinyl.CACHE_QOBUZ = _cache
    finally:
        _shutil.rmtree(_tmp, ignore_errors=True)

    case("todo lado tem rótulo — inclusive o que não é lado")
    # **Sintoma:** a AGORA faz `side["label"]`. O lado único de uma playlist
    # (`continuo: true`) saía SEM rótulo, porque a etiqueta é posta num laço
    # que o atalho da playlist pula — pôr uma playlist do Qobuz e ir para a
    # AGORA levantava KeyError, e a tela principal do sistema virava tela de
    # erro para toda playlist.
    check("os lados de um disco têm rótulo",
          all(s.get("label") for s in alb.sides))
    _tmpc = tempfile.mkdtemp()
    try:
        with open(os.path.join(_tmpc, "disco.json"), "w", encoding="utf-8") as fh:
            json.dump({"fonte": "qobuz-lista", "artist": "Dono",
                       "album": "Grande", "continuo": True,
                       "tracks": [{"title": "F%d" % i, "duration": 200,
                                   "url": "https://x.invalid/%d.flac" % i}
                                  for i in range(40)]}, fh)
        pl = vinyl.Album(_tmpc, envelope=False)
        check("uma playlist de 2h13 continua com UM lado", len(pl.sides) == 1)
        check("e esse lado tem rótulo",
              bool((pl.sides or [{}])[0].get("label")))
        # E não é "LADO A": uma playlist não tem lado nenhum, e é essa a
        # diferença que este sistema existe para marcar.
        check("que não finge ser um lado de disco",
              "SIDE" not in (pl.sides or [{}])[0].get("label", ""))
        check("o side_for dela também responde com rótulo",
              bool(pl.side_for(100.0)[1].get("label")))
    finally:
        _shutil.rmtree(_tmpc, ignore_errors=True)

    # (E aqui rodava o caso "o deck DIZ o que está acontecendo", sobre as
    # legendas do `ritual.py`. Quem diz agora é a tela cheia do lançador, e
    # quem confere é o `ui/tools/test_ui.py`.)

    print(f"\n  \033[1;32m{PASS} passaram\033[0m" + (f", \033[1;31m{FAIL} falharam\033[0m" if FAIL else "") + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
