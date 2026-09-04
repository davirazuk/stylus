/* Shim do psp2/kernel/processmgr.h para o preview no PC.
   O ui.c usa o relógio do sistema e o power tick; aqui o relógio vem do
   tempo real da máquina e o power tick não faz nada — não há tela para
   manter acesa. */
#ifndef PSP2_KERNEL_PROCESSMGR_HOST_SHIM_H
#define PSP2_KERNEL_PROCESSMGR_HOST_SHIM_H

#include <stdint.h>

typedef enum SceKernelPowerTickType {
    SCE_KERNEL_POWER_TICK_DEFAULT              = 0,
    SCE_KERNEL_POWER_TICK_DISABLE_AUTO_SUSPEND = 1,
    SCE_KERNEL_POWER_TICK_DISABLE_OLED_OFF     = 4,
    SCE_KERNEL_POWER_TICK_DISABLE_OLED_DIMMING = 6
} SceKernelPowerTickType;

int      sceKernelPowerTick(int type);
uint64_t sceKernelGetProcessTimeWide(void);
uint32_t sceKernelGetProcessTimeLow(void);
void     sceKernelExitProcess(int res);

#endif
