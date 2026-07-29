#!/usr/bin/env python3
"""Paper-trading signal generator: runs on the SAME Windows machine as a
live MT5 terminal (uses the official MetaTrader5 Python package to pull
fresh bars directly from the terminal), computes signals with the exact
same goldscalper pipeline used for backtesting, and writes them to a
signal file that GoldScalperLiveEA.mq5 watches and acts on.

Division of labor (same split as the original inspiration for this whole
project): this script does all the strategy thinking -- indicators, SMC
detection, Edge Score, direction -- and hands the EA only mechanical
numbers (price-unit offsets for SL/TP/trailing, derived from ATR at
signal time). The EA just executes and manages the position tick-by-
tick; it doesn't need to know anything about the strategy itself.

NOT LIVE-TESTED: written and reasoned through carefully, and it reuses
the exact same goldscalper functions already validated in backtesting,
but this exact script has not been run against a live MT5 connection
(this environment has no market data access to test that with). Run it
in --dry-run mode first and watch the log before trusting it to write
real signals for the EA to act on.

Requirements (on the Windows machine running this):
    pip install MetaTrader5 pandas numpy

Usage:
    python scripts/live_signal_generator.py --symbol GOLD --preset trend_htf
    python scripts/live_signal_generator.py --symbol GOLD --preset trend_htf --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from goldscalper.indicators import add_base_indicators
from goldscalper.mtf import add_multi_timeframe_trend
from goldscalper.edge_score import compute_edge_scores
from goldscalper import presets

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # allowed so --dry-run --replay-csv can be smoke-tested without the package


SIGNAL_COLUMNS = [
    "signal_id", "generated_at", "symbol", "direction",
    "sl_offset", "tp_offset", "trailing_activation_offset", "trailing_distance_offset",
    "edge_score",
]


def get_preset(name: str):
    if name == "trend_htf":
        return presets.TREND_HTF_EDGE_CONFIG, presets.TREND_HTF_BACKTEST_CONFIG, presets.TREND_HTF_MTF_RULES
    if name == "trend_low_dd":
        return presets.TREND_LOW_DRAWDOWN_EDGE_CONFIG, presets.TREND_LOW_DRAWDOWN_BACKTEST_CONFIG, None
    if name == "eurusd":
        return presets.EURUSD_EDGE_CONFIG, presets.EURUSD_BACKTEST_CONFIG, presets.EURUSD_MTF_RULES
    raise ValueError(f"Unknown preset: {name}")


def fetch_recent_bars(symbol: str, n_bars: int) -> pd.DataFrame:
    """Pull the last n_bars *closed* H1 bars from the running MT5 terminal."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, n_bars)  # start=1 skips the still-forming bar
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No rates returned for {symbol} -- check the symbol name and MT5 connection")

    df = pd.DataFrame(rates)
    df["timestamp"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("timestamp")
    df = df.rename(columns={"tick_volume": "volume"})
    df["spread"] = df["spread"].astype(float)
    return df[["open", "high", "low", "close", "volume", "spread"]].astype(float)


def next_bar_close(now: datetime) -> datetime:
    """The next top-of-the-hour boundary after `now`, plus a small buffer
    so the broker has definitely finalized that bar's data."""
    next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    return next_hour + timedelta(seconds=10)


def read_last_signal_id(signal_path: Path) -> int:
    if not signal_path.exists():
        return -1
    with open(signal_path, newline="") as f:
        rows = list(csv.DictReader(f))
    return int(rows[-1]["signal_id"]) if rows else -1


def append_signal(signal_path: Path, row: dict) -> None:
    is_new = not signal_path.exists()
    with open(signal_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SIGNAL_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def run_once(symbol: str, preset_name: str, signal_path: Path, log_path: Path, dry_run: bool) -> None:
    edge_cfg, bt_cfg, mtf_rules = get_preset(preset_name)

    df = fetch_recent_bars(symbol, n_bars=1000)  # generous lookback for EMA/RSI/ATR/SMC warmup
    df = add_base_indicators(df)
    if mtf_rules:
        df = add_multi_timeframe_trend(df, mtf_rules)

    scores = compute_edge_scores(df, edge_cfg)
    latest = scores.iloc[-1]
    latest_bar = df.iloc[-1]
    atr = float(latest_bar["atr"])

    log_line = (
        f"{datetime.now(timezone.utc).isoformat()} bar={df.index[-1]} "
        f"score_buy={latest['score_buy']:.1f} score_sell={latest['score_sell']:.1f} "
        f"approved={bool(latest['approved'])} direction={latest['direction']} atr={atr:.3f}\n"
    )
    print(log_line.strip())
    with open(log_path, "a") as f:
        f.write(log_line)

    if not latest["approved"]:
        return

    signal_id = read_last_signal_id(signal_path) + 1
    row = {
        "signal_id": signal_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "direction": latest["direction"],
        "sl_offset": bt_cfg.sl_atr_mult * atr,
        "tp_offset": bt_cfg.tp_atr_mult * atr,
        "trailing_activation_offset": bt_cfg.trailing_activation_atr_mult * atr,
        "trailing_distance_offset": bt_cfg.trailing_distance_atr_mult * atr,
        "edge_score": float(latest["score"]),
    }

    if dry_run:
        print(f"[DRY RUN] would write signal: {row}")
    else:
        append_signal(signal_path, row)
        print(f"Signal #{signal_id} written to {signal_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper-trading live signal generator")
    parser.add_argument("--symbol", required=True, help="Exact MT5 symbol name, e.g. GOLD")
    parser.add_argument("--preset", choices=["trend_htf", "trend_low_dd", "eurusd"], default="trend_htf")
    parser.add_argument("--signal-file", default="goldscalper_signal.csv")
    parser.add_argument("--log-file", default="goldscalper_live_log.txt")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print signals but don't write the file")
    parser.add_argument("--once", action="store_true", help="Run a single check and exit (for testing)")
    args = parser.parse_args()

    if mt5 is None:
        parser.error("MetaTrader5 package not installed -- run: pip install MetaTrader5")

    if not mt5.initialize():
        parser.error(f"MT5 initialize() failed: {mt5.last_error()} -- is the MT5 terminal running and logged in?")

    signal_path = Path(args.signal_file)
    log_path = Path(args.log_file)
    print(f"Connected to MT5. Watching {args.symbol} with preset '{args.preset}'.")
    print(f"Signal file: {signal_path.resolve()}")
    print(f"Log file:    {log_path.resolve()}")

    try:
        if args.once:
            run_once(args.symbol, args.preset, signal_path, log_path, args.dry_run)
            return

        while True:
            try:
                run_once(args.symbol, args.preset, signal_path, log_path, args.dry_run)
            except Exception as e:
                err_line = f"{datetime.now(timezone.utc).isoformat()} ERROR: {e}\n"
                print(err_line.strip())
                with open(log_path, "a") as f:
                    f.write(err_line)

            wake_at = next_bar_close(datetime.now())
            sleep_s = max(1.0, (wake_at - datetime.now()).total_seconds())
            print(f"Sleeping {sleep_s/60:.1f} min until next H1 close check ({wake_at})...")
            time.sleep(sleep_s)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
