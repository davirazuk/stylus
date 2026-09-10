#!/usr/bin/env python3
"""Reparte a MESMA grade de discos pelas duas regras e compara lado a lado.

Não compara marcador nem trecho de código: compara o CORTE. As peças podem
estar todas presentes e o resultado sair diferente, que foi exatamente o que
aconteceu com o celular quando o teto físico entrou só de um lado.

O lado de lá é o `Album._build_sides` de verdade, importado do vinyl.py do
desktop — não uma cópia dele. Uma cópia derivaria, que é a doença que esta
conferência existe para pegar.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ONDE PROCURAR O vinyl.py.
#
# Só havia um palpite: ".../vita/player/tools/../../.." — o vitastylus DENTRO
# do repo do STYLUS. Quando ele virou repo separado (que é como está na
# máquina do dono, em ~/vitastylus), esse palpite passou a errar, e a
# conferência PULOU calada. Uma conferência que pula é uma que não existe: os
# lados ficaram sem comparação com o desktop justamente enquanto o dono
# relatava "detecting disks and sides in a weird way".
#
# Agora são vários caminhos, do mais explícito ao mais provável. O
# STYLUS_SOURCE é o mesmo que o sync.sh da máquina usa.
LIB = "airootfs/usr/share/stylus/lib"
CANDIDATOS = []
if os.environ.get("STYLUS_SOURCE"):
    # STYLUS_SOURCE aponta para o airootfs; sobe um para a raiz do clone
    CANDIDATOS.append(os.path.join(os.environ["STYLUS_SOURCE"],
                                   "usr/share/stylus/lib"))
CANDIDATOS += [
    os.path.abspath(os.path.join(HERE, "..", "..", "..", LIB)),
    os.path.expanduser(os.path.join("~/stylus", LIB)),
    os.path.abspath(os.path.join(HERE, "..", "..", "stylus", LIB)),
    "/usr/share/stylus/lib",
]

DESKTOP = None
for c in CANDIDATOS:
    if os.path.isfile(os.path.join(c, "vinyl.py")):
        DESKTOP = c
        break

if DESKTOP is None:
    print("PULA: o vinyl.py do desktop não está aqui (repo do vitastylus sozinho)")
    sys.exit(77)

sys.path.insert(0, DESKTOP)
try:
    import vinyl
except Exception as e:                                    # noqa: BLE001
    print("PULA: não consegui importar o vinyl.py (%s)" % e)
    sys.exit(77)

dump = sys.argv[1] if len(sys.argv) > 1 else "/tmp/vitastylus_sides_dump"
out = subprocess.run([dump], capture_output=True, text=True, check=True).stdout

def desktop_cut(total, n):
    d = total // n
    durs = [d] * n
    durs[-1] += total - d * n
    a = vinyl.Album.__new__(vinyl.Album)
    a.tracks = []
    acc = 0.0
    for x in durs:
        a.tracks.append({"start": acc, "duration": float(x)})
        acc += x
    a.total = float(total)
    a.continuo = False
    a._build_sides()
    return len(a.sides), a.discos, [len(s["tracks"]) for s in a.sides]

bad = 0
rows = 0
for line in out.strip().splitlines():
    head, mid, tail = line.split("|")
    total, n = (int(v) for v in head.split())
    c_sides, c_discos = (int(v) for v in mid.split())
    c_counts = [int(v) for v in tail.split()]
    rows += 1
    p_sides, p_discos, p_counts = desktop_cut(total, n)
    if (c_sides, c_discos, c_counts) != (p_sides, p_discos, p_counts):
        bad += 1
        if bad <= 8:
            print("  %d min em %d faixas:" % (total // 60, n))
            print("     Vita     : %d lados, %d discos, %s" % (c_sides, c_discos, c_counts))
            print("     desktop  : %d lados, %d discos, %s" % (p_sides, p_discos, p_counts))

print("%d formas de disco comparadas, %d divergem" % (rows, bad))
sys.exit(1 if bad else 0)
