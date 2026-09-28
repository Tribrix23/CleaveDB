#pragma once

#include <cstdint>
#include <cstddef>

extern "C" {
    void bloom_probe_avx2(const uint8_t* filter, const uint32_t* hashes, size_t n, uint8_t* results);
}
