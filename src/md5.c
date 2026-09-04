#include "md5.h"

#include <stdint.h>
#include <string.h>

#define LROT(x, c) (((x) << (c)) | ((x) >> (32 - (c))))

typedef struct {
    uint32_t a, b, c, d;
    uint64_t len;      /* bytes processados */
    unsigned char buf[64];
} Md5Ctx;

static const uint32_t K[64] = {
    0xd76aa478,0xe8c7b756,0x242070db,0xc1bdceee,0xf57c0faf,0x4787c62a,
    0xa8304613,0xfd469501,0x698098d8,0x8b44f7af,0xffff5bb1,0x895cd7be,
    0x6b901122,0xfd987193,0xa679438e,0x49b40821,0xf61e2562,0xc040b340,
    0x265e5a51,0xe9b6c7aa,0xd62f105d,0x02441453,0xd8a1e681,0xe7d3fbc8,
    0x21e1cde6,0xc33707d6,0xf4d50d87,0x455a14ed,0xa9e3e905,0xfcefa3f8,
    0x676f02d9,0x8d2a4c8a,0xfffa3942,0x8771f681,0x6d9d6122,0xfde5380c,
    0xa4beea44,0x4bdecfa9,0xf6bb4b60,0xbebfbc70,0x289b7ec6,0xeaa127fa,
    0xd4ef3085,0x04881d05,0xd9d4d039,0xe6db99e5,0x1fa27cf8,0xc4ac5665,
    0xf4292244,0x432aff97,0xab9423a7,0xfc93a039,0x655b59c3,0x8f0ccc92,
    0xffeff47d,0x85845dd1,0x6fa87e4f,0xfe2ce6e0,0xa3014314,0x4e0811a1,
    0xf7537e82,0xbd3af235,0x2ad7d2bb,0xeb86d391};

static const int R[64] = {
     7,12,17,22, 7,12,17,22, 7,12,17,22, 7,12,17,22,
     5, 9,14,20, 5, 9,14,20, 5, 9,14,20, 5, 9,14,20,
     4,11,16,23, 4,11,16,23, 4,11,16,23, 4,11,16,23,
     6,10,15,21, 6,10,15,21, 6,10,15,21, 6,10,15,21};

static uint32_t load32(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void store32(unsigned char *p, uint32_t v)
{
    p[0] = (unsigned char)(v); p[1] = (unsigned char)(v >> 8);
    p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24);
}

static void md5_block(Md5Ctx *s, const unsigned char *blk)
{
    uint32_t M[16], f, g, temp;
    for (int i = 0; i < 16; i++) M[i] = load32(blk + 4 * i);
    uint32_t a = s->a, b = s->b, c = s->c, d = s->d;
    for (int i = 0; i < 64; i++) {
        if (i < 16) { f = (b & c) | (~b & d); g = i; }
        else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
        else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) & 15; }
        else { f = c ^ (b | ~d); g = (7 * i) & 15; }
        temp = d; d = c; c = b;
        b = b + LROT((a + f + K[i] + M[g]), (uint32_t)R[i]);
        a = temp;
    }
    s->a += a; s->b += b; s->c += c; s->d += d;
}

static void md5_init(Md5Ctx *s)
{
    s->a = 0x67452301; s->b = 0xefcdab89;
    s->c = 0x98badcfe; s->d = 0x10325476;
    s->len = 0;
}

static void md5_update(Md5Ctx *s, const void *data, size_t n)
{
    const unsigned char *p = data;
    size_t fill = (size_t)(s->len & 63);
    s->len += n;
    if (fill && fill + n >= 64) {
        memcpy(s->buf + fill, p, 64 - fill);
        md5_block(s, s->buf);
        p += 64 - fill;
        n -= 64 - fill;
        fill = 0;
    }
    while (n >= 64) {
        md5_block(s, p);
        p += 64;
        n -= 64;
    }
    memcpy(s->buf + fill, p, n);
}

static void md5_final(Md5Ctx *s, unsigned char out[16])
{
    unsigned char bits[8];
    uint64_t bitlen = s->len * 8;
    for (int i = 0; i < 8; i++) bits[i] = (unsigned char)(bitlen >> (8 * i));
    /* pad */
    size_t fill = (size_t)(s->len & 63);
    size_t padlen = (fill < 56) ? (56 - fill) : (120 - fill);
    unsigned char pad[64];
    memset(pad, 0, sizeof(pad));
    pad[0] = 0x80;
    md5_update(s, pad, padlen);
    md5_update(s, bits, 8);
    /* dump digests little-endian */
    store32(out, s->a);
    store32(out + 4, s->b);
    store32(out + 8, s->c);
    store32(out + 12, s->d);
}

void md5_hex(const char *data, size_t len, char out[33])
{
    Md5Ctx s;
    unsigned char d[16];
    md5_init(&s);
    md5_update(&s, data, len);
    md5_final(&s, d);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 16; i++) {
        out[2 * i] = hex[d[i] >> 4];
        out[2 * i + 1] = hex[d[i] & 15];
    }
    out[32] = '\0';
}
