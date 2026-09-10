# Vitastylus — Claude Code project memory

## What is this
PS Vita music player (homebrew). Plays local files from SD card and streams from Qobuz.
Cross-compile: `./build.sh` (VitaSDK at `~/vitasdk`). VPK output: `build/vitastylus.vpk`.
SD card at `/run/media/davirazuk/VITASD/` (maps to `ux0:` on Vita).

## How to test
1. `./build.sh` — builds VPK (uses Ninja; falls back to Make)
2. `./tools/check.sh` — runs all checks (must be 0 failures)
3. Copy VPK to SD card root: `cp build/vitastylus.vpk /run/media/davirazuk/VITASD/`
4. User installs via VitaShell on the Vita (select vpk, press X)
5. **Cannot install remotely.** No FTP access to the Vita.
6. Optional overlay plugin: `cd overlay && mkdir build && cd build && cmake .. -G Ninja && ninja`
   Install `vitastylus_overlay.skprx` to `ux0:tai/` and add to config.txt.

## Status of the bugs (updated 2026-09-05, evening)

Read this before re-diagnosing anything. Several earlier guesses were
**measured and disproven** — repeating them costs a trip to the device.

### 1. Music files not found — **FIXED, CONFIRMED ON DEVICE**
Root cause was `vita_create_self()` without `UNSAFE`: the "safe" HENkaku
sandbox only exposes `ux0:data`, so `ux0:music` returned EPERM. `CMakeLists`
now passes `UNSAFE` (authid `...0001`).
Proof, from the card's own `varredura.txt`: `[x] ux0:music audio=3729`,
388 albums, 507 folders — and `last_session` shows a track playing from
`ux0:music`. **Do not reopen this.**

### 2. Qobuz search returns nothing
**Ruled out, with evidence — do not re-check these:**
- The API and credentials are fine: replaying the exact request `qobuz.c`
  builds, with the card's own keys, returns **HTTP 200 / 14 KB**.
- The parser is fine: running the real `qobuz_busca()` over the real saved
  response extracts **12 albums correctly** (only `ano` comes out 0 — small
  separate bug).
- It is **not the keyboard**. A previous session guessed
  `sceCommonDialogSetConfigParam` (never called → NOT_CONFIGURED) was the
  cause. The user confirms the keyboard has worked for a long time. The call
  was added anyway because it is correct and its rc is now reported, but
  **it was not the bug**.
- It is **not Wi-Fi**. The user confirms PKGj and other online things work.

**The live hypothesis: the device's TLS is too old for these servers.**
Independent evidence from the user: **the Vita's own native web browser does
not work** — the classic signature of a 2012 TLS stack against modern sites.
Measured here:

| server | accepts a legacy cipher (AES128-SHA)? |
| --- | --- |
| `ws.audioscrobbler.com` (last.fm) | **yes** — and last.fm is the one feature that works |
| `www.qobuz.com` | **no** — TLS 1.2 AEAD only (ECDHE-RSA-AES-GCM) |
| `lrclib.net` (lyrics) | **no** — ECDSA cert, ECDHE-ECDSA-CHACHA20 |

`SceHttpSslVersion` in the vitasdk headers stops at `SCE_HTTPS_TLSV1`. That
lines up exactly with which features work and which do not.

### 3. Lyrics never appear
- **Still open.** Square on PLAYING only toggles `u->show_lyrics` — no
  keyboard involved, so the fix above does not cover it.
- **There is not a single `.lrc` file on the card**, so lyrics depend
  entirely on lrclib.net, which serves an **ECDSA** cert and negotiates
  `ECDHE-ECDSA-CHACHA20-POLY1305` — well beyond a 2012 TLS stack. The network
  reason codes now in `net.c` will name the failure when it is exercised.

