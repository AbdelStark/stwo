#!/usr/bin/env python3
"""
Generate HTML comparison report from benchmark results.

This script takes two JSON benchmark result files and generates
a comprehensive HTML comparison report with charts and statistics.
"""

import argparse
import json
import html
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple


def load_json(path: str) -> Dict[str, Any]:
    """Load a JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


def format_time(ns: float) -> str:
    """Format time in nanoseconds to human readable format."""
    if ns >= 1e9:
        return f"{ns / 1e9:.2f} s"
    elif ns >= 1e6:
        return f"{ns / 1e6:.2f} ms"
    elif ns >= 1e3:
        return f"{ns / 1e3:.2f} µs"
    else:
        return f"{ns:.2f} ns"


def format_percentage(pct: float) -> str:
    """Format percentage with sign."""
    if pct > 0:
        return f"+{pct:.1f}%"
    else:
        return f"{pct:.1f}%"


def calculate_comparison(
    benchmarks_a: List[Dict],
    benchmarks_b: List[Dict]
) -> List[Dict[str, Any]]:
    """
    Calculate comparison between two sets of benchmark results.
    Returns list of comparisons with percentage differences.
    """
    # Create lookup by name
    lookup_a = {b['name']: b for b in benchmarks_a}
    lookup_b = {b['name']: b for b in benchmarks_b}

    # Find all benchmark names
    all_names = set(lookup_a.keys()) | set(lookup_b.keys())

    comparisons = []
    for name in sorted(all_names):
        bench_a = lookup_a.get(name)
        bench_b = lookup_b.get(name)

        comparison = {
            'name': name,
            'category': (bench_a or bench_b).get('category', 'other'),
        }

        if bench_a and bench_b:
            time_a = bench_a['time_ns']
            time_b = bench_b['time_ns']

            # Percentage change (negative means A is faster)
            if time_b > 0:
                pct_change = ((time_a - time_b) / time_b) * 100
            else:
                pct_change = 0

            # Speedup ratio (>1 means B is faster than A)
            if time_a > 0:
                speedup = time_b / time_a
            else:
                speedup = 1

            comparison.update({
                'time_a': time_a,
                'time_b': time_b,
                'variance_a': bench_a.get('variance_ns', 0),
                'variance_b': bench_b.get('variance_ns', 0),
                'pct_change': pct_change,
                'speedup': speedup,
                'status': 'both',
            })
        elif bench_a:
            comparison.update({
                'time_a': bench_a['time_ns'],
                'time_b': None,
                'variance_a': bench_a.get('variance_ns', 0),
                'variance_b': None,
                'pct_change': None,
                'speedup': None,
                'status': 'only_a',
            })
        else:
            comparison.update({
                'time_a': None,
                'time_b': bench_b['time_ns'],
                'variance_a': None,
                'variance_b': bench_b.get('variance_ns', 0),
                'pct_change': None,
                'speedup': None,
                'status': 'only_b',
            })

        comparisons.append(comparison)

    return comparisons


def calculate_summary(comparisons: List[Dict]) -> Dict[str, Any]:
    """Calculate summary statistics from comparisons."""
    # Filter to benchmarks that exist in both versions
    both = [c for c in comparisons if c['status'] == 'both']

    if not both:
        return {
            'total': len(comparisons),
            'common': 0,
            'only_a': len([c for c in comparisons if c['status'] == 'only_a']),
            'only_b': len([c for c in comparisons if c['status'] == 'only_b']),
        }

    pct_changes = [c['pct_change'] for c in both]
    speedups = [c['speedup'] for c in both]

    # Count wins
    a_faster = sum(1 for c in both if c['pct_change'] < -1)  # >1% faster
    b_faster = sum(1 for c in both if c['pct_change'] > 1)   # >1% faster
    similar = len(both) - a_faster - b_faster

    # Calculate geometric mean of speedups
    import math
    if speedups:
        log_sum = sum(math.log(s) for s in speedups if s > 0)
        geomean_speedup = math.exp(log_sum / len(speedups))
    else:
        geomean_speedup = 1.0

    return {
        'total': len(comparisons),
        'common': len(both),
        'only_a': len([c for c in comparisons if c['status'] == 'only_a']),
        'only_b': len([c for c in comparisons if c['status'] == 'only_b']),
        'a_faster_count': a_faster,
        'b_faster_count': b_faster,
        'similar_count': similar,
        'mean_pct_change': sum(pct_changes) / len(pct_changes),
        'median_pct_change': sorted(pct_changes)[len(pct_changes) // 2],
        'geomean_speedup': geomean_speedup,
        'max_improvement': min(pct_changes),  # Most negative = biggest improvement
        'max_regression': max(pct_changes),   # Most positive = biggest regression
    }


def calculate_category_summary(comparisons: List[Dict]) -> Dict[str, Dict]:
    """Calculate summary by category."""
    categories = {}

    for c in comparisons:
        cat = c['category']
        if cat not in categories:
            categories[cat] = {'benchmarks': [], 'total': 0}
        categories[cat]['benchmarks'].append(c)
        categories[cat]['total'] += 1

    # Calculate stats per category
    for cat, data in categories.items():
        both = [b for b in data['benchmarks'] if b['status'] == 'both']
        if both:
            pct_changes = [b['pct_change'] for b in both]
            data['mean_pct_change'] = sum(pct_changes) / len(pct_changes)
            data['a_faster'] = sum(1 for b in both if b['pct_change'] < -1)
            data['b_faster'] = sum(1 for b in both if b['pct_change'] > 1)
        else:
            data['mean_pct_change'] = 0
            data['a_faster'] = 0
            data['b_faster'] = 0

    return categories


def generate_version_ref_html(info: Dict[str, Any]) -> str:
    """Generate the reference HTML for a version."""
    ref = info.get('ref') or info.get('branch')
    if ref:
        return f'''<div class="version-meta-item">
                        <span class="version-meta-label">Reference</span>
                        <span class="version-meta-value">{html.escape(ref)}</span>
                    </div>'''
    return ''


def generate_winner_html(summary: Dict[str, Any], name_a: str, name_b: str) -> str:
    """Generate the winner badge HTML."""
    mean_pct = summary.get('mean_pct_change', 0)
    if mean_pct < -1:
        return f'<span class="winner-badge winner-a">🏆 Overall Winner: {name_a} (faster by {-mean_pct:.1f}% on average)</span>'
    elif mean_pct > 1:
        return f'<span class="winner-badge winner-b">🏆 Overall Winner: {name_b} (faster by {mean_pct:.1f}% on average)</span>'
    else:
        return '<span class="winner-badge" style="background: var(--neutral-bg); color: var(--neutral);">🤝 Performance is similar between versions</span>'


def get_summary_stat_class(summary: Dict[str, Any]) -> str:
    """Get the CSS class for the mean change summary stat."""
    mean_pct = summary.get('mean_pct_change', 0)
    if mean_pct < 0:
        return 'success'
    elif mean_pct > 0:
        return 'danger'
    return ''


def generate_html_report(
    version_a: Dict[str, Any],
    version_b: Dict[str, Any],
    info_a: Dict[str, Any],
    info_b: Dict[str, Any],
    comparisons: List[Dict],
    summary: Dict[str, Any],
    category_summary: Dict[str, Dict],
) -> str:
    """Generate the HTML report."""

    name_a = html.escape(version_a.get('version_name', 'Version A'))
    name_b = html.escape(version_b.get('version_name', 'Version B'))

    # Generate conditional HTML sections
    ref_a_html = generate_version_ref_html(info_a)
    ref_b_html = generate_version_ref_html(info_b)
    winner_html = generate_winner_html(summary, name_a, name_b)
    mean_change_class = get_summary_stat_class(summary)

    # Prepare chart data
    chart_labels = []
    chart_data_a = []
    chart_data_b = []
    pct_change_data = []

    for c in comparisons[:50]:  # Limit to top 50 for chart readability
        if c['status'] == 'both':
            chart_labels.append(c['name'][:40])  # Truncate long names
            chart_data_a.append(c['time_a'])
            chart_data_b.append(c['time_b'])
            pct_change_data.append(c['pct_change'])

    # Category chart data
    cat_labels = list(category_summary.keys())
    cat_pct_changes = [category_summary[cat].get('mean_pct_change', 0) for cat in cat_labels]

    # Category options for filter
    category_options = ' '.join(
        f'<option value="{cat}">{cat.capitalize()}</option>'
        for cat in sorted(category_summary.keys())
    )

    html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STWO Benchmark Comparison Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --success: #22c55e;
            --success-bg: #dcfce7;
            --danger: #ef4444;
            --danger-bg: #fee2e2;
            --warning: #f59e0b;
            --warning-bg: #fef3c7;
            --neutral: #6b7280;
            --neutral-bg: #f3f4f6;
            --bg: #ffffff;
            --bg-secondary: #f9fafb;
            --text: #111827;
            --text-secondary: #6b7280;
            --border: #e5e7eb;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg-secondary);
            color: var(--text);
            line-height: 1.6;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }}

        header {{
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: white;
            padding: 2rem;
            margin-bottom: 2rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}

        header h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}

        header .subtitle {{
            opacity: 0.9;
            font-size: 1rem;
        }}

        .card {{
            background: var(--bg);
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            margin-bottom: 1.5rem;
            overflow: hidden;
        }}

        .card-header {{
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            font-size: 1.1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .card-body {{
            padding: 1.5rem;
        }}

        .version-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}

        .version-card {{
            background: var(--bg);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }}

        .version-card h3 {{
            color: var(--primary);
            margin-bottom: 1rem;
            font-size: 1.2rem;
        }}

        .version-meta {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}

        .version-meta-item {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px dashed var(--border);
        }}

        .version-meta-label {{
            color: var(--text-secondary);
        }}

        .version-meta-value {{
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9rem;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }}

        .summary-stat {{
            text-align: center;
            padding: 1.5rem;
            border-radius: 8px;
            background: var(--bg-secondary);
        }}

        .summary-stat .value {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--primary);
        }}

        .summary-stat .label {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-top: 0.25rem;
        }}

        .summary-stat.success .value {{
            color: var(--success);
        }}

        .summary-stat.danger .value {{
            color: var(--danger);
        }}

        .summary-stat.warning .value {{
            color: var(--warning);
        }}

        .chart-container {{
            position: relative;
            height: 400px;
            margin: 1rem 0;
        }}

        .chart-container.large {{
            height: 600px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}

        th, td {{
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}

        th {{
            background: var(--bg-secondary);
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }}

        tr:hover {{
            background: var(--bg-secondary);
        }}

        .benchmark-name {{
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.85rem;
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .time-cell {{
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            text-align: right;
        }}

        .change-cell {{
            font-weight: 600;
            text-align: center;
        }}

        .change-positive {{
            color: var(--danger);
            background: var(--danger-bg);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
        }}

        .change-negative {{
            color: var(--success);
            background: var(--success-bg);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
        }}

        .change-neutral {{
            color: var(--neutral);
            background: var(--neutral-bg);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
        }}

        .badge {{
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }}

        .badge-category {{
            background: var(--neutral-bg);
            color: var(--neutral);
        }}

        .winner-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-weight: 600;
        }}

        .winner-a {{
            background: var(--success-bg);
            color: var(--success);
        }}

        .winner-b {{
            background: var(--danger-bg);
            color: var(--danger);
        }}

        .filter-controls {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}

        .filter-controls input {{
            padding: 0.5rem 1rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.9rem;
            min-width: 200px;
        }}

        .filter-controls select {{
            padding: 0.5rem 1rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.9rem;
            background: white;
        }}

        .category-section {{
            margin-bottom: 2rem;
        }}

        .category-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            background: var(--bg-secondary);
            border-radius: 8px;
            margin-bottom: 1rem;
            cursor: pointer;
        }}

        .category-header:hover {{
            background: var(--border);
        }}

        .category-title {{
            font-weight: 600;
            text-transform: capitalize;
        }}

        .category-stats {{
            display: flex;
            gap: 1rem;
        }}

        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}

        .tabs {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
            border-bottom: 2px solid var(--border);
            padding-bottom: 0.5rem;
        }}

        .tab {{
            padding: 0.5rem 1rem;
            border-radius: 6px 6px 0 0;
            cursor: pointer;
            font-weight: 500;
            color: var(--text-secondary);
            transition: all 0.2s;
        }}

        .tab:hover {{
            background: var(--bg-secondary);
        }}

        .tab.active {{
            color: var(--primary);
            border-bottom: 2px solid var(--primary);
            margin-bottom: -2px;
        }}

        .tab-content {{
            display: none;
        }}

        .tab-content.active {{
            display: block;
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 1rem;
            }}

            .summary-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}

            table {{
                font-size: 0.8rem;
            }}

            th, td {{
                padding: 0.5rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 STWO Benchmark Comparison Report</h1>
            <p class="subtitle">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </header>

        <!-- Version Information -->
        <div class="version-grid">
            <div class="version-card">
                <h3>🅰️ {name_a}</h3>
                <div class="version-meta">
                    <div class="version-meta-item">
                        <span class="version-meta-label">Type</span>
                        <span class="version-meta-value">{html.escape(info_a.get('type', 'unknown'))}</span>
                    </div>
                    <div class="version-meta-item">
                        <span class="version-meta-label">Commit</span>
                        <span class="version-meta-value">{html.escape(info_a.get('commit', 'unknown'))}</span>
                    </div>
                    {ref_a_html}
                    <div class="version-meta-item">
                        <span class="version-meta-label">Benchmarks</span>
                        <span class="version-meta-value">{len(version_a.get('benchmarks', []))}</span>
                    </div>
                </div>
            </div>
            <div class="version-card">
                <h3>🅱️ {name_b}</h3>
                <div class="version-meta">
                    <div class="version-meta-item">
                        <span class="version-meta-label">Type</span>
                        <span class="version-meta-value">{html.escape(info_b.get('type', 'unknown'))}</span>
                    </div>
                    <div class="version-meta-item">
                        <span class="version-meta-label">Commit</span>
                        <span class="version-meta-value">{html.escape(info_b.get('commit', 'unknown'))}</span>
                    </div>
                    {ref_b_html}
                    <div class="version-meta-item">
                        <span class="version-meta-label">Benchmarks</span>
                        <span class="version-meta-value">{len(version_b.get('benchmarks', []))}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Summary Statistics -->
        <div class="card">
            <div class="card-header">📈 Summary</div>
            <div class="card-body">
                <div class="summary-grid">
                    <div class="summary-stat">
                        <div class="value">{summary.get('common', 0)}</div>
                        <div class="label">Common Benchmarks</div>
                    </div>
                    <div class="summary-stat success">
                        <div class="value">{summary.get('a_faster_count', 0)}</div>
                        <div class="label">{name_a} Faster</div>
                    </div>
                    <div class="summary-stat danger">
                        <div class="value">{summary.get('b_faster_count', 0)}</div>
                        <div class="label">{name_b} Faster</div>
                    </div>
                    <div class="summary-stat">
                        <div class="value">{summary.get('similar_count', 0)}</div>
                        <div class="label">Similar (±1%)</div>
                    </div>
                    <div class="summary-stat {mean_change_class}">
                        <div class="value">{format_percentage(summary.get('mean_pct_change', 0))}</div>
                        <div class="label">Mean Change</div>
                    </div>
                    <div class="summary-stat">
                        <div class="value">{summary.get('geomean_speedup', 1):.3f}x</div>
                        <div class="label">Geomean Speedup</div>
                    </div>
                </div>

                <div style="text-align: center; margin-top: 1.5rem;">
                    {winner_html}
                </div>
            </div>
        </div>

        <!-- Charts -->
        <div class="card">
            <div class="card-header">📊 Visualizations</div>
            <div class="card-body">
                <div class="tabs">
                    <div class="tab active" onclick="showTab('chart-comparison')">Time Comparison</div>
                    <div class="tab" onclick="showTab('chart-pct')">Percentage Change</div>
                    <div class="tab" onclick="showTab('chart-category')">By Category</div>
                </div>

                <div id="chart-comparison" class="tab-content active">
                    <div class="chart-container large">
                        <canvas id="comparisonChart"></canvas>
                    </div>
                </div>

                <div id="chart-pct" class="tab-content">
                    <div class="chart-container large">
                        <canvas id="pctChangeChart"></canvas>
                    </div>
                </div>

                <div id="chart-category" class="tab-content">
                    <div class="chart-container">
                        <canvas id="categoryChart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <!-- Detailed Results -->
        <div class="card">
            <div class="card-header">📋 Detailed Results</div>
            <div class="card-body">
                <div class="filter-controls">
                    <input type="text" id="filterInput" placeholder="Filter by benchmark name..." onkeyup="filterTable()">
                    <select id="categoryFilter" onchange="filterTable()">
                        <option value="">All Categories</option>
                        {category_options}
                    </select>
                    <select id="changeFilter" onchange="filterTable()">
                        <option value="">All Results</option>
                        <option value="faster">A Faster</option>
                        <option value="slower">B Faster</option>
                        <option value="similar">Similar</option>
                    </select>
                </div>

                <table id="resultsTable">
                    <thead>
                        <tr>
                            <th>Benchmark</th>
                            <th>Category</th>
                            <th style="text-align: right;">{name_a}</th>
                            <th style="text-align: right;">{name_b}</th>
                            <th style="text-align: center;">Change</th>
                            <th style="text-align: center;">Speedup</th>
                        </tr>
                    </thead>
                    <tbody>
                        {generate_table_rows(comparisons, name_a, name_b)}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Category Breakdown -->
        <div class="card">
            <div class="card-header">📁 Category Breakdown</div>
            <div class="card-body">
                {generate_category_sections(category_summary, comparisons, name_a, name_b)}
            </div>
        </div>

        <footer>
            <p>Generated by STWO Benchmark Comparison Tool</p>
            <p>Report contains {summary.get('total', 0)} benchmarks from {len(category_summary)} categories</p>
        </footer>
    </div>

    <script>
        // Chart.js configuration
        const chartLabels = {json.dumps(chart_labels)};
        const dataA = {json.dumps(chart_data_a)};
        const dataB = {json.dumps(chart_data_b)};
        const pctChanges = {json.dumps(pct_change_data)};
        const catLabels = {json.dumps(cat_labels)};
        const catPctChanges = {json.dumps(cat_pct_changes)};

        // Comparison Chart
        new Chart(document.getElementById('comparisonChart'), {{
            type: 'bar',
            data: {{
                labels: chartLabels,
                datasets: [
                    {{
                        label: '{name_a}',
                        data: dataA,
                        backgroundColor: 'rgba(34, 197, 94, 0.7)',
                        borderColor: 'rgb(34, 197, 94)',
                        borderWidth: 1
                    }},
                    {{
                        label: '{name_b}',
                        data: dataB,
                        backgroundColor: 'rgba(239, 68, 68, 0.7)',
                        borderColor: 'rgb(239, 68, 68)',
                        borderWidth: 1
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {{
                    title: {{
                        display: true,
                        text: 'Execution Time Comparison (ns)'
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                return context.dataset.label + ': ' + formatTime(context.raw);
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        type: 'logarithmic',
                        title: {{
                            display: true,
                            text: 'Time (ns, log scale)'
                        }}
                    }}
                }}
            }}
        }});

        // Percentage Change Chart
        new Chart(document.getElementById('pctChangeChart'), {{
            type: 'bar',
            data: {{
                labels: chartLabels,
                datasets: [{{
                    label: 'Change (%)',
                    data: pctChanges,
                    backgroundColor: pctChanges.map(v => v < 0 ? 'rgba(34, 197, 94, 0.7)' : 'rgba(239, 68, 68, 0.7)'),
                    borderColor: pctChanges.map(v => v < 0 ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)'),
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {{
                    title: {{
                        display: true,
                        text: 'Performance Change (negative = {name_a} faster)'
                    }},
                    legend: {{
                        display: false
                    }}
                }},
                scales: {{
                    x: {{
                        title: {{
                            display: true,
                            text: 'Change (%)'
                        }}
                    }}
                }}
            }}
        }});

        // Category Chart
        new Chart(document.getElementById('categoryChart'), {{
            type: 'bar',
            data: {{
                labels: catLabels,
                datasets: [{{
                    label: 'Mean Change (%)',
                    data: catPctChanges,
                    backgroundColor: catPctChanges.map(v => v < 0 ? 'rgba(34, 197, 94, 0.7)' : 'rgba(239, 68, 68, 0.7)'),
                    borderColor: catPctChanges.map(v => v < 0 ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)'),
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    title: {{
                        display: true,
                        text: 'Mean Performance Change by Category'
                    }},
                    legend: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        title: {{
                            display: true,
                            text: 'Change (%)'
                        }}
                    }}
                }}
            }}
        }});

        // Tab switching
        function showTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }}

        // Table filtering
        function filterTable() {{
            const filterText = document.getElementById('filterInput').value.toLowerCase();
            const categoryFilter = document.getElementById('categoryFilter').value.toLowerCase();
            const changeFilter = document.getElementById('changeFilter').value;

            const rows = document.querySelectorAll('#resultsTable tbody tr');
            rows.forEach(row => {{
                const name = row.cells[0].textContent.toLowerCase();
                const category = row.cells[1].textContent.toLowerCase();
                const changeCell = row.cells[4].textContent;

                let showRow = true;

                if (filterText && !name.includes(filterText)) showRow = false;
                if (categoryFilter && category !== categoryFilter) showRow = false;

                if (changeFilter) {{
                    const pct = parseFloat(changeCell) || 0;
                    if (changeFilter === 'faster' && pct >= -1) showRow = false;
                    if (changeFilter === 'slower' && pct <= 1) showRow = false;
                    if (changeFilter === 'similar' && (pct < -1 || pct > 1)) showRow = false;
                }}

                row.style.display = showRow ? '' : 'none';
            }});
        }}

        // Time formatting helper
        function formatTime(ns) {{
            if (ns >= 1e9) return (ns / 1e9).toFixed(2) + ' s';
            if (ns >= 1e6) return (ns / 1e6).toFixed(2) + ' ms';
            if (ns >= 1e3) return (ns / 1e3).toFixed(2) + ' µs';
            return ns.toFixed(2) + ' ns';
        }}
    </script>
</body>
</html>
'''

    return html_template


def generate_table_rows(comparisons: List[Dict], name_a: str, name_b: str) -> str:
    """Generate HTML table rows for benchmark comparisons."""
    rows = []

    # Sort by absolute percentage change (most significant first)
    sorted_comparisons = sorted(
        comparisons,
        key=lambda c: abs(c.get('pct_change', 0)) if c.get('pct_change') is not None else 0,
        reverse=True
    )

    for c in sorted_comparisons:
        name = html.escape(c['name'])
        category = html.escape(c['category'])

        if c['status'] == 'both':
            time_a = format_time(c['time_a'])
            time_b = format_time(c['time_b'])
            pct = c['pct_change']

            if pct < -1:
                change_class = 'change-negative'
            elif pct > 1:
                change_class = 'change-positive'
            else:
                change_class = 'change-neutral'

            pct_str = format_percentage(pct)
            speedup = f"{c['speedup']:.2f}x"
        elif c['status'] == 'only_a':
            time_a = format_time(c['time_a'])
            time_b = '—'
            pct_str = '—'
            speedup = '—'
            change_class = 'change-neutral'
        else:
            time_a = '—'
            time_b = format_time(c['time_b'])
            pct_str = '—'
            speedup = '—'
            change_class = 'change-neutral'

        rows.append(f'''
            <tr data-category="{category}" data-pct="{c.get('pct_change', 0)}">
                <td class="benchmark-name" title="{name}">{name}</td>
                <td><span class="badge badge-category">{category}</span></td>
                <td class="time-cell">{time_a}</td>
                <td class="time-cell">{time_b}</td>
                <td class="change-cell"><span class="{change_class}">{pct_str}</span></td>
                <td class="change-cell">{speedup}</td>
            </tr>
        ''')

    return '\n'.join(rows)


def generate_category_sections(
    category_summary: Dict[str, Dict],
    comparisons: List[Dict],
    name_a: str,
    name_b: str
) -> str:
    """Generate HTML sections for each category."""
    sections = []

    for cat, data in sorted(category_summary.items()):
        mean_pct = data.get('mean_pct_change', 0)

        if mean_pct < -1:
            winner = f'🟢 {name_a} faster'
        elif mean_pct > 1:
            winner = f'🔴 {name_b} faster'
        else:
            winner = '⚪ Similar'

        sections.append(f'''
            <div class="category-section">
                <div class="category-header">
                    <span class="category-title">{cat.capitalize()} ({data['total']} benchmarks)</span>
                    <div class="category-stats">
                        <span>Mean: {format_percentage(mean_pct)}</span>
                        <span>{winner}</span>
                    </div>
                </div>
            </div>
        ''')

    return '\n'.join(sections)


def main():
    parser = argparse.ArgumentParser(
        description='Generate HTML comparison report from benchmark results'
    )
    parser.add_argument(
        '--version-a', '-a',
        required=True,
        help='JSON results file for version A'
    )
    parser.add_argument(
        '--version-b', '-b',
        required=True,
        help='JSON results file for version B'
    )
    parser.add_argument(
        '--info-a',
        required=True,
        help='JSON info file for version A'
    )
    parser.add_argument(
        '--info-b',
        required=True,
        help='JSON info file for version B'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output HTML file'
    )

    args = parser.parse_args()

    # Load data
    print(f"Loading version A results from {args.version_a}")
    version_a = load_json(args.version_a)

    print(f"Loading version B results from {args.version_b}")
    version_b = load_json(args.version_b)

    print(f"Loading version A info from {args.info_a}")
    info_a = load_json(args.info_a)

    print(f"Loading version B info from {args.info_b}")
    info_b = load_json(args.info_b)

    # Calculate comparisons
    print("Calculating comparisons...")
    comparisons = calculate_comparison(
        version_a.get('benchmarks', []),
        version_b.get('benchmarks', [])
    )

    # Calculate summaries
    summary = calculate_summary(comparisons)
    category_summary = calculate_category_summary(comparisons)

    # Generate report
    print("Generating HTML report...")
    html_content = generate_html_report(
        version_a,
        version_b,
        info_a,
        info_b,
        comparisons,
        summary,
        category_summary,
    )

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        f.write(html_content)

    print(f"Report generated: {output_path}")

    # Print summary to console
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total benchmarks compared: {summary.get('common', 0)}")
    print(f"{version_a.get('version_name', 'Version A')} faster: {summary.get('a_faster_count', 0)}")
    print(f"{version_b.get('version_name', 'Version B')} faster: {summary.get('b_faster_count', 0)}")
    print(f"Similar: {summary.get('similar_count', 0)}")
    print(f"Mean change: {format_percentage(summary.get('mean_pct_change', 0))}")
    print(f"Geometric mean speedup: {summary.get('geomean_speedup', 1):.3f}x")
    print("=" * 60)


if __name__ == '__main__':
    main()
