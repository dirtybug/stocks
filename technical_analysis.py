#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import math
import os
from pathlib import Path
import urllib.parse
import urllib.request

from alpaca_env import load_env


ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
load_env()


def env(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def fetch_json(url, headers=None):
    headers = headers or {}
    headers.setdefault("Accept", "application/json")
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bars(symbols, feed, timeframe, limit):
    headers = {
        "APCA-API-KEY-ID": env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": env("APCA_API_SECRET_KEY"),
    }
    end = dt.datetime.utcnow().replace(microsecond=0)
    start = end - dt.timedelta(days=370)
    next_page_token = None
    bars = {}

    while True:
        params = {
            "symbols": ",".join(symbols),
            "feed": feed,
            "timeframe": timeframe,
            "limit": str(limit),
            "adjustment": "split",
            "start": start.isoformat() + "Z",
            "end": end.isoformat() + "Z",
        }
        if next_page_token:
            params["page_token"] = next_page_token

        query = urllib.parse.urlencode(params)
        data = fetch_json(f"{ALPACA_BARS_URL}?{query}", headers=headers)
        for symbol, symbol_bars in (data.get("bars") or {}).items():
            bars.setdefault(symbol, []).extend(symbol_bars)

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            return bars


def read_favorites(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sma(values, length):
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def rsi(values, length=14):
    if len(values) <= length:
        return None

    gains = []
    losses = []
    for prev, cur in zip(values[-length - 1 : -1], values[-length:]):
        change = cur - prev
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def ema(values, length):
    if len(values) < length:
        return None
    multiplier = 2 / (length + 1)
    result = sum(values[:length]) / length
    for value in values[length:]:
        result = (value - result) * multiplier + result
    return result


def macd(values):
    if len(values) < 26:
        return None
    fast = ema(values, 12)
    slow = ema(values, 26)
    if fast is None or slow is None:
        return None
    return fast - slow


def pct_change(first, last):
    if not first:
        return None
    return (last - first) / first * 100


def safe_symbol(symbol):
    return "".join(char for char in symbol if char.isalnum() or char in ("-", "_")) or "chart"


def chart_url(symbol):
    return f"technical_charts/{safe_symbol(symbol)}.html"


def candle_patterns(bars):
    if len(bars) < 2:
        return []

    last = bars[-1]
    prev = bars[-2]
    open_price = last["o"]
    high = last["h"]
    low = last["l"]
    close = last["c"]
    body = abs(close - open_price)
    candle_range = high - low
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    patterns = []

    if candle_range and body / candle_range <= 0.1:
        patterns.append("doji")
    if body and lower_wick >= body * 2 and upper_wick <= body:
        patterns.append("hammer")
    if close > open_price and prev["c"] < prev["o"] and close >= prev["o"] and open_price <= prev["c"]:
        patterns.append("bullish engulfing")
    if close < open_price and prev["c"] > prev["o"] and close <= prev["o"] and open_price >= prev["c"]:
        patterns.append("bearish engulfing")

    return patterns


def swing_points(bars, field, kind, radius=3):
    values = [bar[field] for bar in bars]
    points = []
    for index in range(radius, len(values) - radius):
        current = values[index]
        window = values[index - radius : index + radius + 1]
        if kind == "high" and current == max(window):
            points.append((index, current))
        if kind == "low" and current == min(window):
            points.append((index, current))
    return points


def within_pct(left, right, tolerance):
    if not left or not right:
        return False
    return abs(left - right) / ((left + right) / 2) <= tolerance


def slope(points):
    if len(points) < 2:
        return 0
    first_index, first_value = points[0]
    last_index, last_value = points[-1]
    if last_index == first_index:
        return 0
    return (last_value - first_value) / (last_index - first_index)


def find_double_top(bars, high_swings, tolerance=0.035):
    lows = [bar["l"] for bar in bars]
    close = bars[-1]["c"]
    recent = [point for point in high_swings if point[0] >= len(bars) - 100]

    for left, right in reversed([(a, b) for i, a in enumerate(recent) for b in recent[i + 1 :]]):
        left_index, left_price = left
        right_index, right_price = right
        if right_index - left_index < 8 or right_index < len(bars) - 35:
            continue
        if not within_pct(left_price, right_price, tolerance):
            continue
        neckline = min(lows[left_index:right_index + 1])
        avg_peak = (left_price + right_price) / 2
        if neckline > avg_peak * 0.95:
            continue
        if close < neckline:
            return ("double top confirmed", right_index, left_index, neckline)
        if neckline <= close <= avg_peak * 1.02:
            return ("double top forming", right_index, left_index, neckline)
    return None


def find_double_bottom(bars, low_swings, tolerance=0.035):
    highs = [bar["h"] for bar in bars]
    close = bars[-1]["c"]
    recent = [point for point in low_swings if point[0] >= len(bars) - 100]

    for left, right in reversed([(a, b) for i, a in enumerate(recent) for b in recent[i + 1 :]]):
        left_index, left_price = left
        right_index, right_price = right
        if right_index - left_index < 8 or right_index < len(bars) - 35:
            continue
        if not within_pct(left_price, right_price, tolerance):
            continue
        neckline = max(highs[left_index:right_index + 1])
        avg_bottom = (left_price + right_price) / 2
        if neckline < avg_bottom * 1.05:
            continue
        if close > neckline:
            return ("double bottom confirmed", right_index, left_index, neckline)
        if avg_bottom * 0.98 <= close <= neckline:
            return ("double bottom forming", right_index, left_index, neckline)
    return None


def find_head_shoulders(bars, high_swings, low_swings):
    close = bars[-1]["c"]
    recent_highs = [point for point in high_swings if point[0] >= len(bars) - 120]
    recent_lows = [point for point in low_swings if point[0] >= len(bars) - 120]
    if len(recent_highs) < 3 or len(recent_lows) < 2:
        return ""

    left, head, right = recent_highs[-3:]
    if not (left[0] < head[0] < right[0]):
        return ""
    shoulders_match = within_pct(left[1], right[1], 0.08)
    head_is_higher = head[1] > left[1] * 1.04 and head[1] > right[1] * 1.04
    neckline_lows = [point[1] for point in recent_lows if left[0] < point[0] < right[0]]
    if shoulders_match and head_is_higher and neckline_lows:
        neckline = sum(neckline_lows[-2:]) / min(len(neckline_lows), 2)
        if close < neckline:
            return "head and shoulders confirmed"
        return "head and shoulders forming"
    return ""


def find_inverse_head_shoulders(bars, low_swings, high_swings):
    close = bars[-1]["c"]
    recent_lows = [point for point in low_swings if point[0] >= len(bars) - 120]
    recent_highs = [point for point in high_swings if point[0] >= len(bars) - 120]
    if len(recent_lows) < 3 or len(recent_highs) < 2:
        return ""

    left, head, right = recent_lows[-3:]
    if not (left[0] < head[0] < right[0]):
        return ""
    shoulders_match = within_pct(left[1], right[1], 0.08)
    head_is_lower = head[1] < left[1] * 0.96 and head[1] < right[1] * 0.96
    neckline_highs = [point[1] for point in recent_highs if left[0] < point[0] < right[0]]
    if shoulders_match and head_is_lower and neckline_highs:
        neckline = sum(neckline_highs[-2:]) / min(len(neckline_highs), 2)
        if close > neckline:
            return "inverse head and shoulders confirmed"
        return "inverse head and shoulders forming"
    return ""


def triangle_pattern(bars, high_swings, low_swings):
    recent_highs = [point for point in high_swings if point[0] >= len(bars) - 70][-4:]
    recent_lows = [point for point in low_swings if point[0] >= len(bars) - 70][-4:]
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return ""

    high_values = [point[1] for point in recent_highs]
    low_values = [point[1] for point in recent_lows]
    high_flat = (max(high_values) - min(high_values)) / max(high_values) <= 0.04
    low_flat = (max(low_values) - min(low_values)) / max(low_values) <= 0.04
    high_slope = slope(recent_highs)
    low_slope = slope(recent_lows)

    if high_flat and low_slope > 0:
        return "ascending triangle"
    if low_flat and high_slope < 0:
        return "descending triangle"
    if high_slope < 0 and low_slope > 0:
        return "symmetrical triangle"
    return ""


def flag_pattern(closes):
    if len(closes) < 35:
        return ""

    prior_return = pct_change(closes[-35], closes[-12])
    consolidation_return = pct_change(closes[-12], closes[-1])
    if prior_return is None or consolidation_return is None:
        return ""
    if prior_return >= 12 and -8 <= consolidation_return <= 3:
        return "bull flag"
    if prior_return <= -12 and -3 <= consolidation_return <= 8:
        return "bear flag"
    return ""


def chart_patterns(bars):
    if len(bars) < 40:
        return []

    high_swings = swing_points(bars, "h", "high")
    low_swings = swing_points(bars, "l", "low")
    closes = [bar["c"] for bar in bars]
    patterns = []

    double_top = find_double_top(bars, high_swings)
    double_bottom = find_double_bottom(bars, low_swings)
    double_patterns = [pattern for pattern in (double_top, double_bottom) if pattern]
    if double_patterns:
        double_patterns.sort(
            key=lambda item: ("confirmed" in item[0], item[1]),
            reverse=True,
        )
        patterns.append(double_patterns[0][0])

    for pattern in (
        find_head_shoulders(bars, high_swings, low_swings),
        find_inverse_head_shoulders(bars, low_swings, high_swings),
        triangle_pattern(bars, high_swings, low_swings),
        flag_pattern(closes),
    ):
        if pattern and pattern not in patterns:
            patterns.append(pattern)

    return patterns


def detect(symbol, company, bars):
    bars = sorted(bars, key=lambda item: item["t"])
    closes = [bar["c"] for bar in bars]
    volumes = [bar["v"] for bar in bars]
    last = bars[-1] if bars else None

    if not last or len(closes) < 20:
        return {
            "symbol": symbol,
            "company": company,
            "chart_url": chart_url(symbol),
            "last_close": "",
            "trend": "not enough data",
            "rsi": "",
            "macd": "",
            "candle_patterns": "",
            "chart_patterns": "",
            "volume_signal": "",
            "twenty_day_return_pct": "",
            "fifty_day_return_pct": "",
        }

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    rsi14 = rsi(closes, 14)
    macd_value = macd(closes)
    candles = candle_patterns(bars)
    charts = chart_patterns(bars)
    last_close = closes[-1]

    signals = []
    if sma20 and last_close > sma20:
        signals.append("above SMA20")
    if sma50 and last_close > sma50:
        signals.append("above SMA50")
    if sma20 and sma50 and sma20 > sma50:
        signals.append("bull trend")
    if sma20 and sma50 and sma20 < sma50:
        signals.append("bear trend")
    if len(closes) >= 21 and last_close >= max(closes[-20:-1]):
        signals.append("20-day breakout")
    if len(closes) >= 21 and last_close <= min(closes[-20:-1]):
        signals.append("20-day breakdown")
    if rsi14 is not None and rsi14 >= 70:
        signals.append("RSI overbought")
    if rsi14 is not None and rsi14 <= 30:
        signals.append("RSI oversold")
    if macd_value is not None and macd_value > 0:
        signals.append("MACD positive")
    if macd_value is not None and macd_value < 0:
        signals.append("MACD negative")

    avg_volume = sma(volumes, 20)
    volume_signal = ""
    if avg_volume and volumes[-1] > avg_volume * 1.5:
        volume_signal = "volume spike"

    return {
        "symbol": symbol,
        "company": company,
        "chart_url": chart_url(symbol),
        "last_close": fmt(last_close),
        "trend": ", ".join(signals) or "neutral",
        "rsi": fmt(rsi14),
        "macd": fmt(macd_value),
        "candle_patterns": ", ".join(candles),
        "chart_patterns": ", ".join(charts),
        "volume_signal": volume_signal,
        "twenty_day_return_pct": fmt(pct_change(closes[-20], last_close)) if len(closes) >= 20 else "",
        "fifty_day_return_pct": fmt(pct_change(closes[-50], last_close)) if len(closes) >= 50 else "",
    }


def fmt(value):
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.2f}"


def write_csv(path, rows):
    ensure_parent(path)
    fields = [
        "symbol",
        "company",
        "chart_url",
        "last_close",
        "trend",
        "rsi",
        "macd",
        "candle_patterns",
        "chart_patterns",
        "volume_signal",
        "twenty_day_return_pct",
        "fifty_day_return_pct",
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


def ensure_parent(path):
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def dated_report_dir(report_name):
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = Path("reports") / report_name / stamp
    path = base
    counter = 2

    while path.exists():
        path = Path("reports") / report_name / f"{stamp}_{counter:02d}"
        counter += 1

    path.mkdir(parents=True, exist_ok=False)
    return path


def rolling_sma(values, length):
    result = []
    for index in range(len(values)):
        if index + 1 < length:
            result.append(None)
        else:
            result.append(sum(values[index + 1 - length : index + 1]) / length)
    return result


def polyline(points, stroke, width=2, dash=""):
    if not points:
        return ""
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline points="{joined}" fill="none" stroke="{stroke}" stroke-width="{width}"{dash_attr} />'


def chart_svg(symbol, row, bars):
    bars = sorted(bars, key=lambda item: item["t"])[-120:]
    if len(bars) < 2:
        return '<div class="empty">Not enough bar data to draw a chart.</div>'

    width = 1120
    height = 560
    left = 58
    right = 52
    price_top = 34
    price_height = 350
    volume_top = 420
    volume_height = 86
    plot_width = width - left - right
    closes = [bar["c"] for bar in bars]
    highs = [bar["h"] for bar in bars]
    lows = [bar["l"] for bar in bars]
    volumes = [bar["v"] for bar in bars]
    sma20 = rolling_sma(closes, 20)
    sma50 = rolling_sma(closes, 50)
    price_min = min(lows + [value for value in sma20 + sma50 if value is not None])
    price_max = max(highs + [value for value in sma20 + sma50 if value is not None])
    padding = (price_max - price_min) * 0.08 or 1
    price_min -= padding
    price_max += padding
    max_volume = max(volumes) or 1
    candle_width = max(3, plot_width / len(bars) * 0.55)

    def x_for(index):
        return left + index * plot_width / max(1, len(bars) - 1)

    def y_price(value):
        return price_top + (price_max - value) / (price_max - price_min) * price_height

    def y_volume(value):
        return volume_top + volume_height - (value / max_volume * volume_height)

    grid = []
    for step in range(5):
        y = price_top + step * price_height / 4
        price = price_max - step * (price_max - price_min) / 4
        grid.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e7edf2" />')
        grid.append(f'<text x="{width - right + 8}" y="{y + 4:.2f}" class="axis">{price:.2f}</text>')

    volume_shapes = []
    candles = []
    for index, bar in enumerate(bars):
        x = x_for(index)
        color = "#0f7a3b" if bar["c"] >= bar["o"] else "#b42318"
        body_top = y_price(max(bar["o"], bar["c"]))
        body_height = max(1, abs(y_price(bar["o"]) - y_price(bar["c"])))
        volume_shapes.append(
            f'<rect x="{x - candle_width / 2:.2f}" y="{y_volume(bar["v"]):.2f}" width="{candle_width:.2f}" '
            f'height="{volume_top + volume_height - y_volume(bar["v"]):.2f}" fill="{color}" opacity="0.22" />'
        )
        candles.append(
            f'<line x1="{x:.2f}" y1="{y_price(bar["h"]):.2f}" x2="{x:.2f}" y2="{y_price(bar["l"]):.2f}" '
            f'stroke="{color}" stroke-width="1.2" />'
        )
        candles.append(
            f'<rect x="{x - candle_width / 2:.2f}" y="{body_top:.2f}" width="{candle_width:.2f}" '
            f'height="{body_height:.2f}" fill="{color}" rx="1" />'
        )

    sma20_line = polyline(
        [(x_for(index), y_price(value)) for index, value in enumerate(sma20) if value is not None],
        "#2563eb",
        2,
    )
    sma50_line = polyline(
        [(x_for(index), y_price(value)) for index, value in enumerate(sma50) if value is not None],
        "#7c3aed",
        2,
    )

    high_swings = swing_points(bars, "h", "high")
    low_swings = swing_points(bars, "l", "low")
    swing_marks = []
    for index, value in high_swings[-12:]:
        swing_marks.append(f'<circle cx="{x_for(index):.2f}" cy="{y_price(value):.2f}" r="3" fill="#b42318" opacity="0.75" />')
    for index, value in low_swings[-12:]:
        swing_marks.append(f'<circle cx="{x_for(index):.2f}" cy="{y_price(value):.2f}" r="3" fill="#0f7a3b" opacity="0.75" />')

    annotations = []
    chart_text = row["chart_patterns"].lower()
    double_top = find_double_top(bars, high_swings)
    double_bottom = find_double_bottom(bars, low_swings)
    if "double top" in chart_text and double_top:
        label, right_index, left_index, neckline = double_top
        peak_y = y_price((bars[left_index]["h"] + bars[right_index]["h"]) / 2)
        annotations.append(polyline([(x_for(left_index), y_price(bars[left_index]["h"])), (x_for(right_index), y_price(bars[right_index]["h"]))], "#b42318", 3))
        annotations.append(polyline([(x_for(left_index), y_price(neckline)), (x_for(right_index), y_price(neckline))], "#b42318", 2, "6 4"))
        annotations.append(f'<text x="{x_for(left_index):.2f}" y="{peak_y - 12:.2f}" class="bear-label">{html_escape(label)}</text>')
    if "double bottom" in chart_text and double_bottom:
        label, right_index, left_index, neckline = double_bottom
        bottom_y = y_price((bars[left_index]["l"] + bars[right_index]["l"]) / 2)
        annotations.append(polyline([(x_for(left_index), y_price(bars[left_index]["l"])), (x_for(right_index), y_price(bars[right_index]["l"]))], "#0f7a3b", 3))
        annotations.append(polyline([(x_for(left_index), y_price(neckline)), (x_for(right_index), y_price(neckline))], "#0f7a3b", 2, "6 4"))
        annotations.append(f'<text x="{x_for(left_index):.2f}" y="{bottom_y + 22:.2f}" class="bull-label">{html_escape(label)}</text>')

    if "triangle" in chart_text:
        recent_highs = [point for point in high_swings if point[0] >= len(bars) - 70][-4:]
        recent_lows = [point for point in low_swings if point[0] >= len(bars) - 70][-4:]
        if len(recent_highs) >= 2:
            annotations.append(polyline([(x_for(i), y_price(v)) for i, v in recent_highs], "#7c3aed", 2, "5 4"))
        if len(recent_lows) >= 2:
            annotations.append(polyline([(x_for(i), y_price(v)) for i, v in recent_lows], "#7c3aed", 2, "5 4"))
    if "flag" in chart_text:
        start = max(0, len(bars) - 35)
        flag_start = max(0, len(bars) - 12)
        annotations.append(polyline([(x_for(start), y_price(closes[start])), (x_for(flag_start), y_price(closes[flag_start]))], "#2563eb", 3))
        annotations.append(polyline([(x_for(flag_start), y_price(max(closes[flag_start:]))), (x_for(len(bars) - 1), y_price(max(closes[flag_start:])))], "#2563eb", 2, "5 4"))
        annotations.append(polyline([(x_for(flag_start), y_price(min(closes[flag_start:]))), (x_for(len(bars) - 1), y_price(min(closes[flag_start:])))], "#2563eb", 2, "5 4"))

    first_date = bars[0]["t"][:10]
    last_date = bars[-1]["t"][:10]
    return f"""<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html_escape(symbol)} technical price graph">
      <rect x="0" y="0" width="{width}" height="{height}" fill="white" />
      <text x="{left}" y="22" class="title">{html_escape(symbol)} daily chart</text>
      <text x="{width - right - 190}" y="22" class="axis">{first_date} to {last_date}</text>
      {''.join(grid)}
      <line x1="{left}" y1="{volume_top}" x2="{width - right}" y2="{volume_top}" stroke="#d9e1e8" />
      {''.join(volume_shapes)}
      {''.join(candles)}
      {sma20_line}
      {sma50_line}
      {''.join(swing_marks)}
      {''.join(annotations)}
      <text x="{left}" y="{height - 24}" class="legend"><tspan fill="#2563eb">SMA20</tspan>  <tspan fill="#7c3aed">SMA50</tspan>  <tspan fill="#b42318">swing highs</tspan>  <tspan fill="#0f7a3b">swing lows</tspan></text>
    </svg>"""


def badge_list(value):
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return '<span class="muted">None detected</span>'
    return " ".join(f'<span class="badge">{html_escape(item)}</span>' for item in items)


def write_chart_pages(directory, rows, bars_by_symbol):
    chart_dir = Path(directory)
    chart_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        symbol = row["symbol"]
        bars = bars_by_symbol.get(symbol, [])
        graph = chart_svg(symbol, row, bars)
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(symbol)} Technical Graph</title>
  <style>
    :root {{
      --ink: #17202a;
      --muted: #607080;
      --line: #d9e1e8;
      --panel: #f6f8fa;
      --positive: #0f7a3b;
      --negative: #b42318;
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
      padding: 26px 18px 44px;
    }}
    a {{
      color: #205493;
      text-decoration: none;
      font-weight: 700;
    }}
    h1 {{
      margin: 14px 0 4px;
      font-size: 28px;
    }}
    .meta {{
      color: var(--muted);
      margin: 0 0 18px;
    }}
    .summary {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      margin: 0 0 18px;
      padding: 14px;
    }}
    .label {{
      color: var(--muted);
      display: block;
      font-size: 12px;
      text-transform: uppercase;
    }}
    .badge {{
      background: white;
      border: 1px solid var(--line);
      border-radius: 6px;
      display: inline-block;
      margin: 4px 5px 0 0;
      padding: 4px 7px;
    }}
    .muted, .axis, .legend {{
      color: var(--muted);
      fill: var(--muted);
      font-size: 13px;
    }}
    .chart {{
      border: 1px solid var(--line);
      border-radius: 8px;
      width: 100%;
      height: auto;
    }}
    .title {{
      fill: var(--ink);
      font-size: 16px;
      font-weight: 700;
    }}
    .bull-label {{
      fill: var(--positive);
      font-size: 14px;
      font-weight: 700;
    }}
    .bear-label {{
      fill: var(--negative);
      font-size: 14px;
      font-weight: 700;
    }}
    .empty {{
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--muted);
      padding: 24px;
    }}
  </style>
