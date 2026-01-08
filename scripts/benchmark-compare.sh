#!/bin/bash
#
# Performance Comparison Tool for STWO
# =====================================
# Compare performance between two versions of the STWO project.
#
# Usage Examples:
#   1. Compare local version vs GitHub version:
#      ./scripts/benchmark-compare.sh --local --github https://github.com/starkware-libs/stwo --ref v1.0.0
#
#   2. Compare two GitHub versions:
#      ./scripts/benchmark-compare.sh \
#        --github https://github.com/starkware-libs/stwo --ref main \
#        --github https://github.com/starkware-libs/stwo --ref v1.0.0
#
#   3. Compare versions from different forks:
#      ./scripts/benchmark-compare.sh \
#        --github https://github.com/fork1/stwo --ref feature-branch \
#        --github https://github.com/fork2/stwo --ref main
#
#   4. With custom benchmark filter:
#      ./scripts/benchmark-compare.sh --local --github https://github.com/starkware-libs/stwo --ref main --filter fft
#
#   5. With parallel feature enabled:
#      ./scripts/benchmark-compare.sh --local --github https://github.com/starkware-libs/stwo --ref main --features parallel

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default values
OUTPUT_DIR="${PROJECT_ROOT}/benchmark-results"
BENCHMARK_FILTER=""
EXTRA_FEATURES=""
WARMUP_RUNS=0
SAMPLE_SIZE=""
CLEANUP=true
VERBOSE=false

# Version tracking
VERSION_COUNT=0
declare -a VERSION_TYPES
declare -a VERSION_SOURCES
declare -a VERSION_REFS
declare -a VERSION_NAMES

# Print usage information
usage() {
    cat << EOF
Performance Comparison Tool for STWO
=====================================

USAGE:
    $(basename "$0") [OPTIONS] VERSION1 VERSION2

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

EXAMPLES:
    # Compare local version vs upstream main branch
    $(basename "$0") --local --github https://github.com/starkware-libs/stwo --ref main

    # Compare two specific tags
    $(basename "$0") \\
        --github https://github.com/starkware-libs/stwo --ref v1.0.0 \\
        --github https://github.com/starkware-libs/stwo --ref v2.0.0

    # Compare with custom names and filter
    $(basename "$0") \\
        --name "Current" --local \\
        --name "Upstream" --github https://github.com/starkware-libs/stwo --ref main \\
        --filter fft

    # Compare forks with parallel feature
    $(basename "$0") \\
        --github https://github.com/fork1/stwo --ref feature \\
        --github https://github.com/fork2/stwo --ref main \\
        --features parallel

EOF
    exit 0
}

# Log functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

# Parse command line arguments
NEXT_NAME=""
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --local)
                VERSION_COUNT=$((VERSION_COUNT + 1))
                VERSION_TYPES+=("local")
                VERSION_SOURCES+=("$PROJECT_ROOT")
                VERSION_REFS+=("local")
                if [[ -n "$NEXT_NAME" ]]; then
                    VERSION_NAMES+=("$NEXT_NAME")
                    NEXT_NAME=""
                else
                    VERSION_NAMES+=("Local")
                fi
                shift
                ;;
            --github)
                if [[ -z "$2" ]]; then
                    log_error "--github requires a URL"
                    exit 1
                fi
                VERSION_COUNT=$((VERSION_COUNT + 1))
                VERSION_TYPES+=("github")
                VERSION_SOURCES+=("$2")
                shift 2
                ;;
            --ref)
                if [[ -z "$2" ]]; then
                    log_error "--ref requires a reference (branch/tag/commit)"
                    exit 1
                fi
                # Apply ref to the last github version
                local last_idx=$((${#VERSION_TYPES[@]} - 1))
                if [[ "${VERSION_TYPES[$last_idx]}" != "github" ]]; then
                    log_error "--ref must follow --github"
                    exit 1
                fi
                VERSION_REFS+=("$2")
                if [[ -n "$NEXT_NAME" ]]; then
                    VERSION_NAMES+=("$NEXT_NAME")
                    NEXT_NAME=""
                else
                    # Generate name from URL and ref
                    local url="${VERSION_SOURCES[$last_idx]}"
                    local repo_name=$(echo "$url" | sed -E 's|.*/([^/]+)/([^/]+)(\.git)?$|\1/\2|')
                    VERSION_NAMES+=("${repo_name}@$2")
                fi
                shift 2
                ;;
            -n|--name)
                if [[ -z "$2" ]]; then
                    log_error "--name requires a value"
                    exit 1
                fi
                NEXT_NAME="$2"
                shift 2
                ;;
            -o|--output)
                if [[ -z "$2" ]]; then
                    log_error "--output requires a directory path"
                    exit 1
                fi
                OUTPUT_DIR="$2"
                shift 2
                ;;
            -f|--filter)
                if [[ -z "$2" ]]; then
                    log_error "--filter requires a pattern"
                    exit 1
                fi
                BENCHMARK_FILTER="$2"
                shift 2
                ;;
            --features)
                if [[ -z "$2" ]]; then
                    log_error "--features requires a value"
                    exit 1
                fi
                EXTRA_FEATURES="$2"
                shift 2
                ;;
            --warmup)
                if [[ -z "$2" ]]; then
                    log_error "--warmup requires a number"
                    exit 1
                fi
                WARMUP_RUNS="$2"
                shift 2
                ;;
            --sample-size)
                if [[ -z "$2" ]]; then
                    log_error "--sample-size requires a number"
                    exit 1
                fi
                SAMPLE_SIZE="$2"
                shift 2
                ;;
            --no-cleanup)
                CLEANUP=false
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

