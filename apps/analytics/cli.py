"""Command-Line Interface for AegisAI Executive Analytics.

Usage:
    python -m apps.analytics.cli generate [--out-dir=data/analytics_export]
    python -m apps.analytics.cli report
    python -m apps.analytics.cli kpis
"""

import argparse
import sys
from pathlib import Path

from apps.analytics.engine import ExecutiveAnalyticsEngine
from apps.analytics.exporter import BIExporter

# Safe stdout configuration for Windows UTF-8
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def cmd_generate(out_dir: str = "data/analytics_export") -> None:
    """Generate the full executive benchmark dataset and export BI assets."""
    print("=" * 65)
    print("[*] AegisAI Executive Analytics Generator")
    print("=" * 65)

    engine = ExecutiveAnalyticsEngine()
    print("[*] Synthesizing 48 calibrated annual enterprise incident records...")
    raw_incidents = engine.generate_annual_benchmark_dataset()

    records = [engine.process_incident(inc) for inc in raw_incidents]
    aggregate = engine.compute_executive_kpis(raw_incidents)

    exporter = BIExporter(export_dir=Path(out_dir))
    exported = exporter.export_all(records, aggregate)

    print(f"\n[PASS] Successfully exported {len(exported)} BI artifacts to '{out_dir}':")
    for name, path in exported.items():
        print(f"  - {name}: {path}")

    print("\n[*] Executive Reliability Highlights:")
    print(f"  - Total Incidents Evaluated  : {aggregate.total_incidents}")
    print(f"  - Baseline Avg MTTR          : {aggregate.baseline_avg_mttr_minutes:.1f} mins")
    print(f"  - AegisAI Avg MTTR           : {aggregate.aegis_avg_mttr_minutes:.1f} mins ({aggregate.mttr_reduction_percent:.1f}% reduction)")
    print(f"  - Gross Downtime Avoided     : ${aggregate.total_downtime_exposure_avoided_gross:,.2f}")
    print(f"  - Realized Net Savings (25%) : ${aggregate.realized_net_savings:,.2f}")
    print(f"  - Net Enterprise ROI         : +{aggregate.net_roi_percent:,.1f}%")
    print(f"  - Payback Period             : {aggregate.payback_period_days:.1f} days")
    print("\n[SUCCESS] Executive Analytics generation completed successfully!\n")


def cmd_report() -> None:
    """Print the markdown executive ROI report to stdout."""
    engine = ExecutiveAnalyticsEngine()
    raw_incidents = engine.generate_annual_benchmark_dataset()
    aggregate = engine.compute_executive_kpis(raw_incidents)
    exporter = BIExporter()
    report = exporter.generate_markdown_report(aggregate)
    print(report)


def cmd_kpis() -> None:
    """Print a concise summary table of executive KPIs."""
    engine = ExecutiveAnalyticsEngine()
    raw_incidents = engine.generate_annual_benchmark_dataset()
    aggregate = engine.compute_executive_kpis(raw_incidents)

    print("=" * 65)
    print("           AEGISAI EXECUTIVE BOARD SCORECARD")
    print("=" * 65)
    print(f"Total Incidents Evaluated      : {aggregate.total_incidents}")
    print(f"Resolved Incidents             : {aggregate.resolved_incidents}")
    print(f"False Positive Rate            : {aggregate.false_positive_rate_percent:.1f}%")
    print(f"Baseline Mean Time to Remediate: {aggregate.baseline_avg_mttr_minutes:.1f} minutes")
    print(f"AegisAI Mean Time to Remediate : {aggregate.aegis_avg_mttr_minutes:.1f} minutes")
    print(f"MTTR Improvement               : -{aggregate.mttr_reduction_percent:.1f}%")
    print(f"Engineering Hours Reclaimed    : {aggregate.total_engineering_hours_reclaimed:.1f} hrs")
    print(f"Downtime Losses Avoided (Gross): ${aggregate.total_downtime_exposure_avoided_gross:,.2f}")
    print(f"Realized Bottom-Line Savings   : ${aggregate.realized_net_savings:,.2f}")
    print(f"Net Platform ROI               : +{aggregate.net_roi_percent:,.1f}%")
    print(f"Capital Payback Period         : {aggregate.payback_period_days:.1f} days")
    print("=" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisAI Executive Analytics CLI")
    subparsers = parser.add_subparsers(dest="command")

    gen_parser = subparsers.add_parser("generate", help="Generate benchmark dataset and export BI files")
    gen_parser.add_argument("--out-dir", default="data/analytics_export", help="Output directory")

    subparsers.add_parser("report", help="Display full executive markdown report")
    subparsers.add_parser("kpis", help="Display executive board scorecard")

    args = parser.parse_args()
    if args.command == "report":
        cmd_report()
    elif args.command == "kpis":
        cmd_kpis()
    else:
        out_dir = getattr(args, "out_dir", "data/analytics_export")
        cmd_generate(out_dir)


if __name__ == "__main__":
    main()
