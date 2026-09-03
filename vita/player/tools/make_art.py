#!/usr/bin/env python3
"""Desenha o ícone e o fundo da LiveArea — sem PIL, com zlib e struct.

A lei do desenho (§5.5) vale aqui também: um disco de LUZ no quase-preto, o
âmbar como única cor viva. Nada de plinto, madeira ou foto de toca-discos.
O VPK saía sem arte nenhuma: no menu do Vita ele era um quadrado em branco
entre os jogos, o que é a diferença entre "um app" e "um arquivo".
"""
import math, struct, zlib, os, sys

def png(path, w, h, px):
    raw = b"".join(b"\x00" + bytes(px[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    out = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    open(path, "wb").write(out)

AMBER = (255, 170, 40)
BRIGHT = (255, 197, 107)

def bg(x, y, w, h):
    t = y / max(h - 1, 1)
    return [int(6 + 7 * t), int(8 + 10 * t), int(13 + 15 * t)]

def mix(base, col, a):
    return [int(base[i] + (col[i] - base[i]) * a) for i in range(3)]

def draw(w, h, cx, cy, R, ntracks=11, with_arm=True):
    px = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            c = bg(x, y, w, h)
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy)

            # halo respirando atrás do disco (luz, não sombra)
            if d < R * 1.55:
                a = max(0.0, 1.0 - d / (R * 1.55)) ** 2 * 0.16
                c = mix(c, (32, 48, 74), a)
            # corpo do disco: quase-preto FRIO, não plástico cinza
            if d <= R:
                c = mix(c, (14, 16, 24), 0.95)
                # os sulcos são as faixas: dá para contá-las a três metros
                # os sulcos precisam de FOLGA entre si: encostados eles viram
                # moiré na miniatura de 128 px, que lê como ruído e não como
                # "dá para contar as músicas"
                for i in range(ntracks):
                    rr = R * (0.22 + 0.74 * (i + 1) / (ntracks + 1))
                    if abs(d - rr) < max(0.7, R * 0.010):
                        c = mix(c, AMBER, 0.20)
                # o anel de leitura, aceso
                rread = R * 0.62
                if abs(d - rread) < max(1.0, R * 0.020):
                    c = mix(c, BRIGHT, 0.85)
                # o selo
                if d < R * 0.17:
                    c = mix(c, AMBER, 0.30)
                if d < R * 0.035:
                    c = mix(c, BRIGHT, 0.95)
                # brilho de borda: a luz vem da própria coisa
                if d > R * 0.955:
                    c = mix(c, AMBER, 0.60 * (d - R * 0.955) / (R * 0.045))
            px[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes(max(0, min(255, v)) for v in c)

    if with_arm:
        # o braço é o FACHO: o corpo começa a 38% e quase toda a luz na ponta
        ang = -math.pi / 2 + 0.34
        pxx, pyy = cx + math.cos(ang) * R * 0.62, cy + math.sin(ang) * R * 0.62
        oxx, oyy = cx + math.cos(ang) * R * 1.5, cy + math.sin(ang) * R * 1.5
        steps = 260
        for i in range(steps):
            t = 0.38 + (1.0 - 0.38) * i / steps
            X = oxx + (pxx - oxx) * t
            Y = oyy + (pyy - oyy) * t
            a = (t ** 2.2) * 0.75
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    ix, iy = int(X) + ox, int(Y) + oy
                    if 0 <= ix < w and 0 <= iy < h:
                        k = (iy * w + ix) * 3
                        cur = list(px[k:k + 3])
                        px[k:k + 3] = bytes(mix(cur, AMBER, a * (0.5 if (ox or oy) else 1.0)))
        # a agulha: cruz curta e quente
        for r in range(-4, 5):
            for (ix, iy) in ((int(pxx) + r, int(pyy)), (int(pxx), int(pyy) + r)):
                if 0 <= ix < w and 0 <= iy < h:
                    k = (iy * w + ix) * 3
                    px[k:k + 3] = bytes(BRIGHT)
    return px

out = sys.argv[1] if len(sys.argv) > 1 else "sce_sys"
os.makedirs(os.path.join(out, "livearea", "contents"), exist_ok=True)
png(os.path.join(out, "icon0.png"), 128, 128, draw(128, 128, 64, 66, 51, 6))
png(os.path.join(out, "livearea", "contents", "bg.png"), 840, 500, draw(840, 500, 596, 250, 186, 11))
png(os.path.join(out, "livearea", "contents", "startup.png"), 280, 158, draw(280, 158, 140, 80, 63, 7))
print("arte gerada em", out)
