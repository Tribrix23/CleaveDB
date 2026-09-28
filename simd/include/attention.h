#pragma once
#include <cstddef>

extern "C" {
    /// Computes Multi-Head Self-Attention forward pass.
    /// X: Input sequence (seq_len x embed_dim)
    /// W_q, W_k, W_v: Weight matrices (embed_dim x embed_dim)
    /// W_o: Output weight matrix (embed_dim x embed_dim)
    /// Output: Result sequence (seq_len x embed_dim)
    void cleavedb_multi_head_attention(
        const float* X, 
        const float* W_q, const float* W_k, const float* W_v, const float* W_o,
        float* Output,
        size_t seq_len, size_t embed_dim, size_t num_heads
    );
}
