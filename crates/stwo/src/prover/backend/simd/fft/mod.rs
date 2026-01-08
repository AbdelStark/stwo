use std::simd::{simd_swizzle, u32x16, u32x8};

#[cfg(feature = "parallel")]
use rayon::prelude::*;

use super::m31::PackedBaseField;
use super::utils::UnsafeMut;
use crate::core::fields::m31::P;
use crate::parallel_iter;

pub mod ifft;
pub mod rfft;

// Block size for cache-aware transpose. Each block processes TRANSPOSE_BLOCK_SIZE^2 / 2 swaps.
// Each swap accesses 2 cache lines (128 bytes), so we want:
//   BLOCK_SIZE^2 * 128 bytes < L1 cache (32KB)
// => BLOCK_SIZE < sqrt(32KB / 128) = sqrt(256) = 16
// We use 8 as a conservative choice that works well across architectures.
const TRANSPOSE_BLOCK_SIZE: usize = 8;

// Threshold (in log_n_vecs) above which we use blocked transpose.
// For small arrays, the overhead of blocking isn't worth it.
// 2^12 vecs = 2^12 * 16 elements = 2^16 elements = 256KB
const BLOCKED_TRANSPOSE_THRESHOLD: usize = 12;

// FFT cached size threshold: determines when to use cached vs non-cached FFT algorithm.
// This value should be tuned to match the L2/L3 cache size of the target architecture.
// For a CACHED_FFT_LOG_SIZE of N, the FFT will cache up to 2^N elements (each 4 bytes).
//
// Architecture-specific tuning rationale:
// - AVX512 (server CPUs): Large L3 caches (10-50MB), can cache larger FFTs (2^18 = 1MB)
// - AVX2 (consumer CPUs): Moderate L3 (8-16MB), use 2^17 (512KB) for safety margin
// - NEON (ARM64): Highly variable (512KB-12MB), use 2^16 (256KB) for portability
// - WASM/Generic: Conservative 2^15 (128KB) for browser environments
cfg_if::cfg_if! {
    if #[cfg(all(target_arch = "x86_64", target_feature = "avx512f"))] {
        // Server CPUs with AVX512 typically have 1MB+ L2 and 10MB+ L3 per core
        pub const CACHED_FFT_LOG_SIZE: u32 = 18;
    } else if #[cfg(all(target_arch = "x86_64", target_feature = "avx2"))] {
        // Consumer CPUs with AVX2 typically have 256KB-1MB L2 and 8-16MB shared L3
        pub const CACHED_FFT_LOG_SIZE: u32 = 17;
    } else if #[cfg(all(target_arch = "aarch64", target_feature = "neon"))] {
        // ARM64 varies widely: Apple Silicon has large caches, embedded ARM may not
        pub const CACHED_FFT_LOG_SIZE: u32 = 16;
    } else if #[cfg(target_arch = "wasm32")] {
        // WASM runs in browsers with limited memory/cache visibility
        pub const CACHED_FFT_LOG_SIZE: u32 = 15;
    } else {
        // Generic fallback
        pub const CACHED_FFT_LOG_SIZE: u32 = 16;
    }
}

pub const MIN_FFT_LOG_SIZE: u32 = 5;

// TODO(andrew): FFTs return a redundant representation, that can get the value P. need to deal with
// it. Either: reduce before commitment or regenerate proof with new seed if redundant value
// decommitted.

/// Transposes the SIMD vectors in the given array.
///
/// Swaps the bit index abc <-> cba, where |a|=|c| and |b| = 0 or 1, according to the parity of
/// `log_n_vecs`.
/// When log_n_vecs is odd, transforms the index abc <-> cba, w
///
/// # Arguments
///
/// - `values`: A mutable pointer to the values that are to be transposed.
/// - `log_n_vecs`: The log of the number of SIMD vectors in the `values` array.
///
/// # Safety
///
/// Behavior is undefined if `values` does not have the same alignment as [`u32x16`].
pub unsafe fn transpose_vecs(values: *mut u32, log_n_vecs: usize) {
    // Use blocked transpose for large arrays to improve cache locality.
    // For small arrays, the simple approach has less overhead.
    if log_n_vecs >= BLOCKED_TRANSPOSE_THRESHOLD {
        transpose_vecs_blocked(values, log_n_vecs);
    } else {
        transpose_vecs_simple(values, log_n_vecs);
    }
}

