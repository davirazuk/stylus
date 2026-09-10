cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED CMAKE_TOOLCHAIN_FILE)
  if(DEFINED ENV{VITASDK})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VITASDK}/share/vita.toolchain.cmake" CACHE PATH "toolchain file")
  else()
    message(FATAL_ERROR "Please define VITASDK to point to your SDK path!")
  endif()
endif()

project(vitastylus_overlay C)
include("${VITASDK}/share/vita.cmake" REQUIRED)

# Kernel module: no crt0, no main — entry via module_start/module_stop
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -std=gnu11 -Wall -Wextra -O2")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -nostartfiles")

add_executable(${PROJECT_NAME}
  src/overlay.c
)

target_link_libraries(${PROJECT_NAME}
  SceLibKernel_stub
  SceCtrl_stub
  SceDisplay_stub
  SceSysmem_stub
  SceKernelThreadMgr_stub
  SceRtc_stub
)

vita_create_self(${PROJECT_NAME}.skprx ${PROJECT_NAME}
  KERNEL
  UNRESOLVED
  MODULE_ENTRY "module_start,module_stop"
)
