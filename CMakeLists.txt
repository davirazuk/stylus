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

set(VITA_APP_NAME "STYLUS Vinil")
set(VITA_TITLEID  "STYS00001")
set(VITA_VERSION  "01.00")
set(VITA_TITLE  "STYLUS")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -std=gnu11 -Wall -Wextra -O2 -ffunction-sections -fdata-sections")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--gc-sections")

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
  ${CMAKE_CURRENT_SOURCE_DIR}/src/resume.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/fsutil.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/ui_layout.c
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
  SceGxm_stub
  SceCtrl_stub
  SceTouch_stub
  SceDisplay_stub
  SceAudio_stub
  ScePgf_stub
  ScePvf_stub
  SceSysmodule_stub
  SceAppUtil_stub
  SceAppMgr_stub
  SceJpeg_stub
  ScePower_stub
  SceRtc_stub
  SceLibKernel_stub
  SceIofilemgr_stub
  SceNet_stub
  SceNetCtl_stub
  SceHttp_stub
  SceSsl_stub
  SceHid_stub
  SceMotion_stub
  SceAudioIn_stub
  SceCommonDialog_stub
  pthread
  m
)

vita_create_self(${PROJECT_NAME}.self ${PROJECT_NAME})
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
