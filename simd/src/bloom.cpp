#include "bloom.h"
#include <immintrin.h>

extern "C" void bloom_probe_avx2(const uint8_t* filter, const uint32_t* hashes, size_t n, uint8_t* results) {
    size_t i = 0;
    const uint32_t MASK = 1023; // Assuming 1024 bits for the masks
    
    __m256i mask_vec = _mm256_set1_epi32(MASK);

    // Process 8 hashes at a time using AVX2
    for (; i + 8 <= n; i += 8) {
        __m256i h = _mm256_loadu_si256((const __m256i*)(hashes + i));
        
        // Compute 3 bit indices per hash
        __m256i h1 = _mm256_and_si256(h, mask_vec);
        __m256i h2 = _mm256_and_si256(_mm256_srli_epi32(h, 10), mask_vec);
        __m256i h3 = _mm256_and_si256(_mm256_srli_epi32(h, 20), mask_vec);
        
        // Byte indices
        __m256i byte_idx1 = _mm256_srli_epi32(h1, 3);
        __m256i byte_idx2 = _mm256_srli_epi32(h2, 3);
        __m256i byte_idx3 = _mm256_srli_epi32(h3, 3);
        
        // Gather bytes from filter
        __m256i bytes1 = _mm256_i32gather_epi32((const int*)filter, byte_idx1, 1);
        __m256i bytes2 = _mm256_i32gather_epi32((const int*)filter, byte_idx2, 1);
        __m256i bytes3 = _mm256_i32gather_epi32((const int*)filter, byte_idx3, 1);
        
        // Bit positions
        __m256i bit_pos1 = _mm256_and_si256(h1, _mm256_set1_epi32(7));
        __m256i bit_pos2 = _mm256_and_si256(h2, _mm256_set1_epi32(7));
        __m256i bit_pos3 = _mm256_and_si256(h3, _mm256_set1_epi32(7));
        
        // Check if bits are set
        __m256i bit_mask1 = _mm256_sllv_epi32(_mm256_set1_epi32(1), bit_pos1);
        __m256i bit_mask2 = _mm256_sllv_epi32(_mm256_set1_epi32(1), bit_pos2);
        __m256i bit_mask3 = _mm256_sllv_epi32(_mm256_set1_epi32(1), bit_pos3);
        
        __m256i v1 = _mm256_and_si256(bytes1, bit_mask1);
        __m256i v2 = _mm256_and_si256(bytes2, bit_mask2);
        __m256i v3 = _mm256_and_si256(bytes3, bit_mask3);
        
        __m256i cmp1 = _mm256_cmpgt_epi32(v1, _mm256_setzero_si256());
        __m256i cmp2 = _mm256_cmpgt_epi32(v2, _mm256_setzero_si256());
        __m256i cmp3 = _mm256_cmpgt_epi32(v3, _mm256_setzero_si256());
        
        __m256i all_set = _mm256_and_si256(cmp1, _mm256_and_si256(cmp2, cmp3));
        
        // Write boolean results to results array
        int32_t res[8];
        _mm256_storeu_si256((__m256i*)res, all_set);
        
        for (int j = 0; j < 8; ++j) {
            results[i + j] = res[j] ? 1 : 0;
        }
    }
    
    // Tail processing
    for (; i < n; ++i) {
        uint32_t h = hashes[i];
        uint32_t h1 = h & MASK;
        uint32_t h2 = (h >> 10) & MASK;
        uint32_t h3 = (h >> 20) & MASK;
        
        bool b1 = filter[h1 / 8] & (1 << (h1 % 8));
        bool b2 = filter[h2 / 8] & (1 << (h2 % 8));
        bool b3 = filter[h3 / 8] & (1 << (h3 % 8));
        
        results[i] = (b1 && b2 && b3) ? 1 : 0;
    }
}
