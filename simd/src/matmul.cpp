#include "matmul.h"
#include <cstring>
#include <algorithm>

#if defined(__AVX512F__)
#include <immintrin.h>
#elif defined(__AVX2__)
#include <immintrin.h>
#endif

// Tile sizes optimized for L1/L2 caches
#define TILE_M 64
#define TILE_K 64
#define TILE_N 64

extern "C" {

void cleavedb_matmul(const float* A, const float* B, float* C, size_t m, size_t k, size_t n) {
    // Initialize C to 0
    std::memset(C, 0, m * n * sizeof(float));

    // Cache blocked (tiled) matrix multiplication
    for (size_t i0 = 0; i0 < m; i0 += TILE_M) {
        size_t imax = std::min(i0 + TILE_M, m);
        for (size_t k0 = 0; k0 < k; k0 += TILE_K) {
            size_t kmax = std::min(k0 + TILE_K, k);
            for (size_t j0 = 0; j0 < n; j0 += TILE_N) {
                size_t jmax = std::min(j0 + TILE_N, n);

                // Micro-kernel
                for (size_t i = i0; i < imax; ++i) {
                    for (size_t p = k0; p < kmax; ++p) {
                        float a_val = A[i * k + p];
                        size_t j = j0;

#if defined(__AVX512F__)
                        __m512 va = _mm512_set1_ps(a_val);
                        // Process 16 floats at a time
                        for (; j + 15 < jmax; j += 16) {
                            __m512 vb = _mm512_loadu_ps(&B[p * n + j]);
                            __m512 vc = _mm512_loadu_ps(&C[i * n + j]);
                            vc = _mm512_fmadd_ps(va, vb, vc);
                            _mm512_storeu_ps(&C[i * n + j], vc);
                        }
#elif defined(__AVX2__)
                        __m256 va = _mm256_set1_ps(a_val);
                        // Process 8 floats at a time
                        for (; j + 7 < jmax; j += 8) {
                            __m256 vb = _mm256_loadu_ps(&B[p * n + j]);
                            __m256 vc = _mm256_loadu_ps(&C[i * n + j]);
                            vc = _mm256_fmadd_ps(va, vb, vc);
                            _mm256_storeu_ps(&C[i * n + j], vc);
                        }
#endif
                        // Scalar fallback/remainder
                        for (; j < jmax; ++j) {
                            C[i * n + j] += a_val * B[p * n + j];
                        }
                    }
                }
            }
        }
    }
}

} // extern "C"
