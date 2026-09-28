#pragma once
#include <cstddef>

extern "C" {
    /// Performs Matrix Multiplication C = A * B
    /// A is (m x k), B is (k x n), C is (m x n).
    /// All matrices are stored in row-major order.
    void cleavedb_matmul(const float* A, const float* B, float* C, size_t m, size_t k, size_t n);
}
