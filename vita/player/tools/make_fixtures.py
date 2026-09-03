#!/usr/bin/env python3
"""Gera os arquivos de áudio que o teste do decodificador usa.

Um sinal CONHECIDO — não ruído, não silêncio. O silêncio passa em qualquer
decodificador quebrado (zero é zero), e o ruído não deixa comparar amostra a
amostra depois de um seek. Isto aqui é uma rampa por canal com frequências
diferentes nos dois lados: se os canais forem trocados, ou se o intercalado
sair errado, ou se um seek cair no lugar errado, a comparação acusa.
"""
import math, os, struct, subprocess, sys, wave

RATE = 44100
SECS = 4
N = RATE * SECS

def samples():
    for i in range(N):
        t = i / RATE
        # esquerdo 220 Hz, direito 330 Hz — canais distinguíveis de propósito
        l = int(22000 * math.sin(2 * math.pi * 220 * t))
        r = int(18000 * math.sin(2 * math.pi * 330 * t))
        yield l, r

def write_wav(path, bits=16, floatfmt=False):
    data = bytearray()
    if floatfmt:
        for l, r in samples():
            data += struct.pack('<ff', l / 32768.0, r / 32768.0)
        fmt_tag, bps = 3, 32
    elif bits == 16:
        for l, r in samples():
            data += struct.pack('<hh', l, r)
        fmt_tag, bps = 1, 16
    elif bits == 24:
        for l, r in samples():
            for v in (l, r):
                v24 = v << 8
                data += struct.pack('<i', v24)[0:3]
        fmt_tag, bps = 1, 24
    elif bits == 8:
        for l, r in samples():
            data += bytes([(l >> 8) + 128 & 0xFF, (r >> 8) + 128 & 0xFF])
        fmt_tag, bps = 1, 8
    else:
        raise ValueError(bits)

    block = bps // 8 * 2
    hdr = b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
    hdr += b'fmt ' + struct.pack('<IHHIIHH', 16, fmt_tag, 2, RATE,
                                 RATE * block, block, bps)
    hdr += b'data' + struct.pack('<I', len(data))
    open(path, 'wb').write(hdr + bytes(data))

def run(*a):
    subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
j = lambda n: os.path.join(out, n)

write_wav(j('tone16.wav'), 16)
write_wav(j('tone24.wav'), 24)
write_wav(j('tone8.wav'), 8)
write_wav(j('tonef32.wav'), floatfmt=True)

# uma capa PNG minúscula, para o teste da capa embutida ter o que casar
png = (b'\x89PNG\r\n\x1a\n'
       b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00'
       b'\x90wS\xde'
       b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00'
       b'\x18\xdd\x8d\xb0'
       b'\x00\x00\x00\x00IEND\xaeB`\x82')
open(j('cover.png'), 'wb').write(png)

run('flac', '-8', '-f', '-s', '-o', j('tone.flac'),
    '-T', 'TITLE=Faixa de Teste', '-T', 'ARTIST=Artista Teste',
    '-T', 'ALBUM=Album Teste', '-T', 'TRACKNUMBER=7/12',
    '--picture=3||||' + j('cover.png'), j('tone16.wav'))
# um FLAC de 24 bits: o caminho que DESCE para 16 no Vita
run('flac', '-8', '-f', '-s', '-o', j('tone24.flac'), j('tone24.wav'))
run('oggenc', '-Q', '-q', '6', '-o', j('tone.ogg'),
    '-t', 'Faixa de Teste', '-a', 'Artista Teste', '-l', 'Album Teste',
    '-N', '7', j('tone16.wav'))
run('opusenc', '--quiet', '--bitrate', '128',
    '--title', 'Faixa de Teste', '--artist', 'Artista Teste',
    '--album', 'Album Teste', '--comment', 'TRACKNUMBER=7',
    '--picture', j('cover.png'), j('tone16.wav'), j('tone.opus'))
run('lame', '--quiet', '-b', '192',
    '--tt', 'Faixa de Teste', '--ta', 'Artista Teste',
    '--tl', 'Album Teste', '--tn', '7', '--ti', j('cover.png'),
    j('tone16.wav'), j('tone.mp3'))

print("fixtures em", out)
