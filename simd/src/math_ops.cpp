#include "../include/math_ops.h"

#if defined(__AVX512F__)
#include <immintrin.h>
#elif defined(__AVX2__)
#include <immintrin.h>
#endif

namespace cleavedb::simd {

float dot_product_scalar(const float* a, const float* b, int n) {
    float sum = 0.0f;
    for (int i = 0; i < n; ++i) {
        sum += a[i] * b[i];
    }
    return sum;
}

#if defined(__AVX512F__)
float dot_product_avx512(const float* a, const float* b, int n) {
    __m512 acc0 = _mm512_setzero_ps();
    __m512 acc1 = _mm512_setzero_ps();
    __m512 acc2 = _mm512_setzero_ps();
    __m512 acc3 = _mm512_setzero_ps();

    int i = 0;
    // Unrolled: process 64 floats per iteration (4 x 16)
    for (; i + 63 < n; i += 64) {
        __m512 a0 = _mm512_loadu_ps(a + i);
        __m512 b0 = _mm512_loadu_ps(b + i);
        acc0 = _mm512_fmadd_ps(a0, b0, acc0);

        __m512 a1 = _mm512_loadu_ps(a + i + 16);
        __m512 b1 = _mm512_loadu_ps(b + i + 16);
        acc1 = _mm512_fmadd_ps(a1, b1, acc1);

        __m512 a2 = _mm512_loadu_ps(a + i + 32);
        __m512 b2 = _mm512_loadu_ps(b + i + 32);
        acc2 = _mm512_fmadd_ps(a2, b2, acc2);

        __m512 a3 = _mm512_loadu_ps(a + i + 48);
        __m512 b3 = _mm512_loadu_ps(b + i + 48);
        acc3 = _mm512_fmadd_ps(a3, b3, acc3);
    }

    for (; i + 15 < n; i += 16) {
        __m512 av = _mm512_loadu_ps(a + i);
        __m512 bv = _mm512_loadu_ps(b + i);
        acc0 = _mm512_fmadd_ps(av, bv, acc0);
    }

    if (i < n) {
        __mmask16 mask = (1u << (n - i)) - 1;
        __m512 av = _mm512_maskz_loadu_ps(mask, a + i);
        __m512 bv = _mm512_maskz_loadu_ps(mask, b + i);
        acc0 = _mm512_fmadd_ps(av, bv, acc0);
    }

    acc0 = _mm512_add_ps(acc0, acc1);
    acc2 = _mm512_add_ps(acc2, acc3);
    acc0 = _mm512_add_ps(acc0, acc2);
    return _mm512_reduce_add_ps(acc0);
}
#else
float dot_product_avx512(const float* a, const float* b, int n) {
    return dot_product_scalar(a, b, n);
}
#endif

#if defined(__AVX2__) || defined(__AVX512F__)
float dot_product_avx2(const float* a, const float* b, int n) {
    __m256 acc0 = _mm256_setzero_ps();
    __m256 acc1 = _mm256_setzero_ps();
    __m256 acc2 = _mm256_setzero_ps();
    __m256 acc3 = _mm256_setzero_ps();

    int i = 0;
    // Unrolled: process 32 floats per iteration (4 x 8)
    for (; i + 31 < n; i += 32) {
        __m256 a0 = _mm256_loadu_ps(a + i);
        __m256 b0 = _mm256_loadu_ps(b + i);
        acc0 = _mm256_fmadd_ps(a0, b0, acc0);

        __m256 a1 = _mm256_loadu_ps(a + i + 8);
        __m256 b1 = _mm256_loadu_ps(b + i + 8);
        acc1 = _mm256_fmadd_ps(a1, b1, acc1);

        __m256 a2 = _mm256_loadu_ps(a + i + 16);
        __m256 b2 = _mm256_loadu_ps(b + i + 16);
        acc2 = _mm256_fmadd_ps(a2, b2, acc2);

        __m256 a3 = _mm256_loadu_ps(a + i + 24);
        __m256 b3 = _mm256_loadu_ps(b + i + 24);
        acc3 = _mm256_fmadd_ps(a3, b3, acc3);
    }

    for (; i + 7 < n; i += 8) {
        __m256 av = _mm256_loadu_ps(a + i);
        __m256 bv = _mm256_loadu_ps(b + i);
        acc0 = _mm256_fmadd_ps(av, bv, acc0);
    }

    acc0 = _mm256_add_ps(acc0, acc1);
    acc2 = _mm256_add_ps(acc2, acc3);
    acc0 = _mm256_add_ps(acc0, acc2);

    // Reduce __m256 to scalar
    float tmp[8];
    _mm256_storeu_ps(tmp, acc0);
    float sum = 0.0f;
    for (int j = 0; j < 8; ++j) sum += tmp[j];
    
    // Remainder
    for (; i < n; ++i) {
        sum += a[i] * b[i];
    }
    
    return sum;
}
#else
float dot_product_avx2(const float* a, const float* b, int n) {
    return dot_product_scalar(a, b, n);
}
#endif

} // namespace cleavedb::simd

extern "C" {
    float cleavedb_dot_product_avx512(const float* a, const float* b, int n) {
        return cleavedb::simd::dot_product_avx512(a, b, n);
    }
    float cleavedb_dot_product_avx2(const float* a, const float* b, int n) {
        return cleavedb::simd::dot_product_avx2(a, b, n);
    }
    float cleavedb_dot_product_scalar(const float* a, const float* b, int n) {
        return cleavedb::simd::dot_product_scalar(a, b, n);
    }
}
