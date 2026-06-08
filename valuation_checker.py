#!/usr/bin/env python3
import argparse
import csv
import json
import os
import math
import sys
import time
from datetime import date, datetime
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from alpaca_env import load_env


ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks/trades/latest"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_USER_AGENT = "valuation-checker julio@example.com"
REVENUE_FACTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
)
SHARE_FACTS = (
    "EntityCommonStockSharesOutstanding",
    "CommonStocksIncludingAdditionalPaidInCapitalSharesOutstanding",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
)
DIVIDEND_FACTS = (
    "PaymentsOfDividendsCommonStock",
    "PaymentsOfDividends",
    "DividendsCommonStockCash",
    "CommonStocksDividendsPerShareDeclared",
)
NET_INCOME_FACTS = (
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
)
EBITDA_FACTS = (
    "EarningsBeforeInterestTaxesDepreciationAndAmortization",
    "EarningsBeforeInterestTaxesDepreciationDepletionAndAmortization",
)
OPERATING_INCOME_FACTS = (
    "OperatingIncomeLoss",
)
DEPRECIATION_AMORTIZATION_FACTS = (
    "DepreciationDepletionAndAmortization",
    "DepreciationDepletionAndAmortizationExpense",
    "DepreciationAndAmortization",
)
EQUITY_FACTS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
BOOKING_PROXY_FACTS = (
    "RevenueRemainingPerformanceObligation",
    "ContractWithCustomerLiability",
    "ContractWithCustomerLiabilityCurrent",
)
OPERATING_CASH_FLOW_FACTS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
CAPEX_FACTS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
    "CapitalExpenditures",
)
TOTAL_DEBT_FACTS = (
    "DebtAndFinanceLeaseObligations",
    "LongTermDebtAndFinanceLeaseObligations",
)
CURRENT_DEBT_FACTS = (
    "DebtCurrent",
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtCurrent",
    "ShortTermBorrowings",
    "ShortTermDebt",
)
NONCURRENT_DEBT_FACTS = (
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "LongTermDebtNoncurrent",
    "LongTermDebt",
)
SECTOR_PS = {
    "technology": 7,
    "software": 8,
    "industrial": 4,
    "defense": 2,
    "energy": 2,
    "consumer": 5,
    "healthcare": 4,
}
load_env()


def money(value):
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.2f}"


def number(value):
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.0f}"


def env(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def fetch_json(url, headers=None):
    headers = headers or {}
    headers.setdefault("User-Agent", SEC_USER_AGENT)
    headers.setdefault("Accept", "application/json")
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_prices(symbols, feed):
    query = urllib.parse.urlencode({"symbols": ",".join(symbols), "feed": feed})
    headers = {
        "APCA-API-KEY-ID": env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": env("APCA_API_SECRET_KEY"),
        "Accept": "application/json",
    }
    data = fetch_json(f"{ALPACA_DATA_URL}?{query}", headers=headers)
    trades = data.get("trades") or {}
    return {symbol: trades.get(symbol, {}).get("p") for symbol in symbols}


def fetch_cik_map():
    data = fetch_json(SEC_TICKERS_URL)
    return {
        item["ticker"].upper(): str(item["cik_str"]).zfill(10)
        for item in data.values()
    }


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def period_days(item):
    start = parse_date(item.get("start"))
    end = parse_date(item.get("end"))
    if not start or not end:
        return None
    return (end - start).days


def fact_candidates(facts, names):
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    candidates = []

    for name in names:
        units = us_gaap.get(name, {}).get("units", {})
        for values in units.values():
            for item in values:
                value = item.get("val")
                end = item.get("end")
                form = item.get("form", "")
                frame = item.get("frame", "")
                if value is None or not end:
                    continue
                candidates.append(
                    {
                        "value": float(value),
                        "end": end,
                        "filed": item.get("filed", ""),
                        "form": form,
                        "fp": item.get("fp", ""),
                        "frame": frame,
                        "days": period_days(item),
                    }
                )

    return candidates


def latest_fact(facts, names):
    candidates = fact_candidates(facts, names)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["end"],
            item["filed"],
            item["form"] in {"10-K", "20-F", "40-F"},
        ),
        reverse=True,
    )
    return candidates[0]["value"]