</head>
<body>
  <main>
    <a href="../technical_report.html">Back to technical report</a>
    <h1>{html_escape(symbol)} Technical Graph</h1>
    <p class="meta">{html_escape(row['company'])}. Daily bars from Alpaca. Pattern lines are mechanical approximations.</p>
    <div class="summary">
      <div><span class="label">Chart Pattern</span>{badge_list(row['chart_patterns'])}</div>
      <div><span class="label">Candle Pattern</span>{badge_list(row['candle_patterns'])}</div>
      <div><span class="label">Trend</span>{html_escape(row['trend'])}</div>
      <div><span class="label">RSI / MACD</span>{html_escape(row['rsi'])} / {html_escape(row['macd'])}</div>
    </div>
    {graph}
  </main>
</body>
</html>
"""
        (chart_dir / f"{safe_symbol(symbol)}.html").write_text(html, encoding="utf-8")


def write_html(path, rows):
    ensure_parent(path)
    body = []
    for row in rows:
        trend_class = "neutral"
        trend_text = row["trend"].lower()
        chart_text = row["chart_patterns"].lower()
        if "bull" in trend_text or "breakout" in trend_text or "oversold" in trend_text:
            trend_class = "positive"
        if "bear" in trend_text or "breakdown" in trend_text or "overbought" in trend_text:
            trend_class = "negative"
        if "double bottom" in chart_text or "ascending" in chart_text or "inverse" in chart_text or "bull flag" in chart_text:
            trend_class = "positive"
        if "double top" in chart_text or "descending" in chart_text or ("head and shoulders" in chart_text and "inverse" not in chart_text) or "bear flag" in chart_text:
            trend_class = "negative"

        body.append(
            "<tr>"
            f"<td>{html_escape(row['symbol'])}</td>"
            f"<td><a class=\"chart-link\" href=\"{html_escape(row['chart_url'])}\">Graph</a></td>"
            f"<td>{html_escape(row['company'])}</td>"
            f"<td class=\"num\">{html_escape(row['last_close'])}</td>"
            f"<td class=\"{trend_class}\">{html_escape(row['trend'])}</td>"
            f"<td class=\"num\">{html_escape(row['rsi'])}</td>"
            f"<td class=\"num\">{html_escape(row['macd'])}</td>"
            f"<td>{html_escape(row['candle_patterns'])}</td>"
            f"<td class=\"{trend_class}\">{html_escape(row['chart_patterns'])}</td>"
            f"<td>{html_escape(row['volume_signal'])}</td>"
            f"<td class=\"num\">{pct_text(row['twenty_day_return_pct'])}</td>"
            f"<td class=\"num\">{pct_text(row['fifty_day_return_pct'])}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Technical Analysis Report</title>
  <style>
    :root {{
      --ink: #17202a;
      --muted: #607080;
      --line: #d9e1e8;
      --panel: #f6f8fa;
      --positive: #0f7a3b;
      --negative: #b42318;
    }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: white;
    }}
    main {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
    }}
    p {{
      color: var(--muted);
      margin: 0 0 20px;
    }}
    .page-link {{
      display: inline-block;
      margin: 0 0 20px;
      color: #205493;
      font-weight: 700;
      text-decoration: none;
    }}
    .page-link:hover {{
      text-decoration: underline;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
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
    .positive {{
      color: var(--positive);
      font-weight: 700;
    }}
    .negative {{
      color: var(--negative);
      font-weight: 700;
    }}
    .neutral {{
      color: var(--ink);
    }}
    .chart-link {{
      color: #205493;
      font-weight: 700;
      text-decoration: none;
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
    <h1>Technical Analysis Report</h1>
    <p>Daily-bar pattern scan using Alpaca market data. Signals are mechanical, not trading advice.</p>
    <a class="page-link" href="https://dirtybug.github.io/stocks/" target="_blank" rel="noopener">GitHub Page</a>
    <table>
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Graph</th>
          <th>Company</th>
          <th class="num">Close</th>
          <th>Trend / Signal</th>
          <th class="num">RSI</th>
          <th class="num">MACD</th>
          <th>Candle Pattern</th>
          <th>Chart Pattern</th>
          <th>Volume</th>
          <th class="num">20D Return</th>
          <th class="num">50D Return</th>
        </tr>
      </thead>
      <tbody>
        {''.join(body)}
      </tbody>
    </table>
  </main>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)


def print_summary(rows, limit):
    print("Symbol  Close      RSI     MACD      Chart Pattern                 Trend")
    print("------  ---------  ------  --------  ----------------------------  --------------------------------")
    for row in rows[:limit]:
        print(
            f"{row['symbol']:<6}  "
            f"{row['last_close']:>9}  "
            f"{row['rsi']:>6}  "
            f"{row['macd']:>8}  "
            f"{row['chart_patterns'][:28]:<28}  "
            f"{row['trend'][:32]}"
        )


def main():
    parser = argparse.ArgumentParser(description="Generate a technical-analysis report for favorite stocks.")
    parser.add_argument("--favorites", default="favorite_stocks.csv")
    parser.add_argument("--report-dir")
    parser.add_argument("--output")
    parser.add_argument("--html-output")
    parser.add_argument("--chart-dir")
    parser.add_argument("--feed", default="iex", choices=["iex", "sip"])
    parser.add_argument("--timeframe", default="1Day")
    parser.add_argument("--limit", default=120, type=int)
    parser.add_argument("--summary-limit", default=30, type=int)
    args = parser.parse_args()

    report_dir = Path(args.report_dir) if args.report_dir else dated_report_dir("technical")
    args.output = args.output or str(report_dir / "technical_report.csv")
    args.html_output = args.html_output or str(report_dir / "technical_report.html")
    args.chart_dir = args.chart_dir or str(report_dir / "technical_charts")

    favorites = read_favorites(args.favorites)
    symbols = [favorite["symbol"].strip().upper() for favorite in favorites]
    bars_by_symbol = fetch_bars(symbols, args.feed, args.timeframe, args.limit)

    rows = []
    for favorite in favorites:
        symbol = favorite["symbol"].strip().upper()
        company = favorite["company"].strip()
        rows.append(detect(symbol, company, bars_by_symbol.get(symbol, [])))

    write_chart_pages(args.chart_dir, rows, bars_by_symbol)
    write_csv(args.output, rows)
    write_html(args.html_output, rows)
    print_summary(rows, args.summary_limit)
    print()
    print(f"Saved report to {args.output}")
    print(f"Saved HTML report to {args.html_output}")
    print(f"Saved graph pages to {args.chart_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