/// Simple transpose implementation for small arrays.
/// This is faster for small arrays due to lower overhead.
#[inline(always)]
unsafe fn transpose_vecs_simple(values: *mut u32, log_n_vecs: usize) {
    let half = log_n_vecs / 2;

    let values = UnsafeMut(values);
    parallel_iter!(0..1 << half).for_each(|a| {
        let values = values.get();
        for b in 0..1 << (log_n_vecs & 1) {
            for c in 0..1 << half {
                let i = (a << (log_n_vecs - half)) | (b << half) | c;
                let j = (c << (log_n_vecs - half)) | (b << half) | a;
                if i >= j {
                    continue;
                }
                let val0 = load(values.add(i << 4).cast_const());
                let val1 = load(values.add(j << 4).cast_const());
                store(values.add(i << 4), val1);
                store(values.add(j << 4), val0);
            }
        }
    });
}

/// Blocked transpose implementation for large arrays.
///
/// Processes the transpose in cache-friendly blocks to improve memory access patterns.
/// The matrix is conceptually divided into blocks of size TRANSPOSE_BLOCK_SIZE x
/// TRANSPOSE_BLOCK_SIZE. We process:
/// - Diagonal blocks: only swap where a < c (triangular part)
/// - Off-diagonal blocks: swap all pairs in block (a_block, c_block) where a_block < c_block
///
/// This ensures that memory accesses within each block are localized, improving L1/L2 cache hit
/// rates.
unsafe fn transpose_vecs_blocked(values: *mut u32, log_n_vecs: usize) {
    let half = log_n_vecs / 2;
    let n: usize = 1 << half;
    let block_size = TRANSPOSE_BLOCK_SIZE;
    let n_blocks = n.div_ceil(block_size);

    let values = UnsafeMut(values);

    // Process blocks in parallel. Each block is independent.
    // We iterate over block pairs (a_block, c_block) where a_block <= c_block.
    // For a_block < c_block: process all (a, c) pairs in the blocks
    // For a_block == c_block: process only (a, c) pairs where a < c (diagonal block)
    parallel_iter!(0..n_blocks).for_each(|a_block| {
        let values = values.get();
        let a_start = a_block * block_size;
        let a_end = (a_start + block_size).min(n);

        for c_block in a_block..n_blocks {
            let c_start = c_block * block_size;
            let c_end = (c_start + block_size).min(n);

            // Process this block for all b values
            for b in 0..1 << (log_n_vecs & 1) {
                let params = BlockParams {
                    values,
                    log_n_vecs,
                    half,
                    b,
                    a_start,
                    a_end,
                    c_start,
                    c_end,
                };
                if a_block == c_block {
                    // Diagonal block: only process pairs where a < c
                    transpose_block_diagonal(&params);
                } else {
                    // Off-diagonal block: process all pairs
                    transpose_block_full(&params);
                }
            }
        }
    });
}

/// Parameters for processing a transpose block.
struct BlockParams {
    /// Pointer to the values array.
    values: *mut u32,
    /// Log of the number of vectors.
    log_n_vecs: usize,
    /// Half of log_n_vecs.
    half: usize,
    /// The b index (0 or 1 for odd log_n_vecs).
    b: usize,
    /// Start of a range.
    a_start: usize,
    /// End of a range (exclusive).
    a_end: usize,
    /// Start of c range.
    c_start: usize,
    /// End of c range (exclusive).
    c_end: usize,
}

/// Process a diagonal block (a_block == c_block) where we only swap pairs with a < c.
#[inline(always)]
unsafe fn transpose_block_diagonal(p: &BlockParams) {
    for a in p.a_start..p.a_end {
        // For diagonal blocks, c starts after a to ensure a < c
        let c_loop_start = if p.c_start <= a { a + 1 } else { p.c_start };
        for c in c_loop_start..p.c_end {
            let i = (a << (p.log_n_vecs - p.half)) | (p.b << p.half) | c;
            let j = (c << (p.log_n_vecs - p.half)) | (p.b << p.half) | a;

            // Prefetch next iteration's data to hide memory latency.
            if c + 2 < p.c_end {
                let next_i = (a << (p.log_n_vecs - p.half)) | (p.b << p.half) | (c + 2);
                let next_j = ((c + 2) << (p.log_n_vecs - p.half)) | (p.b << p.half) | a;
                prefetch_read(p.values.add(next_i << 4));
                prefetch_read(p.values.add(next_j << 4));
            }

            let val0 = load(p.values.add(i << 4).cast_const());
            let val1 = load(p.values.add(j << 4).cast_const());
            store(p.values.add(i << 4), val1);
            store(p.values.add(j << 4), val0);
        }
    }
}

