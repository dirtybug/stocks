# Alpaca Command Line Access

This workspace has a small Python CLI for Alpaca paper trading.

## Site

Latest reports:

https://dirtybug.github.io/stocks/

## Setup

Set your Alpaca API credentials in PowerShell:

```powershell
$env:APCA_API_KEY_ID="your_key_here"
$env:APCA_API_SECRET_KEY="your_secret_here"
$env:APCA_API_BASE_URL="https://paper-api.alpaca.markets/v2"
```

Or put them in the local `.env` file. The scripts load `.env` automatically.

The default base URL is already paper trading. Only change it to a live URL if you intentionally want live trading.

## Commands

Check account:

```powershell
python .\alpaca_cli.py account
```

Show positions:

```powershell
python .\alpaca_cli.py positions
```

Show open orders:

```powershell
python .\alpaca_cli.py orders
```

Buy by share quantity:

```powershell
python .\alpaca_cli.py buy AAPL --qty 1
```

Buy by dollar amount:

```powershell
python .\alpaca_cli.py buy AAPL --notional 25
```

Limit buy:

```powershell
python .\alpaca_cli.py buy AAPL --qty 1 --type limit --limit-price 190
```

Cancel all open orders:

```powershell
python .\alpaca_cli.py cancel all
```

## Favorite Stock Valuation Check

This compares your favorite stocks using:

```text
model value per share = sector P/S * annual revenue / shares outstanding
dividend yield = annual dividends paid / shares outstanding / current price
ROI = annual net income / shareholders' equity
FCF margin = (annual operating cash flow - capital expenditure) / annual revenue
debt score = 0-100 score based on debt / shareholders' equity, higher is better
backlog = remaining performance obligation
book/bill = backlog / annual revenue
```

Rating rules:

```text
undervalued and book/bill > 1.2 = BUY CANDIDATE
undervalued and book/bill < 1.0 = VALUE TRAP RISK
overvalued and book/bill > 1.5 = GROWTH PREMIUM
overvalued and book/bill < 1.0 = OVERVALUED
```

Overall score:

```text
overall = 0.40 * valuation score
        + 0.25 * book/bill score
        + 0.20 * debt/EBITDA score
        + 0.15 * ROI score
```

Sector P/S values:

```text
technology = 7
software = 8
industrial = 4
defense = 2
energy = 2
consumer = 5
healthcare = 4
```

Run the report:

```powershell
python .\run_reports.py
```

The combined runner reads `favorite_stocks.csv` and writes each run to one unique generation folder:

```text
reports/YYYY-MM-DD_HHMMSS/valuation/valuation_report.html
reports/YYYY-MM-DD_HHMMSS/valuation/valuation_report.csv
reports/YYYY-MM-DD_HHMMSS/technical/technical_report.html
reports/YYYY-MM-DD_HHMMSS/technical/technical_report.csv
reports/YYYY-MM-DD_HHMMSS/technical/technical_charts/
```

ETFs and commodity funds are skipped because they do not have normal company revenue.

When you say "show me report", open the newest valuation report folder.

```text
reports/YYYY-MM-DD_HHMMSS/valuation/valuation_report.html
```

## Technical Analysis Report

Generate a separate technical-analysis report:

```powershell
python .\technical_analysis.py
```

The combined runner writes:

```text
reports/YYYY-MM-DD_HHMMSS/technical/technical_report.html
reports/YYYY-MM-DD_HHMMSS/technical/technical_report.csv
reports/YYYY-MM-DD_HHMMSS/technical/technical_charts/
```

The technical report detects moving-average trend, RSI, MACD, candle patterns, double tops, double bottoms, head-and-shoulders, inverse head-and-shoulders, ascending/descending/symmetrical triangles, bull flags, and bear flags.
Use the `Graph` link in the newest `technical_report.html` to open the local chart page for a symbol and see the pattern overlay.

## Safety

Treat any API secret shown on screen as exposed. Rotate it in Alpaca before using it for anything important.