# Validate arguments
validate_args() {
    if [[ $VERSION_COUNT -lt 2 ]]; then
        log_error "At least two versions must be specified"
        echo "Use --help for usage information"
        exit 1
    fi

    if [[ $VERSION_COUNT -gt 2 ]]; then
        log_error "Only two versions can be compared at once"
        exit 1
    fi

    # Check that all github versions have refs
    for i in "${!VERSION_TYPES[@]}"; do
        if [[ "${VERSION_TYPES[$i]}" == "github" ]] && [[ -z "${VERSION_REFS[$i]:-}" ]]; then
            log_error "GitHub version ${VERSION_SOURCES[$i]} requires --ref"
            exit 1
        fi
    done
}

# Check required tools
check_requirements() {
    log_info "Checking requirements..."

    local missing=()

    if ! command -v cargo &> /dev/null; then
        missing+=("cargo (Rust toolchain)")
    fi

    if ! command -v git &> /dev/null; then
        missing+=("git")
    fi

    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required tools:"
        for tool in "${missing[@]}"; do
            echo "  - $tool"
        done
        exit 1
    fi

    # Check for criterion
    if ! cargo criterion --help &> /dev/null 2>&1; then
        log_warn "cargo-criterion not found, installing..."
        cargo install cargo-criterion
    fi

    log_success "All requirements satisfied"
}

# Setup output directory
setup_output_dir() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    OUTPUT_DIR="${OUTPUT_DIR}/${timestamp}"

    log_info "Creating output directory: $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR/version_a"
    mkdir -p "$OUTPUT_DIR/version_b"
    mkdir -p "$OUTPUT_DIR/temp"
}

# Clone or prepare a version
prepare_version() {
    local idx=$1
    local version_type="${VERSION_TYPES[$idx]}"
    local version_source="${VERSION_SOURCES[$idx]}"
    local version_ref="${VERSION_REFS[$idx]}"
    local version_name="${VERSION_NAMES[$idx]}"
    local version_dir="$OUTPUT_DIR/temp/version_${idx}"

    log_step "Preparing version $((idx + 1)): $version_name"

    if [[ "$version_type" == "local" ]]; then
        log_info "Using local repository at $PROJECT_ROOT"
        # Create a clean copy to avoid interference
        log_info "Creating clean copy of local repository..."
        mkdir -p "$version_dir"
        rsync -a --exclude='target' --exclude='benchmark-results' --exclude='.git' \
            "$PROJECT_ROOT/" "$version_dir/"

        # Initialize git for version info
        cd "$version_dir"
        git init -q
        git add -A
        git commit -q -m "Local snapshot" || true

        # Get version info
        cd "$PROJECT_ROOT"
        local commit_hash=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        local branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        echo "{\"type\": \"local\", \"path\": \"$PROJECT_ROOT\", \"commit\": \"$commit_hash\", \"branch\": \"$branch\", \"name\": \"$version_name\"}" > "$OUTPUT_DIR/version_${idx}_info.json"

    elif [[ "$version_type" == "github" ]]; then
        log_info "Cloning $version_source at ref $version_ref..."

        # Clone with specific depth for efficiency
        git clone --depth 100 "$version_source" "$version_dir" 2>&1 | while read line; do
            if $VERBOSE; then echo "  $line"; fi
        done

        cd "$version_dir"

        # Fetch the specific ref
        log_info "Checking out ref: $version_ref"
        git fetch origin "$version_ref" --depth=1 2>/dev/null || true
        git checkout "$version_ref" 2>&1 | while read line; do
            if $VERBOSE; then echo "  $line"; fi
        done

        # Get version info
        local commit_hash=$(git rev-parse --short HEAD)
        echo "{\"type\": \"github\", \"url\": \"$version_source\", \"ref\": \"$version_ref\", \"commit\": \"$commit_hash\", \"name\": \"$version_name\"}" > "$OUTPUT_DIR/version_${idx}_info.json"
    fi

    log_success "Version $((idx + 1)) prepared at $version_dir"
    echo "$version_dir"
}

