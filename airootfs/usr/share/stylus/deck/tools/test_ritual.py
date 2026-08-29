#!/usr/bin/env python3
"""Testes sem GL nem janela para a parte não-desenhada do modo ritual.

Por que existe: todos os defeitos da noite em que o ritual foi ligado eram
DESTE tipo - contrato de função, portão que nunca abria, formato de retorno -
e nenhum apareceu lendo o código. Apareceram olhando a tela, que é o jeito
mais caro possível de encontrar um `resolve_album()` que devolve string.

Não testa aparência. Aparência se confere olhando:
    STYLUS_DECK_SHOT_AFTER=20 STYLUS_DECK_SHOT_QUIT=1 vinyl --silent "<álbum>"

    ./venv/bin/python tools/test_ritual.py [--album CAMINHO]
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

    case("a cerimônia anda sozinha")
    # ATENÇÃO, isto custou uma rodada de teste vermelho: o Deck mede o tempo
    # de fase pelo RELÓGIO DA PAREDE (time.monotonic() - t0), não somando o
    # dt que recebe. O dt só serve para a rampa de rotação e para girar o
    # prato. Então um laço apertado passando dt de mentira NÃO faz fase
    # nenhuma avançar - é preciso mexer no t0 (ou esperar de verdade).
    def spin(deck, seconds, playing=True, steps=30):
        for _ in range(steps):
            deck.t0 -= seconds / steps
            deck.update(seconds / steps, playing)

    deck = vinyl.Deck()
    check("começa girando o prato", deck.phase == vinyl.SPINUP)
    seen = set()
    for _ in range(240):
        spin(deck, 0.05)
        seen.add(deck.phase)
        if deck.phase == vinyl.PLAY:
            break
    check("chega em PLAY sozinha", deck.phase == vinyl.PLAY)
    check("passa pelo cue no caminho", vinyl.CUE in seen)
    check("e desce a agulha", vinyl.DROP in seen)
    check("o prato chegou na rotação certa",
          abs(deck.speed - vinyl.REV_PER_SEC) < 0.05)
    # A virada: LIFT -> BREAK sozinho, e o Deck NÃO chama LIFT por conta
    # própria - quem vê a fronteira do lado é quem chama. Era o defeito.
    deck.go(vinyl.LIFT)
    for _ in range(240):
        spin(deck, 0.05, playing=False)
        if deck.phase == vinyl.BREAK:
            break
    check("LIFT vira BREAK sozinho", deck.phase == vinyl.BREAK)
    deck.go(vinyl.RETURN)
    for _ in range(240):
        spin(deck, 0.05)
        if deck.phase == vinyl.CUE:
            break
    check("RETURN volta para o cue", deck.phase == vinyl.CUE)

    case("o fim do disco, e o braço indo até o berço")
    # after_lift é como o RitualScene diz ao Deck se este levantar é a
    # virada de lado (BREAK, prato continua) ou o fim (STOP, prato para).
    deck = vinyl.Deck()
    deck.go(vinyl.PLAY)
    deck.arm_target_radius(0.5)          # é aqui que o lift_radius é guardado
    deck.after_lift = vinyl.STOP
    deck.go(vinyl.LIFT)
    deck.arm_target_radius(0.5)
    for _ in range(240):
        spin(deck, 0.05, playing=False)
        if deck.phase == vinyl.STOP:
            break
    check("com after_lift=STOP, o levantar termina em STOP", deck.phase == vinyl.STOP)
    check("guardou onde a agulha estava", abs(deck.lift_radius - 0.5) < 1e-6)
    # O trajeto até o berço: antes o quadro em que o LIFT vencia jogava a
    # agulha de 0.5 para fora da borda de uma vez só.
    deck.go(vinyl.STOP)
    r0 = deck.arm_target_radius(0.5)
    deck.t0 -= vinyl.TRAVEL_T * 0.5
    r1 = deck.arm_target_radius(0.5)
    deck.t0 -= vinyl.TRAVEL_T
    r2 = deck.arm_target_radius(0.5)
    check("sai de onde a agulha estava", abs(r0 - 0.5) < 0.02)
    check("passa pelo meio do caminho", 0.5 < r1 < vinyl.ARM_REST_RADIUS)
    check("e chega ao berço", abs(r2 - vinyl.ARM_REST_RADIUS) < 1e-6)
    for _ in range(60):
        spin(deck, 0.05, playing=False)
    check("no STOP o prato para", deck.speed < 0.05)

    case("pausar levanta a agulha")
    deck = vinyl.Deck()
    deck.go(vinyl.PLAY)
    for _ in range(40):
        deck.update(0.05, True)
    check("tocando, a agulha está no sulco", deck.arm_lift() < 0.02)
    for _ in range(40):
        deck.update(0.05, False)
    check("pausado, o braço sobe", deck.arm_lift() > 0.95)
    check("mas a fase continua sendo PLAY", deck.phase == vinyl.PLAY)
    check("e o prato não para", deck.speed > vinyl.REV_PER_SEC * 0.9)
    check("o raio não muda: a agulha paira onde estava",
          abs(deck.arm_target_radius(0.61) - 0.61) < 1e-6)
    for _ in range(40):
        deck.update(0.05, True)
    check("despausar baixa de volta", deck.arm_lift() < 0.02)
    # Durante o DROP a fase manda descer; com a música pausada, não desce.
    deck.go(vinyl.DROP)
    for _ in range(40):
        deck.t0 -= 0.02
        deck.update(0.02, False)
    check("a fase não vence a mão da pessoa", deck.arm_lift() > 0.9)

    case("a memória do disco")
    a, b = "/x/Radiohead/Kid A", "/x/Radiohead/Amnesiac"
    check("a semente é estável", vinyl.record_seed(a) == vinyl.record_seed(a))
    check("e é de cada disco", vinyl.record_seed(a) != vinyl.record_seed(b))
    check("barra sobrando não muda a semente",
          vinyl.record_seed(a) == vinyl.record_seed(a + "/"))
    s0, d0 = vinyl.wear_counts(0)
    s5, d5 = vinyl.wear_counts(5)
    s99, d99 = vinyl.wear_counts(999)
    check("disco novo já tem alguma poeira", s0 >= 1 and d0 >= 10)
    check("tocar marca o disco", s5 > s0 and d5 > d0)
    check("mas o desgaste satura", s99 <= 14 and d99 <= 120)
    w_a = vinyl.wear_marks(-0.1, -0.1, 0.76, (0.625, 1.0), 0.0,
                           seed=vinyl.record_seed(a), plays=3)
    w_b = vinyl.wear_marks(-0.1, -0.1, 0.76, (0.625, 1.0), 0.0,
                           seed=vinyl.record_seed(b), plays=3)
    check("dois discos não têm os mesmos arranhões",
          not np.array_equal(w_a[0], w_b[0]))
    w_c = vinyl.wear_marks(-0.1, -0.1, 0.76, (0.625, 1.0), 0.0,
                           seed=vinyl.record_seed(a), plays=3, crackle=1.0)
    check("o estalo acrescenta partículas", len(w_c[0]) > len(w_a[0]))

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
    e1, d1 = vinyl.play_banner(1, 0.0, "disco")
    e9, d9 = vinyl.play_banner(9, time.time() - 40 * 86400, "disco")
    check("a primeira vez é escrita por extenso", e1 == "PRIMEIRA VEZ")
    check("da segunda em diante vem o número", e9.startswith("9"))
    check("e desde quando", d9.startswith("desde"))
    check("os dois lados sempre têm texto", all([e1, d1, e9, d9]))

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

    case("a geometria devolve o formato que o scope.py consome")
    iso = (0.625, 1.0)
    env = alb.envelope_snapshot()
    side = alb.sides[0]
    tracks = [alb.tracks[i] for i in side.get("tracks", [])]
    body = vinyl.disc_body(-0.1, -0.1, 0.76, iso, math.radians(-38.0))
    check("disc_body devolve tiras", len(body) > 0)
    check("cada vértice tem 7 floats", all(v.shape[1] == 7 for v in body))
    check("edge fixado em 0 (área cheia, não traço)",
          all(np.allclose(v[:, 6], 0.0) for v in body))
    check("sem NaN no corpo do disco", all(np.isfinite(v).all() for v in body))
    rings = list(vinyl.groove_rings(-0.1, -0.1, 0.76, iso, side, env, tracks,
                                    math.radians(-38.0), played_ring=10))
    check("groove_rings devolve anéis", len(rings) > 0)
    check("e são pontos finitos", all(np.isfinite(p).all() for p, _c, _w in rings))
    segs, cols, stylus = vinyl.tonearm(-0.1, -0.1, 0.76, iso, 0.7, lift=0.0)
    check("tonearm devolve pares de pontos", len(segs) % 2 == 0 and len(segs) > 0)
    check("uma cor por segmento", len(cols) == len(segs) // 2)
    check("a agulha cai dentro do quadro", abs(stylus[0]) <= 1.5 and abs(stylus[1]) <= 1.5)
    # O braço parado tem que ficar FORA do disco, senão a agulha desenha
    # sulco durante a pausa da virada.
    s2, _c2, st_rest = vinyl.tonearm(-0.1, -0.1, 0.76, iso, vinyl.ARM_REST_RADIUS, lift=1.0)
    dx = (st_rest[0] - (-0.1)) / iso[0]
    dy = (st_rest[1] - (-0.1)) / iso[1]
    check("parado, a agulha fica fora do disco", math.hypot(dx, dy) > 0.76)
    # ── o braço é LUZ, e a lei do §5.5 se confere aqui ────────────────────
    # O que havia era um toca-discos desenhado: tubo em nove cópias,
    # contrapeso em barril, cabeçote, gimbal e um berço em U — e o CLAUDE.md
    # proíbe isso pelo nome. Três perguntas que pegam a volta desse desenho:
    check("nada de berço: arm_rest não existe mais",
          not hasattr(vinyl, "arm_rest"))
    # 1. Nenhum segmento atrás do pivô. O contrapeso morava lá, e é ele que
    #    faz o braço ler como peça de máquina em vez de facho.
    pv, (spx, spy) = vinyl.stylus_xy(-0.1, -0.1, 0.76, iso, 0.7, 0.0)
    ux, uy = spx - pv[0], spy - pv[1]
    atras = [p for p in segs
             if (p[0] - pv[0]) * ux + (p[1] - pv[1]) * uy < -1e-4]
    check("nada desenhado atrás do pivô (o contrapeso saiu)", not atras)
    # 2. A luz mora na PONTA: a metade de fora tem que ser mais clara que a
    #    de dentro, senão voltou a ser haste de brilho uniforme.
    meio = [(sum(c[:3]),
             ((segs[2 * i][0] + segs[2 * i + 1][0]) / 2 - pv[0]) * ux
             + ((segs[2 * i][1] + segs[2 * i + 1][1]) / 2 - pv[1]) * uy)
            for i, c in enumerate(cols)]
    dentro = [b for b, d in meio if d < 0.5 * (ux * ux + uy * uy)]
    fora = [b for b, d in meio if d >= 0.5 * (ux * ux + uy * uy)]
    check("a luz do braço mora na ponta",
          bool(dentro) and bool(fora)
          and sum(fora) / len(fora) > 3.0 * (sum(dentro) / len(dentro)))
    # 3. Levantado, o facho apaga — é assim que este desenho diz "saiu do
    #    sulco", já que não há terceira dimensão para levantar nada.
    check("levantado, o braço apaga",
          float(np.sum(s2)) >= 0.0 and float(np.sum(_c2)) < float(np.sum(cols)))
    # 4. Nenhum segmento de comprimento zero: o build_segs monta o
    #    quadrilátero a partir da normal do segmento, e comprimento zero vira
    #    quatro vértices no mesmo ponto — código que desenha nada.
    zerados = sum(1 for i in range(len(segs) // 2)
                  if math.hypot(segs[2 * i][0] - segs[2 * i + 1][0],
                                segs[2 * i][1] - segs[2 * i + 1][1]) < 1e-6)
    check("nenhum segmento de comprimento zero", zerados == 0)
    # O CUE é 1,7s inteiros de cerimônia; a 3° de arco ele era um tremor.
    ang_rest = vinyl.arm_angle_for_radius(vinyl.ARM_REST_RADIUS)
    ang_lead = vinyl.arm_angle_for_radius(vinyl.R_LEADIN)
    check("o cue percorre um arco que dá para ver",
          math.degrees(abs(ang_rest - ang_lead)) > 6.0)

    # ── de quem é o disco quando ele está solto na raiz ───────────────────
    case("um disco solto na raiz não é da banda 'Songs'")
    import shutil as _shutil
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

    case("o deck DIZ o que está acontecendo")
    # POR QUE ISTO EXISTE
    # -------------------
    # As duas camadas de texto do deck eram criadas no `main()` e desenhadas
    # em todo quadro, e ninguém nunca chamava `set_text` nelas — só a das
    # letras era alimentada. O deck nunca disse nada: nem "LADO A acabou,
    # vire o disco", que é a tese inteira deste sistema, nem "PRIMEIRA VEZ"
    # no instante em que a agulha desce, nem que faixa está tocando. As peças
    # todas já existiam (play_banner, banner(), caption_is_state(), e uma cor
    # ALARM guardada na paleta para o fim do lado); faltava o último fio.
    #
    # A decisão do texto mora no `RitualScene.legendas`, fora do laço de
    # desenho, exatamente para poder ser conferida sem GL: o OpenGL entra
    # aqui como um módulo de mentira.
    from unittest.mock import MagicMock as _MM
    for _n in ("OpenGL", "OpenGL.GL"):
        sys.modules.setdefault(_n, _MM())
    try:
        import importlib.machinery as _im
        import importlib.util as _iu
        _aqui = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _spec = _iu.spec_from_loader("ritualmod", _im.SourceFileLoader(
            "ritualmod", os.path.join(_aqui, "ritual.py")))
        R = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(R)
    except Exception as e:                               # noqa: BLE001
        print(f"    \033[2m—\033[0m sem o ritual.py aqui: {e}")
        R = None
    if R is not None:
        cena = R.RitualScene.__new__(R.RitualScene)
        cena.deck = vinyl.Deck()
        cena._banner = None
        cena._banner_until = 0
        cena._side = 1
        cena._ti_cache = [None, 0]

        class _Alb:
            sides = [{"label": "SIDE A"}, {"label": "SIDE B"}]
            tracks = [{"title": "Come Together", "path": "/x/1.flac"}]

        cena.album = _Alb()

        cena.deck.phase = vinyl.BREAK
        esq, dire = cena.legendas({})
        check("no fim do lado ele manda virar o disco",
              esq == "LADO A acabou — vire o disco para o LADO B")
        check("e o recado do fim do lado tem a cor que a paleta guardou",
              cena.legenda_cor() == vinyl.ALARM)
        check("um recado de ESTADO fica na tela",
              cena.caption_is_state() is True)

        cena.deck.phase = vinyl.STOP
        check("no fim do disco ele diz que acabou",
              cena.legendas({})[0] == "o disco acabou")

        cena.deck.phase = vinyl.PLAY
        cena._banner = ("PRIMEIRA VEZ", "The Beatles — Abbey Road")
        cena._banner_until = time.monotonic() + 5
        check("a agulha descendo anuncia a vez",
              cena.legendas({}) == ("PRIMEIRA VEZ", "The Beatles — Abbey Road"))

        cena._banner = None
        _snap = {"source": "mpv", "path": "/x/1.flac", "track_index": 0}
        check("tocando, o canto diz a faixa",
              cena.legendas(_snap) == (None, "Come Together"))
        # O título sai do ÁLBUM e não do tocador: numa playlist do Qobuz o
        # manifesto diz "quem — o quê" e o mpv diz só "o quê", que numa lista
        # de artistas diferentes não diz nada.
        # A agulha ENCOSTADA não é a mesma pergunta que "a fase é PLAY":
        # pausar levanta a alavanca de cue e a fase continua sendo PLAY. O
        # `stylus_down` respondia só pela fase e ninguém o usava — o ritual
        # fazia a conta certa à mão. Duas respostas para a mesma pergunta.
        d = vinyl.Deck()
        d.phase = vinyl.PLAY
        d.cue_ramp = 0.0
        check("com a agulha no sulco, stylus_down é verdade", d.stylus_down())
        d.cue_ramp = 1.0
        check("pausado (cue no alto) ela NÃO está no sulco",
              not d.stylus_down())
        d.phase = vinyl.BREAK
        check("na virada de lado também não", not d.stylus_down())

        check("e o nome vem do disco, não do tocador",
              cena.faixa_agora({"source": "mpv", "path": "/x/1.flac",
                                "track_index": 0, "title": "outro nome"})
              == "Come Together")

    print(f"\n  \033[1;32m{PASS} passaram\033[0m" + (f", \033[1;31m{FAIL} falharam\033[0m" if FAIL else "") + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
