<div align="center">

![STWO](resources/img/logo.png)

[![CI](https://img.shields.io/github/actions/workflow/status/starkware-libs/stwo/ci.yaml?branch=dev&style=for-the-badge&logo=github&label=CI)](https://github.com/starkware-libs/stwo/actions/workflows/ci.yaml)
[![codecov](https://img.shields.io/codecov/c/github/starkware-libs/stwo?style=for-the-badge&logo=codecov)](https://codecov.io/gh/starkware-libs/stwo)
[![Crates.io](https://img.shields.io/crates/v/stwo?style=for-the-badge&logo=rust)](https://crates.io/crates/stwo)
[![docs.rs](https://img.shields.io/docsrs/stwo?style=for-the-badge&logo=docs.rs)](https://docs.rs/stwo)
[![License](https://img.shields.io/github/license/starkware-libs/stwo?style=for-the-badge)](LICENSE)

**A high-performance Circle STARK prover and verifier**

[Paper](https://eprint.iacr.org/2024/278) | [Documentation](https://docs.rs/stwo) | [Benchmarks](https://starkware-libs.github.io/stwo/dev/bench/index.html)

</div>

---

## Overview

STWO is StarkWare's next-generation implementation of the [Circle STARK](https://eprint.iacr.org/2024/278) (CSTARK) protocol. It provides a complete prover and verifier for STARKs over the Mersenne31 prime field, with native SIMD acceleration for AVX512, AVX2, NEON, and WebAssembly SIMD128.

Circle STARKs operate over the circle group of the Mersenne31 field rather than multiplicative subgroups, enabling efficient proof generation with a 31-bit prime that maps well to modern CPU architectures.

### Status

> **Development**: STWO is under active development. The API is not yet stable and breaking changes may occur between versions. Production deployment should be preceded by thorough security review.

## Features

- **Circle STARK Protocol**: Implementation of the CSTARK protocol from [Circle STARKs](https://eprint.iacr.org/2024/278)
- **Mersenne31 Field Arithmetic**: Optimized operations over M31 (p = 2³¹ - 1) and its extensions CM31 and QM31
- **SIMD Backends**: Native acceleration for AVX512, AVX2, ARM NEON, and WASM SIMD128
- **FRI Protocol**: Fast Reed-Solomon Interactive Oracle Proof of Proximity
- **Constraint Framework**: Algebraic Intermediate Representation (AIR) for defining computation constraints
- **GKR Lookups**: Grand Product argument with GKR protocol for efficient lookup arguments
- **Merkle Commitments**: Blake2s, Blake3, and Poseidon252 hash-based vector commitments
- **no_std Support**: Verifier operates in no_std environments for embedded and blockchain use cases
- **Parallel Proving**: Optional Rayon-based parallelism for multi-core proving

## Installation

Add STWO to your `Cargo.toml`:

```toml
[dependencies]
stwo = "0.1"
```

### Feature Flags

| Feature | Description | Default |
|---------|-------------|---------|
| `std` | Standard library support | Yes |
| `prover` | Enables prover functionality (requires nightly Rust) | No |
| `parallel` | Enables Rayon-based parallelism | No |
| `tracing` | Enables tracing instrumentation | No |

Common configurations:

```toml
# Verifier only (stable Rust, no_std compatible)
stwo = { version = "0.1", default-features = false }

# Prover with parallelism (nightly Rust)
stwo = { version = "0.1", features = ["prover", "parallel"] }
```

### Requirements

- **Verifier**: Rust 1.88.0+ (stable)
- **Prover**: Rust nightly-2025-07-14 (see `rust-toolchain.toml`)

## Quick Start

### Verification (Stable Rust)

```rust
use stwo::core::channel::Blake2sChannel;
use stwo::core::pcs::CommitmentSchemeVerifier;
use stwo::core::verifier::verify;
use stwo::core::vcs::blake2_merkle::Blake2sMerkleChannel;

// Verify a proof
fn verify_proof(
    components: &[&dyn Component],
    proof: StarkProof<Blake2sHash>,
) -> Result<(), VerificationError> {
    let mut channel = Blake2sChannel::default();
    let mut commitment_scheme = CommitmentSchemeVerifier::<Blake2sMerkleChannel>::new();

    // Configure commitment scheme with column sizes...

    verify::<Blake2sMerkleChannel>(
        components,
        &mut channel,
        &mut commitment_scheme,
        proof,
    )
}
```

### Proving (Nightly Rust)

```rust
use stwo::prover::{prove, CommitmentSchemeProver, ComponentProver};
use stwo::prover::backend::simd::SimdBackend;

// Generate a proof
fn generate_proof<B: BackendForChannel<MC>, MC: MerkleChannel>(
    components: &[&dyn ComponentProver<B>],
    commitment_scheme: CommitmentSchemeProver<'_, B, MC>,
) -> Result<StarkProof<MC::H>, ProvingError> {
    let mut channel = MC::C::default();
    prove(components, &mut channel, commitment_scheme)
}
```

## Architecture

### Crate Structure

```
stwo/
├── crates/
│   ├── stwo/                    # Core prover and verifier
│   │   ├── src/core/            # Verifier, fields, polynomials, VCS
│   │   └── src/prover/          # Prover implementation
│   ├── constraint-framework/    # AIR constraint DSL
│   ├── air-utils/               # AIR utilities
│   ├── air-utils-derive/        # Procedural macros
│   ├── examples/                # Reference implementations
│   └── std-shims/               # no_std compatibility
└── ensure-verifier-no_std/      # no_std build verification
```

### Field Tower

STWO uses the Mersenne31 prime field and its extensions:

| Field | Description | Size |
|-------|-------------|------|
| **M31** | Base field, p = 2³¹ - 1 | 31 bits |
| **CM31** | M31[i] / (i² + 1), complex extension | 62 bits |
| **QM31** | CM31[u] / (u² - 2 - i), secure field | 124 bits |

The QM31 extension provides 124-bit security for cryptographic operations.

### Backend Architecture

```
Backend Trait
├── CpuBackend       # Scalar reference implementation
└── SimdBackend      # Vectorized implementation
    ├── AVX512       # 512-bit vectors (16 × M31)
    ├── AVX2         # 256-bit vectors (8 × M31)
    ├── NEON         # 128-bit vectors (4 × M31)
    └── WASM SIMD128 # 128-bit vectors (4 × M31)
```

## Building

```bash
# Build verifier only (stable Rust)
cargo build

# Build with prover (nightly Rust)
cargo build --features prover

# Build with all features
cargo build --all-features

# Build for no_std verification
cd ensure-verifier-no_std && cargo build --release
```

## Testing

```bash
# Unit tests
cargo test --features prover

# Tests with parallelism
cargo test --features "prover,parallel"

# Integration tests (release mode)
cargo test --release --features "prover,slow-tests"

# WASM tests
cargo test --target wasm32-wasip1

# no_std verification
cd ensure-verifier-no_std && cargo build --release
```

## Benchmarks

STWO includes comprehensive benchmarks for performance-critical operations.

```bash
# Run all benchmarks
./scripts/bench.sh

# Run specific benchmark
./scripts/bench.sh fft

# Run with parallelism
./scripts/bench.sh --features parallel

# Poseidon2 proof benchmark
./poseidon_benchmark.sh
```

Continuous benchmark results: [starkware-libs.github.io/stwo/dev/bench](https://starkware-libs.github.io/stwo/dev/bench/index.html)

## Examples

The `crates/examples/` directory contains reference implementations:

| Example | Description |
|---------|-------------|
| `poseidon` | Poseidon2 hash function proving |
| `blake` | Blake2s compression proving |
| `plonk` | PLONKish constraint system |
| `wide_fibonacci` | Wide Fibonacci trace |
| `xor` | XOR with GKR lookups |
| `state_machine` | State machine transitions |

## Development

### Code Quality

```bash
# Format code
./scripts/rust_fmt.sh

# Check formatting (CI mode)
./scripts/rust_fmt.sh --check

# Run clippy
./scripts/clippy.sh
```

### Documentation

```bash
# Generate and open documentation
cargo doc --open
```

## Security

STWO is cryptographic software. While we strive for correctness:

- **No Audit**: This code has not undergone formal security audit
- **No Warranty**: Provided "as is" without warranty of any kind
- **Report Issues**: Security issues should be reported via [security@starkware.co](mailto:security@starkware.co)

### Cryptographic Assumptions

- Mersenne31 field arithmetic correctness
- FRI soundness with configured parameters
- Collision resistance of underlying hash functions (Blake2s, Blake3, Poseidon252)

## Performance Considerations

- **SIMD**: Use AVX512 when available for optimal performance
- **Parallelism**: Enable the `parallel` feature for multi-core proving
- **Memory**: Proof generation is memory-intensive; size scales with trace size
- **Release Mode**: Always benchmark and deploy with `--release`

## References

1. **Circle STARKs**: Haböck, U., Papini, S., & Riabzev, L. (2024). *Circle STARKs*. Cryptology ePrint Archive, Paper 2024/278. [https://eprint.iacr.org/2024/278](https://eprint.iacr.org/2024/278)

2. **STARK Protocol**: Ben-Sasson, E., et al. (2018). *Scalable, transparent, and post-quantum secure computational integrity*. Cryptology ePrint Archive, Paper 2018/046.

3. **FRI Protocol**: Ben-Sasson, E., et al. (2018). *Fast Reed-Solomon Interactive Oracle Proofs of Proximity*. ICALP 2018.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

```
Copyright 2024 StarkWare Industries Ltd.
```

## Contributing

Contributions are welcome. Please ensure:

1. Code passes `cargo test --features prover`
2. Code passes `./scripts/clippy.sh`
3. Code is formatted with `./scripts/rust_fmt.sh`
4. Documentation builds with `cargo doc`
5. no_std compatibility is maintained: `cd ensure-verifier-no_std && cargo build -r`

---

<div align="center">

Built by [StarkWare](https://starkware.co)

</div>
