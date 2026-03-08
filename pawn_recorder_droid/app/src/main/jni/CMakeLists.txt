cmake_minimum_required(VERSION 3.22.1)
project(pawn_recorder_native C)

add_library(
    pawn_recorder_native
    SHARED
    aaudio_recorder.c
)

target_link_libraries(
    pawn_recorder_native
    aaudio      # AAudio NDK library
    log         # Android logging
)
