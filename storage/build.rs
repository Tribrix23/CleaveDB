fn main() {
    println!("cargo:rerun-if-changed=../simd/src/math_ops.cpp");
    println!("cargo:rerun-if-changed=../simd/include/math_ops.h");
    println!("cargo:rerun-if-changed=../simd/src/bloom.cpp");
    println!("cargo:rerun-if-changed=../simd/include/bloom.h");

    cc::Build::new()
        .cpp(true)
        .file("../simd/src/math_ops.cpp")
        .file("../simd/src/bloom.cpp")
        .file("../simd/src/cpu_detect.cpp")
        .file("../simd/src/activations.cpp")
        .file("../simd/src/matmul.cpp")
        .file("../simd/src/attention.cpp")
        .include("../simd/include")
        .flag_if_supported("/arch:AVX512") // MSVC
        .flag_if_supported("/O2")
        .flag_if_supported("/std:c++17")
        .flag_if_supported("-mavx512f")
        .flag_if_supported("-mfma")    // GCC/Clang
        .flag_if_supported("-mavx2")
        .flag_if_supported("-O3")
        .flag_if_supported("-std=c++17")
        .compile("cleavedb_simd");

    println!("cargo:rustc-link-search=native=../coordinator");
    println!("cargo:rustc-link-lib=coordinator");
}
