#!/usr/bin/env python3
"""As telas do lançador em PNG, sem X e sem placa de vídeo.

POR QUE ISTO EXISTE
-------------------
O `test_ui.py` mede: ele sabe dizer que dois textos se cruzam e que um
retângulo saiu da tela. O que ele não sabe dizer é se a tela ficou BONITA —
se o âmbar está no lugar certo, se o disco tem peso, se a página respira ou
se ficou tudo encostado num canto. E "melhorar o visual" foi, historicamente,
a porta por onde entrou toda regressão de desenho deste projeto (§5.5): quem
não VÊ o resultado copia a primeira foto de toca-discos que achar.

O deck já tinha a resposta barata para isso — o `deck/tools/vinyl_preview.py`,
que mostra a composição sem GL. Esta é a mesma ideia para o lançador, e nasce
do mesmo motivo: construir a ISO leva meia hora, e olhar um PNG leva um
segundo.

Uso:
    telas.py                      todas as seções, 1920x1080, em /tmp/stylus-telas
    telas.py --tela AGORA         só uma
    telas.py --tam 1024x600       na tela do painel de carro
    telas.py --vazio              com o prato vazio (o padrão é com disco)
    telas.py --saida PASTA

Sem coleção de verdade, monta uma de mentira igual à do test_ui: quatro
discos com capa e uma playlist. Com `--lib PASTA`, usa a sua.
"""
import argparse
import atexit
import os
import shutil
import sys
import tempfile


def coleção_de_mentira(base):
    """Os mesmos quatro discos do test_ui, e pelo mesmo motivo.

    Dois de nome curto e dois de nome COMPRIDO: é o comprimento que revela
    folga fixa, e uma tela desenhada só com "Abbey Road" dentro é uma tela
    que ninguém viu.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    cores = [(80, 120, 180), (150, 60, 60), (40, 90, 70), (120, 100, 40)]
    for i, (artista, album) in enumerate((
            ("The Beatles", "Abbey Road"),
            ("Radiohead", "OK Computer"),
            ("Godspeed You! Black Emperor",
             "Lift Your Skinny Fists Like Antennas to Heaven"),
            ("Sigur Rós", "Ágætis byrjun (edição de aniversário)"))):
        d = os.path.join(base, artista, album)
        os.makedirs(d, exist_ok=True)
        Image.new("RGB", (600, 600), cores[i]).save(os.path.join(d, "cover.jpg"))
        # WAV de verdade, e não um arquivo de zeros com extensão .flac: sem
        # DURAÇÃO o disco não tem lados (`total <= 0` devolve `sides = []`),
        # e uma AGORA sem lado é meia tela — exatamente a metade que estas
        # imagens existem para mostrar. O módulo `wave` é da biblioteca
        # padrão; é o mesmo truque do check.sh.
        import wave
        for n in range(1, 10):
            with wave.open(os.path.join(d, f"{n:02d} faixa.wav"), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(8000)
                # 3 a 7 minutos, variando: um disco de faixas todas iguais
                # não revela nada sobre como os lados são repartidos.
                w.writeframes(b"\0" * (8000 * 4 * (180 + n * 32)))
    with open(os.path.join(base, "Shoegaze & Dreampop para dormir.m3u"),
              "w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for n in range(1, 4):
            fh.write(f"Radiohead/OK Computer/{n:02d} faixa.wav\n")
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=None, help="a coleção de verdade")
    ap.add_argument("--tela", default=None, help="só esta seção (AGORA, ESTANTE…)")
    ap.add_argument("--tam", default="1920x1080")
    ap.add_argument("--saida", default="/tmp/stylus-telas")
    ap.add_argument("--vazio", action="store_true",
                    help="com o prato vazio (o padrão é com disco tocando)")
    ap.add_argument("--cheia", action="store_true",
                    help="a AGORA em tela cheia, sem trilho")
    args = ap.parse_args()

    larg, alt = (int(v) for v in args.tam.lower().split("x"))

    # Antes do pygame: é assim que se pede uma janela que não existe.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ["STYLUS_UI_WINDOWED"] = "1"

    tmp = tempfile.mkdtemp(prefix="stylus-telas-")
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
    raiz = os.path.dirname(os.path.dirname(aqui))
    sys.path.insert(0, os.path.join(raiz, "lib"))
    sys.path.insert(0, os.path.join(raiz, "ui"))

    import time
    import pygame
    import app as A
    import vinyl

    app = A.App()
    for _ in range(80):
        if app.shelf.ready and not app.shelf.scanning:
            break
        time.sleep(0.05)

    # ── o prato ────────────────────────────────────────────────────────────
    # Com disco por padrão, e não vazio: metade da AGORA nem é desenhada com
    # nada tocando (o `draw` sai cedo pelo `_nothing`), e foi assim que três
    # vazamentos passaram despercebidos por semanas.
    if not args.vazio and app.shelf.items:
        alvo = next((i for i in app.shelf.items
                     if not i.get("playlist") and i.get("tracks")), None)
        if alvo:
            al = vinyl.Album(alvo["folder"])
            side = al.sides[min(1, len(al.sides) - 1)]
            meio = side["start"] + (side["end"] - side["start"]) * 0.42
            # A faixa tem que ser a que TOCA neste instante, e não a terceira
            # do disco: com as duas em desacordo o lado desenha a ordem sem
            # nenhuma faixa acesa, que é uma tela que não existe de verdade.
            faixa = next((t for t in al.tracks
                          if t["start"] <= meio < t["start"] + t["duration"]),
                         al.tracks[0] if al.tracks else None)
            app.playing.album = al
            app.playing.where = lambda: (
                {"status": "Playing", "path": (faixa or {}).get("path", "")},
                al, faixa, side, meio,
                meio / al.total if getattr(al, "total", 0) else 0.3)

    # As miniaturas são decodificadas numa thread; desenhar antes disso dá
    # uma tela de capas vazias, que não é a tela que ninguém vê. Um quadro
    # "quente" primeiro (é o desenho que PEDE cada capa) e depois a espera.
    app.surf = pygame.Surface((larg, alt))
    app.W, app.H = larg, alt
    for i, tela in enumerate(app.screens):
        app._goto(i)
        try:
            tela.draw(app.surf, pygame.Rect(230, 0, larg - 230, alt))
        except Exception:                                   # noqa: BLE001
            pass
    for _ in range(60):
        if not (app.thumbs.pending or app.thumbs_hi.pending):
            break
        time.sleep(0.05)

    os.makedirs(args.saida, exist_ok=True)
    app.surf = pygame.Surface((larg, alt))
    app.W, app.H = larg, alt
    rail_w = 0 if args.cheia else 230
    corpo = pygame.Rect(rail_w, 0, larg - rail_w, alt)

    escritos = []
    for i, tela in enumerate(app.screens):
        if args.tela and tela.name != args.tela.upper():
            continue
        app._goto(i)
        if args.cheia and tela.name == "AGORA":
            tela.tela_cheia = True
        app.surf.fill(A.T.INK)
        try:
            tela.draw(app.surf, corpo)
        except Exception as e:                              # noqa: BLE001
            print(f"  {tela.name}: quebrou — {type(e).__name__}: {e}")
            continue
        if not args.cheia:
            app._draw_rail(app.surf, rail_w)
        nome = os.path.join(args.saida, f"{i:02d}-{tela.name.lower()}.png")
        pygame.image.save(app.surf, nome)
        escritos.append(nome)
        print(f"  {nome}")

    if not escritos:
        print("  nenhuma tela desenhada (o --tela casou com alguma coisa?)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
