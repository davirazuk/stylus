#!/usr/bin/env python3
"""polybar: onde você está no DISCO, não na faixa.

O que a barra já dizia era o nome da música. O que um disco te diz, e um
tocador digital não, é OUTRA coisa: em que lado você está e quanto falta
para ter que levantar e virar. Essa informação existe — as durações estão
nos arquivos — e é ela que faz um álbum ser um álbum em vez de uma fila de
músicas.

    LADO A · 3/5 · vira em 12 min

Clique esquerdo abre o deck com o disco que está tocando.
Clique direito abre a estante.

Só estrutura, sem varredura de intensidade (Album(envelope=False)): esta é a
barra do desktop, não pode sair decodificando álbuns inteiros.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/usr/share/stylus/deck")
try:
    import vinyl
except Exception:
    sys.exit(0)

# O lado do disco é a única coisa VIVA nesta barra, e por isso é âmbar — a
# mesma cor com que a AGORA escreve "LADO A". Era azul (#5bcefa), que na
# barra era também a cor da rede, do bluetooth, da bateria, do perfil de
# energia e das notificações: tudo da mesma cor viva não destaca nada, e ao
# lado da tela cheia (preta com âmbar) a barra parecia de outro sistema.
ACCENT = "#f0a030"
DIM = "#768094"
POLL = 5.0

_cache = {}
_announced = None


# A fonte é o vinyl.Session, não o playerctl direto. Motivo concreto: o
# lançador `vinyl` toca com mpv, e o mpv desta máquina NÃO tem o plugin
# mpv-mpris — ele não aparece no `playerctl -l`. Quem põe um disco pela
# estante ficaria com a barra em branco, ou pior, mostrando o disco do
# tocador antigo enquanto sai o som do novo. O Session já resolve isso:
# prefere o socket IPC do mpv e cai no MPRIS quando não há. De quebra, ele
# pesquisa numa thread própria, então isto para de abrir dois processos
# playerctl a cada cinco segundos.
_session = None


def sessao():
    global _session
    if _session is None:
        _session = vinyl.Session()
    return _session


def playing_path():
    snap = sessao().snapshot()
    path = snap.get("path") or ""
    return path if path and os.path.isfile(path) else None


def position_s():
    pos, _dur = sessao().position()
    return pos


def album_for(path):
    folder = vinyl.resolve_album(path)
    if not folder:
        return None
    alb = _cache.get(folder)
    if alb is None:
        try:
            alb = vinyl.Album(folder, envelope=False)
        except Exception:
            return None
        if not alb.tracks:
            return None
        _cache.clear()          # um álbum de cada vez basta
        _cache[folder] = alb
        global _announced
        if _announced is not None and _announced != folder:
            anunciar(alb)
            registrar(alb, folder)
        _announced = folder
    return alb


def registrar(alb, folder):
    """Anota que este disco foi posto, e quando.

    Uma coleção de verdade tem memória: você lembra vagamente que não ouve
    aquele há muito tempo, e é essa lembrança que faz você tirar ele da
    estante. Um tocador digital não lembra de nada, e por isso sempre oferece
    as mesmas dez coisas. Este arquivo é essa memória — o `stylus record`
    lê daqui para sortear puxando para os discos esquecidos, e a cerimônia do
    modo ritual lê para saber quantas marcas o disco carrega.

    Uma linha por vez que um ÁLBUM começa, não por faixa. Escrever pelo
    vinyl.log_play e não direto no arquivo é o que faz a barra e a cerimônia
    não contarem a mesma colocação duas vezes: quem escrever primeiro ganha,
    o outro vê a linha recente e não repete.
    """
    try:
        vinyl.log_play(folder, alb.artist, alb.name)
    except Exception:
        pass


def anunciar(alb):
    """O momento de pôr o disco: quando o ÁLBUM muda, o desktop reconhece.

    Trocar de faixa não avisa nada — isso seria ruído, e a barra já mostra.
    Trocar de DISCO avisa uma vez, com a capa e como o disco está dividido
    em lados. É o equivalente digital de olhar a capa enquanto a agulha
    desce, que é metade do motivo de um disco não ser chato.
    """
    lados = []
    for sd in alb.sides:
        mins = int((sd["end"] - sd["start"]) // 60)
        lados.append(f"{sd['label'].replace('SIDE', 'Lado')}: "
                     f"{len(sd.get('tracks', []))} faixas, {mins} min")
    corpo = "\n".join(lados) or f"{len(alb.tracks)} faixas"
    args = ["notify-send", "--app-name=STYLUS", "--urgency=low",
            "--hint=string:x-dunst-stack-tag:stylus-album",
            f"{alb.artist} — {alb.name}", corpo]
    if alb.cover and os.path.isfile(alb.cover):
        args.insert(1, f"--icon={alb.cover}")
    try:
        subprocess.run(args, timeout=5)
    except Exception:
        pass


def humano(seg):
    """Curto de propósito: a barra tem largura fixa e este módulo entrou numa
    que já estava cheia — com o texto por extenso, a data e o botão de desligar
    saíam para fora da tela."""
    m = int(seg // 60)
    if m >= 60:
        return f"{m//60}h{m%60:02d}"
    return f"{m}min" if m else "<1min"


def line():
    path = playing_path()
    if not path:
        return ""
    alb = album_for(path)
    if alb is None or not alb.total:
        return ""
    # A mesma conta que o modo ritual faz, e agora literalmente a mesma
    # função: casa o caminho contra as faixas, porque sob MPRIS o tocador não
    # numera nada e o número que sobra no Session é de outra sessão.
    idx = vinyl.track_index_for(alb, sessao().snapshot())
    if not (0 <= idx < len(alb.tracks)):
        return ""
    t_abs = alb.album_time(idx, position_s())
    side_i, side = alb.side_for(t_abs)
    if side is None:
        return ""
    n_side = len(side.get("tracks", [])) or len(alb.tracks)
    pos_in_side = side["tracks"].index(idx) + 1 if idx in side.get("tracks", []) else 1
    restam = max(0.0, side["end"] - t_abs)
    ultimo = side_i >= len(alb.sides) - 1
    # "vira em" é a informação que só um disco dá. No último lado não há o que
    # virar, então vira "acaba em" — dizer "vira" ali seria mentira bonita.
    cauda = f"fim {humano(restam)}" if ultimo else f"vira {humano(restam)}"
    return (f"%{{F{ACCENT}}}󰀥%{{F-}} {side['label'].replace('SIDE', 'LADO')} "
            f"%{{F{DIM}}}·%{{F-}} {pos_in_side}/{n_side} "
            f"%{{F{DIM}}}·%{{F-}} {cauda}")


def main():
    last = None
    while True:
        try:
            cur = line()
        except Exception:
            cur = ""
        if cur != last:
            print(cur, flush=True)
            last = cur
        time.sleep(POLL)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        # O Session pesquisa numa thread e leva meio segundo para ter a
        # primeira resposta. No laço isso não aparece; no modo "once" sim, e
        # sem esta espera ele imprime vazio e parece quebrado.
        sessao()
        for _ in range(20):
            if playing_path():
                break
            time.sleep(0.15)
        print(line())
    else:
        main()
