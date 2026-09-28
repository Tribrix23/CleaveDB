#pragma once
#include <cstdint>

namespace cleavedb::simd {

/// Dot product of two f32 vectors using AVX-512 FMA.
/// Handles arbitrary length (pads last chunk).
/// Unrolled across 4 accumulators to hide FMA pipeline latency.
float dot_product_avx512(const float* a, const float* b, int n);

/// Same but AVX2 fallback for older CPUs.
float dot_product_avx2(const float* a, const float* b, int n);

/// Scalar fallback
float dot_product_scalar(const float* a, const float* b, int n);

} // namespace cleavedb::simd

// C FFI exports for Rust
extern "C" {
    float cleavedb_dot_product_avx512(const float* a, const float* b, int n);
    float cleavedb_dot_product_avx2(const float* a, const float* b, int n);
    float cleavedb_dot_product_scalar(const float* a, const float* b, int n);
}
