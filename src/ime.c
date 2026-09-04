#include "ime.h"

#include <string.h>

#ifdef __vita__

#include <psp2/ime_dialog.h>
#include <psp2/sysmodule.h>
#include <vita2d.h>

/* O diálogo fala UTF-16 e o resto do app fala UTF-8. As duas conversões
   abaixo cobrem o plano básico (até U+FFFF) e transformam o que não couber
   em '?' — um nome de usuário do last.fm é ASCII, e uma senha que passe
   disso vale mais avisar do que corromper em silêncio. */
static void para_u16(const char *s, SceWChar16 *out, size_t max)
{
    size_t o = 0;
    while (*s && o + 1 < max) {
        unsigned char c = (unsigned char)*s++;
        unsigned cp;
        if (c < 0x80) cp = c;
        else if ((c & 0xE0) == 0xC0 && (*s & 0xC0) == 0x80) {
            cp = ((c & 0x1Fu) << 6) | (*s++ & 0x3Fu);
        } else if ((c & 0xF0) == 0xE0 && (s[0] & 0xC0) == 0x80 && (s[1] & 0xC0) == 0x80) {
            cp = ((c & 0x0Fu) << 12) | ((s[0] & 0x3Fu) << 6) | (s[1] & 0x3Fu);
            s += 2;
        } else {
            cp = '?';
            while ((*s & 0xC0) == 0x80) s++;   /* pula o resto da sequência */
        }
        out[o++] = (SceWChar16)(cp > 0xFFFF ? '?' : cp);
    }
    out[o] = 0;
}

static void de_u16(const SceWChar16 *in, char *out, size_t cap)
{
    size_t o = 0;
    for (; *in && o + 4 < cap; in++) {
        unsigned cp = *in;
        if (cp < 0x80) out[o++] = (char)cp;
        else if (cp < 0x800) {
            out[o++] = (char)(0xC0 | (cp >> 6));
            out[o++] = (char)(0x80 | (cp & 0x3F));
        } else {
            out[o++] = (char)(0xE0 | (cp >> 12));
            out[o++] = (char)(0x80 | ((cp >> 6) & 0x3F));
            out[o++] = (char)(0x80 | (cp & 0x3F));
        }
    }
    out[o] = '\0';
}

/* 256 caracteres é bem mais do que qualquer campo daqui usa; o teto do
   sistema é 2048 e reservá-lo inteiro seria 8 KB parados à toa. */
#define IME_MAX 256

static bool        g_aberto;
static bool        g_modulo;
static SceWChar16  g_titulo[SCE_IME_DIALOG_MAX_TITLE_LENGTH];
static SceWChar16  g_inicial[IME_MAX];
static SceWChar16  g_buf[IME_MAX];

int ime_abrir(const char *titulo, const char *inicial, size_t max, bool senha)
{
    if (g_aberto) return -1;
    if (!g_modulo) {
        if (sceSysmoduleLoadModule(SCE_SYSMODULE_IME) < 0) return -1;
        g_modulo = true;
    }
    if (max == 0 || max > IME_MAX - 1) max = IME_MAX - 1;

    para_u16(titulo ? titulo : "", g_titulo, SCE_IME_DIALOG_MAX_TITLE_LENGTH);
    para_u16(inicial ? inicial : "", g_inicial, IME_MAX);
    memset(g_buf, 0, sizeof(g_buf));

    SceImeDialogParam p;
    sceImeDialogParamInit(&p);
    p.supportedLanguages = SCE_IME_LANGUAGE_ENGLISH;
    p.languagesForced    = SCE_TRUE;
    p.type               = SCE_IME_TYPE_BASIC_LATIN;
    /* Sem correção automática: isto são credenciais, e um "Sk" virando "SK"
       por capitalização automática seria um erro de login impossível de
       enxergar na tela. */
    p.option             = SCE_IME_OPTION_NO_AUTO_CAPITALIZATION |
                           SCE_IME_OPTION_NO_ASSISTANCE;
    p.dialogMode         = SCE_IME_DIALOG_DIALOG_MODE_WITH_CANCEL;
    p.textBoxMode        = senha ? SCE_IME_DIALOG_TEXTBOX_MODE_PASSWORD
                                 : SCE_IME_DIALOG_TEXTBOX_MODE_WITH_CLEAR;
    p.title              = g_titulo;
    p.maxTextLength      = (SceUInt32)max;
    p.initialText        = g_inicial;
    p.inputTextBuffer    = g_buf;

    if (sceImeDialogInit(&p) < 0) return -1;
    g_aberto = true;
    return 0;
}

bool ime_aberto(void) { return g_aberto; }

int ime_poll(char *out, size_t cap)
{
    if (!g_aberto) return -1;
    if (sceImeDialogGetStatus() != SCE_COMMON_DIALOG_STATUS_FINISHED) return 0;

    SceImeDialogResult r;
    memset(&r, 0, sizeof(r));
    sceImeDialogGetResult(&r);
    sceImeDialogTerm();
    g_aberto = false;

    if (r.button != SCE_IME_DIALOG_BUTTON_ENTER) return -1;
    if (out && cap) de_u16(g_buf, out, cap);
    /* A memória é limpa na saída: uma senha não fica parada num estático
       depois de usada. */
    memset(g_buf, 0, sizeof(g_buf));
    return 1;
}

void ime_desenhar(void)
{
    vita2d_common_dialog_update();
}

#else
/* No PC não há teclado do sistema. Os tocos existem para o teste de host
   linkar a UI inteira; nenhum teste digita. */
int  ime_abrir(const char *t, const char *i, size_t m, bool s)
{ (void)t; (void)i; (void)m; (void)s; return -1; }
bool ime_aberto(void) { return false; }
int  ime_poll(char *out, size_t cap) { (void)out; (void)cap; return -1; }
void ime_desenhar(void) { }
#endif
