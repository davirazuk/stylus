#include <vita2d.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/ctrl.h>
#include <psp2/sysmodule.h>
#include <psp2/appmgr.h>
#include <psp2/apputil.h>
#include <psp2/common_dialog.h>
#include <psp2/shellutil.h>
#include <psp2/system_param.h>
#include <psp2/power.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "library.h"
#include "paths.h"
#include "fsutil.h"
#include "player.h"
#include "ui.h"
#include "playlist.h"
#include "rec.h"
#include "scrobble.h"
#include "resume.h"
#include "decoder.h"
#include "lastfm.h"
#include "sides.h"
#include "qobuz.h"
#include "soundcloud.h"
#include "fonte.h"

/* recomendações e playlists moram no cartão, junto do app — os caminhos são
   do paths.h, que é o único dono deles */
#define UX0_DATA_DIR        STYLUS_DATA_DIR
#define PLAYLIST_DIR        STYLUS_PLAYLISTS
#define REC_HISTORY_BASE    STYLUS_DATA_DIR

/* módulos de rede são pré-carregados para o futuro (Qobuz); inofensivo agora */
static void load_modules(void)
{
    sceSysmoduleLoadModule(SCE_SYSMODULE_NET);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTP);
    sceSysmoduleLoadModule(SCE_SYSMODULE_HTTPS);
    sceSysmoduleLoadModule(SCE_SYSMODULE_SSL);
}

/* ÁUDIO EM SEGUNDO PLANO — as DUAS coisas que precisam valer.

   1. O app tem que PEDIR a porta BGM ao sistema. Com o plugin de CFW
      MusicPremium instalado, o Vita então não suspende este processo enquanto
      há som nela, e a música continua dentro de um jogo. Sem o plugin o
      pedido é inofensivo: a porta não vem e seguimos tocando normal.
   2. O SDL2 só ABRE a saída como BGM com taxa <= 47999 Hz (ver a nota grande
      no decoder.c). Sem o teto, um MP3 de 48 kHz cai na porta MAIN e perde o
      segundo plano em silêncio — numa varredura do cartão do usuário, 996 de
      3728 arquivos eram 48 kHz: 27% da coleção.

   Uma sem a outra não funciona, e é por isso que a tela mostra as duas. */
#define BGM_MAX_RATE  47999L
static bool bgm_port_ok;

/* O Vita dá ao homebrew um heap pequeno por padrão, e uma coleção grande não
   cabe: cada Track são ~1,5 KB e um cartão com 5000 faixas já pede 8 MB só de
   estrutura, mais as capas decodificadas. Sem isto o malloc começa a devolver
   NULL no meio da varredura e a estante fica pela metade, em silêncio. */
/* 48 MB, e NÃO 128 — o tamanho é o que decide se dá para tocar dentro de um
   jogo.

   MEDIDO nesta coleção: 3.729 faixas × 1.592 B = 5,7 MB, mais 388 álbuns ×
   2.888 B = 1,1 MB. Sete megabytes. As CAPAS não entram nesta conta: viram
   textura do vita2d (memória de vídeo), o cache tem teto de 10, e os bytes
   crus são liberados logo depois de decodificar. Ou seja, 128 MB era ~18x o
   necessário — e estava declarado DUAS vezes, uma por alocador.

   POR QUE ISSO IMPEDE O SEGUNDO PLANO: o Vita tem 512 MB no total. Um jogo
   pega 256 MB ou mais, o sistema fica com o seu, e o que o MusicPremium faz é
   impedir a SUSPENSÃO do app que segura a porta BGM — não fabricar memória.
   Um app pendurado em 128 MB (ou 256, somando os dois alocadores) é caro
   demais para o sistema manter vivo quando o jogo pede a memória dele: em vez
   de suspender, ele MATA. O VitaWave, que o usuário citou como referência,
   não declara heap nenhum — roda no padrão.

   48 MB continua sendo quase 7x o que a estante ocupa, com folga para uma
   coleção bem maior; o que sai é a reserva que não era usada por ninguém. Se
   um dia a varredura voltar a parar no meio (o sintoma antigo: malloc
   devolvendo NULL e a estante pela metade, em silêncio), este é o número a
   subir — e a conta acima é como se decide para quanto. */
/* A PILHA DA THREAD PRINCIPAL — 1 MB, contra os 256 KB padrão.

   As letras (`lyrics_load`, chamado do desenho em ui.c) fazem a busca no
   lrclib DE DENTRO da thread principal. Enquanto isso era sceHttp, o
   handshake não custava pilha nossa; com o curl+OpenSSL custa, e o padrão do
   Vita não tem essa folga. Uma pilha estourada aqui não é um erro na tela: é
   o app fechando. */
unsigned int sceUserMainThreadStackSize = 1024 * 1024;

unsigned int sceLibcHeapSize = 48 * 1024 * 1024;
unsigned int _newlib_heap_size_user = 48 * 1024 * 1024;

/* Fila de faixas terminadas.
   O callback do player roda na THREAD DE ÁUDIO. Escrever o histórico dali
   mexia no mesmo `Rec` que o laço principal estava lendo para montar as
   recomendações — realloc de um lado, leitura do outro. Aqui o callback só
   ENFILEIRA (um produtor, um consumidor, sem trava) e quem escreve em disco é
   o laço principal, que é também quem lê. */
#define DONE_Q 16

/* O FORMATO DESTA SESSÃO DE REDE, quando ele não é o configurado.

   O `cfg->formato` é uma escolha sobre DOWNLOAD — quanto do cartão um disco
   baixado vai custar — e o padrão dele é MP3 de propósito, porque num Vita 1
   GB é muito. Isso está certo para baixar e errado para a pílula GET FLAC: o
   botão promete lossless, e com o formato em MP3 ele trocaria o MP3 do cartão
   por um MP3 do Qobuz. Um botão que faz o contrário do que diz é pior que um
   botão que não faz nada — a pessoa acha que ouviu a diferença.

   0 = use o configurado. A troca põe aqui o FLAC (ou o hi-res quando o
   catálogo tem 24 bits daquela gravação), e abrir um disco pela loja põe de
   volta em 0. */
static int g_fmt_sessao;

/* A CONTA DO SOUNDCLOUD, lida uma vez no arranque. Vazia quando o cartão não
   tem `soundcloud.config` — e aí o app segue exatamente como antes. */
static ScConfig g_sc;

