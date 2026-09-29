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

    // First check that the OS supports XSAVE/XGETBV (required for AVX state saving)
    bool os_supports_avx = false;
    bool os_supports_avx512 = false;

#ifdef _WIN32
    __cpuid(info, 1);
    bool has_osxsave = (info[2] & ((int)1 << 27)) != 0;
    features.has_fma = (info[2] & ((int)1 << 12)) != 0;

    if (has_osxsave) {
        // XGETBV to check OS has enabled XMM/YMM state saving
        unsigned long long xcr0 = _xgetbv(0);
        os_supports_avx = (xcr0 & 0x6) == 0x6;           // XMM + YMM
        os_supports_avx512 = (xcr0 & 0xE6) == 0xE6;      // XMM + YMM + opmask + ZMM_Hi256 + Hi16_ZMM
    }

    __cpuid(info, 0);
    int nIds = info[0];
    if (nIds >= 7) {
        __cpuidex(info, 7, 0);
        features.has_avx2 = os_supports_avx && ((info[1] & ((int)1 << 5)) != 0);
        features.has_avx512f = os_supports_avx512 && ((info[1] & ((int)1 << 16)) != 0);
    }
#else
    unsigned int eax, ebx, ecx, edx;
    if (__get_cpuid(1, &eax, &ebx, &ecx, &edx)) {
        features.has_fma = (ecx & (1 << 12)) != 0;
        bool has_osxsave = (ecx & (1 << 27)) != 0;

        if (has_osxsave) {
            unsigned int xcr0_lo, xcr0_hi;
            __asm__ volatile("xgetbv" : "=a"(xcr0_lo), "=d"(xcr0_hi) : "c"(0));
            os_supports_avx = (xcr0_lo & 0x6) == 0x6;
            os_supports_avx512 = (xcr0_lo & 0xE6) == 0xE6;
        }
    }
    if (__get_cpuid_count(7, 0, &eax, &ebx, &ecx, &edx)) {
        features.has_avx2 = os_supports_avx && ((ebx & (1 << 5)) != 0);
        features.has_avx512f = os_supports_avx512 && ((ebx & (1 << 16)) != 0);
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
