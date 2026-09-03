#include <vita2d.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/ctrl.h>
#include <psp2/sysmodule.h>
#include <psp2/appmgr.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "library.h"
#include "player.h"
#include "ui.h"

#define MUSIC_ROOT "ux0:music"

/* módulos de rede são pré-carregados para o futuro (Qobuz); inofensivo agora */
static void load_modules(void)
{
    sceSysmoduleLoadModule(SCE_SYSMODULE_NET);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTP);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTPS);
    sceSysmoduleLoadModule(SCE_SYSMODULE_SSL);
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    sceCtrlSetSamplingMode(SCE_CTRL_MODE_DIGITAL);
    load_modules();

    if (vita2d_init() < 0) {
        sceAppMgrLoadExec("app0:eboot.bin", NULL, NULL);
        return 1;
    }

    Library lib;
    library_init(&lib, MUSIC_ROOT);
    library_scan(&lib);

    Ui *ui = ui_create();
    Player *player = player_create();
    if (!ui || !player) {
        if (ui) ui_destroy(ui);
        if (player) player_destroy(player);
        vita2d_fini();
        sceKernelExitProcess(1);
    }

    int running = 1;
    while (running) {
        int act = ui_handle_input(ui);
        switch (act) {
        case -1:
            running = 0;
            break;
        case 2: {
            int idx = ui_selected(ui);
            if (idx >= 0 && idx < lib.nalbums)
                player_load(player, &lib, idx, 0);
            break;
        }
        case 4:
            player_toggle(player);
            break;
        case 5:
            player_next(player);
            break;
        case 6:
            player_prev(player);
            break;
        case 7:
            player_seek(player, player_track_seconds(player) - 10);
            break;
        default:
            break;
        }
        ui_frame(ui, &lib, player);
    }

    player_destroy(player);
    ui_destroy(ui);
    library_free(&lib);
    vita2d_fini();
    sceKernelExitProcess(0);
    return 0;
}
