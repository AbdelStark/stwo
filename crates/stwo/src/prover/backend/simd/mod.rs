use serde::{Deserialize, Serialize};

use super::{Backend, BackendForChannel};
use crate::core::vcs::blake2_merkle::{Blake2sM31MerkleChannel, Blake2sMerkleChannel};
#[cfg(not(target_arch = "wasm32"))]
use crate::core::vcs::poseidon252_merkle::Poseidon252MerkleChannel;

pub mod accumulation;
pub mod bit_reverse;
pub mod blake2s;
#[cfg(test)]
pub mod blake2s_ref;
pub mod buffer_pool;
pub mod circle;
pub mod cm31;
pub mod column;
pub mod conversion;
pub mod domain;
pub mod fft;
pub mod fri;
mod grind;
pub mod lookups;
pub mod m31;
#[cfg(not(target_arch = "wasm32"))]
pub mod poseidon252;
pub mod prefix_sum;
pub mod qm31;
pub mod quotients;
mod utils;
pub mod very_packed_m31;

#[derive(Copy, Clone, Debug, Deserialize, Serialize)]
pub struct SimdBackend;

impl Backend for SimdBackend {}
impl BackendForChannel<Blake2sMerkleChannel> for SimdBackend {}
impl BackendForChannel<Blake2sM31MerkleChannel> for SimdBackend {}
#[cfg(not(target_arch = "wasm32"))]
impl BackendForChannel<Poseidon252MerkleChannel> for SimdBackend {}

// Optimal chunk sizes determined empirically and tuned per architecture.
// The chunk size affects cache efficiency during batch inversion - larger chunks
// reduce function call overhead but may cause cache thrashing if they exceed L1/L2.
//
// Architecture-specific tuning rationale:
// - AVX512 (server CPUs): Larger caches (1-2MB L2), can handle larger chunks
// - AVX2 (consumer CPUs): Moderate L2 (256KB-512KB), use medium chunks
// - NEON (ARM64): Varies widely, conservative defaults for portability
// - WASM/Generic: Conservative values for broad compatibility
cfg_if::cfg_if! {
    if #[cfg(all(target_arch = "x86_64", target_feature = "avx512f"))] {
        // AVX512 typically found on Xeon/high-end CPUs with large caches
        // M31: 2048 elements * 64 bytes = 128KB fits in L2
        // CM31: 2048 elements * 128 bytes = 256KB fits in L2
        // QM31: 4096 elements * 256 bytes = 1MB fits in L2
        pub(super) const PACKED_M31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 11;
        pub(super) const PACKED_CM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 11;
        pub(super) const PACKED_QM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 12;
    } else if #[cfg(all(target_arch = "x86_64", target_feature = "avx2"))] {
        // AVX2 on consumer CPUs with moderate caches (256KB-512KB L2)
        // Keep original Intel 155u tuned values as baseline
        pub(super) const PACKED_M31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 9;
        pub(super) const PACKED_CM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 10;
        pub(super) const PACKED_QM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 11;
    } else if #[cfg(all(target_arch = "aarch64", target_feature = "neon"))] {
        // ARM64 NEON: Conservative values for broad compatibility
        // Apple Silicon has large caches but many ARM chips have smaller ones
        pub(super) const PACKED_M31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 9;
        pub(super) const PACKED_CM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 10;
        pub(super) const PACKED_QM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 11;
    } else {
        // WASM and generic fallback: use conservative values
        pub(super) const PACKED_M31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 9;
        pub(super) const PACKED_CM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 10;
        pub(super) const PACKED_QM31_BATCH_INVERSE_CHUNK_SIZE: usize = 1 << 11;
    }
}
