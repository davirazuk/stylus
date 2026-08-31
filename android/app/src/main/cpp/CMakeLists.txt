cmake_minimum_required(VERSION 3.22.1)
project(stylus_native LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Oboe's AAR exige c++_shared (nnunca a static) — o pacote vem assim.
set(ANDROID_STL c++_shared)

find_package(oboe REQUIRED CONFIG)

add_library(stylus_native SHARED native_engine.cpp)
target_link_libraries(stylus_native oboe::oboe log)
target_include_directories(stylus_native PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})