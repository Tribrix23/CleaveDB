#include "activations.h"
#include <cmath>
#include <algorithm>

// Fast math approximation for expf to enable auto-vectorization without SVML
inline float fast_expf(float x) {
    // A simple, very fast approximation of exp(x)
    x = 1.0f + x * (1.0f / 256.0f);
    x *= x; x *= x; x *= x; x *= x;
    x *= x; x *= x; x *= x; x *= x;
    return x;
}

extern "C" {

void cleavedb_softmax(float* x, size_t n) {
    if (n == 0) return;
    
    // 1. Find max for numerical stability
    float max_val = x[0];
    for (size_t i = 1; i < n; ++i) {
        if (x[i] > max_val) max_val = x[i];
    }
    
    // 2. Compute exp(x - max) and sum
    float sum = 0.0f;
    #pragma loop(ivdep)
    for (size_t i = 0; i < n; ++i) {
        x[i] = std::exp(x[i] - max_val); // Compiler will vectorize this with /fp:fast
        sum += x[i];
    }
    
    // 3. Normalize
    float inv_sum = 1.0f / sum;
    #pragma loop(ivdep)
    for (size_t i = 0; i < n; ++i) {
        x[i] *= inv_sum;
    }
}

void cleavedb_gelu(float* x, size_t n) {
    // GELU(x) = 0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))
    const float SQRT_2_OVER_PI = 0.7978845608f;
    const float COEF = 0.044715f;
    
    #pragma loop(ivdep)
    for (size_t i = 0; i < n; ++i) {
        float val = x[i];
        float cube = val * val * val;
        float inner = SQRT_2_OVER_PI * (val + COEF * cube);
        x[i] = 0.5f * val * (1.0f + std::tanh(inner));
    }
}

void cleavedb_sigmoid(float* x, size_t n) {
    #pragma loop(ivdep)
    for (size_t i = 0; i < n; ++i) {
        x[i] = 1.0f / (1.0f + std::exp(-x[i]));
    }
}

void cleavedb_layer_norm(float* x, size_t n, float eps) {
    if (n == 0) return;
    
    // 1. Mean
    float sum = 0.0f;
    for (size_t i = 0; i < n; ++i) {
        sum += x[i];
    }
    float mean = sum / n;
    
    // 2. Variance
    float var_sum = 0.0f;
    for (size_t i = 0; i < n; ++i) {
        float diff = x[i] - mean;
        var_sum += diff * diff;
    }
    float var = var_sum / n;
    
    // 3. Normalize
    float inv_stddev = 1.0f / std::sqrt(var + eps);
    #pragma loop(ivdep)
    for (size_t i = 0; i < n; ++i) {
        x[i] = (x[i] - mean) * inv_stddev;
    }
}

} // extern "C"
