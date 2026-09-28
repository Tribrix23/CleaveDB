#pragma once
#include <cstdint>

namespace cleavedb::simd {

/// Detects CPU features at runtime
struct CpuFeatures {
    bool has_avx2;
    bool has_avx512f;
    bool has_fma;
    
    static CpuFeatures detect();
};

/// Global instance initialized at startup
extern const CpuFeatures CPU_FEATURES;

} // namespace cleavedb::simd

extern "C" {
    bool cleavedb_has_avx2();
    bool cleavedb_has_avx512();
}
