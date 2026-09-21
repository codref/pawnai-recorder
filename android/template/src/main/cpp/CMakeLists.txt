cmake_minimum_required(VERSION 3.22.1)
project(pawnai_flac)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Static libFLAC only — linked into pawnai_flac.so and shipped in the APK.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(BUILD_CXXLIBS OFF CACHE BOOL "" FORCE)
set(BUILD_PROGRAMS OFF CACHE BOOL "" FORCE)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(INSTALL_MANPAGES OFF CACHE BOOL "" FORCE)
set(WITH_OGG OFF CACHE BOOL "" FORCE)
set(INSTALL_CMAKE_CONFIG_MODULE OFF CACHE BOOL "" FORCE)

include(FetchContent)
FetchContent_Declare(
    flac
    GIT_REPOSITORY https://github.com/xiph/flac.git
    GIT_TAG 1.4.3
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(flac)

add_library(pawnai_flac SHARED flac_jni.cpp)
target_link_libraries(pawnai_flac PRIVATE FLAC log)
target_compile_options(pawnai_flac PRIVATE -Wall -Wextra -fvisibility=hidden)