/* DE QUE FONTE É ESTA FAIXA.
 *
 * O `remote_id` era sempre um id do Qobuz, porque o Qobuz era a única fonte.
 * Com mais de uma, o id sozinho não diz de onde veio — e "resolver" um id do
 * SoundCloud contra a API do Qobuz devolve um 404 que parece problema de
 * rede.
 *
 * A marca vai no PRÓPRIO id, como prefixo (`sc:123456`), e não num campo
 * novo: um campo novo teria de ser preenchido, copiado e gravado em todo
 * lugar por onde uma Track passa — estante, índice, playlist, cache — e o
 * lugar que alguém esquecesse seria uma faixa que toca a música errada. O id
 * sem prefixo continua sendo Qobuz, então nada do que já existe muda.
 *
 * `remote_id` tem 32 bytes; um id do SoundCloud tem 10 dígitos e o do Qobuz
 * 9, então o prefixo cabe com folga nos dois. */
static int resolve_remote(void *ud, const char *remote_id,
                          char *url, int cap, int *kind)
{
    QobuzConfig *cfg = ud;

    if (remote_id && !strncmp(remote_id, "sc:", 3)) {
        if (sc_url(&g_sc, remote_id + 3, url, cap) != 0) {
            /* O MOTIVO VAI PARA O CARTÃO.
               Uma faixa que não toca e não deixa rastro é a assinatura que
               este projeto já perseguiu três vezes: sem `rede.txt` não dá
               para distinguir "sem Wi-Fi" de "client_id vencido" de "a faixa
               é privada", e as três dão a mesma tela. O `sc_motivo()` sabe
               qual foi; ele só precisava de alguém que o escrevesse. */
            FILE *f = fopen(STYLUS_DATA_DIR "/rede.txt", "a");
            if (f) {
                fprintf(f, "soundcloud %s: %s\n", remote_id + 3, sc_motivo());
                fclose(f);
            }
            return -1;
        }
        /* O SoundCloud progressivo é MP3 — a escolha está no
           `acha_progressiva`, que prefere `audio/mpeg`. */
        *kind = DEC_MP3;
        return 0;
    }

    int formato = g_fmt_sessao ? g_fmt_sessao : cfg->formato;
    int r = qobuz_url(cfg, remote_id, formato, url, cap);
    /* O hi-res não existe para toda gravação e a região também recusa. Cair
       para o FLAC comum é melhor que a faixa simplesmente não tocar depois de
       a tela já ter dito de que disco ela é. */
    if (r != 0 && formato == QB_HIRES) {
        formato = QB_FLAC;
        r = qobuz_url(cfg, remote_id, formato, url, cap);
    }
    if (r != 0) return -1;
    *kind = qobuz_deckind(formato);
    return 0;
}

/* Faixas da rede: armazenamento temporário para álbuns abertos pelo Qobuz.
   O player mantém PONTEIROS para Track durante toda a reprodução — estes
   têm que sobreviver ao escopo de quem chamou player_load_list. Um Album
   fictício serve de encaixe: o deck lê artista, álbum e lado de lá, e sem
   ele a tela diz "nada no prato" upa um disco que está tocando. */
#define REMOTE_MAX 64
static Track  g_remote_tracks[REMOTE_MAX];
static int    g_remote_n;
static Album  g_remote_alb;

/* estado persistente que sobrevive o loop e alimenta a UI a cada frame */
typedef struct {
    Playlist *plists;
    int nplists;
    Rec rec;
    const Track *done_q[DONE_Q];
    volatile int done_head;   /* escrito pela thread de áudio */
    volatile int done_tail;   /* lido pelo laço principal */
    const Track **recs; /* ponteiros dentro de lib; dono é main (rebuild) */
    int nrecs;
    int recs_cap;
    bool dirty_plists;
    bool dirty_recs;
} Session;

#define RECS_MAX 200

static void session_free(Session *s)
{
    if (!s) return;
    if (s->plists) playlist_free(s->plists, s->nplists);
    free(s->recs);
    rec_free(&s->rec);
    memset(s, 0, sizeof(*s));
}

/* thread de áudio: só enfileira. Fila cheia perde a mais nova, que é melhor
   que sobrescrever uma que o laço ainda não leu. */
static void on_track_done(const Track *t, void *ud)
{
    Session *s = ud;
    if (!t || !s) return;
    int head = s->done_head;
    int next = (head + 1) % DONE_Q;
    if (next == s->done_tail) return;
    s->done_q[head] = t;
    s->done_head = next;
}

/* laço principal: escreve o histórico e o scrobble */
static void drain_done(Session *s)
{
    while (s->done_tail != s->done_head) {
        const Track *t = s->done_q[s->done_tail];
        s->done_tail = (s->done_tail + 1) % DONE_Q;
        if (!t) continue;
        /* Faixa da rede não tem caminho local — o remote_id serve como chave
           no histórico e no scrobble. Não é um caminho de arquivo, mas é
           ÚNICO, e é isso que rec_play e scrobble_log precisam. */
        const char *key = t->path[0] ? t->path : t->remote_id;
        rec_play(&s->rec, key, REC_HISTORY_BASE);
        long agora = (long)time(NULL);
        scrobble_log(REC_HISTORY_BASE, t, agora);
        /* Camada last.fm. A ordem importa: ENFILEIRA primeiro, sempre, e só
           depois tenta subir. A escuta fica no cartão antes de qualquer coisa
           poder dar errado — sem rede, sem conta, ou com a bateria acabando
           no meio do envio, ela continua lá e sai na próxima vez. */
        lastfm_enqueue(REC_HISTORY_BASE, t, agora,
                       t->seconds > 0 ? t->seconds : 0);
        lastfm_sync_async(REC_HISTORY_BASE);
        s->dirty_recs = true;
    }
}

/* reconstrói a lista recomendada (chamado quando o histórico muda) */
static void recs_rebuild(Session *s, Library *lib)
{
    if (s->recs_cap == 0) {
        s->recs_cap = RECS_MAX;
        s->recs = malloc((size_t)s->recs_cap * sizeof(*s->recs));
    }
    s->nrecs = 0;
    if (s->recs)
        rec_build_list(&s->rec, lib, s->recs, &s->nrecs, RECS_MAX);
    s->dirty_recs = false;
}

/* resolve uma lista de caminhos (playlist) em bubbles para o player */
static const Track *track_by_path(Library *lib, const char *path)
{
    for (int a = 0; a < lib->nalbums; a++) {
        Album *alb = &lib->albums[a];
        for (int t = 0; t < alb->ntracks; t++)
            if (strcmp(alb->tracks[t].path, path) == 0)
                return &alb->tracks[t];
    }
    return NULL;
}

static int playlist_to_tracks(Library *lib, const Playlist *pl,
                              const Track **out, int max)
{
    int n = 0;
    for (int i = 0; i < pl->n && n < max; i++) {
        const Track *t = track_by_path(lib, pl->files[i]);
        if (t) out[n++] = t;
    }
    return n;
}

