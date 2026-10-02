//! FFI bindings to the C++ SIMD routines (math_ops, bloom, activations, matmul).
//! This completes Day 21 of the implementation plan.

use std::os::raw::{c_float, c_int, c_uchar};

extern "C" {
    // math_ops.h
    pub fn cleavedb_sum_avx512(a: *const c_float, n: c_int) -> c_float;
    fn cleavedb_dot_product_avx512(a: *const c_float, b: *const c_float, n: c_int) -> c_float;
    fn cleavedb_dot_product_avx2(a: *const c_float, b: *const c_float, n: c_int) -> c_float;
    fn cleavedb_dot_product_scalar(a: *const c_float, b: *const c_float, n: c_int) -> c_float;

    // cpu_detect.h
    fn cleavedb_has_avx2() -> bool;
    fn cleavedb_has_avx512() -> bool;

    // activations.h
    fn cleavedb_softmax(x: *mut c_float, n: usize);
    fn cleavedb_gelu(x: *mut c_float, n: usize);
    fn cleavedb_sigmoid(x: *mut c_float, n: usize);
    fn cleavedb_layer_norm(x: *mut c_float, n: usize, eps: c_float);

    // matmul.h
    fn cleavedb_matmul(a: *const c_float, b: *const c_float, c: *mut c_float, m: usize, k: usize, n: usize);

    // attention.h
    fn cleavedb_multi_head_attention(
        x: *const c_float, 
        w_q: *const c_float, w_k: *const c_float, w_v: *const c_float, w_o: *const c_float,
        output: *mut c_float,
        seq_len: usize, embed_dim: usize, num_heads: usize
    );
}

/// Computes the dot product using the best available SIMD instruction set.
pub fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    assert_eq!(a.len(), b.len(), "Vectors must have same length");
    let n = a.len() as c_int;
    unsafe {
        // Simple runtime dispatch
        if cleavedb_has_avx512() {
            cleavedb_dot_product_avx512(a.as_ptr(), b.as_ptr(), n)
        } else if cleavedb_has_avx2() {
            cleavedb_dot_product_avx2(a.as_ptr(), b.as_ptr(), n)
        } else {
            cleavedb_dot_product_scalar(a.as_ptr(), b.as_ptr(), n)
        }
    }
}

/// Applies Softmax in-place
pub fn softmax(x: &mut [f32]) {
    unsafe { cleavedb_softmax(x.as_mut_ptr(), x.len()) }
}

/// Applies GELU in-place
pub fn gelu(x: &mut [f32]) {
    unsafe { cleavedb_gelu(x.as_mut_ptr(), x.len()) }
}

/// Applies Sigmoid in-place
pub fn sigmoid(x: &mut [f32]) {
    unsafe { cleavedb_sigmoid(x.as_mut_ptr(), x.len()) }
}

/// Applies Layer Normalization in-place
pub fn layer_norm(x: &mut [f32], eps: f32) {
    unsafe { cleavedb_layer_norm(x.as_mut_ptr(), x.len(), eps) }
}

/// Performs matrix multiplication C = A * B
/// A is (m x k), B is (k x n), C is (m x n).
pub fn matmul(a: &[f32], b: &[f32], c: &mut [f32], m: usize, k: usize, n: usize) {
    assert_eq!(a.len(), m * k, "A matrix dimension mismatch");
    assert_eq!(b.len(), k * n, "B matrix dimension mismatch");
    assert_eq!(c.len(), m * n, "C matrix dimension mismatch");

    unsafe {
        cleavedb_matmul(a.as_ptr(), b.as_ptr(), c.as_mut_ptr(), m, k, n);
    }
}

pub fn multi_head_attention(
    x: &[f32], 
    w_q: &[f32], w_k: &[f32], w_v: &[f32], w_o: &[f32],
    output: &mut [f32],
    seq_len: usize, embed_dim: usize, num_heads: usize
) {
    assert_eq!(x.len(), seq_len * embed_dim);
    assert_eq!(w_q.len(), embed_dim * embed_dim);
    assert_eq!(output.len(), seq_len * embed_dim);
    
    unsafe {
        cleavedb_multi_head_attention(
            x.as_ptr(),
            w_q.as_ptr(), w_k.as_ptr(), w_v.as_ptr(), w_o.as_ptr(),
            output.as_mut_ptr(),
            seq_len, embed_dim, num_heads
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dot_product() {
        let a = vec![1.0, 2.0, 3.0, 4.0];
        let b = vec![2.0, 3.0, 4.0, 5.0];
        let result = dot_product(&a, &b);
        assert_eq!(result, 1.0*2.0 + 2.0*3.0 + 3.0*4.0 + 4.0*5.0);
    }

    #[test]
    fn test_softmax() {
        let mut a = vec![1.0, 2.0, 3.0];
        softmax(&mut a);
        let sum: f32 = a.iter().sum();
        assert!((sum - 1.0).abs() < 1e-5);
    }

    #[test]
    fn test_multi_head_attention() {
        let seq_len = 2;
        let embed_dim = 4;
        let num_heads = 2;
        
        let x = vec![1.0; seq_len * embed_dim];
        let w_q = vec![0.5; embed_dim * embed_dim];
        let w_k = vec![0.5; embed_dim * embed_dim];
        let w_v = vec![0.5; embed_dim * embed_dim];
        let w_o = vec![0.5; embed_dim * embed_dim];
        
        let mut output = vec![0.0; seq_len * embed_dim];
        
        multi_head_attention(&x, &w_q, &w_k, &w_v, &w_o, &mut output, seq_len, embed_dim, num_heads);
        
        assert!(output[0] > 0.0);
    }
}