/// Process an off-diagonal block (a_block < c_block) where we swap all pairs.
#[inline(always)]
unsafe fn transpose_block_full(p: &BlockParams) {
    for a in p.a_start..p.a_end {
        for c in p.c_start..p.c_end {
            let i = (a << (p.log_n_vecs - p.half)) | (p.b << p.half) | c;
            let j = (c << (p.log_n_vecs - p.half)) | (p.b << p.half) | a;

            // Prefetch next iteration's data to hide memory latency.
            // Prefetch 2 iterations ahead for better latency hiding.
            if c + 2 < p.c_end {
                let next_i = (a << (p.log_n_vecs - p.half)) | (p.b << p.half) | (c + 2);
                let next_j = ((c + 2) << (p.log_n_vecs - p.half)) | (p.b << p.half) | a;
                prefetch_read(p.values.add(next_i << 4));
                prefetch_read(p.values.add(next_j << 4));
            }

            let val0 = load(p.values.add(i << 4).cast_const());
            let val1 = load(p.values.add(j << 4).cast_const());
            store(p.values.add(i << 4), val1);
            store(p.values.add(j << 4), val0);
        }
    }
}

/// Prefetch data for reading. This is a hint to the CPU to load data into cache.
/// Uses architecture-specific intrinsics when available.
#[inline(always)]
unsafe fn prefetch_read(ptr: *const u32) {
    cfg_if::cfg_if! {
        if #[cfg(all(target_arch = "x86_64", target_feature = "sse"))] {
            use std::arch::x86_64::{_mm_prefetch, _MM_HINT_T0};
            _mm_prefetch(ptr as *const i8, _MM_HINT_T0);
        } else if #[cfg(all(target_arch = "aarch64", target_feature = "neon"))] {
            // ARM prefetch using inline assembly
            std::arch::asm!(
                "prfm pldl1keep, [{ptr}]",
                ptr = in(reg) ptr,
                options(nostack, preserves_flags)
            );
        } else {
            // No-op on other architectures
            let _ = ptr;
        }
    }
}