/* retoma onde o app foi encerrado/suspenso, sempre em pausa */
static void try_resume(Library *lib, Player *player)
{
    Resume r;
    resume_load(UX0_DATA_DIR, &r);
    if (!r.valid) return;
    Album *alb = NULL;
    int ti = library_find_track_by_path(lib, &alb, r.track_path);
    if (ti < 0 || !alb) return;
    for (int i = 0; i < lib->nalbums; i++)
        if (&lib->albums[i] == alb) {
            player_set_repeat(player, (RepeatMode)r.repeat);
            player_set_shuffle(player, r.shuffle);
            player_load_album(player, lib, i, ti);
            if (r.position_sec > 0)
                player_seek(player, r.position_sec);
            player_pause(player);
            break;
        }
}

/* grava o ponto de continuação (chamado periodicamente e a cada faixa) */
/* As escolhas da tela de ajustes vivem no MESMO arquivo da sessão, e são
   lidas mesmo quando não há faixa para retomar: quem escolheu CD quer o CD
   de volta na abertura seguinte, tenha ou não sobrado música tocando. Por
   isso são carregadas fora do `try_resume`, que desiste cedo. */
static void carrega_ajustes(Ui *ui)
{
    Resume r;
    resume_load(UX0_DATA_DIR, &r);
    ui_set_midia(ui, r.midia);
    ui_set_toque_tras(ui, r.toque_tras);
    ui_set_tema(ui, r.tema);
    ui_set_bg_trava(ui, r.bg_trava);
    ui_set_fonte(ui, r.fonte);
}

static Ui *g_ui_ajustes;   /* de quem o write_resume lê as preferências */

static void write_resume(Player *player)
{
    const Track *t = player_current_track(player);
    if (!t || !t->path[0]) return;
    Resume r;
    memset(&r, 0, sizeof(r));
    snprintf(r.track_path, sizeof(r.track_path), "%s", t->path);
    r.position_sec = player_track_seconds(player);
    r.repeat = (int)player_repeat(player);
    r.shuffle = player_shuffle(player);
    if (g_ui_ajustes) {
        r.midia = ui_midia(g_ui_ajustes);
        r.toque_tras = ui_toque_tras(g_ui_ajustes);
        r.tema = ui_tema(g_ui_ajustes);
        r.bg_trava = ui_bg_trava(g_ui_ajustes);
        r.fonte = ui_fonte(g_ui_ajustes);
    }
    if (r.track_path[0]) {
        r.valid = true;
        resume_save(UX0_DATA_DIR, &r);
    }
}

/* ESCREVE A FAIXA ATUAL para o plugin de overlay ler.
   O arquivo `now_playing.txt` é lido pelo companion SKPRX (se instalado)
   para mostrar o nome da faixa numa overlay quando o app está em segundo
   plano. Formato simples: primeira linha = título, segunda = artista,
   terceira = álbum, quarta = "1" se tocando, "0" se pausado. */
static void write_now_playing(Player *player)
{
    const Track *t = player_current_track(player);
    const Album *al = player_current_album(player);
    FILE *f = fopen(UX0_DATA_DIR "/now_playing.txt", "w");
    if (!f) return;
    if (t && player_state(player) != PLAYER_STOPPED) {
        fprintf(f, "%s\n", t->title[0] ? t->title : t->file);
        fprintf(f, "%s\n", (al && al->artist[0]) ? al->artist : "");
        fprintf(f, "%s\n", (al && al->album[0])  ? al->album  : "");
        fprintf(f, "%d\n", player_state(player) == PLAYER_PLAYING ? 1 : 0);
    } else {
        fprintf(f, "\n\n\n0\n");
    }
    fclose(f);
}

