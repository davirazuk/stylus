/* Shim do psp2/ctrl.h para o preview no PC. Só o que o ui.c usa.
   Os valores dos botões são os reais do SDK — o preview injeta botões pra
   navegar entre telas, então precisam bater. */
#ifndef PSP2_CTRL_HOST_SHIM_H
#define PSP2_CTRL_HOST_SHIM_H

#include <stdint.h>

#define SCE_CTRL_SELECT   0x000001
#define SCE_CTRL_START    0x000008
#define SCE_CTRL_UP       0x000010
#define SCE_CTRL_RIGHT    0x000020
#define SCE_CTRL_DOWN     0x000040
#define SCE_CTRL_LEFT     0x000080
#define SCE_CTRL_LTRIGGER 0x000100
#define SCE_CTRL_L2       SCE_CTRL_LTRIGGER
#define SCE_CTRL_RTRIGGER 0x000200
#define SCE_CTRL_R2       SCE_CTRL_RTRIGGER
#define SCE_CTRL_L1       0x000400
#define SCE_CTRL_R1       0x000800
#define SCE_CTRL_TRIANGLE 0x001000
#define SCE_CTRL_CIRCLE   0x002000
#define SCE_CTRL_CROSS    0x004000
#define SCE_CTRL_SQUARE   0x008000

#define SCE_CTRL_MODE_DIGITAL 0

typedef struct SceCtrlData {
    uint64_t timeStamp;
    uint32_t buttons;
    uint8_t  lx, ly, rx, ry;
    uint8_t  reserved[16];
} SceCtrlData;

int sceCtrlSetSamplingMode(int mode);
int sceCtrlPeekBufferPositive(int port, SceCtrlData *pad_data, int count);

/* extra só do host: o preview injeta o próximo estado de botões */
void hostctrl_press(uint32_t buttons);

#endif
