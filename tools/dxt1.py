"""Codificador DXT1 — a capa que o app Música da Vita entende.

POR QUE ISTO EXISTE
  O ícone de conteúdo do Vita não é JPEG solto nem caminho de arquivo: é uma
  textura **DDS DXT1 de 128x128**, guardada como BLOB na `tbl_Icon`. Isso não
  está documentado em lugar nenhum — foi lido do próprio cartão, das 38 linhas
  que a Sony escreveu para as fotos da câmera: `codec_type=25`, `data_type=1`,
  128x128, `size=8320` (128 de cabeçalho + 8192 de dados) e o BLOB começando
  com o mágico "DDS " e fourCC "DXT1".

  8192 bytes para 128x128 é exatamente meio byte por pixel — a conta do DXT1
  (blocos de 4x4 em 8 bytes). O Pillow LÊ DXT1 mas só ESCREVE DDS sem
  compressão (49 KB em vez de 8 KB), e não há nvcompress/ImageMagick nesta
  máquina; daí o codificador aqui.

O MÉTODO
  Caixa delimitadora por bloco: os dois extremos por canal viram os
  endpoints. É o "fast DXT1" clássico — não é o melhor compressor do mundo,
  mas numa miniatura de 128x128 a diferença não se vê, e é exato o suficiente
  para a tela do Vita.
"""

import numpy as np


def _to565(c):
    """RGB (N,3) uint8 -> uint16 no formato 565."""
    r = (c[:, 0].astype(np.uint16) >> 3) & 0x1F
    g = (c[:, 1].astype(np.uint16) >> 2) & 0x3F
    b = (c[:, 2].astype(np.uint16) >> 3) & 0x1F
    return (r << 11) | (g << 5) | b


def _from565(v):
    """uint16 565 -> RGB (N,3) float, já expandido como o hardware expande."""
    r = ((v >> 11) & 0x1F).astype(np.float32)
    g = ((v >> 5) & 0x3F).astype(np.float32)
    b = (v & 0x1F).astype(np.float32)
    return np.stack([r * 255.0 / 31.0, g * 255.0 / 63.0, b * 255.0 / 31.0], axis=1)


def encode_dxt1(img):
    """PIL.Image RGB de lado múltiplo de 4 -> bytes DXT1 (sem cabeçalho)."""
    a = np.asarray(img.convert("RGB"), dtype=np.uint8)
    h, w, _ = a.shape
    bh, bw = h // 4, w // 4

    # (bh,4,bw,4,3) -> (nblocos,16,3): cada linha é um bloco de 4x4
    blocos = a.reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    n = blocos.shape[0]

    cmax = blocos.max(axis=1)
    cmin = blocos.min(axis=1)
    c0 = _to565(cmax)
    c1 = _to565(cmin)

    # DXT1 só usa as 4 cores quando c0 > c1; com c0 <= c1 o modo vira
    # 3 cores + transparente, e a capa ganharia buracos. Onde os dois caem no
    # mesmo 565 o bloco é liso: manter c0 == c1 e todos os índices em 0 dá a
    # cor exata, então esse caso não precisa de conserto.
    troca = c0 < c1
    c0[troca], c1[troca] = c1[troca], c0[troca]

    p0 = _from565(c0)
    p1 = _from565(c1)
    paleta = np.stack([p0, p1, (2.0 * p0 + p1) / 3.0, (p0 + 2.0 * p1) / 3.0], axis=1)

    px = blocos.astype(np.float32)                      # (n,16,3)
    d = ((px[:, :, None, :] - paleta[:, None, :, :]) ** 2).sum(axis=3)   # (n,16,4)
    idx = d.argmin(axis=2).astype(np.uint32)            # (n,16)

    # Blocos lisos (c0 == c1): o índice 0 já dá a cor certa e evita depender
    # de uma paleta degenerada.
    lisos = (c0 == c1)
    idx[lisos] = 0

    bits = np.zeros(n, dtype=np.uint32)
    for i in range(16):
        bits |= idx[:, i] << np.uint32(2 * i)

    saida = np.empty((n, 8), dtype=np.uint8)
    saida[:, 0] = (c0 & 0xFF).astype(np.uint8)
    saida[:, 1] = (c0 >> 8).astype(np.uint8)
    saida[:, 2] = (c1 & 0xFF).astype(np.uint8)
    saida[:, 3] = (c1 >> 8).astype(np.uint8)
    saida[:, 4] = (bits & 0xFF).astype(np.uint8)
    saida[:, 5] = ((bits >> 8) & 0xFF).astype(np.uint8)
    saida[:, 6] = ((bits >> 16) & 0xFF).astype(np.uint8)
    saida[:, 7] = ((bits >> 24) & 0xFF).astype(np.uint8)
    return saida.tobytes()


def cabecalho_dds(lado=128):
    """O cabeçalho de 128 bytes, idêntico ao que a Sony grava no cartão."""
    import struct
    h = bytearray(128)
    h[0:4] = b"DDS "
    struct.pack_into("<I", h, 4, 124)            # dwSize
    struct.pack_into("<I", h, 8, 0x00021007)     # CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT
    struct.pack_into("<I", h, 12, lado)          # altura
    struct.pack_into("<I", h, 16, lado)          # largura
    struct.pack_into("<I", h, 20, 0)             # pitch/linear size
    struct.pack_into("<I", h, 24, 0)             # profundidade
    struct.pack_into("<I", h, 28, 1)             # mipmaps
    struct.pack_into("<I", h, 76, 32)            # ddspf.dwSize
    struct.pack_into("<I", h, 80, 0x4)           # ddspf.dwFlags = FOURCC
    h[84:88] = b"DXT1"
    # dwCaps EXATAMENTE como a Sony grava: COMPLEX|TEXTURE|MIPMAP.
    # Conferido byte a byte contra o ícone real do cartão — não
    # inventar aqui: o cabeçalho é o contrato com o decodificador deles.
    struct.pack_into("<I", h, 108, 0x00401008)
    return bytes(h)


def capa_para_icone(img, lado=128):
    """Imagem -> BLOB do jeito que a tbl_Icon quer (8320 bytes em 128x128)."""
    img = img.convert("RGB").resize((lado, lado), 1)   # 1 = LANCZOS
    return cabecalho_dds(lado) + encode_dxt1(img)
