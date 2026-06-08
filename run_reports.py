#!/usr/bin/env python3
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def dated_report_dir():
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = Path("reports") / stamp
    path = base
    counter = 2

    while path.exists():
        path = Path("reports") / f"{stamp}_{counter:02d}"
        counter += 1

    path.mkdir(parents=True, exist_ok=False)
    return path


def run(command):
    subprocess.run(command, check=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run valuation and technical reports into one generation folder."
    )
    parser.add_argument(
        "--report-dir",
        help="Optional generation folder. Defaults to reports/YYYY-MM-DD_HHMMSS.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.report_dir:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
    else:
        report_dir = dated_report_dir()

    valuation_dir = report_dir / "valuation"
    technical_dir = report_dir / "technical"

    print(f"Generation folder: {report_dir}")
    run([sys.executable, "valuation_checker.py", "--report-dir", str(valuation_dir)])
    run([sys.executable, "technical_analysis.py", "--report-dir", str(technical_dir)])

    print()
    print(f"Valuation report: {valuation_dir / 'valuation_report.html'}")
    print(f"Technical report: {technical_dir / 'technical_report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
