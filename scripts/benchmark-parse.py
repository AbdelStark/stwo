#!/usr/bin/env python3
"""
Parse Criterion benchmark output (bencher format) to JSON.

This script parses the bencher-format output from `cargo criterion --output-format bencher`
and converts it to a structured JSON format for comparison.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


def parse_bencher_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single line of bencher format output.

    Format: test benchmark_name ... bench: X ns/iter (+/- Y)
    Or: test benchmark_name ... bench: X,XXX ns/iter (+/- Y)
    """
    # Pattern for bencher format
    # Example: test iffts/simd ifft/16 ... bench:     123,456 ns/iter (+/- 1,234)
    pattern = r'^test\s+(.+?)\s+\.\.\.\s+bench:\s+([\d,]+)\s+ns/iter\s+\(\+/-\s+([\d,]+)\)'

    match = re.match(pattern, line.strip())
    if match:
        name = match.group(1).strip()
        time_ns = int(match.group(2).replace(',', ''))
        variance_ns = int(match.group(3).replace(',', ''))

        return {
            'name': name,
            'time_ns': time_ns,
            'variance_ns': variance_ns,
            'unit': 'ns'
        }

    return None


def parse_criterion_json_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single line of Criterion JSON message format.
    """
    try:
        data = json.loads(line)
        if data.get('reason') == 'benchmark-complete':
            return {
                'name': data.get('id', 'unknown'),
                'time_ns': int(data.get('typical', {}).get('estimate', 0)),
                'variance_ns': int(data.get('typical', {}).get('standard_error', 0)),
                'unit': data.get('typical', {}).get('unit', 'ns'),
                'throughput': data.get('throughput', []),
            }
    except json.JSONDecodeError:
        pass
    return None


def categorize_benchmark(name: str) -> str:
    """
    Categorize a benchmark by its name/group.
    """
    # Common benchmark categories in stwo
    categories = [
        ('fft', ['ifft', 'rfft', 'fft', 'transpose']),
        ('field', ['M31', 'CM31', 'QM31', 'field', 'add', 'mul', 'sub', 'inv']),
        ('merkle', ['merkle', 'hash', 'commit']),
        ('fri', ['fri', 'fold']),
        ('pcs', ['pcs', 'commitment']),
        ('eval', ['eval', 'evaluation', 'barycentric']),
        ('bit_rev', ['bit_rev', 'bit_reverse', 'permute']),
        ('lookups', ['lookup', 'logup']),
        ('quotients', ['quotient']),
        ('prefix_sum', ['prefix', 'sum']),
    ]

    name_lower = name.lower()
    for category, keywords in categories:
        for keyword in keywords:
            if keyword in name_lower:
                return category

    return 'other'


def parse_benchmark_output(input_path: str) -> List[Dict[str, Any]]:
    """
    Parse benchmark output file and return structured results.
    """
    results = []

    with open(input_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Try bencher format first
            result = parse_bencher_line(line)
            if result:
                result['category'] = categorize_benchmark(result['name'])
                results.append(result)
                continue

            # Try JSON format
            result = parse_criterion_json_line(line)
            if result:
                result['category'] = categorize_benchmark(result['name'])
                results.append(result)

    return results


def calculate_statistics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate overall statistics from benchmark results.
    """
    if not results:
        return {}

    times = [r['time_ns'] for r in results]

    # Group by category
    categories = {}
    for r in results:
        cat = r['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    return {
        'total_benchmarks': len(results),
        'total_time_ns': sum(times),
        'mean_time_ns': sum(times) / len(times),
        'min_time_ns': min(times),
        'max_time_ns': max(times),
        'categories': {cat: len(benchmarks) for cat, benchmarks in categories.items()},
    }


def main():
    parser = argparse.ArgumentParser(
        description='Parse Criterion benchmark output to JSON'
    )
    parser.add_argument(
        '--input', '-i',
        required=True,
        help='Input file with benchmark output (bencher format)'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output JSON file'
    )
    parser.add_argument(
        '--name', '-n',
        default='Unknown',
        help='Version name for the results'
    )

    args = parser.parse_args()

    # Parse results
    results = parse_benchmark_output(args.input)

    if not results:
        print(f"Warning: No benchmark results found in {args.input}", file=sys.stderr)

    # Calculate statistics
    stats = calculate_statistics(results)

    # Create output structure
    output = {
        'version_name': args.name,
        'timestamp': datetime.now().isoformat(),
        'statistics': stats,
        'benchmarks': results,
    }

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Parsed {len(results)} benchmark results to {args.output}")


if __name__ == '__main__':
    main()