# Run benchmarks for a version
run_benchmarks() {
    local version_idx=$1
    local version_dir=$2
    local output_subdir=$3
    local version_name="${VERSION_NAMES[$version_idx]}"

    log_step "Running benchmarks for: $version_name"

    cd "$version_dir"

    # Build first to avoid timing compilation
    log_info "Building project..."
    local features="prover"
    if [[ -n "$EXTRA_FEATURES" ]]; then
        features="prover,$EXTRA_FEATURES"
    fi

    RUSTFLAGS="-Awarnings -C target-cpu=native -C opt-level=3" cargo build --release --features "$features" 2>&1 | tail -5

    # Run warmup if requested
    if [[ "$WARMUP_RUNS" -gt 0 ]]; then
        log_info "Running $WARMUP_RUNS warmup iterations..."
        for ((i=1; i<=WARMUP_RUNS; i++)); do
            log_info "Warmup run $i/$WARMUP_RUNS"
            RUSTFLAGS="-Awarnings -C target-cpu=native -C opt-level=3" cargo criterion \
                --features "$features" \
                --output-format bencher \
                ${BENCHMARK_FILTER:+-- "$BENCHMARK_FILTER"} \
                > /dev/null 2>&1 || true
        done
    fi

    # Run actual benchmarks
    log_info "Running benchmarks..."
    local bench_args=(
        --features "$features"
        --output-format bencher
        --message-format json
    )

    if [[ -n "$SAMPLE_SIZE" ]]; then
        bench_args+=(-- --sample-size "$SAMPLE_SIZE")
    fi

    # Run criterion benchmarks and capture output
    local raw_output="$OUTPUT_DIR/${output_subdir}/raw_output.txt"
    local json_output="$OUTPUT_DIR/${output_subdir}/results.json"
    local bencher_output="$OUTPUT_DIR/${output_subdir}/bencher_output.txt"

    # Run with bencher format for parsing
    log_info "Collecting benchmark results..."
    RUSTFLAGS="-Awarnings -C target-cpu=native -C opt-level=3" cargo criterion \
        --features "$features" \
        --output-format bencher \
        ${BENCHMARK_FILTER:+-- "$BENCHMARK_FILTER"} \
        2>&1 | tee "$bencher_output"

    # Parse bencher output to JSON
    log_info "Parsing results..."
    python3 "$SCRIPT_DIR/benchmark-parse.py" \
        --input "$bencher_output" \
        --output "$json_output" \
        --name "$version_name"

    # Copy criterion HTML reports if they exist
    if [[ -d "target/criterion" ]]; then
        log_info "Copying Criterion HTML reports..."
        cp -r target/criterion "$OUTPUT_DIR/${output_subdir}/criterion_reports" 2>/dev/null || true
    fi

    log_success "Benchmarks completed for $version_name"

    cd "$PROJECT_ROOT"
}

# Generate comparison report
generate_report() {
    log_step "Generating comparison report"

    log_info "Running report generator..."
    python3 "$SCRIPT_DIR/benchmark-report.py" \
        --version-a "$OUTPUT_DIR/version_a/results.json" \
        --version-b "$OUTPUT_DIR/version_b/results.json" \
        --info-a "$OUTPUT_DIR/version_0_info.json" \
        --info-b "$OUTPUT_DIR/version_1_info.json" \
        --output "$OUTPUT_DIR/comparison_report.html"

    log_success "Report generated: $OUTPUT_DIR/comparison_report.html"
}

# Cleanup temporary files
cleanup() {
    if $CLEANUP; then
        log_info "Cleaning up temporary directories..."
        rm -rf "$OUTPUT_DIR/temp"
    else
        log_info "Keeping temporary directories (--no-cleanup specified)"
    fi
}

# Print final summary
print_summary() {
    echo ""
    log_step "Benchmark Comparison Complete!"

    echo -e "${GREEN}Results saved to:${NC} $OUTPUT_DIR"
    echo ""
    echo "Files generated:"
    echo "  - comparison_report.html  : Main HTML comparison report"
    echo "  - version_a/              : Benchmark results for ${VERSION_NAMES[0]}"
    echo "  - version_b/              : Benchmark results for ${VERSION_NAMES[1]}"
    echo "  - version_*_info.json     : Version metadata"
    echo ""
    echo -e "Open the report with: ${CYAN}open $OUTPUT_DIR/comparison_report.html${NC}"
    echo ""
}

# Main execution
main() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║        STWO Performance Comparison Tool                        ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    parse_args "$@"
    validate_args
    check_requirements
    setup_output_dir

    # Prepare versions
    VERSION_A_DIR=$(prepare_version 0)
    VERSION_B_DIR=$(prepare_version 1)

    # Run benchmarks sequentially
    run_benchmarks 0 "$VERSION_A_DIR" "version_a"
    run_benchmarks 1 "$VERSION_B_DIR" "version_b"

    # Generate report
    generate_report

    # Cleanup
    cleanup

    # Print summary
    print_summary
}

# Handle interrupts
trap 'echo ""; log_warn "Interrupted. Cleaning up..."; cleanup; exit 1' INT TERM

# Run main
main "$@"