### 4. PS button kills audio (background playing)
Measured, not guessed:
- `sceAppMgrAcquireBgmPort()` returns **0x00000000 — granted** (from the
  device's own `varredura.txt`). The port is not the problem.
- SDL2's Vita backend picks the port **by frequency**. Disassembling
  `SDL_vitaaudio.c.obj` from `libSDL2.a`: `cmp freq, 47999` →
  `movgt r0,#0` (PORT_TYPE_MAIN) / `movle r0,#1` (PORT_TYPE_BGM). Only BGM
  survives in the background — which is exactly why `BGM_MAX_RATE` is 47999.
- Decoding already runs on its **own pthread**, so a suspended main loop
  starving the ring is ruled out.

What is still unknown is which port the device actually landed on. `player.c`
now appends one line per audio-device open to **`ux0:data/vitastylus/audio.txt`**:
requested vs. obtained rate/channels and `-> porta BGM` or `MAIN`. If it says
MAIN, the rate cap is leaking; if it says BGM and audio still dies, the port
is not the mechanism and the next suspect is the app being terminated rather
than suspended.

### 5. GPU crashes — **FILL RATE, NOT CALL COUNT (2026-09-07). ON THE CARD, UNVERIFIED.**

Every guard in this app counted **draw calls**. The device's own `gpu.txt`
from the 12:34 crash on 07/09 said: 1082 draws (cap 4000), `cap hit no`,
`rejected 0`, `clamped 0`, `off-screen 0`, `tex leaked 0` — everything clean,
and the system went down anyway.

**Calls are not cost.** `deck_backdrop()` drew the cover magnified 2.15×
(500 px stretched to cover 960×544 with slack) **six times** with small
offsets to fake a blur, plus the veil: **seven draw calls, and seven full
screens of alpha-blended, texture-sampled fill**, every frame, on the screen
that crashed. Seven out of a 4000 cap — the guard was looking at the wrong
axis of the problem, which is why a week of "everything is clean" happened.

It also explains the timeline nobody could place: the backdrop only draws
once the cover is *served*, so the crash always came **seconds after entering
the deck**, and it got worse exactly when covers were fixed.

What changed:
- **The backdrop is one pass now.** The cover is box-downsampled to a 64×64
  texture **once**, outside the scene (`blur_faz`/`blur_serve` in `ui.c`), and
  the deck magnifies that in a single `draw_texture_scale` with **linear
  filtering** — magnification *is* the blur, done by the hardware. Background
  fill: **7 screens → 2**. The sampled texture drops from 1 MB to 12 KB, which
  fits the SGX texture cache. It also looks better: six offset copies were six
  ghosts, not a blur.
  The miniature is built **lazily**, only for the album the deck asks about —
  building all 29 cached covers would stutter shelf scrolling to throw 28 away.
- **The frame governor was stuck at its floor since it was written.**
  `gpu_t0` was stamped once per frame, so `dt` measured the whole frame
  *period* — which at 60 Hz is 16.7 ms because `vita2d_swap_buffers` waits for
  vsync. Always > 12. Two frames after boot, lean mode latched **on and never
  released** (`gpu.txt` said `lean mode ON` at 1082 draws, a third of the
  call-count trigger). Cost: grooves 24→12, sheen 34→17 and the spectrum off,
  **permanently, on every screen**, buying nothing. Now it times only
  `start_drawing → end_drawing` — the work we hand the GPU — and the vsync
  wait is excluded.
- **The disc is drawn full again.** `draw_disc(..., true)` was hard-coded on
  the deck. The 07/09 crash happened *in* that reduced mode, so the saving was
  paid and bought nothing; the cost was the one visual the owner cares most
  about. The governor decides now.
- **`gg_px_caixa()` measures fill** (screen-clipped area per primitive) and
  `gpu.txt` reports it as `fill … screens`. `tools/varredura.sh` fails above
  **5.0 screens**; the app's worst frame measures **3.8** (it was **8.8**).
  This is the number that did not exist, and the reason none of this was
  visible from the PC.

**On the card, unverified on device.** Old dumps were moved to
`ux0:data/psp2core-antigos/`, so **any `psp2core-*-GPUCRASH` in `ux0:data`
now is from this build.** If one appears, read `gpu.txt` and look at `fill`
first — that line is why it exists.

### 6. Background audio — **IPC FOR OVERLAY, PLUGIN NEEDS TAIHEN**

- PS button lock remains a manual toggle (user wants to leave the app).
- `write_now_playing()` writes current track to `ux0:data/vitastylus/
  now_playing.txt` on: track changes, play/pause, next/prev, exit.
- `overlay/` contains the **IPC protocol and a reference implementation**
  that requires taiHEN to build (kernel stubs for sceCtrl/sceDisplay
  are not in the standard vitasdk). The overlay draws a bar at the bottom
  with 5x7 bitmap font, 2x title (amber), 1x artist (grey), 4s fade.
- **For the overlay to work**: the user needs taiHEN installed, and the
  plugin must be built with taiHEN stubs. The now_playing.txt IPC works
  regardless — any plugin that reads it can display track info.

## What changed (2026-09-05, night) — the network stack was replaced

`src/net.c` no longer uses **sceHttp** on the Vita. It now uses **libcurl +
OpenSSL**, which vitasdk ships — the *same* code the host path already used.
The `#ifdef __vita__` split is gone; the only platform-specific parts left are
bringing `sceNet` up and checking `sceNetCtlInetGetState` for a link.

Why: `sceHttp` goes through the system `sceSsl`, which tops out at TLS 1.0.
`www.qobuz.com` requires TLS 1.2 with AEAD and `lrclib.net` uses an ECDSA cert
with ChaCha20 — neither is reachable from a 2012 stack. `ws.audioscrobbler.com`
accepts legacy ciphers, which is exactly why last.fm was the one thing that
worked. The user's Vita **native browser also fails**, the same signature in a
program that is not ours.

Verified before shipping:
- links and builds for the Vita; `curl_easy_perform`, `SSL_connect`,
  `SSL_CTX_new` and TLS 1.2 cipher strings are present in the binary;
- **live end-to-end test on the host through the very same `net.c`**: loads
  the card's real `qobuz.config`, hits the real API, returns **12 albums**;
- `lrclib.net` returns real `syncedLyrics` for a track in the collection.

Costs and knock-ons:
- VPK went from **1.7 MB to 3.0 MB** (OpenSSL). Far inside the user's budget.
- `SEGPAD_BYTES` in `src/segpad.c` went **16500 → 21936**. The text segment
  grew and the SCE-area slack fell to 4436; adding less than 4436 would have
  made it *worse* (see the warning in that file). Now 7188.
- `SceHttp_stub`/`SceSsl_stub` dropped from `CMakeLists.txt`; `curl ssl crypto
  z zstd` and four more kernel stubs added, in that order (static link).

**Still unverified on device.** If Qobuz still returns nothing, read
`ux0:data/vitastylus/rede.txt` — a failed search writes the stage and code
there (`no Wi-Fi…`, `could not reach the server`, `the request did not go out
(TLS?)`, `the server answered HTTP 401`).

## SoundCloud got a faucet (2026-09-07)

`soundcloud.c` could already PLAY an `sc:` track — resolve the URL, pick the
progressive stream, refuse the 30-second preview — and there was **no way for
one to get in**. It was plumbing with no tap. `check.sh` says so out loud:
"declarada e nunca chamada".

- **`sc_busca()` / `sc_busca_async()`** hit `search/tracks`. The async wrapper
  is the same dance as Qobuz's, and `PILHA_REDE` / `PRIO_REDE` **moved to
  `net.h`** so a second network module cannot re-derive the `0x80028023`
  illegal-priority bug that once killed every network feature. `net_urlenc()`
  moved out of `qobuz.c` for the same reason.
- **The parser is tested against the real wire response**
  (`tests/fixtures-sc-busca.json`, saved raw with the client_id scrubbed — a
  `json.dumps` round-trip inserts spaces the API never sends, and a parser
  tested on that is tested on the wrong text). That fixture contains the exact
  trap: searching "aphex twin avril 14" returns the **label's official upload
  first**, with `"policy":"SNIP"`, `duration: 30000` and no progressive
  stream. Offering it is worse than finding nothing, because it does not look
  like an error — the song just stops. 7 of 8 results survive the filter.
  Duration comes from `full_duration`; on the snipped track `duration` lies.
- **The item anchor is `"artwork_url"`**, the first key of each result, one
  per track. Not `"kind":"track"` — that also appears once per track but comes
  *after* `id` and `duration`, so an item anchored there loses both. And each
  slice is **wrapped in braces** before the JSON readers see it: `valor_no_topo`
  looks at depth 1 of the first `{` it finds, which without the wrapper is
  `publisher_metadata`. That mismatch is why ids parsed fine (text scan) while
  title/artist/duration came out empty (JSON reader) — two mechanisms, one of
  them reading the wrong object.
- **The UI**: source is a row in SETTINGS (persisted in `last_session` as
  `fonte`), never a shortcut. The search tab is now **SEARCH**, not QOBUZ —
  it lied the moment there were two sources, and "SOUNDCLOUD" does not fit the
  tab bar without pushing the clock off. The service is named on the screen
  instead, on one right-aligned line that also carries format and size: the
  first attempt drew the badge and the format as two independent
  right-aligned blocks and they printed on top of each other
  ("~8 MQOBUZB/track").
- Playing a result is **action 27** in `main.c`: a one-track session through
  the same fake-Album path the store uses, with `remote_id` = `sc:<id>`.

## The disc, made of a record instead of a target (2026-09-07)

**"the vinyl looks like a black circle and the cd a white circle"** — said
after a round of disc work in which every element was present and correct.
The drawing was there; the **contrast** was not. Composed and measured against
the disc body:

| trace | vinyl | CD |
| --- | --- | --- |
| fine groove | 1.27 and 1.53:1 | 1.04 and 1.06:1 |
| track gap | 1.51:1 | 1.13:1 |
| rim | 1.93:1 | — |
| body vs screen | 1.27:1 | — |

Everything between 1.0 and 1.9:1. On the Vita 2000's LCD, whose black is a lit
grey (the reason `tools/contraste.py` exists), that whole band is one colour —
and the PC preview approves it, because a desktop monitor separates 1.3:1
without effort. Same family as the font-size trap.

What changed: the body is **opaque** (the blurred backdrop was showing through
the platter and taking away its read as an object); the rim is **cool and
bright**, not amber, because what draws the edge of a black disc is a
reflection; the grooves alternate **light and genuinely dark** instead of two
alphas of the same light colour (two tones of one colour is not texture, and
on the CD's silver body two whites are one white); and the sheen went from
0.055–0.15 to 0.14–0.34.

**`tools/disco.py` measures the rendered PNG**, not the code: it walks radii
inside the recorded annulus and asks how much neighbouring grooves differ.
Wired into `check.sh`. Validated against synthetic flat discs — a flat black
plate and a flat white plate both score **1.00** and fail; the real vinyl
scores 2.74. The first version of that metric took the brightest and darkest
of the *whole* radius and so measured the rim and the amber ring instead of
the surface: it scored the broken disc **2.74 as well**. A check that passes
the defect it exists to catch is worse than no check, which is why it was
tested against a known-bad image before being trusted.

Two more defects, both found by *rendering the screen and looking at it*
(`tools/preview.sh`), not by reading code:

- **The record label had bites taken out of it**, and so did all eighteen
  ARTISTS portraits. `draw_cover_round()` merges neighbouring scanlines into
  one strip while the half-width stays within a pixel — but the break test
  compared against the **running minimum**, which it also updated every row.
  Going down from the equator each row is a hair narrower, `half` followed it
  down, and the test degenerated into "did *one row* change by a pixel?",
  which only happens near the pole. So the block ran from the equator almost
  to the bottom and was drawn at its **narrowest** width: an 18 px bite out of
  a 62 px label. Above the equator the same loop behaved (`half` never grows),
  which is why only the bottom half was wrong and nobody caught it. The bound
  is now the block's *starting* width, which is what the comment always
  promised.
- **The track rings were evenly spaced**, twenty-four of them, covering the
  disc down to `0.08r` — under the label, invisible, drawn anyway. Even
  spacing is exactly what makes a record read as a radar target, which is the
  complaint the surface-grooves comment quotes in the owner's own words; no
  amount of fine grooving fixes it while the rings that *show* sit on a
  regular grid. They now fall where the tracks actually end, by **duration**
  (`Track.seconds`), mapped onto the recorded annulus (label → rim). A
  six-minute track takes three times the groove of a two-minute one — which is
  the irregular signature you recognise a vinyl by, and it is also readable:
  you can *see* which track is the long one. And the non-playing gaps stopped
  being amber: with twenty-four of them the screen was a bullseye, and amber is
  the colour this app uses to say *here* — saying it twenty-four times says
  nothing. They are surface now; amber marks only the track that is playing,
  which is what the comment beside them always claimed.

- **A dark seam ran across the disc's equator.** `ring_segmentos` emits
  independent `SCE_GXM_PRIMITIVE_LINES` pairs, so neighbouring segments share
  a vertex and it is blended **twice**: on the disc body (32,37,47) a dark
  groove at 0.42 gives (20,23,31) once and (13,15,22) twice — and those were
  exactly the pixel values, which is how it was identified rather than
  guessed. Alone it would be invisible dithering; the problem was that *every*
  ring started at angle zero, so all the doubled vertices stacked at 3 and 9
  o'clock. Rings now start at a phase derived from their radius. The doubled
  vertices still exist — that is the price of one `sceGxmDraw` per ring — but
  they are one-pixel noise instead of a scar. Not a preview artifact: the
  device draws the same pairs.

## The UI rework (2026-09-06)

**The hint bars are gone.** Ten screens each carried their own row of button
chips in the footer. `header_hints()` no longer exists; every shortcut moved,
with none lost, into a two-column **Controls** screen reached from Settings.
A shortcut is learned once; a footer is seen always — that mismatch was the
whole problem, not the number of hints.

**A real Settings tab** (`VIEW_AJUSTES`), d-pad *and* touch: theme, record on
the platter (vinyl/CD), rear touch pad, sleep, controls. All persisted in
`last_session`. The rear pad had been disabled by a `#define` I added — that
fixed one complaint by removing the feature, so it is now the user's switch,
defaulting off.

**Themes.** The palette is runtime (`TEMAS[]`, read through `TEMA.x`), so the
251 existing colour call sites were untouched. Two themes: `amber` (the
original phosphor) and `vita` (the system's blue). Background gradient, disc
body and ~22 loose `RGBA8(255,170,40,N)` literals now derive from the theme
via `AMBER_A(n)` / `ALARM_A(n)` / `COLD_A(n)`. **`tools/contraste.py` now
checks every theme against its own background** — a theme that hides the
artist name on a Vita 2000 LCD is a defect, not a style.

**The CD** is not a recoloured vinyl: silver body, iridescence that runs the
spectrum along the radius (34 arcs, because 7 vanish on a light body), a
punched centre hole redrawn *over* the cover art, no tonearm — a CD player has
none — and instead an optical pickup that tracks along a radius at 6 o'clock.
Reading direction is inverted: stylus rim-inward, laser centre-outward.

**`tools/segpad.py`** computes `SEGPAD_BYTES` from the built ELF. That
arithmetic was done by hand four times and the trap (adding a little makes it
*worse*, because slack is the complement of the remainder) is exactly the kind
that bites at 3am.

**The deck now says `bit-perfect`** when nothing resampled or requantised —
the user asked that question directly, and reading three numbers to infer it
is work the screen can do.

**Lists became list + detail.** The screen was a column of names with two
thirds of black beside it, and "Mix 3 · 8 tracks" says nothing about what Mix
3 *is* — you had to open it and lose your place. Now the selected list's
tracks are shown on the right, titles resolved through the library (falling
back to the filename when a track is gone). It is how the Vita's own Music
app, and the iPod before it, solve the same problem.

**"Listen while gaming" stopped being a report.** It opened with three lines
of diagnostics before saying what to do. It now leads with the two routes —
the Vita's Music app first, because that one the system actually guarantees,
and it has had music to play ever since the shelf was written into the system
database — with the diagnostics compressed to one line that only matters when
the sound does *not* follow.

**The frame geometry had two owners.** `ui.c` and `ui_layout.c` each defined
`PAD_X` / `BODY_Y` / `FOOT_Y`. They agreed until the footer moved, and then
only one of them knew — the symptom being a clipped ninth row with both halves
believing they were right. They now come from `UI_PAD_X` and friends in
`ui_layout.h`. Removing the hint bar also freed 16 px that nothing had
reclaimed.

Preview everything with `./tools/preview.sh ~/Músicas <outdir>` — it renders
every screen, both themes and both media, to PNG without a Vita.

## A varredura (2026-09-06) — o caça-travamento sem aparelho

    ./tools/varredura.sh            completa, sob AddressSanitizer (~20 s)
    ./tools/varredura.sh --rapido   sem sanitizador, para iterar

Aperta TODA tecla e toca TODA parte da tela, em TODA tela, e desenha **depois
de cada aperto**. O `check.sh` a roda inteira.

Ela existe porque "o app travou em menos de 2 minutos" é a queixa mais cara
deste projeto e a única ferramenta que havia para ela era instalar o VPK e
esperar. As fotos do `preview.sh` mostram cada tela EM REPOUSO — e nenhum
travamento acontece em repouso: acontece depois de uma tecla pôr a tela num
sub-estado que o desenho seguinte não aguenta.

Três regras, cada uma paga por uma lição do repositório do desktop:
1. **desenhar depois de cada aperto**, não no fim — a última tecla desfaz o
   estado que a anterior criou;
2. **mais de um quadro por aperto** — a tecla não estoura ao ser apertada,
   estoura no quadro seguinte, quando o desenho vai ler o que ela mudou;
3. **prato cheio E vazio** — sem nada tocando, metade do deck nem é
   desenhada.

Mede três coisas: acesso a memória solta (ASAN — é o que valida o cemitério
de texturas), o CUSTO do pior quadro contra o teto de 8000 chamadas (é
estourar a lista de display que enche o cartão de GPUCRASH), e textura
vazando. **Os dois mecanismos foram conferidos com defeito posto de
propósito**: um uso-depois-de-solto plantado no `cover_tex` sai com a pilha
apontando o arquivo e a linha, e baixar o teto para 2000 acende a tela certa.

**Resultado da primeira volta: nada.** ~12 mil quadros, todas as telas, os
dois temas, as duas mídias, coleção cheia e vazia, filtro sem resultado —
nenhum acesso indevido, pior quadro 3145 de 8000, nenhuma textura vazando.
Ou seja: **o caminho de entrada e desenho não é onde o travamento mora.**
Se ele voltar, os suspeitos que sobram são as threads de rede e o decodificador.

Ela nasceu levando 12 minutos, o que a deixaria de fora do `check.sh` — e
conferência que se pula não existe. Passou a levar 20 s ao parar de
rasterizar glifo que ninguém olha (`avanco()` no `vita2d_host.c`) e ao sair
dos laços de pixel no TOPO de cada primitiva. **Não pintar não é a mesma
coisa que não percorrer**: a primeira versão testava dentro do `blend_px`, os
laços continuavam varrendo cada pixel para chamar uma função que voltava na
hora — 5,6 bilhões de chamadas, e 4% de ganho. Os números medidos são
idênticos com e sem a otimização, que é como se sabe que ela não mentiu.

## O GPUCRASH, DE VERDADE (2026-09-06, 17h) — A REGRA QUE NÃO SE QUEBRA

> **Nada entre `vita2d_start_drawing()` e `vita2d_end_drawing()` pode CRIAR
> ou DESTRUIR textura.** Quem precisa de uma, PEDE; quem serve é o quadro
> seguinte, antes da cena abrir.

O `cover_tex` decodificava o JPEG e criava a textura DENTRO do desenho — isto
é, com uma cena da GPU aberta. Criar textura no vita2d é `sceGxmMapMemory`:
mexer no mapa de memória da GPU enquanto a lista de display está sendo
gravada. No Vita isso trava a GPU, e a trava derruba o sistema.

**Por que só apareceu agora.** Esse caminho existia há meses e quase nunca
rodava: a coleção não tem arte embutida, então não havia JPEG para decodificar.
No dia em que o app passou a ler os 324 `cover.jpg` do cartão, os GPUCRASH
voltaram em minutos — 16:39 e 16:43, com o build de 16:31. Foi ao CONSERTAR as
capas que o defeito apareceu, que é o pior jeito de descobrir uma coisa dessas.

O conserto: `cover_tex`/`qb_capa_tex` só CONSULTAM o cache e anotam o pedido
em `u->pede_capa`/`u->pede_qb`; `capa_serve()`/`qb_capa_serve()` fazem o
trabalho no quadro seguinte, chamados antes do `start_drawing`. A capa aparece
um quadro depois — 16 ms que ninguém vê.

**A conferência que impede a volta**: o shim marca a cena aberta e reprova
qualquer textura criada ou solta dentro dela (`hostgfx_tex_na_cena`).
Conferido plantando o código antigo: acusa **1308 violações**.

### E o custo do desenho, de quebra

`draw_cover_round` e `ring_circle` desenhavam UMA TIRA POR LINHA DE PIXEL, e
cada tira é um `sceGxmDraw`. Um círculo de raio 50 custava 101 chamadas; a
tela de ARTISTS, com dezoito, gastava mil e oitocentas só nos retratos. As
bordas quase não andam perto do equador — só correm perto dos polos —, então
agora linhas vizinhas cujas bordas mudam menos de um pixel viram um bloco só.
ARTISTS: **2704 → 1789**. O desenho é o mesmo (a borda já era serrilhada).

**Ainda por fazer, e é grande:** o `vita2d_draw_array` desenha um vetor
inteiro de vértices em UMA chamada (conferido: ele não copia — os vértices têm
de vir do `vita2d_pool_memalign`). O `ring_segmentos` emite até 96
`vita2d_draw_line` por circunferência, e o disco do deck tem dezenas de
sulcos: daria para trocar milhares de chamadas por dezenas. Não foi feito
junto com o conserto acima DE PROPÓSITO — empilhar uma reescrita do núcleo do
desenho sobre um conserto de crash ainda não confirmado torna impossível saber
qual dos dois falhou, se falhar.

## O GPUCRASH, primeira tentativa (2026-09-06) — leia isto antes de mexer em capa

**O cemitério de texturas NÃO tinha resolvido.** Prova: o cartão do dono tem
`psp2core-*-GPUCRASH` de 5 e de 6 de setembro, e o `varredura.txt` do último
diz `build Sep 6 2026 11:41:20` — um build que já o tinha. Três defeitos, e os
três precisavam cair juntos:

1. **A espera era de 2 quadros e o vita2d é TRIPLO-bufferizado.** Medido
   desmontando o `libvita2d.a` deste SDK: `displayBufferData` tem 12 bytes =
   três ponteiros. Com três buffers a CPU corre até dois quadros à frente, e
   soltar em N+2 é soltar na borda. `TEX_ESPERA` agora é 4.
2. **`COVER_CACHE` era 10 e a tela de ARTISTS desenha 12 capas** (6×2), a HOME
   desenha 11 (1 + 2×5). Um cache menor que a tela DEBULHA: a cada quadro
   despeja uma que acabou de ir para a GPU. Agora ele SAI dos números das
   telas (`COVER_NA_TELA + 4`), que moram todos juntos no topo do ui.c.
3. **O desempate do LRU escolhia cego.** `age < age[victim]` a partir de zero:
   com todas as idades IGUAIS (todas desenhadas no mesmo quadro) nenhuma
   comparação é verdadeira e a vítima fica sendo o slot 0 — justamente uma que
   está na tela. Agora um slot com `age == u->clock` nunca é vítima.

**Por que a varredura passava verde por cima disso**: a coleção de teste deste
PC não tem UMA capa (nem arquivo, nem arte embutida — o `album_load_cover` só
lê arte embutida), então o cache nunca enchia e aquele código nunca rodava. O
cartão do aparelho tem 339 capas guardadas. É a lição de sempre na forma mais
cara: **tela medida vazia não é tela medida.**

O que fechou o buraco:
- `tools/capas-de-mentira.sh` monta 24 discos com arte embutida (ffmpeg), e a
  varredura faz uma passada só neles — mais discos do que qualquer tela
  desenha de uma vez, que é a condição em que o cache quebra;
- o shim agora guarda em que quadro cada textura foi desenhada e **reprova
  quem for solta a menos de 3 quadros disso** (`hostgfx_solta_cedo`). A regra
  do aparelho conferida no PC, sem GPU nenhuma.

**Conferido com o defeito posto de propósito**: voltando `COVER_CACHE` a 10,
`TEX_ESPERA` a 2 e o despejo cego, a varredura acusa **82 texturas soltas cedo
demais**. Com o conserto, zero.

## O 2º plano: o interruptor estava a duas abas do problema (2026-09-06)

O `last_session` do cartão dizia **`bg_trava=0`**. O `varredura.txt` do mesmo
dia dizia plugin instalado, listado no `*KERNEL`, e o `audio.txt` mostra 24
aberturas de áudio, TODAS `-> porta BGM`. Ou seja: as três coisas que se
mediam estavam certas, e o som morria assim mesmo — porque a trava do botão
PS, que é o que impede a Shell de suspender o app, nunca foi ligada.

Ela existia, nos AJUSTES, com um rótulo correto. E a tela que explica o
assunto — LISTEN WHILE GAMING — não a oferecia. Agora ela está lá, com o
estado à vista, `[]` ou o dedo, e entrou na linha de diagnóstico: com a trava
desligada a linha inteira fica em ALARME, porque com ela desligada nada
funciona.

## A capa estava no cartão e o app não a lia (2026-09-06)

**324 arquivos `cover.jpg` de 500x500, dentro das pastas dos discos, e a
estante inteira desenhava capa GERADA.** O `album_load_cover` só sabia ler
arte EMBUTIDA no áudio, e esta coleção quase não tem.

Quem os escreveu foi o `tools/musica-para-o-vita.py`, para o app Música da
Sony. Duas metades do mesmo sistema: uma escrevendo, a outra sem saber ler.
É a família do `[module/webdav]` da polybar que ninguém desenhava e do
`set_text` que ninguém chamava — o defeito só existe na RELAÇÃO entre as
duas, e ler um arquivo por vez não pega.

Agora o arquivo vem PRIMEIRO e a arte embutida é reserva: é mais barato (uma
leitura contra abrir os metadados de até oito faixas) e quem pôs um cover.jpg
na pasta escolheu aquela imagem. Nomes numa lista só (`CAPA_NOMES`), comparada
sem maiúscula — o lado desktop teve CINCO listas discordando e a que ninguém
olhava não achava nada. `back.jpg` e `albumartsmall.jpg` ficam de fora de
propósito: são o que um "pega a primeira imagem em ordem alfabética" pegaria.

Medido na coleção do cartão: **de ~15 discos com capa para 339 de 388.**

O `capas-de-mentira.sh` agora faz metade dos discos com capa só em ARQUIVO e
metade só EMBUTIDA — são dois caminhos e os dois precisam rodar na varredura.

## O TEXTO "LOW RES" (2026-09-06, noite) — E POR QUE O PREVIEW NUNCA VIU

Queixa do dono: *"the text shows fine but its like, low res and you cant read
properly"* — e todo PNG do preview saía limpo.

**O Vita não rasteriza no tamanho que se pede.** O `vita2d_load_system_pvf`
chama `scePvfSetCharSize` UMA vez, no load — 10,125 pt a 128 dpi = 18 px
exatos —, guarda os glifos num atlas nesse tamanho, e o `vita2d_pvf_draw_text`
só ESCALA aquela textura. Todo texto do app é um bitmap de 18 px reamostrado.

E o filtro, no `texture_atlas_create` deste `libvita2d.a` (desmontado, não
lembrado):

    vita2d_texture_set_filters(tex, 0, 1)   ->  min=POINT, mag=LINEAR

Ampliar é suave. **REDUZIR é vizinho-mais-próximo** — e os três tamanhos mais
usados são reduções: 13, 15 e 17 px a partir de 18. A 13 px isso descarta 28%
das linhas e colunas do glifo; o traço horizontal de um "e" some. Não é
"borrado", é a letra perdendo pedaço.

**Conserto aplicado** (`pvf_filtro_linear` no ui.c): põe LINEAR nos dois
sentidos. Os deslocamentos saíram do desmonte deste `.a` —
`generic_pvf_draw_text: ldr r3,[r6,#8]` dá `vita2d_pvf + 8 = atlas`, e
`texture_atlas_create: str r0,[r4,#0]` dá `atlas + 0 = textura` — e ainda
assim a leitura é CONFERIDA (largura plausível) antes de valer. Noutro vita2d
a conferência falha e nada acontece.

**O preview foi consertado junto, e isso importa mais.** Ele rasterizava no
tamanho final com FreeType e saía nítido em qualquer escala: aprovava um texto
que o aparelho reprovava. Agora ele rasteriza SEMPRE em 18 e escala o bitmap
com a mesma bilinear — e o `text_width` mede em 18 e multiplica, que é o que o
`vita2d_pvf_text_width` faz lá. As larguras mudaram um pouco, e as de agora
são as do aparelho: é por largura que a UI decide o que cortar.

É a TERCEIRA vez num dia que uma foto aprovou o que o Vita reprova (as outras
duas: a coleção sem capa, e a navegação errada até a tela de Controls).

**O CONSERTO COMPLETO, ainda por fazer:** rasterizar em cada corpo, com um
atlas por tamanho — `scePvfSetCharSize` por fonte, `scePvfGetCharGlyphImage`
num atlas próprio. São ~250 linhas escritas ÀS CEGAS num aparelho que não dá
para depurar, e por isso não foram feitas junto de um conserto de crash ainda
não confirmado. Com LINEAR o texto pequeno fica MOLE; rasterizado no corpo
certo ele fica nítido. O preview honesto agora mostra a diferença.

## A LIVEAREA (2026-09-06, noite)

`tools/livearea.py` gera os três PNGs (bg 840x500, o portão 280x158, o ícone
128x128) a partir da MESMA paleta do app.

A arte anterior era um TOCA-DISCOS — prato, braço de metal, cabeçote, cápsula
— e a lei do desenho deste projeto recusa os quatro pelo nome: o desenho é
FÓSFORO, e o braço é o FACHO. Agora é o disco de luz, com os intervalos das
faixas (o que se conta de longe) e um facho cuja luz mora na ponta.

Três coisas que custaram tentativa:
- **Paleta de 8 bits é OBRIGATÓRIA**: o instalador recusa com 0x9010113D em
  qualquer outro modo. A primeira versão saiu em RGB e o `check.sh` pegou —
  o VPK não teria instalado. O pontilhado de Floyd-Steinberg resolve o
  bandeamento que 256 cores causariam num gradiente.
- **Desenhar em 4x e reduzir**: o `ellipse` do PIL com `width=1` num raio
  grande sai serrilhado a ponto de parecer TRACEJADO. E a espessura tem de
  ser `S` px no desenho grande para virar 1 px no fim — senão os anéis somem.
- **A densidade sai do tamanho FINAL**: oito intervalos num disco de 230 px
  são um disco; num ícone de 47 px são uma mancha laranja.

## O REWORK DA ESTANTE (2026-09-06, noite)

**Oito discos de 388 eram quarenta e nove páginas.** A grade era 4×2 porque o
CARD era grande — moldura, sombra em três camadas, borda de seleção e três
linhas de texto — e o card era grande porque não havia capa: um quadrado vazio
precisa de decoração para parecer alguma coisa.

Com arte em 339 dos 388, vale a lição do Sonara: **a arte É o card**.

- **6×3 = 18 por página** (22 páginas em vez de 49), capa de 97 px.
- **Sem moldura**: saíram sombra, fundo e as quatro bordas — nove retângulos
  por disco, 162 por tela, só de decoração. E dezoito caixas com sombra formam
  um MURO, que é o contrário do que uma estante existe para fazer.
- A seleção é um halo âmbar atrás da capa, um filete de 2 px sob ela e o nome
  em âmbar. Legível sem caixa nenhuma.
- **O disco só sai da capa no MARCADO.** Com quatro por tela o vinil espiando
  atrás de cada capa era a assinatura; com dezoito eram dezoito pratos pretos
  brigando com dezoito artes. Agora ele significa alguma coisa: o disco que
  você está escolhendo é o que começa a deslizar para fora.
- **Capa e rótulo partem da mesma borda esquerda.** Centrar a capa (que é
  limitada pela ALTURA da fileira, não pela coluna) e alinhar o texto nela
  fazia "Arctic Monkeys" virar "Arctic…" em metade da tela.

Custo do quadro: **3214 → 894 desenhos**, com mais que o dobro de discos.

`label2_dy` saiu do `UiShelfGeom`: o card tem duas linhas de rótulo agora, e
um campo escrito para valer o mesmo que outro é estado morto. O teste de
geometria foi ajustado junto.

## A LISTA DE FAIXAS DO DECK VIROU ALVO (2026-09-06, noite)

Ela era **só desenho**. Para chegar à faixa 20 de um show de 35 eram dezenove
apertos de [direita] — cada um abrindo e fechando um arquivo — com as faixas
escritas ali do lado do disco. É a família do `[module/webdav]` que a barra
desenhava e ninguém acionava.

`player_goto(p, idx)` é novo (havia só `next`/`prev`); o desenho anota onde
cada linha caiu (`deck_lin_y`/`deck_lin_i`) e o toque lê daqui — um dono só
para a geometria, como em toda outra lista deste arquivo. Ação 26.

## Um defeito no PREVIEW que vinha mentindo

Ele navegava até a tela de Controls com DOIS [baixo], e a lista de ajustes tem
SEIS linhas: o [X] caía em "rear touch pad". A foto chamada `8e-controles`
mostrava os AJUSTES — e de quebra o preview LIGAVA aquele ajuste a cada
execução. Já tinha acontecido neste arquivo com as abas, e a lição é a mesma:
uma foto que mente é pior que foto nenhuma.

## A leva de visuais (2026-09-06, tarde)

Tudo isto só apareceu porque o preview passou a rodar contra a coleção DO
CARTÃO (`./tools/preview.sh /run/media/.../VITASD/music <out>`), que tem 324
capas — a do PC não tem nenhuma. Mais uma vez: tela medida vazia não é tela
medida.

- **ARTISTS mostrava 113 "artistas" e metade era DATA** — "1998-04-02 -…",
  "2013-10-26 -…". O artista saía do primeiro segmento do caminho, e neste
  acervo ele é `DATA - ARTISTA - TÍTULO`. Agora o `set_artist_album` usa o
  mesmo `pula_data` do `album_display` e pega o meio. 113 → 109, zero datas.
- **A grade de ARTISTS virou 6×3.** Com duas fileiras a célula tinha 215 px
  para um círculo de 100: faixa morta entre as fileiras e no rodapé.
- **JUST ADDED na home.** `Album.mtime` é novo e é gravado no índice, então o
  `CACHE_VER` subiu para 2 — o índice velho é recusado uma vez e a estante
  revarre. De propósito: um índice sem a data faria a fileira mentir.
- **O tamanho das capas da home sai do espaço que sobra.** Três faixas com 86
  px estouravam a tela em 130. E o número de faixas COM CONTEÚDO varia (uma
  seção vazia colapsa para 26 px), então a conta é sobre isso.
- **A contagem da coleção foi para o vazio ao lado do CONTINUE**, liberando os
  48 px que faltavam para a terceira faixa caber.
- **A pílula principal das listas ficou CHEIA** e o ícone de cada lista virou
  a capa do primeiro disco dela — eram quatro discos genéricos idênticos.
- **Buscas recentes na loja**, em `buscas.txt`, com o dedo ou esquerda/direita.

E duas coisas no PREVIEW, que é o que torna tudo acima possível de ver:
- ele roda dentro de uma caixa de areia `ux0:` (`$OUT/ux0-sandbox`), então
  `STYLUS_DATA_DIR` — que é relativo no PC — passa a existir: dá para
  fotografar a loja COM conta e COM buscas recentes, e não só a tela de
  primeira vez;
- `ui_qobuz_finge_conta()` impede a tela da loja de reler o config por cima.

## A pílula GET FLAC (2026-09-06)

Na linha do sinal do deck: acha a MESMA música no Qobuz e toca a versão
lossless no lugar do arquivo do cartão. `qobuz_casa_async` busca por faixa e
pontua os candidatos — título 30%, artista 25%, **duração 45%**, porque
título e artista batem em toda versão da mesma música (estúdio, acústica,
quatro ao vivo, um cover) e é a duração que separa a GRAVAÇÃO. Abaixo de 60
de 100 ele diz que não achou e conta o que chegou perto. Ações 24 (procura) e
25 (toca) no `main.c`; o resto do encanamento já existia — uma `Track` com
`remote_id` vira URL pelo resolvedor.

## O GPUCRASH, terceira volta (2026-09-06, noite) — O QUE FOI MEDIDO E DESCARTADO

Dez GPUCRASH num dia, com builds que já tinham os consertos das duas voltas
anteriores. Antes de mexer em qualquer coisa, **leia isto: metade dos
suspeitos já foi eliminada com prova.**

**Como ler um dump** (`zcat X.psp2dmp > X.core` — é gzip sobre um core ELF):
as notas trazem `MODULE_INFO` (entradas de 0x88, nome em +0x24, base do
segmento em +0x58 — **muda a cada arranque**, some com o `0x81000000` do ELF
para achar o deslocamento), `THREAD_INFO` (entradas de 0xc8: +4 uid, +8 nome),
`THREAD_REG_INFO` (+8 = r0..r12, sp, lr, pc, cpsr), `MEM_BLK_INFO` (entradas
de **0x48**: +8 nome, +0x2c base, +0x30 tamanho) e `BUDGET_INFO` (por
partição: +48 total, +52 livre). Symbolizar = varrer a pilha por palavras no
texto com o bit Thumb aceso, passar pelo `addr2line -e build/vitastylus` —
**só vale contra o binário DAQUELE build**, e reconstruir apaga o de antes.

O que os dumps disseram:
- A thread principal morre parada no `vita2d_swap_buffers` dentro do
  `ui_frame`: a CPU **espera** uma GPU que já travou. Diz que morreu, não diz
  desenhando o quê.
- **NÃO é falta de memória.** Dump de 20:54: CDRAM **74 MB livres de 112**,
  RAM do jogo 188 de 256. De quebra confirma o triplo buffer (três blocos de
  2 MB) e que cada capa custa 768 KB.
- **NÃO é volume de desenho.** Pior quadro de TODAS as 11 telas: **1.141**.
- **NÃO é o palpite de offset do `pvf_filtro_linear`.** Desmontado o
  `vita2d_pvf.o`: o atlas ESTÁ em `((void**)f)[2]` (`str r0,[r5,#8]`). O
  palpite está certo.
- A queda de 20:54 foi **14 s depois do arranque** — não é desgaste de uso.

**O buraco que ninguém tinha visto**, e é embaraçoso de tão simples: o
`coord_ok` existia e era chamado em **2** dos 148 desenhos. O
`vita2d_draw_rectangle` — **127 dos 148** — não era conferido em lugar nenhum,
nem no app nem no shim do PC (o detector do host olhava só `draw_line` e
`draw_array`). Conferir a primitiva rara e não a comum é o mesmo erro do
contador que não contava glifo.

O que foi feito:
- **A porteira da GPU** (topo do `ui.c`): `#define` desviam as 148 chamadas
  para wrappers que recusam NaN/absurdo antes do sceGxm, CONTAM, e guardam a
  primeira por extenso. Mais um teto de 12.000 desenhos por quadro.
- `arco()` fazia `if (r <= 0) return;` — **não pega NaN** — e alimenta
  `vita2d_draw_array` (vértices crus). `ring_segmentos` conferia o raio e não
  o centro. Os dois fechados.
- `tex_matar` com a fila cheia chamava `vita2d_free_texture` **na hora**, e
  quem chama esse caminho (`qb_capas_esquece`) roda DENTRO da cena. A fila
  passou de 32 para 128 e o transbordo VAZA (contado): 768 KB perdidos valem
  menos que desmapear memória de GPU com a lista de display aberta.
- **`ux0:data/vitastylus/gpu.txt`**, a caixa-preta: escrita ANTES do desenho,
  a cada troca de tela e a cada ~5 s. Diz que tela ia ser desenhada, o pior
  quadro, quantas coordenadas foram recusadas e qual foi a primeira.
  **É o primeiro arquivo a ler no próximo crash.**
- `ok_porteira` no `desenho_test.c` empurra NaN de propósito e exige 4 recusas
  / 0 desenhos. **Pegou um defeito real na primeira rodada**: a função de
  teste estava ACIMA dos `#define` e chamava o vita2d cru. A diferença entre
  estar protegido e não estar era a ORDEM de duas linhas, e não aparece lendo.

## O qobuz-dl saiu do caminho (2026-09-06, noite)

`tools/qobuz_api.py` é novo e fala a API do Qobuz sem o pacote `qobuz-dl`. O
`qobuz-vita.py` e o `qobuz-chaves.py` usam ele.

Veio de ler o **SpotiFLAC** (github.com/spotbye/SpotiFLAC), e a conclusão
importante é o que **não** há para copiar:
- O backend Qobuz dele faz **exatamente** o que o `src/qobuz.c` já faz —
  mesma URL, mesmo `X-App-Id`, mesma assinatura
  `md5(caminho + params ordenados + ts + segredo)`. Conferido lado a lado.
  **Não há nada a trocar no aparelho.**
- Tidal e Amazon Music **não saem de API pública**: saem de servidores-relé do
  próprio projeto, com o endereço em AES-GCM dentro do binário
  (`backend/community_endpoints.go`). Contas de outra pessoa, num servidor que
  some. Não entra num app em C que roda num Vita.
- Spotify, no SpotiFLAC, é **só metadado**. SoundCloud e YouTube não existem
  lá — são extensões do app Flutter do celular.

O que valeu copiar: **app_id e segredo saem do tocador web do Qobuz**
(`open.qobuz.com/track/1` → `main.js` → `app_id:"…",app_secret:"…"`), com
cache de 24 h. Medido ao vivo: app_id 712109809. Só o **token da conta**
continua vindo do config, porque identifica a pessoa.

E o **casamento por ISRC** (`deezer_isrcs`), que é a arquitetura de verdade do
SpotiFLAC: procurar num catálogo de busca boa e trazer o mesmo fonograma do
Qobuz. Vale demais — a busca do Qobuz por "weird fishes arpeggi" devolve
**cinco covers e nenhum Radiohead**; via Deezer→ISRC→Qobuz o original é o
primeiro resultado.

**Não há par de reserva embutido no código**: o `check.sh` reprova hexadecimal
de 32 dígitos versionado, e está certo — além de que uma reserva que só serve
quando não há rede é inútil, porque sem rede a chamada seguinte também falha.

## Mais de uma fonte de streaming (2026-09-06, noite)

`player.c` nunca conheceu o Qobuz: ele chama um **resolvedor injetado**,
`g_resolve(ud, remote_id, url, &kind)`. Isso já era o trilho; faltava a marca
da fonte. Agora o `remote_id` leva um prefixo — `sc:123456` — e o
`resolve_remote` do main.c despacha. **Id sem prefixo continua sendo Qobuz**,
então nada do que existe muda. A marca vai no id e não num campo novo: um
campo novo teria de ser preenchido, copiado e gravado em toda passagem de uma
Track (estante, índice, playlist, cache), e o lugar esquecido tocaria a música
errada.

**SoundCloud entrou primeiro porque não pede nada novo ao aparelho.** Medido
extensão por extensão:

| fonte | o que entrega | dá para tocar no Vita? |
| --- | --- | --- |
| Qobuz | arquivo HTTPS assinado | já funciona |
| SoundCloud | MP3 128 progressivo em `sndcdn.com` | **sim, limpo** |
| YouTube | o Cobalt devolve `.opus`/`.m4a`/`.mp3` | sim, precisa de uma instância Cobalt |
| Tidal | manifesto BTS dá FLAC direto; ou DASH+XML | metade — e o auth passa por `api.zarz.moe` |
| Deezer | cifrado em Blowfish (`g4el58wc0zvf9na1`, CBC) | só com Blowfish no app |
| Amazon | MP4 cifrado (CENC/AES-CTR) + `eac3`/`ac4`/**flac** | o flac é possível; eac3/ac4 não têm decodificador |

O `src/soundcloud.c` faz três chamadas HTTPS e lê JSON — o `net.c` e o
`qobuz_json_str` já faziam as duas coisas. **Conferido ao vivo com o MESMO
código que o Vita roda** (`sc_url` compilado no host contra a API de verdade):
devolve uma URL assinada de `cf-media.sndcdn.com` terminada em `.mp3`.

**A armadilha, e o teste que a prende:** a resposta real de uma faixa traz
QUATRO transcodificações, TRÊS delas HLS — e **uma das HLS se anuncia como
`audio/mpeg`**. Quem procurasse "audio/mpeg" entregaria uma PLAYLIST ao
decodificador de MP3, e a falha teria cara de rede caída. O
`tests/soundcloud_test.c` roda contra a resposta GRAVADA de uma faixa real e
exige: progressiva, nunca HLS, nunca prévia de 30 s, MP3 antes de Opus.

O `client_id` vem do cartão (`soundcloud.config`, escrito pelo
`tools/soundcloud-chaves.py` a cada `pro-cartao.sh`), pela mesma conta que fez
as chaves do Qobuz virarem arquivo: ele está publicado no JavaScript do site e
raspá-lo é baixar 1,2 MB e varrer — trabalho de PC, não de aparelho sem
depurador.

**O QUE AINDA FALTA, e é a metade que o dono vai notar:** nada no aparelho
PRODUZ um id `sc:` ainda. O resolvedor está de pé e testado, mas não há tela
de busca do SoundCloud — hoje o caminho é baixar pelo PC
(`tools/spotiflac.js` ou `tools/soundcloud_api.py`) e a faixa vira arquivo no
cartão. A tela é o próximo passo, e é onde o `qobuz.c` serve de molde.

## Still open

- **Background audio.** The BGM port + MUSIC_PLAYER shell lock handle
  background audio. `now_playing.txt` IPC is written on all state changes.
  **The overlay plugin needs taiHEN to build** (kernel stubs for sceCtrl
  and sceDisplay). Test on device: does music survive PS → another app?
- **GPU crashes.** Ver a seção "terceira volta" acima. A porteira fecha a
  classe NaN/absurdo e a caixa-preta nomeia a tela. **Falta confirmar no
  aparelho**: os dumps velhos foram movidos para
  `ux0:data/psp2core-antigos/` (cópia em `~/backups/psp2core-2026-09-06/`),
  então QUALQUER `psp2core-*` novo em `ux0:data` é um crash desta versão — e
  aí o `gpu.txt` diz em que tela.
- **DECK ENXUTO ao entrar (2026-09-07).** Todo GPUCRASH deste aparelho caiu
  no PRIMEIRO quadro do deck após uma troca de tela (dump de 23:16 de 6/9:
  frame 47, `came from ARTISTS`, plugins outros desligados, contagens todas
  limpas). O exame exaustivo absolveu o desenho: vértices só do pool
  mapeado, coordenadas conferidas (0 recusas), janelas de textura aparadas,
  serve fora da cena, sem criar/destruir textura na cena, capa do Muse 500×500
  normal, pool de 1 MB com folga. Os endereços do bloco GXM
  (`0x4066B9C8`/`0x4066BB00`) são do lado GPU (zero ocorrências como u32 nos
  três cores). SUSPEITO QUE SOBROU: a lista de display da tela mais pesada
  do app (~1081 chamadas) entrando na troca — a família do overlay de
  volume que já estourou a lista antes. CONSERTO: os DOIS primeiros quadros
  do deck agora desenham só o essencial (`u->deck_enxuto = DECK_ENXUTO_QUADROS`,
  armado em `ui_frame` quando a tela não é o deck, consumido no `draw_deck`):
  fundo, corpo do disco, capa no rótulo, título/artista — ~40 chamadas no
  lugar de ~1100. Invisível (32 ms) e medido: a varredura continua vendo o
  deck cheio (pior quadro 1141). O `gpu.txt` ganhou a linha `deck entry`.
  Build `Sep 7 2026 01:27` no cartão. **Precisa da confirmação no aparelho:
  entrar no deck vindo da ARTISTS/estante era o gatilho.**
- **O DISCO VOLTOU A LER COMO OBJETO (2026-09-07).** Queixa do dono: o disco
  era "just a black circle" (vinil) e o CD "a white circle". Causa: o deck
  roda com `gpu_safe` PERMANENTE, que cortava o lustro do vinil a 4 arcos —
  no LCD eles sumiam — e todo o resto era desenhado leve demais para sobreviver.
  Em `draw_disc`: corpo do vinil 0,09→0,15; silhueta nova (sombra interna no aro
  + lábio claro na borda) para os dois; sulcos mais pesados (0,13/0,22); vãos de
  faixa 0,11→0,26; lustro do vinil 0,055+0,095·f e CONTINUA com 7 arcos em modo
  enxuto (custa 7); CD ganhou faixa curva de sombra perto do aro e um glint
  especular (2 arcos). Custo: deck 1018→1023, CD 838→846. E o teste do
  `indice_test.c` tinha `fprintf(..., RAIZ ...)` sem `%s` (variável, não macro) —
  bug novo num merge que os binários velhos de `/tmp` mascaravam; o `check.sh`
  passou a compilar de verdade e o defeito apareceu. Build `Sep 7 2026 12:30`
  no cartão.
- **Lyrics fallback.** `fetch_online()` only accepts `syncedLyrics`; tracks
  that only have `plainLyrics` will still show nothing. Worth a fallback.
- **`ano` is always 0** in Qobuz search results — small parser gap.

## A leva do dia 08/09 (deck, travas e LCD)

**O crash ao entrar no deck, enfim com assinatura.** Dois dumps novos caíram
no PRIMEIRO quadro cheio depois da troca (frame 107 vindo da ARTISTS com
fill 3.6, frame 195 vindo da SEARCH com fill 4.0 — nos dois o anterior saiu
"whole frame OK"). Com triplo buffer a GPU ainda mastiga as listas velhas
quando o degrau 40 → 1050 chamadas chega: lite-2 não bastava. Agora a entrada
é em rampa, `DECK_ENXUTO_QUADROS` 2 → 4 (2 lite + 2 médios: disco e agulha,
sem lista/espectro/textura de fundo), e o véu do backdrop vai ASSADO na
miniatura 64×64 (escurecer e ampliar comutam — pixel idêntico, uma tela cheia
a menos por quadro). Fill pior: 3.7 → 2.7. **No aparelho, não verificado.**

**O crash "depois de pausar" era o WAKE se matando sozinho.** O caminho de
reinicialização pós-suspensão liberava fonte e texturas do cache DEPOIS do
`vita2d_fini()` — que já as destruiu. Double-free: corrompe o heap e a queda
vem quadros depois, longe da causa (pausou → largou → tela dormiu → ao voltar
morreu "do nada"). A fila de mortos e o cache do Qobuz tinham a mesma forma
adiada. Agora o wake só ESQUECE os ponteiros e reconstrói. De quebra: pausar
no meio da cerimônia vazava áudio sob o PAUSED (o unmute do fim do ritual só
vale se ainda estiver tocando).

**R1+L1 era DOIS recursos.** A trava de input (nível, sem debounce no host)
engolia o "apaga a tela" do deck e, travado, o atalhos_test girava para sempre
(13 min a 100% — não era lento, era laço infinito). Agora é por ORDEM: R1+L1
apaga a tela, L1+R1 trava (por borda, sem repetição), os dois na tela de
Controls, e o teste prende trava/destrava.

**O disco, pela TERCEIRA vez, e agora pelo LCD.** Campo denso de anel fino
vira cinza médio no olho/LCD (a média ótica come o contraste) — 96 anéis
"ricos" chegaram como "a mesma coisa cinza". E os vãos de faixa (24× 1.8px a
0.80) cobriam metade do prato: eram ELES o cinza-azulado, não o corpo. Agora:
corpo preto total, 10 sulcos claros espaçados, vão fino (1px) e apagado (só o
que toca vai âmbar forte), lustro contido. CD espelhado (prata clara, sulco
escuro). `tools/disco.py` mede a silhueta no MÁXIMO (corpo, aro) — vinil preto
reprova corpo-vs-fundo por desenho; o aro é o separador. Conferido contra
chapa sintética sem aro: reprova nas duas, como deve.

## How to debug without a terminal
There is no shell/terminal on the Vita. To add debug output:
1. Write to a file in `ux0:data/vitastylus/` (e.g., `debug.log`)
2. Use `fopen/fprintf/fclose` in the code
3. User reads the file via VitaShell after testing
4. Remove debug code before shipping

## Architecture quick reference
- `src/main.c` — entry, module loading, BGM port, event loop
- `src/player.c` — SDL audio, decoder management, Goertzel spectrum
- `src/decoder.c` — mpg123/libFLAC/Vorbis/Opus/WAV decoders, resampler
- `src/qobuz.c` — Qobuz API (search, download, streaming, auth)
- `src/ui.c` — all screens (shelf, playing, qobuz, playlists, recs, account, handoff)
- `src/net.c` — HTTP (sceHttp on Vita, libcurl on host)
- `src/lyrics.c` — local .lrc reader + lrclib.net fetch
- `src/library.c` — music scanner, track/album structs
- `src/lastfm.c` — last.fm scrobbling
- `src/fonte.c` — network streaming source (ring buffer via libcurl)
- `src/sides.c` — disc side splitting logic
- `tools/check.sh` — all validation checks

## Git status
Branch: `fusao`. 1500+ lines of uncommitted changes across 24+ files.
All comments in Portuguese (Brazilian), terse/philosophical style.
Text the user sees is in English.
All code comments are in Portuguese.
