#include "attention.h"
#include "matmul.h"
#include "activations.h"
#include <vector>
#include <cmath>
#include <algorithm>

namespace {
    void transpose(const float* src, float* dst, size_t rows, size_t cols) {
        for (size_t r = 0; r < rows; ++r) {
            for (size_t c = 0; c < cols; ++c) {
                dst[c * rows + r] = src[r * cols + c];
            }
        }
    }
}

extern "C" {

void cleavedb_multi_head_attention(
    const float* X, 
    const float* W_q, const float* W_k, const float* W_v, const float* W_o,
    float* Output,
    size_t seq_len, size_t embed_dim, size_t num_heads
) {
    size_t head_dim = embed_dim / num_heads;
    size_t seq_embed_size = seq_len * embed_dim;

    // Allocate workspaces
    std::vector<float> Q(seq_embed_size);
    std::vector<float> K(seq_embed_size);
    std::vector<float> V(seq_embed_size);
    std::vector<float> K_t(seq_embed_size);
    
    // Q = X * W_q, K = X * W_k, V = X * W_v
    cleavedb_matmul(X, W_q, Q.data(), seq_len, embed_dim, embed_dim);
    cleavedb_matmul(X, W_k, K.data(), seq_len, embed_dim, embed_dim);
    cleavedb_matmul(X, W_v, V.data(), seq_len, embed_dim, embed_dim);

    // Compute Attention per head
    std::vector<float> S(seq_len * seq_len);
    std::vector<float> Z(seq_embed_size); // concatenated head outputs
    
    float scale = 1.0f / std::sqrt((float)head_dim);

    for (size_t h = 0; h < num_heads; ++h) {
        // Extract Q_h, K_h, V_h
        std::vector<float> Q_h(seq_len * head_dim);
        std::vector<float> K_h(seq_len * head_dim);
        std::vector<float> V_h(seq_len * head_dim);
        
        for (size_t i = 0; i < seq_len; ++i) {
            for (size_t j = 0; j < head_dim; ++j) {
                Q_h[i * head_dim + j] = Q[i * embed_dim + h * head_dim + j];
                K_h[i * head_dim + j] = K[i * embed_dim + h * head_dim + j];
                V_h[i * head_dim + j] = V[i * embed_dim + h * head_dim + j];
            }
        }
        
        // Transpose K_h
        std::vector<float> K_h_t(head_dim * seq_len);
        transpose(K_h.data(), K_h_t.data(), seq_len, head_dim);
        
        // Scores = Q_h * K_h^T
        cleavedb_matmul(Q_h.data(), K_h_t.data(), S.data(), seq_len, head_dim, seq_len);
        
        // Scale and Softmax per row
        for (size_t i = 0; i < seq_len; ++i) {
            for (size_t j = 0; j < seq_len; ++j) {
                S[i * seq_len + j] *= scale;
            }
            cleavedb_softmax(&S[i * seq_len], seq_len);
        }
        
        // Z_h = Scores * V_h
        std::vector<float> Z_h(seq_len * head_dim);
        cleavedb_matmul(S.data(), V_h.data(), Z_h.data(), seq_len, seq_len, head_dim);
        
        // Copy to Z
        for (size_t i = 0; i < seq_len; ++i) {
            for (size_t j = 0; j < head_dim; ++j) {
                Z[i * embed_dim + h * head_dim + j] = Z_h[i * head_dim + j];
            }
        }
    }
    
    // Output = Z * W_o
    cleavedb_matmul(Z.data(), W_o, Output, seq_len, embed_dim, embed_dim);
}

} // extern "C"
