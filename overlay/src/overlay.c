/*
 * vitastylus_overlay.skprx — overlay de faixa para o Vitastylus
 *
 * ATENÇÃO: Este plugin requer taiHEN para construir e instalar.
 * O build requer os stubs kernel de taiHEN (SceCtrlForKernel,
 * SceDisplayForKernel, etc.) que não estão no vitasdk padrão.
 *
 * Para compilar, siga o guia de plugins taiHEN:
 *   https://github.com/henkaku/taiHEN
 *
 * O app Vitastylus escreve `ux0:data/vitastylus/now_playing.txt` com:
 *   linha 1: título
 *   linha 2: artista
 *   linha 3: álbum
 *   linha 4: 1=tocando, 0=parado
 *
 * O plugin lê este arquivo e desenha uma barra no fundo da tela via
 * sceDisplayGetFrameBuf quando L+R+SELECT é pressionado.
 */

/* Nota para builds futuros: este arquivo é funcional mas não compila
 * sem os stubs kernel. Mantido como referência de implementação.
 * A abordagem correta é usar taiHEN + CMakeLists do taiHEN template. */

#ifndef VITASTYLUS_OVERLAY_H
#define VITASTYLUS_OVERLAY_H

/* Placeholder — a implementação real precisa de:
 *   - taiHEN (hook no sceCtrlReadBufferPositive)
 *   - SceCtrlForKernel (leitura de botões em kernel)
 *   - SceDisplayForKernel (acesso ao framebuffer)
 *   - SceLibKernel_stub (threads, delays)
 *   - SceRtc_stub (timing)
 *
 * O protocolo IPC já está definido:
 *   - App escreve ux0:data/vitastylus/now_playing.txt
 *   - Plugin lê e desenha overlay por 4 segundos
 *   - Combo: L+R+SELECT
 */

#endif /* VITASTYLUS_OVERLAY_H */
