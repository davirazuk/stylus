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

set(VITA_APP_NAME "Stilus Vinil")
set(VITA_TITLEID  "STYS00001")
set(VITA_VERSION  "01.00")
set(VITA_TITLE  "Stilus")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -std=gnu11 -Wall -Wextra -O2 -ffunction-sections -fdata-sections")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--gc-sections")

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/src)

add_executable(${PROJECT_NAME}
  ${CMAKE_CURRENT_SOURCE_DIR}/src/main.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/library.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/tags.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/player.c
  ${CMAKE_CURRENT_SOURCE_DIR}/src/ui.c
)

target_link_libraries(${PROJECT_NAME}
  vita2d
  vitashark
  freetype
  png
  jpeg
  z
  mpg123
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
)
