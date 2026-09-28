#pragma once
#include <cstddef>

extern "C" {
    /// Computes the Softmax of a vector in-place.
    void cleavedb_softmax(float* x, size_t n);

    /// Computes the GELU activation in-place.
    void cleavedb_gelu(float* x, size_t n);

    /// Computes the Sigmoid activation in-place.
    void cleavedb_sigmoid(float* x, size_t n);

    /// Computes Layer Normalization in-place: x = (x - mean) / sqrt(var + eps)
    void cleavedb_layer_norm(float* x, size_t n, float eps);
}
