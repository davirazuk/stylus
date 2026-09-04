#ifndef STYLUS_MD5_H
#define STYLUS_MD5_H

#include <stddef.h>

/* MD5 (RFC 1321) compacto e portátil — usado só para a assinatura do last.fm
   (não é criptografia de segurança). */
void md5_hex(const char *data, size_t len, char out[33]);

#endif
