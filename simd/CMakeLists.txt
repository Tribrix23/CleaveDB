cmake_minimum_required(VERSION 3.20)
project(cleavedb_simd LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Enable AVX-512 and AVX2 via compiler flags if MSVC or GCC/Clang
if(MSVC)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /arch:AVX512 /O2 /fp:fast")
else()
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -mavx512f -mavx2 -mfma -O3 -funroll-loops -ffast-math -march=native")
endif()

# Source files
set(SIMD_SOURCES
    src/math_ops.cpp
)

# Build shared library
add_library(cleavedb_simd SHARED ${SIMD_SOURCES})

# Target definitions for FFI
target_compile_definitions(cleavedb_simd PRIVATE CLEAVEDB_EXPORT)
