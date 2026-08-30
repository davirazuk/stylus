#!/usr/bin/env python3
"""stylus record — põe um DISCO, em vez de escolher uma música.

O problema que isto ataca: a música digital é chata porque a decisão que ela
te oferece é "qual faixa", e a resposta honesta quase sempre é "sei lá,
embaralha". Um disco não oferece essa decisão. Você escolhe UM objeto, e
depois o objeto manda por quarenta minutos — e é justamente não ter que
decidir de novo a cada três minutos que faz ouvir um álbum ser diferente de
ouvir uma playlist.

    stylus record                     sorteia um disco e mostra os lados
    stylus record --artist Radiohead  sorteia dentro de um artista
    stylus record "Duster/Stratosphere"  mostra esse
    stylus record --play              e já põe para tocar, na ordem
    stylus record --ritual            tocando, com o disco na tela
"""
import argparse
import os
import random
import subprocess
import time
import sys

try:
    import vinyl
except ImportError:
    sys.path.insert(0, os.path.expanduser("/usr/share/stylus/lib"))
    try:
        import vinyl
    except Exception as e:
        sys.exit(f"preciso do vinyl.py: {e}")

# vinyl.LIBRARY_ROOT nunca existiu — o vinyl expõe library_root(), uma
# FUNÇÃO, porque a estante pode mudar com o programa aberto. Escrito assim,
# `stylus record` estourava com AttributeError na primeira linha, em toda
# máquina: um dos comandos do README, morto desde sempre. Erro de execução,
# não de sintaxe, e por isso a conferência de python passava por cima dele.
ROOT = vinyl.library_root()

c_b = "\033[1m"; c_dim = "\033[2m"; c_acc = "\033[38;5;117m"
c_pink = "\033[38;5;218m"; c_off = "\033[0m"

# A estante, o registro de escutas e o sorteio com peso moram no vinyl.py.
# Estavam aqui, e passaram para lá quando a CERIMÔNIA passou a precisar deles
# também: o fim de um disco é exatamente o momento em que "e agora qual?"
# aparece, e o modo ritual responde essa pergunta com o mesmo sorteio que
# este comando — o que não faria sentido nenhum se fossem dois sorteios
# diferentes com duas ideias diferentes de o que é um disco.
candidatos = lambda artista=None: vinyl.shelf(artist=artista)
ultima_escuta = vinyl.last_played
sorteia = vinyl.draw_record


def mostra(alb):
    print()
    print(f"  {c_dim}põe este:{c_off}")
    print(f"  {c_b}{alb.artist}{c_off}")
    print(f"  {c_acc}{alb.name}{c_off}" + (f"  {c_dim}{alb.year}{c_off}" if alb.year else ""))
    mins = int((alb.total or 0) // 60)
    quando = ultima_escuta().get(os.path.normpath(alb.folder))
    if quando is None:
        nota = "nunca posto desde que isto começou a anotar"
    else:
        dias = int((time.time() - quando) // 86400)
        nota = ("posto hoje" if dias == 0 else
                "posto ontem" if dias == 1 else
                "último toque há " + vinyl.plural(dias, "dia"))
    print(f"  {c_dim}{vinyl.plural(len(alb.tracks), 'faixa')} · {mins} min · "
          f"{vinyl.plural(len(alb.sides), 'lado')} · {nota}{c_off}\n")
    for sd in alb.sides:
        dur = int((sd["end"] - sd["start"]) // 60)
        print(f"  {c_pink}{sd['label'].replace('SIDE', 'LADO')}{c_off}  {c_dim}{dur} min{c_off}")
        for i in sd.get("tracks", []):
            t = alb.tracks[i]
            d = t.get("duration") or 0
            print(f"     {c_dim}{i+1:2d}{c_off}  {t['title'][:52]:<52} {c_dim}{int(d)//60}:{int(d)%60:02d}{c_off}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--artist")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--ritual", action="store_true")
    args = ap.parse_args()

    if args.alvo:
        folder = args.alvo
        if not os.path.isdir(folder):
            # Procura em TODAS as estantes, não só na de casa: o disco pedido
            # pelo nome pode estar no celular.
            for r in vinyl.library_roots():
                cand = os.path.join(r, args.alvo)
                if os.path.isdir(cand):
                    folder = cand
                    break
            else:
                folder = os.path.join(ROOT, args.alvo)
        folder = os.path.expanduser(folder)
        if not os.path.isdir(folder):
            sys.exit(f"não achei: {args.alvo}")
    else:
        c = candidatos(args.artist)
        if not c:
            sys.exit("nenhum álbum com faixas suficientes por aqui")
        folder = sorteia(c)

    alb = vinyl.Album(folder, envelope=False)
    if not alb.tracks:
        sys.exit(f"sem faixas em {folder}")
    mostra(alb)

    if alb.cover and os.path.isfile(alb.cover):
        corpo = " · ".join(
            f"{sd['label'].replace('SIDE','Lado')} {int((sd['end']-sd['start'])//60)}min"
            for sd in alb.sides)
        try:
            subprocess.run(["notify-send", "--app-name=STYLUS",
                            "--urgency=low", f"--icon={alb.cover}",
                            "--hint=string:x-dunst-stack-tag:stylus-album",
                            f"{alb.artist} — {alb.name}", corpo or ""],
                           stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            # Sem libnotify — por ssh, num contêiner — o `stderr=DEVNULL` não
            # ajuda: quem estoura é o Popen, com FileNotFoundError. O comando
            # imprimia o disco inteiro, bonito, e terminava com um traceback.
            pass

    if args.ritual or args.play:
        # O `stylus-deck`, que é quem põe disco neste sistema — a estante do
        # rofi, o lançador e o `stylus play` todos passam por ele.
        #
        # **Sintoma:** aqui estava `~/.local/bin/vinyl`, um lançador que não
        # existe em máquina nenhuma: não é instalado por este repositório e
        # nunca foi. `stylus record --play` respondia "o lançador `vinyl` não
        # está instalado" e parava — e o atalho `Mod+Shift+O` do i3, que é
        # justamente "sorteia um disco e põe para tocar", roda esse comando
        # sem terminal: apertar a tecla não fazia absolutamente nada, sem uma
        # palavra em lugar nenhum.
        import shutil as _shutil
        deck = _shutil.which("stylus-deck") or "stylus-deck"
        if deck == "stylus-deck":
            for cand in ("/usr/local/bin/stylus-deck",
                         "/usr/share/stylus/stylus-deck"):
                if os.path.isfile(cand):
                    deck = cand
                    break
        cmd = [deck] + ([] if args.ritual else ["--no-scope"]) + [folder]
        print(f"  {c_dim}tocando o lado inteiro, na ordem…{c_off}\n")
        try:
            os.execvp(cmd[0], cmd)
        except OSError as e:
            sys.exit(f"não consegui abrir o stylus-deck: {e}")
    else:
        # O disco pode ter vindo de OUTRA estante que não a de casa — a do
        # celular, montada pelo stylus webdav. Um relpath contra a raiz errada
        # devolve um punhado de "../.." que não serve para copiar e colar.
        rel = folder
        for r in vinyl.library_roots():
            if folder.startswith(r.rstrip("/") + "/"):
                rel = os.path.relpath(folder, r)
                break
        print(f"  {c_dim}para tocar:  stylus record \"{rel}\" --play{c_off}")
        print(f"  {c_dim}com o disco na tela:  --ritual{c_off}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