/// Computes the twiddles for the first fft layer from the second, and loads both to SIMD registers.
///
/// Returns the twiddles for the first layer and the twiddles for the second layer.
pub fn compute_first_twiddles(twiddle1_dbl: u32x8) -> (u32x16, u32x16) {
    // Start by loading the twiddles for the second layer (layer 1):
    let t1 = simd_swizzle!(
        twiddle1_dbl,
        twiddle1_dbl,
        [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
    );

    // The twiddles for layer 0 can be computed from the twiddles for layer 1.
    // Since the twiddles are bit reversed, we consider the circle domain in bit reversed order.
    // Each consecutive 4 points in the bit reversed order of a coset form a circle coset of size 4.
    // A circle coset of size 4 in bit reversed order looks like this:
    //   [(x, y), (-x, -y), (y, -x), (-y, x)]
    // Note: This is related to the choice of M31_CIRCLE_GEN, and the fact the a quarter rotation
    //   is (0,-1) and not (0,1). (0,1) would yield another relation.
    // The twiddles for layer 0 are the y coordinates:
    //   [y, -y, -x, x]
    // The twiddles for layer 1 in bit reversed order are the x coordinates:
    //   [x, y]
    // Works also for inverse of the twiddles.

    // The twiddles for layer 0 are computed like this:
    //   t0[4i:4i+3] = [t1[2i+1], -t1[2i+1], -t1[2i], t1[2i]]
    // Xoring a double twiddle with P*2 transforms it to the double of it negation.
    // Note that this keeps the values as a double of a value in the range [0, P].
    const P2: u32 = P * 2;
    const NEGATION_MASK: u32x16 =
        u32x16::from_array([0, P2, P2, 0, 0, P2, P2, 0, 0, P2, P2, 0, 0, P2, P2, 0]);
    let t0 = simd_swizzle!(
        t1,
        [
            0b0001, 0b0001, 0b0000, 0b0000, 0b0011, 0b0011, 0b0010, 0b0010, 0b0101, 0b0101, 0b0100,
            0b0100, 0b0111, 0b0111, 0b0110, 0b0110,
        ]
    ) ^ NEGATION_MASK;
    (t0, t1)
}

#[inline]
const unsafe fn load(mem_addr: *const u32) -> u32x16 {
    std::ptr::read(mem_addr as *const u32x16)
}

#[inline]
const unsafe fn store(mem_addr: *mut u32, a: u32x16) {
    std::ptr::write(mem_addr as *mut u32x16, a);
}

/// Computes `v * twiddle`
fn mul_twiddle(v: PackedBaseField, twiddle_dbl: u32x16) -> PackedBaseField {
    // TODO: Come up with a better approach than `cfg`ing on target_feature.
    // TODO: Ensure all these branches get tested in the CI.
    cfg_if::cfg_if! {
        if #[cfg(all(target_arch = "aarch64", target_feature = "neon"))] {
            // TODO: For architectures that when multiplying require doubling then the twiddles
            // should be precomputed as double. For other architectures, the twiddle should be
            // precomputed without doubling.
            crate::prover::backend::simd::m31::mul_doubled_neon(v, twiddle_dbl)
        } else if #[cfg(all(target_arch = "wasm32", target_feature = "simd128"))] {
            crate::prover::backend::simd::m31::mul_doubled_wasm(v, twiddle_dbl)
        } else if #[cfg(all(target_arch = "x86_64", target_feature = "avx512f"))] {
            crate::prover::backend::simd::m31::mul_doubled_avx512(v, twiddle_dbl)
        } else if #[cfg(all(target_arch = "x86_64", target_feature = "avx2"))] {
            crate::prover::backend::simd::m31::mul_doubled_avx2(v, twiddle_dbl)
        } else {
            crate::prover::backend::simd::m31::mul_doubled_simd(v, twiddle_dbl)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::mem::transmute;

    use rand::rngs::SmallRng;
    use rand::{Rng, SeedableRng};

    use super::{transpose_vecs, BLOCKED_TRANSPOSE_THRESHOLD};
    use crate::core::fields::m31::BaseField;
    use crate::prover::backend::simd::m31::{PackedBaseField, N_LANES};

    /// Test transpose_vecs for sizes below and above the blocked threshold.
    /// Verifies that both simple and blocked transpose produce the same result.
    #[test]
    fn test_transpose_vecs_correctness() {
        // Test a range of sizes including both simple and blocked paths
        for log_n_vecs in 6..=BLOCKED_TRANSPOSE_THRESHOLD + 2 {
            let n_vecs: usize = 1 << log_n_vecs;
            let mut rng = SmallRng::seed_from_u64(log_n_vecs as u64);

            // Create test data - use BaseField values
            let values: Vec<PackedBaseField> = (0..n_vecs)
                .map(|_| {
                    let arr: [BaseField; N_LANES] = rng.gen();
                    PackedBaseField::from_array(arr)
                })
                .collect();

            // Compute expected result using reference implementation
            let expected = reference_transpose(&values, log_n_vecs);

            // Test our implementation
            let mut result = values.clone();
            unsafe {
                transpose_vecs(
                    transmute::<*mut PackedBaseField, *mut u32>(result.as_mut_ptr()),
                    log_n_vecs,
                );
            }

            // Compare by converting to arrays
            for (i, (r, e)) in result.iter().zip(expected.iter()).enumerate() {
                assert_eq!(
                    r.to_array(),
                    e.to_array(),
                    "Transpose mismatch at log_n_vecs={log_n_vecs}, index={i}"
                );
            }
        }
    }

    /// Reference implementation of transpose for testing.
    fn reference_transpose(values: &[PackedBaseField], log_n_vecs: usize) -> Vec<PackedBaseField> {
        let mut result = values.to_vec();
        let half = log_n_vecs / 2;

        for a in 0..1 << half {
            for b in 0..1 << (log_n_vecs & 1) {
                for c in 0..1 << half {
                    let i = (a << (log_n_vecs - half)) | (b << half) | c;
                    let j = (c << (log_n_vecs - half)) | (b << half) | a;
                    if i < j {
                        result.swap(i, j);
                    }
                }
            }
        }

        result
    }

    /// Test that the blocked transpose produces identical results to simple transpose.
    #[test]
    fn test_blocked_vs_simple_transpose() {
        // Test at the threshold boundary
        let log_n_vecs = BLOCKED_TRANSPOSE_THRESHOLD;
        let n_vecs: usize = 1 << log_n_vecs;
        let mut rng = SmallRng::seed_from_u64(42);

        let values: Vec<PackedBaseField> = (0..n_vecs)
            .map(|_| {
                let arr: [BaseField; N_LANES] = rng.gen();
                PackedBaseField::from_array(arr)
            })
            .collect();

        // Compute using simple transpose (by temporarily calling it directly)
        let mut simple_result = values.clone();
        unsafe {
            super::transpose_vecs_simple(
                transmute::<*mut PackedBaseField, *mut u32>(simple_result.as_mut_ptr()),
                log_n_vecs,
            );
        }

        // Compute using blocked transpose
        let mut blocked_result = values.clone();
        unsafe {
            super::transpose_vecs_blocked(
                transmute::<*mut PackedBaseField, *mut u32>(blocked_result.as_mut_ptr()),
                log_n_vecs,
            );
        }

        // Compare by converting to arrays
        for (i, (s, b)) in simple_result.iter().zip(blocked_result.iter()).enumerate() {
            assert_eq!(
                s.to_array(),
                b.to_array(),
                "Simple vs blocked transpose mismatch at index={i}"
            );
        }
    }
}
