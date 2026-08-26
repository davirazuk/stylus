# STYLUS — Android (bit-perfect vinyl)

Port of the STYLUS deck + launcher to Android. The phone is now its own
bit-perfect player like UAPP, with the same vinyl gimmick that makes the
desktop special: radius is time, groove is loudness, needle controls play.

Phone detected: `samsung SM-S938B` (Android 16) on `RQCY204AYDD` — ready for `adb`.

## O que está aqui

* **Bit-perfect** — `Oboe`/`AAudio` exclusive (`SharingMode::Exclusive`,
  `PerformanceMode::LowLatency`), sample rate follows file (44.1/48/88.2/96/176.4/192/352.8/384),
  `PcmFormat::Float`, `replaygain=no`, `volume=1.0` (system mixer bypassed).
  USB DAC via `UsbManager` bulk transfer when `ACTION_USB_DEVICE_ATTACHED` —
  same path UAPP uses, not `AudioTrack` mix.

* **Vinyl** — `VinylRenderer` (OpenGL ES 3.0). **LEIA A LEI DO DESENHO em
  `../CLAUDE.md` §5.5 antes de mexer: NÃO É REALISMO.** O ritual é o analógico
  (raio=tempo, sulco conta faixa, cerimônia SPINUP→CUE→DROP); o desenho é
  irmão do scope: disco de luz no quase-preto, feixe âmbar na agulha (rastro
  que se apaga + ponto quente + bloom), faíscas no `crackle` da gota, halo
  respirando atrás do disco, grão sutil. Sem madeira, sem plinto, sem sala,
  sem braço de metal — isso já foi tentado e reprovado pelo usuário.

* **Launcher** — `Library` ports `vinyl.shelf` + `track_paths` recursive depth 4,
  `library_roots` via `SAF` + `WebDAV` (rclone config imported, or native `OkHttp` WebDAV
  client for `stylus webdav` mounts). Subfolders (Disc 01/Disc 02, `Genre/Artist/Album`)
  counted as one disc, same `N_RINGS` envelope.

* **Needle-sync** — same `Deck` ceremony (`SPINUP 1.1s, CUE 1.05s, DROP 0.55s`):
  ExoPlayer starts `pause=true` during ceremony, `play` on `DROP→PLAY`.
  Closing the vinyl (`onPause`) does **not** stop music (player is `Service`),
  opening (`onResume` with `VIEW` intent) just observes via `Session`.

## WebDAV + subfolders no celular

O mesmo `~/.config/stylus/library` do desktop vira `SharedPreferences` +
`SAF` tree. `stylus webdav ligar http://...` no desktop escreve o
`webdav` conf; o app importa via `adb pull` ou QR, monta com `OkHttp`
(`PROPFIND`/`GET` streaming, cache 64MiB) e soma à estante. Sem copiar:
monta como pasta virtual, `WebDavLibraryRoot` aparece junto com `Music/`.
Subpastas são varridas até 4 níveis — o mesmo `_collect_audio_recursive`
do desktop.

## Build

```bash
# na máquina STYLUS (Arch) ou com cmdline-tools:
cd ~/stylus/android
./gradlew assembleDebug          # APK em app/build/outputs/apk/debug/
adb -s RQCY204AYDD install -r app/build/outputs/apk/debug/app-debug.apk
# bit-perfect test: plug USB DAC, play 96k FLAC, check log: "aaudio: rate 96000 exclusive"
```

Sem SDK aqui, o scaffold compila assim que `cmdline-tools` e NDK estiverem:

```bash
sudo pacman -S android-tools android-sdk-cmdline-tools-latest
sdkmanager "platforms;android-34" "build-tools;34.0.0" "ndk;26.3.11579264"
```

## Estrutura

```
app/src/main/kotlin/io/stylus/player/
  MainActivity.kt     — launcher (shelf) + AGORA + deck view intent
  VinylRenderer.kt    — GL ES 3.0, disc_body/groove/live port
  BitPerfectPlayer.kt — ExoPlayer + AAudio exclusive + USB DAC
  Library.kt          — shelf, webdav, subfolders
  Deck.kt             — ceremony state machine (port of vinyl.Deck)
```

Desktop remains source of truth (`~/stylus` → `stylus-update --stylus`);
Android reads same `vinyl.py` logic ported to Kotlin so radius is time
and loudness is still real measured envelope.

— Boa noite. Quando acordar, `adb shell pm list packages | grep stylus`
  e o disco vai estar no bolso.