/* desenhada durante a varredura, a cada punhado de pastas */
static void scan_progress(void *ud, const char *where, int files)
{
    ui_draw_scanning((Ui *)ud, where, files);
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    sceCtrlSetSamplingMode(SCE_CTRL_MODE_DIGITAL);
    load_modules();
    dec_global_init();
    dec_set_max_rate(BGM_MAX_RATE);
    /* O rc CRU, e não só o sim/não: "o segundo plano não funciona" é a
       terceira coisa que ele mais pede, e a tela nunca disse se a porta foi
       recusada ou concedida. Vai para o varredura.txt, que é o arquivo que
       já respondeu perguntas assim sem uma viagem ao aparelho. */
    /* DIZER AO SISTEMA QUE ISTO É UM TOCADOR DE MÚSICA.

       A porta BGM sozinha não bastava: ela dá o CANAL de áudio, mas quem
       decide se o app continua vivo com a tela apagada é a Shell, e para ela
       este app era um app qualquer. `SCE_SHELL_UTIL_LOCK_TYPE_MUSIC_PLAYER`
       é o papel de tocador — a Shell tem esse conceito, e nunca o pedimos.

       Achado lendo o ElevenMPV-A (GrapheneCt), que é o homebrew que
       comprovadamente toca em segundo plano: ele abre a porta BGM direto e
       chama `sceShellUtilInitEvents` + `sceShellUtilLock` no começo do main.
       Ele usa LOCK_TYPE_PS_BTN; aqui vai o MUSIC_PLAYER, que é o papel certo
       e não corre o risco de prender a pessoa dentro do app — travar o botão
       PS é o próximo degrau se este não bastar. */
    sceShellUtilInitEvents(0);
    sceShellUtilLock(SCE_SHELL_UTIL_LOCK_TYPE_MUSIC_PLAYER);

    int bgm_rc = sceAppMgrAcquireBgmPort();
    bgm_port_ok = (bgm_rc >= 0);
    library_set_bgm(bgm_rc, BGM_MAX_RATE);

    if (vita2d_init() < 0) {
        sceAppMgrLoadExec("app0:eboot.bin", NULL, NULL);
        return 1;
    }

    /* ANTES de qualquer escrita. O `mkdir` cru não cria pai, e ninguém criava
       este: o histórico, o scrobble e o ponto de continuação abriam o arquivo
       para escrita numa pasta inexistente, o fopen devolvia NULL, cada função
       voltava em silêncio e NADA do que a pessoa ouviu era guardado — entre
       sessões o app esquecia tudo, sem uma linha de erro em lugar nenhum. */
    mkdir_p(UX0_DATA_DIR);
    mkdir_p(PLAYLIST_DIR);

    /* A PORTA DA FRENTE PARA ux0:music.

       SINTOMA, e ele durou meses: `sceIoDopen("ux0:music")` devolvia EPERM
       com 3.729 arquivos lá dentro. Passamos por duas explicações erradas —
       grafia do caminho, e depois o sandbox de homebrew "safe". A sonda que o
       app agora escreve no cartão matou as duas de uma vez:

         [x] ux0:  [x] ux0:app  [x] ux0:tai  [x] ux0:pkgj  [x] ux0:video
         [ ] ux0:music   0x80010001 (EPERM)

       ux0: INTEIRO abre. Só `music` não. Não é sandbox (senão nada abriria
       fora de ux0:data) e não é "pasta de mídia" em geral (ux0:video abre).
       É a biblioteca de música do sistema, que o Content Manager guarda e que
       um app só enxerga depois de PEDIR — e pedir é isto. Sem esta chamada o
       app estava batendo na porta dos fundos e concluindo que não havia casa.

       O retorno vai para o relatório: se um dia voltar a falhar, o número
       está escrito no cartão em vez de virar outra rodada de adivinhação. */
    {
        SceAppUtilInitParam ip;
        SceAppUtilBootParam bp;
        memset(&ip, 0, sizeof(ip));
        memset(&bp, 0, sizeof(bp));
        int r_init = sceAppUtilInit(&ip, &bp);
        int r_mount = sceAppUtilMusicMount();
        library_set_music_mount(r_init, r_mount);
    }

    /* O TECLADO DO SISTEMA NÃO ABRE SEM ISTO.

       Todo diálogo comum do Vita — o teclado (sceImeDialog) inclusive — só
       funciona depois de UMA chamada de configuração. Sem ela o
       sceImeDialogInit devolve 0x80020407 (NOT_CONFIGURED) e some: quem
       aperta [quadrado] para buscar não vê nada acontecer.

       O SINTOMA que isto conserta: "qobuz not working". A busca do Qobuz
       nunca chegou a acontecer — não era rede, não era a API, não era o
       parser. Era não haver como DIGITAR o termo. Vale para todos os campos
       do app (a busca da estante, o login do last.fm, as chaves), e é por
       isso que as chaves do Qobuz precisaram vir do PC pelo pro-cartao.sh:
       o teclado nunca abriu, nesta ou em qualquer versão anterior.

       O botão de confirmar e a língua saem do sistema: quem trocou ✕/◯ nas
       configurações espera que o teclado obedeça à escolha dele. */
    {
        SceCommonDialogConfigParam dcfg;
        sceCommonDialogConfigParamInit(&dcfg);
        int lang = SCE_SYSTEM_PARAM_LANG_ENGLISH_US;
        int enter = SCE_SYSTEM_PARAM_ENTER_BUTTON_CROSS;
        sceAppUtilSystemParamGetInt(SCE_SYSTEM_PARAM_ID_LANG, &lang);
        sceAppUtilSystemParamGetInt(SCE_SYSTEM_PARAM_ID_ENTER_BUTTON, &enter);
        dcfg.language = (SceSystemParamLang)lang;
        dcfg.enterButtonAssign = (SceSystemParamEnterButtonAssign)enter;
        library_set_dialog(sceCommonDialogSetConfigParam(&dcfg));
    }

    /* Só para o relatório: o [quadrado] que busca no Qobuz só existe na tela
       de BUSCA, e ela só aparece com as chaves completas. Sem esta linha, um
       "não dá para buscar" não distingue tecla morta de tela errada. */
    {
        QobuzConfig qc;
        qobuz_config_load(&qc, STYLUS_DATA_DIR);
        /* O SoundCloud é OPCIONAL: sem `soundcloud.config` no cartão o
           `g_sc.ok` fica 0, o resolvedor recusa `sc:` com uma frase clara, e
           tudo o mais segue idêntico. Uma fonte nova não pode ser motivo de
           o app não subir. */
        sc_config_load(&g_sc, STYLUS_DATA_DIR);
        library_set_qobuz(qc.app_id[0] || qc.token[0], qc.configured);
    }

    Ui *boot = ui_create();

    Library lib;
    library_init(&lib);
    /* O ÍNDICE primeiro, numa estante ainda vazia — ele traz as próprias
       raízes. Confere sozinho se ainda vale (as datas das ~500 pastas que a
       varredura visitou) e, se não valer, devolve -1 sem ter mexido em nada.
       Ou seja: ou economiza a varredura inteira, ou custa ~500 stats. */
    if (library_cache_load(&lib, STYLUS_ESTANTE) != 0) {
        library_roots_from(&lib, UX0_DATA_DIR);
        /* varrer um cartão cheio leva segundos; sem esta tela é preto e
           parado, que da poltrona é indistinguível de travado */
        library_set_progress(&lib, scan_progress, boot);
        library_scan(&lib);
        library_cache_save(&lib, STYLUS_ESTANTE);
    }
    /* Deixa o que a varredura viu escrito no cartão. Quem conserta o app
       quase nunca é quem está com o aparelho na mão, e a tela some quando se
       muda de tela — foi um arquivo assim que revelou o opendir devolvendo
       NULL. Custa uma escrita pequena por arranque. */
    library_report(&lib, STYLUS_DATA_DIR "/varredura.txt");

    Session ses;
    memset(&ses, 0, sizeof(ses));
    playlist_load_dir(&ses.plists, &ses.nplists, PLAYLIST_DIR);
    rec_load(&ses.rec, REC_HISTORY_BASE);

    /* A fila que sobrou de quando não havia rede sai agora, atrás do
       arranque. Não trava nada: volta na hora se estiver vazia. */
    lastfm_sync_async(REC_HISTORY_BASE);
    recs_rebuild(&ses, &lib);

    Ui *ui = boot;
    Player *player = player_create();
    if (!ui || !player) {
        if (ui) ui_destroy(ui);
        if (player) player_destroy(player);
        library_free(&lib);
        session_free(&ses);
        vita2d_fini();
        sceKernelExitProcess(1);
    }
    player_set_complete_cb(player, on_track_done, &ses);
    /* O resolvedor de faixas remotas: quando o player abrir uma faixa da rede,
       ele pergunta ao main como transformar o id numa URL. O QobuzConfig
       precisa ficar vivo — e fica, porque é um campo da Ui. */
    player_set_resolver(resolve_remote, ui_qobuz_cfg(ui));

    ui_set_data(ui, ses.plists, ses.nplists, ses.recs, ses.nrecs);
    /* O histórico é do main; a home só LÊ dele para montar "mais tocados" e
       "nunca tocados". Passar o ponteiro uma vez basta: o Rec vive tanto
       quanto a sessão. */
    ui_set_rec(ui, &ses.rec);
    ui_set_bgm(ui, bgm_port_ok);

    /* Abrir com música já tocando NÃO encena a cerimônia: o disco não foi
       posto agora, foi encontrado no meio. */
    g_ui_ajustes = ui;
    carrega_ajustes(ui);
    try_resume(&lib, player);
    ui_skip_ritual(ui);

    int running = 1;
    int frame = 0;
    while (running) {
        int act = ui_handle_input(ui);
        switch (act) {
        case -1:
            running = 0;
            break;
        case 2: {
            int idx = ui_selected(ui);
            if (idx >= 0 && idx < lib.nalbums &&
                player_load_album(player, &lib, idx, 0) == 0) {
                player_mute(player);
                ui_begin_ritual(ui);
            }
            break;
        }
        case 4:
            player_toggle(player);
            write_now_playing(player);
            break;
        case 5:
            player_next(player);
            write_now_playing(player);
            break;
        case 6:
            player_prev(player);
            write_now_playing(player);
            break;
        case 7:
            player_seek(player, player_track_seconds(player) - 10);
            break;
        case 11: { /* tocar recomendações, a partir da que está MARCADA */
            int ri = ui_rec_idx(ui);
            if (ses.nrecs > 0) {
                if (ri < 0 || ri >= ses.nrecs) ri = 0;
                if (player_load_list(player, &lib, ses.recs, ses.nrecs, ri) == 0) {
                    player_mute(player);
                    ui_begin_ritual(ui);
                }
            }
            break;
        }
        case 23:   /* tocar a lista EMBARALHADA (a pílula "shuffle") */
        case 12: { /* tocar playlist selecionada */
            /* A pílula de embaralhar liga o modo ANTES de carregar: ligar
               depois faria a primeira faixa sair na ordem e só a segunda
               obedecer — e "shuffle" que começa certo é o que se espera. */
            if (act == 23) player_set_shuffle(player, true);
            int pi = ui_playlist_idx(ui);
            if (ses.plists && pi >= 0 && pi < ses.nplists && ses.plists[pi].n > 0) {
                const Track *tracks[1600];
                int n = playlist_to_tracks(&lib, &ses.plists[pi],
                                           tracks, 1600);
                if (n > 0 && player_load_list(player, &lib, tracks, n, 0) == 0) {
                    player_mute(player);
                    ui_begin_ritual(ui);
                }
            }
            break;
        }
        case 13: { /* criar playlist nova com o que está tocando */
            const Track *sess[1600];
            int n = player_session_tracks(player, sess, 1600);
            if (n > 0) {
                if (playlist_new(&ses.plists, &ses.nplists, PLAYLIST_NAME_PREFIX,
                                 sess, n) == 0) {
                    const Playlist *pl = &ses.plists[ses.nplists - 1];
                    playlist_save(pl, PLAYLIST_DIR);
                }
            }
            break;
        }
        case 14: { /* cicla repetição: ALL → ONE → OFF */
            RepeatMode r = player_repeat(player);
            r = (RepeatMode)(((int)r + 1) % 3);
            player_set_repeat(player, r);
            break;
        }
        case 15: /* alterna o sorteio */
            player_set_shuffle(player, !player_shuffle(player));
            break;
        case 16: /* avança +10s */
            player_seek(player, player_track_seconds(player) + 10);
            break;
        case 30: { /* ═══ SHUFFLE ALL: todas as faixas da coleção, aleatório ═══
                     Coleta todos os ponteiros de Track de todos os álbuns num
                     vetor único, e manda o player tocá-los embaralhados. O
                     vetor é da PILHA — a coleção tem no máximo 507 pastas
                     com ~8 faixas = ~4000 tracks, cabendo em 1600 ponteiros
                     no limite do DISC_FAIXAS_MAX e do `tracks[1600]` já
                     usado na playlist. */
            {
                const Track *all[1600];
                int na = 0;
                for (int i = 0; i < lib.nalbums && na < 1600; i++) {
                    Album *a = &lib.albums[i];
                    album_load_meta(a);
                    for (int j = 0; j < a->ntracks && na < 1600; j++)
                        all[na++] = &a->tracks[j];
                }
                if (na > 0) {
                    player_set_shuffle(player, true);
                    if (player_load_list(player, &lib, all, na, 0) == 0) {
                        player_mute(player);
                        ui_begin_ritual(ui);
                    }
                }
            }
            break;
        }
        case 31: { /* ═══ ALBUM SHUFFLE: ordem dos discos aleatória ════════════
                     Embaralha os índices dos álbuns e concatena suas faixas.
                     Cada disco toca inteiro e na ordem das faixas — muda só a
                     ordem em que os discos aparecem. Shuffle DESLIGADO no
                     player, porque o embaralhamento já foi feito aqui. */
                int idx[256];
                int n = lib.nalbums < 256 ? lib.nalbums : 256;
                for (int i = 0; i < n; i++) idx[i] = i;
                /* Fisher-Yates com o rand() que o player já usa */
                for (int i = n - 1; i > 0; i--) {
                    int j = rand() % (i + 1);
                    int tmp = idx[i]; idx[i] = idx[j]; idx[j] = tmp;
                }
                const Track *all[1600];
                int na = 0;
                for (int k = 0; k < n && na < 1600; k++) {
                    Album *a = &lib.albums[idx[k]];
                    album_load_meta(a);
                    for (int j = 0; j < a->ntracks && na < 1600; j++)
                        all[na++] = &a->tracks[j];
                }
                if (na > 0) {
                    player_set_shuffle(player, false);
                    if (player_load_list(player, &lib, all, na, 0) == 0) {
                        player_mute(player);
                        ui_begin_ritual(ui);
                    }
                }
            }
            break;
        case 19: { /* a régua: pula para o primeiro disco daquela letra */
            int want = ui_jump_letter(ui);
            for (int i = 0; i < lib.nalbums; i++) {
                const char *nm = lib.albums[i].artist[0] ? lib.albums[i].artist
                                                         : lib.albums[i].album;
                char c0 = nm[0];
                if (c0 >= 'a' && c0 <= 'z') c0 -= 32;
                int letra = (c0 >= 'A' && c0 <= 'Z') ? c0 - 'A' : 26;
                if (letra == want) { ui_set_sel(ui, i); break; }
            }
            break;
        }
        case 21: {
            /* Revarrer, sem sair do app.

               Existe por causa do download do Qobuz: um disco que acabou de
               cair no cartão não aparecia na estante até a próxima abertura
               do app. "Baixei e não está lá" é indistinguível de "o download
               falhou", e as duas coisas pedem reações opostas.

               O que TOCA não é interrompido: o player segura ponteiros para
               dentro da biblioteca antiga, então a varredura só substitui a
               estante quando não há nada tocando. Com música no ar, a tela
               diz para voltar depois — mentir que revarreu seria pior. */
            if (player_state(player) != PLAYER_STOPPED) {
                break;
            }
            ui_set_data(ui, NULL, 0, NULL, 0);   /* solta as recomendações */
            library_free(&lib);
            library_init(&lib);
            library_roots_from(&lib, UX0_DATA_DIR);
            library_set_progress(&lib, scan_progress, ui);
            library_scan(&lib);
            /* Revarrer à mão é justamente quando o índice tem de ser
               refeito: a pessoa está aqui porque mexeu no cartão. */
            library_cache_save(&lib, STYLUS_ESTANTE);
            library_report(&lib, STYLUS_DATA_DIR "/varredura.txt");
            recs_rebuild(&ses, &lib);
            ui_set_sel(ui, 0);
            break;
        }
        case 20: { /* a soneca: desligada → esmaece → fim do lado → desligada */
            int m2 = (player_sleep_mode(player) + 1) % 3;
            int last = -1;
            if (m2 == 2) {
                /* o fim do LADO, não um relógio: é o disco que decide */
                const Album *a = player_current_album(player);
                if (a && a->lados.n > 0) {
                    int l = sides_of_track(&a->lados, player_track_idx(player));
                    if (l >= 0) last = a->lados.sides[l].last;
                }
                if (last < 0) m2 = 0;   /* sem lados, não prometa o que não sabe */
            }
            player_set_sleep(player, m2, last);
            break;
        }
        case 18: { /* o dedo largou a barra: busca para onde ele apontou */
            float f = ui_scrub(ui);
            int dur = player_track_duration(player);
            if (f >= 0 && dur > 0) player_seek(player, (int)(f * (float)dur));
            break;
        }
        case 17: { /* apagar playlist (confirmado em 2 toques via R2) */
            int pi = ui_playlist_idx(ui);
            if (ses.plists && pi >= 0 && pi < ses.nplists)
                playlist_remove_file(ses.plists, &ses.nplists, pi, PLAYLIST_DIR);
            break;
        }
        case 22: { /* tocar da rede: o disco foi aberto, as faixas estão prontas */
            QobuzFaixa fx[REMOTE_MAX];
            int nfx = 0;
            bool ativo = false;
            QobuzAlbum alb;
            qobuz_abre_estado(fx, REMOTE_MAX, &nfx, &ativo, &alb);
            if (nfx <= 0 || nfx > REMOTE_MAX) break;
            g_fmt_sessao = 0;      /* disco da loja: vale o formato configurado */
            /* Album fictício: o deck lê artista e álbum de lá. Sem ele a tela
               diz "nada no prato" — que é o estado de quem não tem disco,
               não o de quem está ouvindo pela rede. */
            memset(&g_remote_alb, 0, sizeof(g_remote_alb));
            snprintf(g_remote_alb.artist, sizeof(g_remote_alb.artist),
                     "%s", alb.artista);
            snprintf(g_remote_alb.album, sizeof(g_remote_alb.album),
                     "%s", alb.titulo);
            g_remote_n = 0;
            for (int i = 0; i < nfx; i++) {
                Track *t = &g_remote_tracks[g_remote_n];
                memset(t, 0, sizeof(*t));
                /* A precisão limita a LEITURA, e não só a escrita: o `id` é um
                   vetor de tamanho fixo que pode chegar sem terminador, e aí
                   o "%s" sairia lendo pelos campos seguintes — e pelas faixas
                   seguintes, que é o que o compilador avisava com "up to
                   12799 bytes" (64 faixas de struct, uma atrás da outra). */
                snprintf(t->remote_id, sizeof(t->remote_id), "%.*s",
                         (int)sizeof(t->remote_id) - 1, fx[i].id);
                snprintf(t->title, sizeof(t->title), "%s", fx[i].titulo);
                t->number = fx[i].numero;
                t->seconds = fx[i].segundos;
                t->decodable = true;
                t->owner = &g_remote_alb;
                g_remote_n++;
            }
            g_remote_alb.ntracks = g_remote_n;
            g_remote_alb.seconds_total = 0;
            for (int i = 0; i < g_remote_n; i++)
                if (g_remote_tracks[i].seconds > 0)
                    g_remote_alb.seconds_total += g_remote_tracks[i].seconds;
            g_remote_alb.tracks = g_remote_tracks;
            /* A capa deste disco vive no Qobuz, não no cartão. Pendurar aqui
               id + URL é o que deixa o deck pedi-la; a baixa é do mesmo
               cache das capas da loja, só que de um disco só. */
            snprintf(g_remote_alb.qb_kapa, sizeof(g_remote_alb.qb_kapa),
                     "%s", alb.id);
            snprintf(g_remote_alb.qb_kapa_url, sizeof(g_remote_alb.qb_kapa_url),
                     "%s", alb.capa);
            if (alb.capa[0]) qobuz_capas_async(&alb, 1, STYLUS_DATA_DIR);
            const Track *ptrs[REMOTE_MAX];
            for (int i = 0; i < g_remote_n; i++) ptrs[i] = &g_remote_tracks[i];
            if (player_load_list(player, &lib, ptrs, g_remote_n, 0) == 0) {
                player_mute(player);
                ui_begin_ritual(ui);
            }
            qobuz_abre_limpa();
            break;
        }

        case 27: { /* tocar UMA faixa do SoundCloud */
            /* O SoundCloud devolve faixa solta, não disco: a sessão tem uma
               linha só. Vai pelo MESMO caminho do disco da loja (um Album
               fictício + player_load_list) porque o deck, o scrobble e os
               LADOS já sabem ler isso — uma segunda espécie de sessão seria
               um segundo tocador. */
            char id[24], artista[96], titulo[160];
            int segs = 0;
            if (!ui_sc_escolhida(ui, id, (int)sizeof(id),
                                 artista, (int)sizeof(artista),
                                 titulo, (int)sizeof(titulo), &segs))
                break;

            g_fmt_sessao = 0;
            memset(&g_remote_alb, 0, sizeof(g_remote_alb));
            snprintf(g_remote_alb.artist, sizeof(g_remote_alb.artist), "%s", artista);
            /* o "álbum" é o próprio nome da fonte: mentir um nome de disco
               aqui faria o deck afirmar uma coisa que não existe */
            snprintf(g_remote_alb.album, sizeof(g_remote_alb.album), "SoundCloud");

            Track *t = &g_remote_tracks[0];
            memset(t, 0, sizeof(*t));
            /* O PREFIXO É O QUE DIZ DE ONDE ELA VEM. Sem ele o
               `resolve_remote` mandaria este id para a API do Qobuz e o 404
               teria cara de problema de rede — ver a nota lá em cima. */
            snprintf(t->remote_id, sizeof(t->remote_id), "sc:%.*s",
                     (int)sizeof(t->remote_id) - 4, id);
            snprintf(t->title, sizeof(t->title), "%s", titulo);
            t->number = 1;
            t->seconds = segs;
            t->decodable = true;
            t->owner = &g_remote_alb;

            g_remote_n = 1;
            g_remote_alb.ntracks = 1;
            g_remote_alb.seconds_total = segs > 0 ? segs : 0;
            g_remote_alb.tracks = g_remote_tracks;

            const Track *um[1] = { &g_remote_tracks[0] };
            if (player_load_list(player, &lib, um, 1, 0) == 0) {
                player_mute(player);
                ui_begin_ritual(ui);
            }
            break;
        }

        case 28: { /* GET FLAC pronto: qobuz_abre_async terminou */
            QobuzFaixa fx[REMOTE_MAX];
            int nfx = 0;
            bool ativo = false;
            QobuzAlbum alb;
            qobuz_abre_estado(fx, REMOTE_MAX, &nfx, &ativo, &alb);
            qobuz_getflac_done();
            if (nfx <= 0 || nfx > REMOTE_MAX) break;
            /* O formato vem do casamento (hi-res ou FLAC), não do
               configurado — é o que o botão GET FLAC promete. */
            g_fmt_sessao = qobuz_getflac_fmt();
            memset(&g_remote_alb, 0, sizeof(g_remote_alb));
            snprintf(g_remote_alb.artist, sizeof(g_remote_alb.artist),
                     "%s", alb.artista);
            snprintf(g_remote_alb.album, sizeof(g_remote_alb.album),
                     "%s", alb.titulo);
            g_remote_n = 0;
            for (int i = 0; i < nfx; i++) {
                Track *t = &g_remote_tracks[g_remote_n];
                memset(t, 0, sizeof(*t));
                snprintf(t->remote_id, sizeof(t->remote_id), "%.*s",
                         (int)sizeof(t->remote_id) - 1, fx[i].id);
                snprintf(t->title, sizeof(t->title), "%s", fx[i].titulo);
                t->number = fx[i].numero;
                t->seconds = fx[i].segundos;
                t->decodable = true;
                t->owner = &g_remote_alb;
                g_remote_n++;
            }
            g_remote_alb.ntracks = g_remote_n;
            g_remote_alb.seconds_total = 0;
            for (int i = 0; i < g_remote_n; i++)
                if (g_remote_tracks[i].seconds > 0)
                    g_remote_alb.seconds_total += g_remote_tracks[i].seconds;
            g_remote_alb.tracks = g_remote_tracks;
            snprintf(g_remote_alb.qb_kapa, sizeof(g_remote_alb.qb_kapa),
                     "%s", alb.id);
            snprintf(g_remote_alb.qb_kapa_url, sizeof(g_remote_alb.qb_kapa_url),
                     "%s", alb.capa);
            if (alb.capa[0]) qobuz_capas_async(&alb, 1, STYLUS_DATA_DIR);
            const Track *ptrs[REMOTE_MAX];
            for (int i = 0; i < g_remote_n; i++) ptrs[i] = &g_remote_tracks[i];
            player_load_list(player, &lib, ptrs, g_remote_n, 0);
            qobuz_abre_limpa();
            break;
        }

        /* ═══ A MESMA MÚSICA, EM LOSSLESS ═══════════════════════════════
           24 sai procurando; 25 toca o que se achou. Duas ações e não uma
           porque no meio há rede: entre apertar e ouvir passam um ou dois
           segundos, e fazer isso no laço de vídeo deixaria a tela congelada
           exatamente no instante em que a pessoa está olhando para ela. */
        case 24: {  /* procurar a versão do catálogo desta faixa */
            const Track *t = player_current_track(player);
            const Album *al = player_current_album(player);
            if (!t || t->remote_id[0]) break;   /* já é da rede: nada a trocar */
            /* O TÍTULO da tag, e o nome do arquivo como reserva. Um acervo
               sem tag nenhuma — que existe, e é metade deste — casaria por
               caminho, e caminho não é nome de música. */
            const char *tit = t->title[0] ? t->title : t->file;
            const char *art = (al && al->artist[0]) ? al->artist : "";
            if (qobuz_casa_async(ui_qobuz_cfg(ui), tit, art, t->seconds) == 0)
                ui_set_casando(ui, true);
            else
                ui_diz_casa(ui, "sign in to Qobuz first — see the ACCOUNT tab");
            break;
        }
        case 25: {  /* a busca voltou com uma faixa: põe ELA no prato */
            QobuzCasamento c;
            int est = 0;
            bool ativo = false;
            qobuz_casa_estado(&c, &est, &ativo);
            if (est != 1 || !c.id[0]) break;

            if (c.album_id[0]) {
                /* Temos o album_id: buscar as faixas em SEGUNDO PLANO.
                   Antes isto chamava qobuz_faixas de forma síncrona, que
                   congelava a tela por 1-2 s e compartilhava um buffer
                   estático com abre_corpo (risco de corrida se o usuário
                   abrisse um disco da loja ao mesmo tempo). Agora reusa
                   qobuz_abre_async: a tela continua viva, e o resultado
                   vem pela ação 28 quando a thread terminar. */
                g_fmt_sessao = c.hires ? QB_HIRES : QB_FLAC;
                QobuzAlbum a;
                memset(&a, 0, sizeof(a));
                snprintf(a.id, sizeof(a.id), "%s", c.album_id);
                snprintf(a.titulo, sizeof(a.titulo), "%s",
                         c.album[0] ? c.album : c.titulo);
                snprintf(a.artista, sizeof(a.artista), "%s", c.artista);
                snprintf(a.capa, sizeof(a.capa), "%s", c.capa);
                qobuz_setflac_pending(g_fmt_sessao);
                qobuz_abre_async(ui_qobuz_cfg(ui), &a);
                /* Pedir a capa agora: quando abre terminar, o deck já
                   pode ter a textura pronta. */
                if (c.capa[0]) qobuz_capas_async(&a, 1, STYLUS_DATA_DIR);
                break;
            }

            /* Sem album_id (busca antiga): carregar só a faixa encontrada.
               Este caminho NÃO chama qobuz_faixas, então não há corrida
               no buffer estático — é seguro manter síncrono. */
            g_fmt_sessao = c.hires ? QB_HIRES : QB_FLAC;

            memset(&g_remote_alb, 0, sizeof(g_remote_alb));
            snprintf(g_remote_alb.artist, sizeof(g_remote_alb.artist),
                     "%s", c.artista);
            snprintf(g_remote_alb.album, sizeof(g_remote_alb.album),
                     "%s", c.album[0] ? c.album : c.titulo);

            g_remote_n = 0;

            {   /* Fallback: carregar só a faixa encontrada. Melhor que
                   silêncio, mesmo que não seja o disco inteiro. */
                Track *t = &g_remote_tracks[0];
                memset(t, 0, sizeof(*t));
                snprintf(t->remote_id, sizeof(t->remote_id), "%.*s",
                         (int)sizeof(t->remote_id) - 1, c.id);
                snprintf(t->title, sizeof(t->title), "%s", c.titulo);
                t->number = 1;
                t->seconds = c.segundos;
                t->decodable = true;
                t->owner = &g_remote_alb;
                g_remote_n = 1;
            }

            g_remote_alb.ntracks = g_remote_n;
            g_remote_alb.tracks = g_remote_tracks;
            g_remote_alb.seconds_total = c.segundos > 0 ? c.segundos : 0;

            {
                snprintf(g_remote_alb.qb_kapa, sizeof(g_remote_alb.qb_kapa),
                         "%s", c.id);
                snprintf(g_remote_alb.qb_kapa_url,
                         sizeof(g_remote_alb.qb_kapa_url), "%s", c.capa);
                if (c.capa[0]) {
                    QobuzAlbum a;
                    memset(&a, 0, sizeof(a));
                    snprintf(a.id, sizeof(a.id), "%s", c.id);
                    snprintf(a.capa, sizeof(a.capa), "%s", c.capa);
                    qobuz_capas_async(&a, 1, STYLUS_DATA_DIR);
                }
            }

            const Track *ptrs[REMOTE_MAX];
            for (int i = 0; i < g_remote_n; i++) ptrs[i] = &g_remote_tracks[i];
            player_load_list(player, &lib, ptrs, g_remote_n, 0);
            break;
        }

        case 26: {  /* o dedo escolheu uma faixa na lista do deck */
            int i = ui_deck_alvo(ui);
            if (i >= 0) player_goto(player, i);
            break;
        }

        default:
            break;
        }
        /* O Vita SUSPENDE sozinho depois de alguns minutos sem toque, e
           suspenso o áudio para: um álbum inteiro nunca chegava ao fim se a
           pessoa não encostasse no aparelho. Cancelar o timer de suspensão é
           uma linha, e nada no app a tinha.

           A tela, ao contrário, DEIXAMOS apagar: é um tocador de música, e o
           OLED aceso é o que come a bateria. Por isso só o timer de suspensão
           é cancelado, e não o da tela. */
        if (player_state(player) == PLAYER_PLAYING)
            sceKernelPowerTick(SCE_KERNEL_POWER_TICK_DISABLE_AUTO_SUSPEND);

        /* A TRAVA DO BOTÃO PS, ligada e desligada pela tela de ajustes.

           Pedir o papel de tocador (MUSIC_PLAYER, no arranque) não bastou. O
           que o ElevenMPV-A faz a mais é segurar o PS_BTN: a Shell não
           suspende quem está com ele travado, e é assim que o som atravessa
           a saída do app. O preço é que o botão PS deixa de levar para a
           tela inicial enquanto estiver ligado — por isso é um interruptor
           que a pessoa alcança, e não uma decisão minha escondida no código.

           Só se chama quando MUDA: `sceShellUtilLock` a sessenta vezes por
           segundo seria falar com a Shell o tempo todo para dizer a mesma
           coisa. */
        {
            static int trava_agora = -1;
            int quer = ui_bg_trava(ui) ? 1 : 0;
            if (quer != trava_agora) {
                if (quer) sceShellUtilLock(SCE_SHELL_UTIL_LOCK_TYPE_PS_BTN);
                else if (trava_agora >= 0)
                    sceShellUtilUnlock(SCE_SHELL_UTIL_LOCK_TYPE_PS_BTN);
                trava_agora = quer;
            }
        }

        drain_done(&ses);
        /* No repouso a tela está apagada e ninguém está olhando: remontar a
           lista recomendada varre a coleção inteira, e fazer isso a cada
           faixa com a tela preta é gastar bateria para desenhar nada. Fica
           marcado como sujo e é refeito quando a pessoa voltar. */
        if (ses.dirty_recs && !ui_resting(ui))
            recs_rebuild(&ses, &lib);
        ui_set_data(ui, ses.plists, ses.nplists, ses.recs, ses.nrecs);
        ui_frame(ui, &lib, player);
        /* A agulha tocou o disco: liberar o som. O player_mute deixou o
           decoder preenchendo o ring buffer em silêncio; agora liberamos.
           Só se ainda estiver tocando: pausar no meio da cerimônia não
           pode vazar áudio por baixo da tela de PAUSED. */
        if (ui_ritual_done(ui) &&
            player_state(player) == PLAYER_PLAYING)
            player_unmute(player);
        /* Atualiza now_playing.txt quando a faixa MUDA — não a cada quadro.
           O arquivo é lido pelo plugin de overlay (se instalado). */
        {
            static const Track *last_track = NULL;
            const Track *cur = player_current_track(player);
            if (cur != last_track) {
                last_track = cur;
                write_now_playing(player);
            }
        }
        /* Persiste o ponto de continuação a cada ~2 s, e SÓ quando ele mudou:
           robusto se o app for suspenso sem saída limpa, sem escrever no
           cartão duas vezes por segundo a noite inteira. O now_playing.txt
           é escrito junto: é o arquivo que o plugin de overlay lê. */
        if ((++frame & 127) == 0 && player_state(player) != PLAYER_STOPPED) {
            static int last_written = -1;
            int now_sec = player_track_seconds(player);
            if (now_sec != last_written) {
                write_resume(player);
                write_now_playing(player);
                last_written = now_sec;
            }
        }
    }

    if (player_state(player) != PLAYER_STOPPED) {
        write_resume(player);
        write_now_playing(player);
    }
    player_destroy(player);
    drain_done(&ses);
    ui_destroy(ui);
    session_free(&ses);
    library_free(&lib);
    /* devolve a porta BGM: presa, a próxima abertura leva
       SCE_APPMGR_ERROR_BGM_PORT_BUSY e o áudio de fundo some sem explicação */
    if (bgm_port_ok) sceAppMgrReleaseBgmPort();
    vita2d_fini();
    sceKernelExitProcess(0);
    return 0;
}
