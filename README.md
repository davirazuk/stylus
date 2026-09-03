# vitastylus — tocador de música para PS Vita

Porte do tocador Stylus (PC/Android) para PS Vita: biblioteca local com
capas, estante de álbuns e deck vinil em âmbar sobre quase-preto.

Parte do desafio "homebrew para Vita". Ainda não é cliente Qobuz —
Qobuz/streaming e scrobbling são marcos futuros; por ora toca música local
MP3 de `ux0:music/`.

## Build

Requisitos (nesta máquina):
- VitaSDK em `~/vitasdk` (`export VITASDK=$HOME/vitasdk; export PATH=$VITASDK/bin:$PATH`)
- vdpm com: libvita2d r188, vitaShaRK 1.5, libpng, libjpeg-turbo, mpg123,
  sdl2

```sh
cd ~/stylus/vita/player
./build.sh
```

Saída: `build/vitastylus.vpk`.

## Instalar no Vita

1. Copie `build/vitastylus.vpk` para o cartão SD2VITA (ux0:).
2. Instale via VitaShell (o arquivo .vpk) ou como `.vpk`/homebrew.
3. Música deve estar em `ux0:music/<Artista>/<Álbum>/*.mp3`.
4. Abra o aplicativo. Use o D-pad para navegar a estante, CROSS para
   selecionar álbum/faixa, triângulo/círculo para ações de tocar.

## Teste fora do Vita (host)

O núcleo (varredura de biblioteca + tags + capas) é testável no PC, sem
VitaSDK, compilando `library.c` + `tags.c` contra o `libmpg123` do sistema:

```sh
cd /tmp/opencode
gcc -O1 -o cover_scan cover_scan.c \
  ../vita/player/src/library.c ../vita/player/src/tags.c \
  -I../vita/player/src $(pkg-config --cflags --libs libmpg123)
./cover_scan "/home/davirazuk/staging-vita/vita-mp3/"
```

Isso valida: agrupamento por álbum, ordenação, e extração de capa embutida
(APIC).

## Capas

O player lê a capa embutida (APIC front cover) dos MP3s. A conversão para
MP3 originalmente não embutia capas; o script em `/tmp/opencode/embed_covers.sh`
injeta (a 500px JPEG) `cover.jpg` da fonte lossless `~/Músicas/Songs` nos
MP3s de `~/staging-vita/vita-mp3/` (o que vai para o cartão), combinando
por nome da pasta do álbum. Renovado antes de ressincronizar o cartão.

## Estrutura

- `src/main.c` — loop principal, vida2d, carga de módulos (NET/HTTP/SSL p/ futuro Qobuz)
- `src/library.c/.h` — varredura recursiva de `ux0:music/`, agrupamento, ordenação, capas
- `src/tags.c/.h` — leitura de ID3v2 (título/artista/álbum/faixa/duração/capa) com mpg123
- `src/player.c/.h` — thread de decodificação (mpg123) → anel → callback SDL2; play/pause/seguinte/voltar/seek
- `src/ui.c/.h` — estante (grade 3×3 com capas) e deck vinil (disco âmbar, sulcos, agulha, halo)
- `CMakeLists.txt` / `build.sh` — pipeline VPK (vita.cmake)

## Estado

- [x] VPK compila sem warnings (1.1 MB) e faz a jogada completa no host
- [x] Biblioteca: agrupamento/ordenação/capas validados (405 álbuns, 339 com capa)
- [ ] Teste de hardware no Vita (cartão está no aparelho; sem via de cópia confirmada ainda)
- [ ] FLAC/OGG decode (o scanner já pega esses arquivos)
- [ ] Playlists
- [ ] Scrobbling (last.fm) e Qobuz/streaming
