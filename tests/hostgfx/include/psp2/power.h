#ifndef HOSTGFX_PSP2_POWER_H
#define HOSTGFX_PSP2_POWER_H

/* No PC não há bateria. Estes tocos existem para o ui.c compilar IGUAL nos
   dois lados — o preview desenha um valor plausível e fixo, e o que se julga
   na imagem é o desenho do indicador, não a carga. */
static inline int  scePowerGetBatteryLifePercent(void) { return 72; }
static inline int  scePowerIsBatteryCharging(void)     { return 0; }

#endif