def latest_annual_fact(facts, names):
    candidates = fact_candidates(facts, names)
    annual = [
        item
        for item in candidates
        if (
            (item["days"] is not None and item["days"] >= 300)
            or item["fp"] == "FY"
            or (item["frame"].startswith("CY") and "Q" not in item["frame"])
        )
    ]

    if not annual:
        return latest_fact(facts, names)

    annual.sort(
        key=lambda item: (
            item["end"],
            item["filed"],
            item["form"] in {"10-K", "20-F", "40-F"},
        ),
        reverse=True,
    )
    return annual[0]["value"]


def fetch_fundamentals(symbol, cik_map):
    cik = cik_map.get(symbol.upper())
    if not cik:
        raise ValueError("No SEC CIK mapping found")

    facts = fetch_json(SEC_FACTS_URL.format(cik=cik))
    total_debt = latest_fact(facts, TOTAL_DEBT_FACTS)
    if total_debt is None:
        current_debt = latest_fact(facts, CURRENT_DEBT_FACTS) or 0
        noncurrent_debt = latest_fact(facts, NONCURRENT_DEBT_FACTS) or 0
        total_debt = current_debt + noncurrent_debt if current_debt or noncurrent_debt else None
    ebitda = latest_annual_fact(facts, EBITDA_FACTS)
    if ebitda is None:
        operating_income = latest_annual_fact(facts, OPERATING_INCOME_FACTS)
        depreciation_amortization = latest_annual_fact(facts, DEPRECIATION_AMORTIZATION_FACTS)
        if operating_income is not None and depreciation_amortization is not None:
            ebitda = operating_income + abs(depreciation_amortization)

    return {
        "revenue": latest_annual_fact(facts, REVENUE_FACTS),
        "shares_outstanding": latest_fact(facts, SHARE_FACTS),
        "dividends": latest_annual_fact(facts, DIVIDEND_FACTS),
        "net_income": latest_annual_fact(facts, NET_INCOME_FACTS),
        "equity": latest_fact(facts, EQUITY_FACTS),
        "backlog": latest_fact(facts, BOOKING_PROXY_FACTS),
        "operating_cash_flow": latest_annual_fact(facts, OPERATING_CASH_FLOW_FACTS),
        "capex": latest_annual_fact(facts, CAPEX_FACTS),
        "total_debt": total_debt,
        "ebitda": ebitda,
        "cik": cik,
    }


def valuation(price, revenue, shares, ps_multiplier):
    if not price or not revenue or not shares:
        return None, None, None

    model_value = ps_multiplier * revenue / shares
    discount_pct = (model_value - price) / price * 100
    price_to_model = price / model_value if model_value else None
    return model_value, discount_pct, price_to_model


def dividend_return(price, shares, dividends):
    if not price or not shares or dividends is None:
        return None, None

    dividend_per_share = abs(dividends) / shares
    dividend_yield_pct = dividend_per_share / price * 100
    return dividend_per_share, dividend_yield_pct


def free_cash_flow(operating_cash_flow, capex):
    if operating_cash_flow is None or capex is None:
        return None
    return operating_cash_flow - abs(capex)


def debt_score(total_debt, equity):
    if total_debt is None:
        return None
    if total_debt <= 0:
        return 100
    if equity is None or equity <= 0:
        return 0

    debt_to_equity = total_debt / equity
    if debt_to_equity <= 0.25:
        return 95
    if debt_to_equity <= 0.5:
        return 85
    if debt_to_equity <= 1:
        return 70
    if debt_to_equity <= 2:
        return 50
    if debt_to_equity <= 3:
        return 30
    return 10


def valuation_score(upside_pct):
    if upside_pct is None:
        return None
    if upside_pct > 50:
        return 100
    if upside_pct > 20:
        return 80
    if upside_pct > 0:
        return 60
    if upside_pct > -20:
        return 40
    return 20


def book_to_bill_score(book_to_bill):
    if book_to_bill is None:
        return None
    if book_to_bill >= 2.0:
        return 100
    if book_to_bill >= 1.5:
        return 80
    if book_to_bill >= 1.0:
        return 60
    if book_to_bill >= 0.8:
        return 40
    return 20


def debt_to_ebitda_score(debt_to_ebitda):
    if debt_to_ebitda is None:
        return None
    if debt_to_ebitda < 0:
        return None
    if debt_to_ebitda <= 1:
        return 100
    if debt_to_ebitda <= 2:
        return 80
    if debt_to_ebitda <= 3:
        return 60
    if debt_to_ebitda <= 4:
        return 40
    return 20


