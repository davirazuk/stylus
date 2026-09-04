/* Shim do psp2/touch.h para o preview no PC. Só o que o ui.c usa.
   No preview ninguém toca na tela: o sceTouchPeek devolve zero toques, então
   a UI desenha os botões e nunca dispara nenhum. */
#ifndef PSP2_TOUCH_HOST_SHIM_H
#define PSP2_TOUCH_HOST_SHIM_H

#include <stdint.h>

#define SCE_TOUCH_MAX_REPORT 8

typedef enum SceTouchPortType {
    SCE_TOUCH_PORT_FRONT   = 0,
    SCE_TOUCH_PORT_BACK    = 1,
    SCE_TOUCH_PORT_MAX_NUM = 2
} SceTouchPortType;

typedef enum SceTouchSamplingState {
    SCE_TOUCH_SAMPLING_STATE_STOP  = 0,
    SCE_TOUCH_SAMPLING_STATE_START = 1
} SceTouchSamplingState;

typedef struct SceTouchPanelInfo {
    int16_t  minAaX, minAaY, maxAaX, maxAaY;
    int16_t  minDispX, minDispY, maxDispX, maxDispY;
    uint8_t  minForce, maxForce;
    uint8_t  reserved[30];
} SceTouchPanelInfo;

typedef struct SceTouchReport {
    uint8_t  id;
    uint8_t  force;
    int16_t  x;
    int16_t  y;
    uint8_t  reserved[8];
    uint16_t info;
} SceTouchReport;

typedef struct SceTouchData {
    uint64_t       timeStamp;
    uint32_t       status;
    uint32_t       reportNum;
    SceTouchReport report[SCE_TOUCH_MAX_REPORT];
} SceTouchData;

int sceTouchSetSamplingState(uint32_t port, uint32_t state);
int sceTouchEnableTouchForce(uint32_t port);
int sceTouchGetPanelInfo(uint32_t port, SceTouchPanelInfo *info);
int sceTouchPeek(uint32_t port, SceTouchData *data, uint32_t nBufs);

/* extra só do host: o preview injeta um toque na tela (coords de TELA) */
void hosttouch_tap(int x, int y);

#endif
