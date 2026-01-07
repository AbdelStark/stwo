# CLAUDE.md - Agentic Context for STWO

<overview>
STWO is StarkWare's next-generation Circle STARK prover and verifier implementation in Rust.
It implements the CSTARK protocol (https://eprint.iacr.org/2024/278) with high-performance
SIMD optimizations for cryptographic proof generation.
</overview>

<stack>
- **Language**: Rust (nightly required)
- **Toolchain**: `nightly-2025-07-14` (see `rust-toolchain.toml`)
- **Build**: Cargo workspace with 6 crates
- **Package Manager**: Cargo
- **CI**: GitHub Actions
- **Targets**: Native (AVX512/AVX2/NEON), WASM32, no_std
</stack>

<structure>
```
stwo/
├── crates/
│   ├── stwo/              # Core prover/verifier library
│   │   ├── src/core/      # Core types, fields, polynomials, VCS
│   │   ├── src/prover/    # Prover implementation (feature-gated)
│   │   └── benches/       # Performance benchmarks
│   ├── constraint-framework/  # AIR constraint framework
│   ├── air-utils/         # AIR utilities
│   ├── air-utils-derive/  # Procedural macros for AIR
│   ├── examples/          # Example implementations (poseidon, blake, etc.)
│   └── std-shims/         # no_std compatibility shims
├── ensure-verifier-no_std/  # Ensures verifier builds in no_std (excluded from workspace)
├── scripts/               # CI and development scripts
└── resources/             # Assets
```

**Where to add code:**
- Core prover logic: `crates/stwo/src/prover/`
- Core types/fields: `crates/stwo/src/core/`
- Constraint framework: `crates/constraint-framework/src/`
- New examples: `crates/examples/src/`
- New benchmarks: `crates/stwo/benches/`
</structure>

<quickstart>
```bash
# Install (workspace)
cargo build --workspace

# Build with prover features
cargo build --features prover

# Build with all features (parallel + prover + tracing)
cargo build --all-features

# Run tests (basic)
cargo test --features prover

# Run tests with parallelism
cargo test --features "parallel,prover"

# Run slow tests (release mode required)
cargo test --release --features "slow-tests,prover"

# Lint
./scripts/clippy.sh

# Format
./scripts/rust_fmt.sh

# Format check (CI-style)
./scripts/rust_fmt.sh --check

# Benchmarks
./scripts/bench.sh                    # All benchmarks
./scripts/bench.sh M31                # Filter by name
./scripts/bench.sh --features parallel  # With parallel

# Poseidon benchmark (single-threaded proof benchmark)
./poseidon_benchmark.sh

# Generate docs
cargo doc --open
```
</quickstart>

<features>
**Cargo Features (stwo crate):**
- `std` (default): Standard library support
- `prover`: Enables prover code (requires nightly features)
- `parallel`: Enables Rayon parallelism
- `tracing`: Enables tracing instrumentation
- `slow-tests`: Enables expensive integration tests

**Common feature combinations:**
- `--features prover` - Development with prover
- `--features "prover,parallel"` - Parallel prover
- `--all-features` - Everything (CI full test)
- `--no-default-features` - no_std verifier only
</features>

<workflow>
**Feature development:**
1. Create branch from `dev`
2. Make changes in appropriate crate
3. Run `cargo test --features prover`
4. Run `./scripts/clippy.sh`
5. Run `./scripts/rust_fmt.sh`
6. If performance-critical: run `./scripts/bench.sh` to check regression
7. Commit with descriptive message
8. Push and create PR against `dev`

**Bug fixes:**
1. Write failing test first
2. Fix the bug
3. Verify all tests pass: `cargo test --features prover`
4. Run clippy and format checks
5. Commit and push

**Verification checklist (before "done"):**
- [ ] `cargo test --features prover` passes
- [ ] `./scripts/clippy.sh` passes
- [ ] `./scripts/rust_fmt.sh --check` passes
- [ ] If public API changed: `cargo doc` builds without warnings
- [ ] If no_std affected: `cd ensure-verifier-no_std && cargo build -r`
</workflow>

<constraints>
**Performance:**
- This is a performance-critical cryptographic library
- Avoid unnecessary allocations in hot paths
- Consider SIMD implications for any field/polynomial operations
- Run benchmarks for any changes to core algorithms

**Rust Nightly:**
- Nightly features used: `array_chunks`, `iter_array_chunks`, `portable_simd`, `slice_ptr_get`
- AVX512 uses `stdarch_x86_avx512` feature
- Must maintain compatibility with specified nightly version

**no_std Compatibility:**
- Core verifier must work in no_std environments
- Use `std-shims` crate for compatibility
- Test with `cd ensure-verifier-no_std && cargo build -r`

**Dependencies:**
- Minimize new dependencies
- All deps must support no_std (or be feature-gated)
- Workspace dependencies defined in root `Cargo.toml`
</constraints>

<security>
- This is cryptographic code - correctness is paramount
- No unsafe code without thorough justification
- Field arithmetic must be constant-time where relevant
- No secrets in code or logs
</security>

<forbidden_files>
**Do not edit:**
- `Cargo.lock` - Managed by Cargo
- `rust-toolchain.toml` - Toolchain version is coordinated
- `.github/workflows/*` - CI configuration (edit with extreme care)
- `ensure-verifier-no_std/` - Validation crate, rarely needs changes

**Edit with care:**
- `Cargo.toml` (root) - Workspace configuration
- `.cargo/config.toml` - Build configuration
- `scripts/*` - CI scripts (changes affect all PRs)
</forbidden_files>

<context_sources>
**Truth sources (in priority order):**
1. `Cargo.toml` files - Dependencies, features, crate structure
2. `.github/workflows/ci.yaml` - Canonical CI commands
3. `scripts/` - Development scripts
4. `rust-toolchain.toml` - Required Rust version
5. Tests in `**/tests/` and inline `#[test]` - Expected behavior

**Finding things:**
- Grep for type/function: `grep -r "fn foo" crates/`
- Find file: `find crates -name "*.rs" | xargs grep -l "pattern"`
- List modules: `ls crates/stwo/src/core/`
</context_sources>

<testing>
**Test commands by scope:**
```bash
# Unit tests (fast)
cargo test --features prover --lib

# Integration tests
cargo test --features prover

# Specific test
cargo test --features prover test_name

# Slow tests (release required)
cargo test --release --features "slow-tests,prover"

# no_std verification
cd ensure-verifier-no_std && cargo build -r

# WASM tests (requires wasmtime)
cargo test --target wasm32-wasip1

# Constraint framework tests
cargo test --package stwo-constraint-framework --no-default-features
```

**Benchmark commands:**
```bash
# All benchmarks with native CPU optimization
./scripts/bench.sh

# Specific benchmark
./scripts/bench.sh fft

# With parallel feature
./scripts/bench.sh --features parallel
```
</testing>

<architecture>
**Core concepts:**
- **Fields**: M31, CM31, QM31 - Mersenne prime field and extensions
- **Polynomials**: Circle polynomials evaluated over cosets
- **VCS**: Vector Commitment Scheme (Merkle-based)
- **PCS**: Polynomial Commitment Scheme
- **FRI**: Fast Reed-Solomon Interactive Oracle Proof
- **AIR**: Algebraic Intermediate Representation for constraints

**Key modules:**
- `core::fields::` - Field implementations (M31, CM31, QM31)
- `core::poly::` - Polynomial operations
- `core::vcs::` - Vector commitment (Merkle trees)
- `prover::backend::` - SIMD backends (AVX512, AVX2, NEON, etc.)
- `prover::pcs::` - Polynomial commitment implementation
</architecture>

<notes_and_state>
**Agent working notes:**
- State files: `.claude/harness/state.md` (if created)
- Progress log: `.claude/harness/progress.log` (if created)

**Current focus areas:**
- Performance optimization
- SIMD backend improvements
- Constraint framework enhancements
</notes_and_state>
