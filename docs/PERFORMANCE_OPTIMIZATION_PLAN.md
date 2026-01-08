# STWO Prover Performance Optimization Plan

## Executive Summary

This document presents a comprehensive performance optimization plan for the STWO Circle STARK prover, based on extensive analysis of the codebase. The optimizations are prioritized by expected impact and implementation complexity, targeting a **2-5x overall proving speedup** through a combination of algorithmic improvements, memory optimizations, enhanced SIMD utilization, and better parallelization.

---

## Table of Contents

1. [Performance Profile Overview](#1-performance-profile-overview)
2. [Critical Path Analysis](#2-critical-path-analysis)
3. [Tier 1: High-Impact Optimizations](#3-tier-1-high-impact-optimizations)
4. [Tier 2: Medium-Impact Optimizations](#4-tier-2-medium-impact-optimizations)
5. [Tier 3: Lower-Impact Optimizations](#5-tier-3-lower-impact-optimizations)
6. [Implementation Roadmap](#6-implementation-roadmap)
7. [Benchmarking Strategy](#7-benchmarking-strategy)
8. [Risk Assessment](#8-risk-assessment)

---

## 1. Performance Profile Overview

### 1.1 Proving Pipeline Breakdown

Based on code analysis and benchmark instrumentation, the proving pipeline distributes computational cost approximately as follows:

| Stage | Estimated Cost | Key Operations |
|-------|---------------|----------------|
| FFT/IFFT Operations | 40-50% | Circle polynomial evaluation, interpolation |
| Constraint Evaluation | 15-25% | Domain accumulation, QM31 field operations |
| FRI Commitment | 10-15% | Folding, layer commitments |
| Merkle Tree Construction | 8-12% | Blake2s/Blake3 hashing |
| Quotient Computation | 5-10% | Denominator inversion, numerator accumulation |
| Proof of Work | 2-5% | Hash grinding (configurable) |
| Other | 5-10% | Channel operations, serialization |

### 1.2 Memory Bandwidth Characteristics

The prover is fundamentally **memory-bandwidth bound** for large proofs:

- **Arithmetic Intensity**: ~6 operations per byte for FFT (log n / 4)
- **Working Set Sizes**: 64MB-1GB for typical proofs (2^24-2^28 elements)
- **Cache Pressure**: FFT transpose operations stress L3 cache

### 1.3 Current SIMD Utilization

| Component | Vectorization Quality | Notes |
|-----------|----------------------|-------|
| M31 Field Ops | Excellent (9/10) | Platform-specific multiplies |
| CM31/QM31 Ops | Very Good (8/10) | Karatsuba optimization |
| FFT Core | Excellent (9/10) | 16-lane vectorization |
| Bit Reversal | Good (7/10) | Hierarchical approach |
| Blake2s | Good (7/10) | 16-hash parallel |
| Poseidon252 | Poor (3/10) | **Scalar-only** |
| FRI Folding | Good (7/10) | Falls back for small sizes |

---

## 2. Critical Path Analysis

### 2.1 FFT Hot Spots

**Location**: `crates/stwo/src/prover/backend/simd/fft/`

The FFT implementation uses a sophisticated multi-stage strategy:
1. Lower layers with vecwise operations (within SIMD vectors)
2. Transpose operation for cache efficiency
3. Upper layers (cross-vector operations)

**Critical Bottleneck**: The transpose operation (`transpose_vecs`) can consume 30-50% of FFT time for large transforms (>2^22 elements).

```
File: fft/mod.rs:35-57
Issue: Transpose involves O(n) memory movement with poor cache locality
```

### 2.2 FRI Folding Allocations

**Location**: `crates/stwo/src/prover/fri.rs:58-59`

```rust
// TODO(andrew): Make folding factor generic.
// TODO(andrew): Fold directly into FRI layer to prevent allocation.
```

Each FRI layer currently allocates a new buffer, then copies into the final layer. Direct folding would eliminate intermediate allocations.

### 2.3 Quotient Computation Inefficiencies

**Location**: `crates/stwo/src/prover/backend/simd/quotients.rs:85`

```rust
// TODO(Ohad): Try to optimize out all these copies.
```

The quotient extension loop involves multiple buffer copies that could be eliminated with better memory management.

---

## 3. Tier 1: High-Impact Optimizations

### 3.1 FFT Transpose Optimization

**Expected Impact**: 10-20% overall speedup
**Complexity**: Medium
**Location**: `prover/backend/simd/fft/mod.rs`

#### Problem
The current transpose uses a naive swapping pattern that causes cache thrashing for large FFTs.

#### Solution
Implement **blocked transpose** with explicit cache-line management:

```rust
// Proposed approach:
// 1. Process in blocks that fit L1/L2 cache (32KB-256KB)
// 2. Use prefetch instructions for upcoming blocks
// 3. Consider SIMD shuffle instructions for in-register transposition
```

**Implementation Steps**:
1. Profile transpose to establish baseline
2. Implement blocked transpose with configurable block size
3. Add prefetch hints using `_mm_prefetch` (AVX) or `PRFM` (NEON)
4. Benchmark across different problem sizes
5. Auto-tune block size based on detected cache size

### 3.2 FRI Direct Folding

**Expected Impact**: 5-10% overall speedup
**Complexity**: Medium
**Location**: `prover/fri.rs`, `prover/backend/simd/fri.rs`

#### Problem
Current implementation: `fold_circle_into_line` allocates output, then it's accumulated into the layer.

#### Solution
Modify folding functions to accumulate directly into destination buffer:

```rust
// Current signature:
fn fold_circle_into_line(
    dst: &mut LineEvaluation<Self>,
    src: &SecureEvaluation<Self, BitReversedOrder>,
    alpha: SecureField,
    twiddles: &TwiddleTree<Self>,
);

// Proposed: Add accumulation mode
fn fold_circle_into_line_accumulate(
    dst: &mut LineEvaluation<Self>,  // accumulate into existing
    src: &SecureEvaluation<Self, BitReversedOrder>,
    alpha: SecureField,
    alpha_sq: SecureField,  // precomputed alpha^2
    twiddles: &TwiddleTree<Self>,
);
```

**Implementation Steps**:
1. Add accumulation variant of fold functions
2. Modify `FriProver::commit_inner_layers` to use direct accumulation
3. Eliminate intermediate allocations in the folding loop
4. Validate correctness with existing tests

### 3.3 Poseidon252 SIMD Implementation

**Expected Impact**: 3-8% overall speedup (depending on workload)
**Complexity**: High
**Location**: `prover/backend/simd/poseidon252.rs:24`

```rust
// TODO(ShaharS): replace with SIMD implementation.
```

#### Problem
Poseidon252 Merkle hashing is purely scalar, missing 10-16x potential speedup from vectorization.

#### Solution
Implement vectorized Poseidon252 similar to the Blake2s SIMD implementation:

**Implementation Steps**:
1. Study starknet-crypto Poseidon252 internals
2. Design SIMD state layout (16 parallel Poseidon instances)
3. Implement vectorized round function using `PackedM31` operations
4. Handle domain separation and padding in parallel
5. Add platform-specific optimizations (AVX512, AVX2, NEON)

### 3.4 Quotient Computation Memory Optimization

**Expected Impact**: 3-6% overall speedup
**Complexity**: Medium
**Location**: `prover/backend/simd/quotients.rs`

#### Problem
Lines 85-98 perform multiple buffer copies during quotient extension:

```rust
// TODO(Ohad): Try to optimize out all these copies.
for (ci, &c) in subdomain_shifts.iter().enumerate() {
    // ... copies data multiple times
}
```

#### Solution
1. Pre-allocate unified output buffer
2. Compute twiddles for all shifts upfront
3. Use strided writes directly to final buffer
4. Consider fusing interpolation with extension

---

## 4. Tier 2: Medium-Impact Optimizations

### 4.1 Twiddle Factor Caching Improvements

**Expected Impact**: 2-5% overall speedup
**Complexity**: Low-Medium
**Location**: `prover/backend/simd/circle.rs:37, 81, 161`

#### Problems Identified

```rust
// circle.rs:37
// TODO(Ohad): optimize.

// circle.rs:81
// TODO(Ohad): optimize. consider changing the caller to expect the mappings in
// a different order for larger log sizes.

// circle.rs:161
// TODO(alont): Cache this inversion.
```

#### Solutions
1. **Cache twiddle inversions**: Pre-compute and store inverse twiddles alongside forward twiddles
2. **Optimize mapping order**: Restructure twiddle generation for better cache access patterns
3. **Lazy evaluation**: Compute twiddles on-demand for rarely-used sizes

### 4.2 Redundant Field Value Handling

**Expected Impact**: 1-3% overall speedup
**Complexity**: Low
**Location**: `prover/backend/simd/fft/mod.rs:18-20`

```rust
// TODO(andrew): FFTs return a redundant representation, that can get the value P.
// need to deal with it. Either: reduce before commitment or regenerate proof
// with new seed if redundant value decommitted.
```

#### Solution
Add explicit reduction pass after FFT when values will be committed:

```rust
// Add after FFT completion
fn reduce_to_canonical(values: &mut BaseColumn) {
    // Replace P values with 0 (they're equivalent mod P)
    for v in values.data.iter_mut() {
        *v = v.reduce_if_p();  // SIMD-friendly conditional
    }
}
```

### 4.3 Batch Inverse Optimization

**Expected Impact**: 1-3% overall speedup
**Complexity**: Low
**Location**: `prover/backend/simd/m31.rs`

The current batch inverse uses empirically-tuned chunk sizes:
- M31: 512 elements
- CM31: 1024 elements
- QM31: 2048 elements

#### Solution
1. Profile batch inverse across modern CPUs
2. Consider adaptive chunk sizing based on input size
3. Explore Montgomery batch inversion for better parallelism

### 4.4 Domain Iteration Optimization

**Expected Impact**: 2-4% overall speedup
**Complexity**: Medium
**Location**: `prover/backend/simd/quotients.rs:136`

```rust
// TODO(andrew): Spapini said: Use optimized domain iteration. Is there a better way to do this?
```

#### Solution
Replace generic domain iteration with specialized iterators:

```rust
// Current: General-purpose CircleDomainBitRevIterator
// Proposed: Specialized iterator that computes multiple point coordinates simultaneously
struct OptimizedDomainIterator {
    // Pre-compute y-values in batches of 64
    // Use SIMD to compute multiple twiddle lookups
}
```

### 4.5 FFT Butterfly-Permute Fusion

**Expected Impact**: 2-4% overall speedup
**Complexity**: Medium-High
**Location**: `prover/backend/simd/fft/rfft.rs:378`, `ifft.rs:339`

```rust
// TODO(andrew): Can the permute be fused with the _mm512_srli_epi64 inside the butterfly?
```

#### Solution
Investigate fusing the interleave/deinterleave permutation with the shift operation inside butterfly computations. This requires careful analysis of the instruction scheduling on different architectures.

---

## 5. Tier 3: Lower-Impact Optimizations

### 5.1 SecureField Bit Reversal

**Expected Impact**: 0.5-1% overall speedup
**Complexity**: Medium
**Location**: `prover/backend/simd/bit_reverse.rs:39-42`

```rust
// Currently: todo!() for SecureField bit reversal
```

Implement SIMD-accelerated bit reversal for QM31 columns to avoid CPU fallback.

### 5.2 GKR Code Deduplication

**Expected Impact**: Code quality (minimal performance)
**Complexity**: Low
**Location**: `prover/backend/simd/lookups/gkr.rs:198, 378`

```rust
// TODO(andrew): Code duplication of `next_logup_generic_layer`. Consider unifying these.
// TODO(andrew): Code duplication of `eval_logup_generic_sum`. Consider unifying these.
```

Refactor to eliminate duplication, potentially improving instruction cache utilization.

### 5.3 Sumcheck Coefficient Optimization

**Expected Impact**: 0.5-2% for GKR-heavy workloads
**Complexity**: Low
**Location**: `prover/lookups/sumcheck.rs:163`

```rust
// TODO: optimize this by sending one less coefficient, and computing it from the
```

Reduce communication complexity by deriving the last coefficient.

### 5.4 Memory Pool for Hot Allocations

**Expected Impact**: 1-2% overall speedup
**Complexity**: Medium

Implement a thread-local memory pool for frequently allocated structures:
- `SecureColumnByCoords`
- `LineEvaluation`
- Intermediate FFT buffers

### 5.5 Constraint Evaluation Vectorization

**Expected Impact**: 1-3% for constraint-heavy workloads
**Complexity**: Medium
**Location**: `crates/constraint-framework/src/`

Improve vectorization in the constraint framework's domain evaluators to better utilize SIMD for constraint checking.

---

## 6. Implementation Roadmap

### Phase 1: Quick Wins (1-2 weeks)

| Optimization | Est. Speedup | Effort |
|--------------|--------------|--------|
| Twiddle inversion caching | 1-2% | 2 days |
| Redundant value reduction | 1% | 1 day |
| Batch inverse tuning | 1% | 2 days |
| GKR deduplication | - | 1 day |

**Milestone**: 3-5% speedup with low-risk changes

### Phase 2: Core Optimizations (2-4 weeks)

| Optimization | Est. Speedup | Effort |
|--------------|--------------|--------|
| FRI direct folding | 5-10% | 1 week |
| Quotient memory optimization | 3-6% | 1 week |
| Domain iteration optimization | 2-4% | 3 days |

**Milestone**: 10-20% cumulative speedup

### Phase 3: FFT Deep Dive (3-4 weeks)

| Optimization | Est. Speedup | Effort |
|--------------|--------------|--------|
| Blocked transpose | 10-20% | 2 weeks |
| Butterfly-permute fusion | 2-4% | 1 week |
| Architecture-specific tuning | 2-5% | 1 week |

**Milestone**: 25-40% cumulative speedup

### Phase 4: Advanced Optimizations (4-6 weeks)

| Optimization | Est. Speedup | Effort |
|--------------|--------------|--------|
| Poseidon252 SIMD | 3-8% | 3 weeks |
| Memory pool implementation | 1-2% | 1 week |
| SecureField bit reversal | 0.5-1% | 3 days |

**Milestone**: 30-50% cumulative speedup

---

## 7. Benchmarking Strategy

### 7.1 Micro-Benchmarks

Existing Criterion benchmarks should be extended:

```bash
# Current benchmarks
./scripts/bench.sh fft        # FFT operations
./scripts/bench.sh merkle     # Merkle tree construction
./scripts/bench.sh fri        # FRI folding
./scripts/bench.sh quotients  # Quotient accumulation

# Proposed additions
./scripts/bench.sh transpose  # FFT transpose specifically
./scripts/bench.sh twiddles   # Twiddle computation
./scripts/bench.sh fold_acc   # FRI folding with accumulation
```

### 7.2 Integration Benchmarks

```bash
# Full prover benchmark
LOG_N_INSTANCES=18 ./poseidon_benchmark.sh

# Proposed: Parameterized benchmark suite
./scripts/bench_full.sh --log-size 20 --features parallel
./scripts/bench_full.sh --log-size 24 --features parallel
./scripts/bench_full.sh --log-size 28 --features parallel
```

### 7.3 Profiling Infrastructure

Recommended profiling tools:
- **perf**: CPU cycle analysis, cache misses
- **flamegraph**: Call stack visualization
- **LIKWID**: Memory bandwidth measurement
- **Intel VTune**: Deep microarchitecture analysis (x86)

```bash
# Example profiling workflow
RUSTFLAGS="-g" cargo build --release --features "prover,parallel"
perf record -g ./target/release/examples/poseidon_prover
perf report
```

### 7.4 Regression Testing

Implement CI performance regression checks:

```yaml
# .github/workflows/benchmark.yaml
- name: Run benchmarks
  run: ./scripts/bench.sh --save-baseline main

- name: Compare with baseline
  run: ./scripts/bench.sh --compare main
  # Fail if >5% regression
```

---

## 8. Risk Assessment

### 8.1 High-Risk Optimizations

| Optimization | Risk | Mitigation |
|--------------|------|------------|
| FFT transpose rewrite | Correctness | Extensive property-based testing |
| Poseidon252 SIMD | Complexity | Staged implementation, compatibility tests |
| Butterfly fusion | Platform-specific | Architecture-gated implementation |

### 8.2 Medium-Risk Optimizations

| Optimization | Risk | Mitigation |
|--------------|------|------------|
| FRI direct folding | API changes | Maintain backward compatibility |
| Memory pools | Thread safety | Use thread-local storage |
| Domain iteration | Correctness | Validate against CPU backend |

### 8.3 Low-Risk Optimizations

| Optimization | Risk | Mitigation |
|--------------|------|------------|
| Twiddle caching | Memory usage | Monitor memory consumption |
| Batch inverse tuning | Performance variance | A/B test on multiple CPUs |
| Code deduplication | None | Standard refactoring |

---

## Appendix A: Code Locations Reference

### FFT Implementation
- `crates/stwo/src/prover/backend/simd/fft/mod.rs` - Common utilities, transpose
- `crates/stwo/src/prover/backend/simd/fft/rfft.rs` - Forward FFT
- `crates/stwo/src/prover/backend/simd/fft/ifft.rs` - Inverse FFT

### FRI Implementation
- `crates/stwo/src/prover/fri.rs` - FRI prover orchestration
- `crates/stwo/src/prover/backend/simd/fri.rs` - SIMD FRI operations
- `crates/stwo/src/core/fri.rs` - Core FRI protocol

### Field Operations
- `crates/stwo/src/prover/backend/simd/m31.rs` - PackedM31 (692 lines)
- `crates/stwo/src/prover/backend/simd/cm31.rs` - PackedCM31
- `crates/stwo/src/prover/backend/simd/qm31.rs` - PackedQM31

### Commitment Schemes
- `crates/stwo/src/prover/pcs/mod.rs` - PCS orchestration
- `crates/stwo/src/prover/pcs/quotient_ops.rs` - Quotient computation
- `crates/stwo/src/prover/vcs/prover.rs` - Merkle tree prover

### Hash Functions
- `crates/stwo/src/prover/backend/simd/blake2s.rs` - SIMD Blake2s
- `crates/stwo/src/prover/backend/simd/poseidon252.rs` - Poseidon (scalar)

---

## Appendix B: TODOs from Codebase

The following TODOs were identified as optimization opportunities:

```
prover/fri.rs:58-59       - FRI folding factor & direct allocation
prover/backend/simd/fft/mod.rs:18-20  - Redundant FFT representation
prover/backend/simd/fft/rfft.rs:378   - Permute-shift fusion
prover/backend/simd/fft/ifft.rs:339   - Permute-shift fusion
prover/backend/simd/circle.rs:37,81   - Twiddle optimization
prover/backend/simd/circle.rs:161     - Cache twiddle inversion
prover/backend/simd/quotients.rs:85   - Copy elimination
prover/backend/simd/quotients.rs:136  - Domain iteration
prover/backend/simd/poseidon252.rs:24 - SIMD implementation
prover/backend/simd/m31.rs:81         - Double operation optimization
prover/backend/simd/grind.rs:24       - Support >32 bits
prover/lookups/sumcheck.rs:163        - Coefficient optimization
core/fri.rs:766,795                   - Twiddle buffer storage
```

---

## Appendix C: Platform-Specific Considerations

### x86_64 (AVX512)
- Full 16-lane M31 vectorization
- Best performance profile
- Consider AVX512IFMA for multiplication chains

### x86_64 (AVX2)
- 8-lane operations, doubled for 16 lanes
- Slightly lower throughput
- Fallback for older Intel/AMD

### ARM (NEON)
- Native 4-lane, quadrupled for 16 lanes
- Consider Apple Silicon optimizations (M1/M2/M3)
- SVE/SVE2 investigation for newer ARM

### WASM32
- 4-lane SIMD128
- Significant overhead vs native
- Focus on correctness over performance

---

*Document Version: 1.0*
*Last Updated: 2026-01-07*
*Author: Performance Analysis Team*