def roi_score(roi):
    if roi is None:
        return None
    if roi >= 25:
        return 100
    if roi >= 15:
        return 80
    if roi >= 10:
        return 60
    if roi >= 5:
        return 40
    return 20


def overall_score(upside_pct, book_to_bill, debt_to_ebitda, roi):
    val = valuation_score(upside_pct)
    btb = book_to_bill_score(book_to_bill)
    debt = debt_to_ebitda_score(debt_to_ebitda)
    roi_s = roi_score(roi)

    if None in (val, btb, debt, roi_s):
        return None

    score = (
        0.40 * val
        + 0.25 * btb
        + 0.20 * debt
        + 0.15 * roi_s
    )
    return round(score, 1)


def valuation_rating(discount_pct, book_to_bill):
    if discount_pct is None or book_to_bill is None:
        return ""

    undervalued = discount_pct > 0
    overvalued = discount_pct < 0

    if undervalued and book_to_bill > 1.2:
        return "BUY CANDIDATE"
    if undervalued and book_to_bill < 1.0:
        return "VALUE TRAP RISK"
    if overvalued and book_to_bill > 1.5:
        return "GROWTH PREMIUM"
    if overvalued and book_to_bill < 1.0:
        return "OVERVALUED"
    return ""


def pct(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return numerator / denominator * 100


def ratio(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def read_favorites(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ensure_parent(path):
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def dated_report_dir(report_name):
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = Path("reports") / report_name / stamp
    path = base
    counter = 2

    while path.exists():
        path = Path("reports") / report_name / f"{stamp}_{counter:02d}"
        counter += 1

    path.mkdir(parents=True, exist_ok=False)
    return path


def write_report(path, rows):
    ensure_parent(path)
    fields = [
        "symbol",
        "company",
        "sector",
        "ps_multiplier",
        "rating",
        "overall_score",
        "valuation_score",
        "book_to_bill_score",
        "debt_score_weighted",
        "roi_score",
        "current_price",
        "model_value",
        "discount_pct",
        "price_to_model",
        "dividend_per_share",
        "dividend_yield_pct",
        "roi_pct",
        "fcf_margin_pct",
        "debt_score",
        "debt_to_equity",
        "debt_to_ebitda",
        "ebitda",
        "backlog",
        "book_to_bill",
        "revenue",
        "shares_outstanding",
        "currency",
        "quote_type",
        "notes",
        "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def html_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def pct_text(value):
    return f"{html_escape(value)}%" if value else ""


def write_html_report(path, rows):
    ensure_parent(path)
    ranked = [row for row in rows if row["status"] == "ok"]
    skipped = [row for row in rows if row["status"] != "ok"]
    ranked.sort(
        key=lambda row: (
            float(row["overall_score"]) if row["overall_score"] else -1,
            float(row["discount_pct"]),
        ),
        reverse=True,
    )

    def valuation_class(row):
        try:
            value = float(row["discount_pct"])
        except ValueError:
            return ""
        if value >= 50:
            return "good"
        if value >= 0:
            return "watch"
        return "bad"

    table_rows = []
    for row in ranked:
        table_rows.append(
            "<tr>"
            f"<td data-col=\"symbol\">{html_escape(row['symbol'])}</td>"
            f"<td data-col=\"company\">{html_escape(row['company'])}</td>"
            f"<td data-col=\"sector\">{html_escape(row['sector'])}</td>"
            f"<td data-col=\"ps\" class=\"num\">{html_escape(row['ps_multiplier'])}</td>"
            f"<td data-col=\"rating\">{html_escape(row['rating'])}</td>"
            f"<td data-col=\"overall\" class=\"num\">{html_escape(row['overall_score'])}</td>"
            f"<td data-col=\"valuation-score\" class=\"num\">{html_escape(row['valuation_score'])}</td>"
            f"<td data-col=\"btb-score\" class=\"num\">{html_escape(row['book_to_bill_score'])}</td>"
            f"<td data-col=\"debt-score-weighted\" class=\"num\">{html_escape(row['debt_score_weighted'])}</td>"
            f"<td data-col=\"roi-score\" class=\"num\">{html_escape(row['roi_score'])}</td>"
            f"<td data-col=\"price\" class=\"num\">{html_escape(row['current_price'])}</td>"
            f"<td data-col=\"model\" class=\"num\">{html_escape(row['model_value'])}</td>"
            f"<td data-col=\"upside\" class=\"num {valuation_class(row)}\">{pct_text(row['discount_pct'])}</td>"
            f"<td data-col=\"price-model\" class=\"num\">{html_escape(row['price_to_model'])}</td>"
            f"<td data-col=\"div-share\" class=\"num\">{html_escape(row['dividend_per_share'])}</td>"
            f"<td data-col=\"div-yield\" class=\"num\">{pct_text(row['dividend_yield_pct'])}</td>"
            f"<td data-col=\"roi\" class=\"num\">{pct_text(row['roi_pct'])}</td>"
            f"<td data-col=\"fcf-margin\" class=\"num\">{pct_text(row['fcf_margin_pct'])}</td>"
            f"<td data-col=\"debt-score\" class=\"num\">{html_escape(row['debt_score'])}</td>"
            f"<td data-col=\"debt-equity\" class=\"num\">{html_escape(row['debt_to_equity'])}</td>"
            f"<td data-col=\"debt-ebitda\" class=\"num\">{html_escape(row['debt_to_ebitda'])}</td>"
            f"<td data-col=\"ebitda\" class=\"num\">{html_escape(row['ebitda'])}</td>"
            f"<td data-col=\"backlog\" class=\"num\">{html_escape(row['backlog'])}</td>"
            f"<td data-col=\"book-bill\" class=\"num\">{html_escape(row['book_to_bill'])}</td>"
            f"<td data-col=\"revenue\" class=\"num\">{html_escape(row['revenue'])}</td>"
            f"<td data-col=\"shares\" class=\"num\">{html_escape(row['shares_outstanding'])}</td>"
            f"<td data-col=\"notes\">{html_escape(row['notes'])}</td>"
            "</tr>"
        )

    skipped_rows = []
    for row in skipped:
        skipped_rows.append(
            "<tr>"
            f"<td>{html_escape(row['symbol'])}</td>"
            f"<td>{html_escape(row['company'])}</td>"
            f"<td>{html_escape(row['status'])}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Favorite Stock Valuation Report</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #607080;
      --line: #d9e1e8;
      --panel: #f6f8fa;
      --good: #0f7a3b;
      --watch: #9a6400;
      --bad: #b42318;
    }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: white;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1.2;
    }}
    .meta {{
      color: var(--muted);
      margin: 0 0 20px;
    }}
    .formula {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      margin-bottom: 22px;
      font-family: Consolas, Monaco, monospace;
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 18px;
    }}
    .controls label {{
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      gap: 6px;
      padding: 7px 9px;
      user-select: none;
    }}
    .controls input {{
      margin: 0;
    }}
    .hidden-col {{
      display: none;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 28px;
      font-size: 14px;
    }}
    caption {{
      text-align: left;
      font-weight: 700;
      margin-bottom: 8px;
      font-size: 18px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 9px;
      vertical-align: top;
    }}
    th {{
      background: var(--panel);
      text-align: left;
      font-size: 12px;
      text-transform: uppercase;
      color: #415160;
      letter-spacing: 0;
    }}
    .num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .good {{
      color: var(--good);
      font-weight: 700;
    }}
    .watch {{
      color: var(--watch);
      font-weight: 700;
    }}
    .bad {{
      color: var(--bad);
      font-weight: 700;
    }}
    @media (max-width: 820px) {{
      main {{
        padding: 18px 10px 32px;
      }}
      table {{
        display: block;
        overflow-x: auto;
        white-space: nowrap;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Favorite Stock Valuation Report</h1>
    <p class="meta">Generated from favorite_stocks.csv using Alpaca prices and SEC company facts.</p>
    <div class="formula">model value per share = sector P/S * annual revenue / shares outstanding</div>
    <div class="formula">Sector P/S: technology 7, software 8, industrial 4, defense 2, energy 2, consumer 5, healthcare 4</div>
    <div class="controls" aria-label="Column visibility controls">
      <label><input type="checkbox" data-toggle-col="symbol" checked>Symbol</label>
      <label><input type="checkbox" data-toggle-col="company" checked>Company</label>
      <label><input type="checkbox" data-toggle-col="sector" checked>Sector</label>
      <label><input type="checkbox" data-toggle-col="ps" checked>P/S</label>
      <label><input type="checkbox" data-toggle-col="rating" checked>Rating</label>
      <label><input type="checkbox" data-toggle-col="overall" checked>Overall Score</label>
      <label><input type="checkbox" data-toggle-col="valuation-score">Valuation Score</label>
      <label><input type="checkbox" data-toggle-col="btb-score">Book/Bill Score</label>
      <label><input type="checkbox" data-toggle-col="debt-score-weighted">Debt/EBITDA Score</label>
      <label><input type="checkbox" data-toggle-col="roi-score">ROI Score</label>
      <label><input type="checkbox" data-toggle-col="price">Price</label>
      <label><input type="checkbox" data-toggle-col="model">Model Value</label>
      <label><input type="checkbox" data-toggle-col="upside" checked>Upside</label>
      <label><input type="checkbox" data-toggle-col="price-model">Price / Model</label>
      <label><input type="checkbox" data-toggle-col="div-share">Dividend / Share</label>
      <label><input type="checkbox" data-toggle-col="div-yield" checked>Dividend Yield</label>
      <label><input type="checkbox" data-toggle-col="roi" checked>ROI</label>
      <label><input type="checkbox" data-toggle-col="fcf-margin" checked>FCF Margin</label>
      <label><input type="checkbox" data-toggle-col="debt-score" checked>Debt Score</label>
      <label><input type="checkbox" data-toggle-col="debt-equity">Debt / Equity</label>
      <label><input type="checkbox" data-toggle-col="debt-ebitda" checked>Debt / EBITDA</label>
      <label><input type="checkbox" data-toggle-col="ebitda">EBITDA</label>
      <label><input type="checkbox" data-toggle-col="backlog" checked>Backlog</label>
      <label><input type="checkbox" data-toggle-col="book-bill" checked>Book/Bill</label>
      <label><input type="checkbox" data-toggle-col="revenue">Revenue</label>
      <label><input type="checkbox" data-toggle-col="shares">Shares</label>
      <label><input type="checkbox" data-toggle-col="notes">Notes</label>
    </div>

    <table>
      <caption>Operating Companies</caption>
      <thead>
        <tr>
          <th data-col="symbol">Symbol</th>
          <th data-col="company">Company</th>
          <th data-col="sector">Sector</th>
          <th data-col="ps" class="num">P/S</th>
          <th data-col="rating">Rating</th>
          <th data-col="overall" class="num">Overall Score</th>
          <th data-col="valuation-score" class="num">Valuation Score</th>
          <th data-col="btb-score" class="num">Book/Bill Score</th>
          <th data-col="debt-score-weighted" class="num">Debt/EBITDA Score</th>
          <th data-col="roi-score" class="num">ROI Score</th>
          <th data-col="price" class="num">Price</th>
          <th data-col="model" class="num">Model Value</th>
          <th data-col="upside" class="num">Upside</th>
          <th data-col="price-model" class="num">Price / Model</th>
          <th data-col="div-share" class="num">Dividend / Share</th>
          <th data-col="div-yield" class="num">Dividend Yield</th>
          <th data-col="roi" class="num">ROI</th>
          <th data-col="fcf-margin" class="num">FCF Margin</th>
          <th data-col="debt-score" class="num">Debt Score</th>
          <th data-col="debt-equity" class="num">Debt / Equity</th>
          <th data-col="debt-ebitda" class="num">Debt / EBITDA</th>
          <th data-col="ebitda" class="num">EBITDA</th>
          <th data-col="backlog" class="num">Backlog</th>
          <th data-col="book-bill" class="num">Book/Bill</th>
          <th data-col="revenue" class="num">Revenue</th>
          <th data-col="shares" class="num">Shares</th>
          <th data-col="notes">Notes</th>
        </tr>
      </thead>
      <tbody>
        {''.join(table_rows)}
      </tbody>
    </table>

    <table>
      <caption>Skipped / Incomplete</caption>
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Name</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {''.join(skipped_rows)}
      </tbody>
    </table>
  </main>
  <script>
    const toggles = Array.from(document.querySelectorAll("[data-toggle-col]"));

    function setColumn(column, visible) {{
      document.querySelectorAll(`[data-col="${{column}}"]`).forEach((cell) => {{
        cell.classList.toggle("hidden-col", !visible);
      }});
    }}

    toggles.forEach((toggle) => {{
      setColumn(toggle.dataset.toggleCol, toggle.checked);
      toggle.addEventListener("change", () => {{
        setColumn(toggle.dataset.toggleCol, toggle.checked);
      }});
    }});
  </script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)


def is_fund_like(company, notes):
    text = f"{company} {notes}".lower()
    keywords = (" etf", "fund", "trust", "gold", "silver", "uranium")
    return any(keyword in text for keyword in keywords)


def print_table(rows, limit):
    ranked = [row for row in rows if row["status"] == "ok"]
    ranked.sort(
        key=lambda row: (
            float(row["overall_score"]) if row["overall_score"] else -1,
            float(row["discount_pct"]),
        ),
        reverse=True,
    )

    print("Symbol  Score  P/S  Rating           Price      Model      Upside%   FCF%     Debt/EBITDA  Book/Bill  Company")
    print("------  -----  ---  ---------------  ---------  ---------  --------  -------  -----------  ---------  ------------------------------")
    for row in ranked[:limit]:
        print(
            f"{row['symbol']:<6}  "
            f"{row['overall_score']:>5}  "
            f"{row['ps_multiplier']:>3}  "
            f"{row['rating'][:15]:<15}  "
            f"{row['current_price']:>9}  "
            f"{row['model_value']:>9}  "
            f"{row['discount_pct']:>8}  "
            f"{row['fcf_margin_pct']:>7}  "
            f"{row['debt_to_ebitda']:>11}  "
            f"{row['book_to_bill']:>9}  "
            f"{row['company'][:30]}"
        )

    missing = [row for row in rows if row["status"] != "ok"]
    if missing:
        print()
        print("Skipped / incomplete data:")
        for row in missing:
            print(f"- {row['symbol']}: {row['status']}")


def main():
    parser = argparse.ArgumentParser(
        description="Compare favorite stocks against sector P/S * annual revenue / shares outstanding."
    )
    parser.add_argument("--favorites", default="favorite_stocks.csv")
    parser.add_argument("--report-dir")
    parser.add_argument("--output")
    parser.add_argument("--html-output")
    parser.add_argument("--limit", default=25, type=int)
    parser.add_argument("--pause", default=0.2, type=float, help="Seconds to pause between symbols.")
    parser.add_argument("--feed", default="iex", choices=["iex", "sip"], help="Alpaca market data feed.")
    args = parser.parse_args()

    report_dir = Path(args.report_dir) if args.report_dir else dated_report_dir("valuation")
    args.output = args.output or str(report_dir / "valuation_report.csv")
    args.html_output = args.html_output or str(report_dir / "valuation_report.html")

    favorites = read_favorites(args.favorites)
    symbols = [favorite["symbol"].strip().upper() for favorite in favorites]
    prices = fetch_prices(symbols, args.feed)
    cik_map = fetch_cik_map()
    rows = []
    for favorite in favorites:
        symbol = favorite["symbol"].strip().upper()
        company = favorite["company"].strip()
        sector = favorite.get("sector", "").strip().lower()
        notes = favorite.get("notes", "").strip()

        try:
            price = prices.get(symbol)
            if is_fund_like(company, notes):
                rows.append(
                    {
                        "symbol": symbol,
                        "company": company,
                        "sector": sector,
                        "ps_multiplier": "",
                        "rating": "",
                        "overall_score": "",
                        "valuation_score": "",
                        "book_to_bill_score": "",
                        "debt_score_weighted": "",
                        "roi_score": "",
                        "current_price": money(price),
                        "model_value": "",
                        "discount_pct": "",
                        "price_to_model": "",
                        "dividend_per_share": "",
                        "dividend_yield_pct": "",
                        "roi_pct": "",
                        "fcf_margin_pct": "",
                        "debt_score": "",
                        "debt_to_equity": "",
                        "debt_to_ebitda": "",
                        "ebitda": "",
                        "backlog": "",
                        "book_to_bill": "",
                        "revenue": "",
                        "shares_outstanding": "",
                        "currency": "USD" if price else "",
                        "quote_type": "fund_or_commodity",
                        "notes": notes,
                        "status": "model not applicable to ETFs, funds, or commodity trusts",
                    }
                )
                continue

            ps_multiplier = SECTOR_PS.get(sector)
            if ps_multiplier is None:
                raise ValueError(f"No sector P/S multiplier for sector: {sector or 'blank'}")

            fundamentals = fetch_fundamentals(symbol, cik_map)
            model_value, discount_pct, price_to_model = valuation(
                price,
                fundamentals["revenue"],
                fundamentals["shares_outstanding"],
                ps_multiplier,
            )
            dividend_per_share, dividend_yield_pct = dividend_return(
                price,
                fundamentals["shares_outstanding"],
                fundamentals["dividends"],
            )
            roi_pct = pct(fundamentals["net_income"], fundamentals["equity"])
            fcf = free_cash_flow(fundamentals["operating_cash_flow"], fundamentals["capex"])
            fcf_margin_pct = pct(fcf, fundamentals["revenue"])
            debt_to_equity = ratio(fundamentals["total_debt"], fundamentals["equity"])
            debt_to_ebitda = ratio(fundamentals["total_debt"], fundamentals["ebitda"])
            score = debt_score(fundamentals["total_debt"], fundamentals["equity"])
            book_to_bill = ratio(fundamentals["backlog"], fundamentals["revenue"])
            rating = valuation_rating(discount_pct, book_to_bill)
            val_score = valuation_score(discount_pct)
            btb_score = book_to_bill_score(book_to_bill)
            weighted_debt_score = debt_to_ebitda_score(debt_to_ebitda)
            weighted_roi_score = roi_score(roi_pct)
            final_score = overall_score(discount_pct, book_to_bill, debt_to_ebitda, roi_pct)
            status = "ok" if model_value is not None else "missing revenue, shares, or price"
            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "sector": sector,
                    "ps_multiplier": str(ps_multiplier),
                    "rating": rating,
                    "overall_score": money(final_score),
                    "valuation_score": number(val_score),
                    "book_to_bill_score": number(btb_score),
                    "debt_score_weighted": number(weighted_debt_score),
                    "roi_score": number(weighted_roi_score),
                    "current_price": money(price),
                    "model_value": money(model_value),
                    "discount_pct": money(discount_pct),
                    "price_to_model": money(price_to_model),
                    "dividend_per_share": money(dividend_per_share),
                    "dividend_yield_pct": money(dividend_yield_pct),
                    "roi_pct": money(roi_pct),
                    "fcf_margin_pct": money(fcf_margin_pct),
                    "debt_score": number(score),
                    "debt_to_equity": money(debt_to_equity),
                    "debt_to_ebitda": money(debt_to_ebitda),
                    "ebitda": number(fundamentals["ebitda"]),
                    "backlog": number(fundamentals["backlog"]),
                    "book_to_bill": money(book_to_bill),
                    "revenue": number(fundamentals["revenue"]),
                    "shares_outstanding": number(fundamentals["shares_outstanding"]),
                    "currency": "USD",
                    "quote_type": "equity_or_etf",
                    "notes": notes,
                    "status": status,
                }
            )
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as exc:
            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "sector": sector,
                    "ps_multiplier": "",
                    "rating": "",
                    "overall_score": "",
                    "valuation_score": "",
                    "book_to_bill_score": "",
                    "debt_score_weighted": "",
                    "roi_score": "",
                    "current_price": "",
                    "model_value": "",
                    "discount_pct": "",
                    "price_to_model": "",
                    "dividend_per_share": "",
                    "dividend_yield_pct": "",
                    "roi_pct": "",
                    "fcf_margin_pct": "",
                    "debt_score": "",
                    "debt_to_equity": "",
                    "debt_to_ebitda": "",
                    "ebitda": "",
                    "backlog": "",
                    "book_to_bill": "",
                    "revenue": "",
                    "shares_outstanding": "",
                    "currency": "",
                    "quote_type": "",
                    "notes": notes,
                    "status": str(exc),
                }
            )

        if args.pause:
            time.sleep(args.pause)

    write_report(args.output, rows)
    write_html_report(args.html_output, rows)
    print_table(rows, args.limit)
    print()
    print(f"Saved report to {args.output}")
    print(f"Saved HTML report to {args.html_output}")


if __name__ == "__main__":
    raise SystemExit(main())
