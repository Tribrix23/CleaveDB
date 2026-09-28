#include "cpu_detect.h"

#ifdef _WIN32
#include <intrin.h>
#else
#include <cpuid.h>
#endif

namespace cleavedb::simd {

CpuFeatures CpuFeatures::detect() {
    CpuFeatures features = {false, false, false};
    int info[4];

#ifdef _WIN32
    __cpuid(info, 0);
    int nIds = info[0];

    if (nIds >= 1) {
        __cpuid(info, 1);
        features.has_fma = (info[2] & ((int)1 << 12)) != 0;
    }

    if (nIds >= 7) {
        __cpuidex(info, 7, 0);
        features.has_avx2 = (info[1] & ((int)1 << 5)) != 0;
        features.has_avx512f = (info[1] & ((int)1 << 16)) != 0;
    }
#else
    unsigned int eax, ebx, ecx, edx;
    if (__get_cpuid(1, &eax, &ebx, &ecx, &edx)) {
        features.has_fma = (ecx & (1 << 12)) != 0;
    }
    if (__get_cpuid_count(7, 0, &eax, &ebx, &ecx, &edx)) {
        features.has_avx2 = (ebx & (1 << 5)) != 0;
        features.has_avx512f = (ebx & (1 << 16)) != 0;
    }
#endif

    return features;
}

const CpuFeatures CPU_FEATURES = CpuFeatures::detect();

} // namespace cleavedb::simd

extern "C" {
    bool cleavedb_has_avx2() { return cleavedb::simd::CPU_FEATURES.has_avx2; }
    bool cleavedb_has_avx512() { return cleavedb::simd::CPU_FEATURES.has_avx512f; }
}
