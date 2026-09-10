cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED CMAKE_TOOLCHAIN_FILE)
  if(DEFINED ENV{VITASDK})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VITASDK}/share/vita.toolchain.cmake" CACHE PATH "toolchain file")
  else()
    message(FATAL_ERROR "Please define VITASDK to point to your SDK path!")
  endif()
endif()

project(vitastylus C)
include("${VITASDK}/share/vita.cmake" REQUIRED)

set(VITA_APP_NAME "Stylus Vinyl")
set(VITA_TITLEID  "STYS00001")
set(VITA_VERSION  "01.00")
set(VITA_TITLE  "Stylus")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -std=gnu11 -Wall -Wextra -O2 -ffunction-sections -fdata-sections")
# max-page-size=8192: a área SCE (module info + tabelas de import) é gravada
# na folga entre o fim do segmento de código e o início do de dados, e essa
# folga não passa do alinhamento de segmento. Com 4096 o teto era 4096 — e ao
# ganhar rede (SceNet, SceNetCtl, SceHttp, SceSsl) e teclado (SceIme) as
# tabelas passaram a pedir 4948 bytes. Não era questão de regular o
# enchimento: NÃO CABIA, em nenhum ajuste. Dobrar a página dobra o teto.
# Custo: no máximo 4 KB a mais de imagem. Ver src/segpad.c.
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--gc-sections -Wl,-z,max-page-size=8192")

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/src)
# o opusfile.h faz #include <opus_multistream.h> sem o prefixo da pasta
include_directories(SYSTEM $ENV{VITASDK}/arm-vita-eabi/include/opus)

add_executable(${PROJECT_NAME}
  ${CMAKE_CURRENT_SOURCE_DIR}/src/main.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/library.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/decoder.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/compat.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/sides.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/lyrics.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/player.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/ui.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/playlist.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/rec.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/scrobble.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/lastfm.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/md5.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/net.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/resume.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/fsutil.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/ui_layout.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/ime.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/qobuz.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/soundcloud.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/fonte.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/segpad.c
)

# A ordem importa num link estático: quem usa vem ANTES de quem fornece.
# opusfile → opus → ogg; vorbisfile → vorbis → ogg; FLAC → ogg.
target_link_libraries(${PROJECT_NAME}
  vita2d
  vitashark
  freetype
  png
  jpeg
  z
  mpg123
  FLAC
  vorbisfile
  vorbis
  opusfile
  opus
  ogg
  SDL2
  SDL2main
  # A pilha HTTP do aparelho. O sceHttp saiu (o sceSsl dele para em TLS 1.0 e
  # os servidores do Qobuz e do lrclib exigem 1.2 com AEAD); quem fala agora é
  # o curl com OpenSSL que o vitasdk traz — o MESMO código do caminho do PC.
  # A ordem importa no link estático: curl antes de ssl/crypto/z/zstd.
  curl
  ssl
  crypto
  z
  zstd
  SceGxm_stub
  SceCtrl_stub
  SceTouch_stub
  SceDisplay_stub
  SceAudio_stub
  ScePgf_stub
  ScePvf_stub
  SceSysmodule_stub
  SceIme_stub
  SceAppUtil_stub
  SceAppMgr_stub
  SceJpeg_stub
  ScePower_stub
  SceRtc_stub
  SceLibKernel_stub
  SceIofilemgr_stub
  SceNet_stub
  SceNetCtl_stub
  SceSysmem_stub
  SceKernelThreadMgr_stub
  SceKernelModulemgr_stub
  SceProcessmgr_stub
  SceHid_stub
  SceMotion_stub
  SceAudioIn_stub
  SceCommonDialog_stub
  # a Shell: é dela o papel de "tocador de música" (ver o main.c)
  SceShellSvc_stub
  pthread
  m
)

# UNSAFE não é bravata: sem ele o vita.cmake passa "-s" ao vita-make-fself e
# o app sobe como homebrew "safe". Nesse modo o sandbox do HENkaku só deixa o
# app enxergar "ux0:data" e "app0:" — o resto do cartão não existe para ele.
#
# SINTOMA: o relatório que o app deixa no cartão dizia, no mesmo arranque,
#     [ ] ux0:music                    DID NOT OPEN: 0x80010001
#     [ ] ux0:data/vitastylus/music    DID NOT OPEN: 0x80010002
# EPERM na pasta que EXISTE (3.729 arquivos, 122 álbuns) e ENOENT na que não
# existe. Um caminho mal escrito dá ENOENT nos dois; permissão negada só num.
# Isso não é grafia de caminho — foi por ler isso como grafia que a tentativa
# anterior (tentar "ux0:music" e "ux0:/music") não mudou nada.
#
# Custo: o VitaShell avisa "unsafe homebrew" ao instalar, e o aparelho precisa
# de "Enable unsafe homebrew" ligado no HENkaku Settings. Este já tem — o
# VitaShell, o PKGj e o AutoPlugin2 no cartão também são unsafe.
vita_create_self(${PROJECT_NAME}.self ${PROJECT_NAME} UNSAFE)
vita_create_vpk(${PROJECT_NAME}.vpk ${VITA_TITLEID} ${PROJECT_NAME}.self
  VERSION ${VITA_VERSION}
  NAME ${VITA_APP_NAME}
  FILE ${CMAKE_CURRENT_SOURCE_DIR}/sce_sys/icon0.png sce_sys/icon0.png
  FILE ${CMAKE_CURRENT_SOURCE_DIR}/sce_sys/livearea/contents/bg.png
       sce_sys/livearea/contents/bg.png
  FILE ${CMAKE_CURRENT_SOURCE_DIR}/sce_sys/livearea/contents/startup.png
       sce_sys/livearea/contents/startup.png
  FILE ${CMAKE_CURRENT_SOURCE_DIR}/sce_sys/livearea/contents/template.xml
       sce_sys/livearea/contents/template.xml
)
