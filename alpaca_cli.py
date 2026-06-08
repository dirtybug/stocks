#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from alpaca_env import load_env


DEFAULT_BASE_URL = "https://paper-api.alpaca.markets/v2"
load_env()


class AlpacaError(Exception):
    pass


def env(name):
    value = os.environ.get(name)
    if not value:
        raise AlpacaError(f"Missing required environment variable: {name}")
    return value


def request(method, path, body=None):
    base_url = os.environ.get("APCA_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}{path}"
    headers = {
        "APCA-API-KEY-ID": env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": env("APCA_API_SECRET_KEY"),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method=method, headers=headers, data=data)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise AlpacaError(f"{method} {url} failed with HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise AlpacaError(f"{method} {url} failed: {exc.reason}") from exc


def print_json(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def account(_args):
    print_json(request("GET", "/account"))


def positions(_args):
    print_json(request("GET", "/positions"))


def orders(args):
    params = {
        "status": args.status,
        "limit": str(args.limit),
        "direction": "desc",
    }
    print_json(request("GET", f"/orders?{urllib.parse.urlencode(params)}"))


def buy(args):
    order = {
        "symbol": args.symbol.upper(),
        "side": "buy",
        "type": args.type,
        "time_in_force": args.time_in_force,
    }

    if args.qty is not None:
        order["qty"] = str(args.qty)
    if args.notional is not None:
        order["notional"] = str(args.notional)
    if args.limit_price is not None:
        order["limit_price"] = str(args.limit_price)

    print_json(request("POST", "/orders", order))


def cancel(args):
    if args.order_id == "all":
        print_json(request("DELETE", "/orders"))
    else:
        print_json(request("DELETE", f"/orders/{urllib.parse.quote(args.order_id)}"))


def build_parser():
    parser = argparse.ArgumentParser(description="Small Alpaca trading CLI.")
    subparsers = parser.add_subparsers(required=True)

    account_parser = subparsers.add_parser("account", help="Show account details.")
    account_parser.set_defaults(func=account)

    positions_parser = subparsers.add_parser("positions", help="Show open positions.")
    positions_parser.set_defaults(func=positions)

    orders_parser = subparsers.add_parser("orders", help="Show orders.")
    orders_parser.add_argument("--status", default="open", choices=["open", "closed", "all"])
    orders_parser.add_argument("--limit", default=50, type=int)
    orders_parser.set_defaults(func=orders)

    buy_parser = subparsers.add_parser("buy", help="Submit a buy order.")
    buy_parser.add_argument("symbol", help="Ticker symbol, such as AAPL.")
    size_group = buy_parser.add_mutually_exclusive_group(required=True)
    size_group.add_argument("--qty", type=float, help="Share quantity.")
    size_group.add_argument("--notional", type=float, help="Dollar amount.")
    buy_parser.add_argument("--type", default="market", choices=["market", "limit"])
    buy_parser.add_argument("--limit-price", type=float)
    buy_parser.add_argument("--time-in-force", default="day", choices=["day", "gtc", "opg", "cls", "ioc", "fok"])
    buy_parser.set_defaults(func=buy)

    cancel_parser = subparsers.add_parser("cancel", help="Cancel one order id, or all open orders.")
    cancel_parser.add_argument("order_id", help="Order id, or 'all'.")
    cancel_parser.set_defaults(func=cancel)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "type", None) == "limit" and args.limit_price is None:
        parser.error("buy --type limit requires --limit-price")

    try:
        args.func(args)
    except AlpacaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
