#!/usr/bin/env python3
import argparse
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path

GITHUB_PAGES_URL = "https://dirtybug.github.io/stocks/"


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


def link_for(path):
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def write_latest_index(report_dir, valuation_report, technical_report):
    generation = report_dir.name
    index = Path("index.html")
    index.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Latest Stock Reports</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f6f7f9;
      color: #111827;
    }}
    main {{
      max-width: 780px;
      margin: 56px auto;
      padding: 0 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
    }}
    p {{
      margin: 0 0 24px;
      color: #4b5563;
    }}
    .page-link {{
      display: inline-block;
      margin: 0 0 24px;
      color: #2563eb;
      font-size: 16px;
      font-weight: 700;
      text-decoration: none;
    }}
    .page-link:hover {{
      text-decoration: underline;
    }}
    .links {{
      display: grid;
      gap: 14px;
    }}
    a {{
      display: block;
      padding: 18px 20px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      background: white;
      color: #111827;
      text-decoration: none;
      font-size: 18px;
      font-weight: 700;
    }}
    a span {{
      display: block;
      margin-top: 4px;
      color: #6b7280;
      font-size: 14px;
      font-weight: 400;
    }}
    a:hover {{
      border-color: #2563eb;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Latest Stock Reports</h1>
    <p>Generated folder: {escape(generation)}</p>
    <a class="page-link" href="{GITHUB_PAGES_URL}" target="_blank" rel="noopener">GitHub Page</a>
    <div class="links">
      <a href="{escape(link_for(valuation_report))}">
        Valuation Analysis
        <span>{escape(link_for(valuation_report))}</span>
      </a>
      <a href="{escape(link_for(technical_report))}">
        Technical Analysis
        <span>{escape(link_for(technical_report))}</span>
      </a>
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return index


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

    valuation_report = valuation_dir / "valuation_report.html"
    technical_report = technical_dir / "technical_report.html"
    index = write_latest_index(report_dir, valuation_report, technical_report)

    print()
    print(f"Index: {index}")
    print(f"Valuation report: {valuation_report}")
    print(f"Technical report: {technical_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
