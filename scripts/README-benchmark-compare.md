# STWO Performance Comparison Tool

A comprehensive tool for comparing benchmark performance between different versions of the STWO project.

## Features

- **Multiple comparison scenarios**:
  - Local version vs GitHub version
  - Two different GitHub versions (tags, branches, commits)
  - Versions from different forks

- **Automated workflow**:
  - Clones/prepares both versions
  - Runs benchmarks sequentially (to avoid interference)
  - Generates comprehensive HTML report

- **Rich HTML reports**:
  - Interactive charts (time comparison, percentage changes, by category)
  - Filterable detailed results table
  - Summary statistics with winner determination
  - Category-wise breakdown

## Requirements

- Rust toolchain (nightly)
- Git
- Python 3.6+
- `cargo-criterion` (installed automatically if missing)

## Usage

### Basic Usage

```bash
# Compare local version vs GitHub version
./scripts/benchmark-compare.sh \
    --local \
    --github https://github.com/starkware-libs/stwo --ref main

# Compare two GitHub tags
./scripts/benchmark-compare.sh \
    --github https://github.com/starkware-libs/stwo --ref v1.0.0 \
    --github https://github.com/starkware-libs/stwo --ref v2.0.0

# Compare different forks
./scripts/benchmark-compare.sh \
    --github https://github.com/fork1/stwo --ref feature-branch \
    --github https://github.com/fork2/stwo --ref main
```

### With Custom Names

```bash
./scripts/benchmark-compare.sh \
    --name "My Changes" --local \
    --name "Upstream Main" --github https://github.com/starkware-libs/stwo --ref main
```

### Filtering Benchmarks

```bash
# Only run FFT benchmarks
./scripts/benchmark-compare.sh \
    --local \
    --github https://github.com/starkware-libs/stwo --ref main \
    --filter fft

# Only run field operations benchmarks
./scripts/benchmark-compare.sh \
    --local \
    --github https://github.com/starkware-libs/stwo --ref main \
    --filter field
```

### With Parallel Feature

```bash
./scripts/benchmark-compare.sh \
    --local \
    --github https://github.com/starkware-libs/stwo --ref main \
    --features parallel
```

### Full Options

```
./scripts/benchmark-compare.sh --help

USAGE:
    benchmark-compare.sh [OPTIONS] VERSION1 VERSION2

VERSION SPECIFICATION:
    --local                     Use the current local repository as a version
    --github URL --ref REF      Use a GitHub repository at the specified ref
                                (ref can be a branch, tag, or commit hash)

OPTIONS:
    -o, --output DIR            Output directory for results (default: ./benchmark-results)
    -f, --filter PATTERN        Filter benchmarks by name pattern
    --features FEATURES         Additional Cargo features to enable (e.g., "parallel")
    -n, --name NAME             Custom name for the next version (for display)
    --warmup N                  Number of warmup runs before benchmarking (default: 0)
    --sample-size N             Custom sample size for criterion
    --no-cleanup                Don't remove temporary directories after completion
    -v, --verbose               Verbose output
    -h, --help                  Show this help message
```

## Output

After completion, the tool creates a timestamped directory in `benchmark-results/` containing:

```
benchmark-results/
└── 20240115_143022/
    ├── comparison_report.html   # Main HTML comparison report
    ├── version_a/
    │   ├── results.json         # Parsed benchmark results
    │   ├── bencher_output.txt   # Raw benchmark output
    │   └── criterion_reports/   # Criterion HTML reports (if available)
    ├── version_b/
    │   ├── results.json
    │   ├── bencher_output.txt
    │   └── criterion_reports/
    ├── version_0_info.json      # Version A metadata
    └── version_1_info.json      # Version B metadata
```

### Viewing the Report

```bash
# macOS
open benchmark-results/<timestamp>/comparison_report.html

# Linux
xdg-open benchmark-results/<timestamp>/comparison_report.html

# Or open in browser manually
```

## Report Features

### Summary Section
- Total benchmarks compared
- Count of benchmarks where each version is faster
- Mean percentage change
- Geometric mean speedup
- Overall winner determination

### Interactive Charts
1. **Time Comparison**: Side-by-side bar chart (log scale)
2. **Percentage Change**: Shows improvement/regression for each benchmark
3. **By Category**: Average performance change per benchmark category

### Detailed Results Table
- Sortable and filterable
- Filter by benchmark name, category, or change type
- Shows execution time, percentage change, and speedup ratio

### Category Breakdown
Categories automatically detected:
- FFT operations
- Field arithmetic
- Merkle tree operations
- FRI protocol
- PCS (Polynomial Commitment Scheme)
- Evaluation operations
- Bit reversal
- Lookups
- Quotients
- Prefix sum

## Interpreting Results

### Percentage Change
- **Negative** (green): Version A is faster
- **Positive** (red): Version B is faster
- **Near zero** (gray): Similar performance (within ±1%)

### Speedup Ratio
- `speedup = time_b / time_a`
- `> 1.0`: Version A is faster
- `< 1.0`: Version B is faster
- `= 1.0`: Same performance

## Examples

### Comparing a PR against main

```bash
# Assuming you're on a feature branch
./scripts/benchmark-compare.sh \
    --name "My PR" --local \
    --name "main" --github https://github.com/starkware-libs/stwo --ref main \
    --filter "fft\|field"  # Only test FFT and field operations for faster results
```

### Comparing two releases

```bash
./scripts/benchmark-compare.sh \
    --name "v1.0" --github https://github.com/starkware-libs/stwo --ref v1.0.0 \
    --name "v2.0" --github https://github.com/starkware-libs/stwo --ref v2.0.0
```

### Full benchmark suite with warmup

```bash
./scripts/benchmark-compare.sh \
    --local \
    --github https://github.com/starkware-libs/stwo --ref main \
    --warmup 2 \
    --features parallel
```

## Troubleshooting

### "cargo-criterion not found"
The tool automatically installs it, but you can also run:
```bash
cargo install cargo-criterion
```

### Benchmarks failing to compile
Ensure you have the correct Rust nightly version:
```bash
rustup override set nightly-2025-07-14
```

### Out of memory during benchmarks
Try filtering to run fewer benchmarks:
```bash
./scripts/benchmark-compare.sh --local --github ... --ref ... --filter fft
```

### Slow benchmark runs
- Use `--filter` to run specific benchmarks
- Consider using `--sample-size 10` for faster (but less accurate) results
