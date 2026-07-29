#!/usr/bin/env python3
"""CLI entry point: run the GoldScalper SMC backtest end-to-end.

Usage:
    python scripts/run_backtest.py --csv data/xauusd_h1.csv
    python scripts/run_backtest.py --synthetic --bars 3000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldscalper.backtest import BacktestConfig, run_backtest
from goldscalper.data import generate_synthetic, load_csv
from goldscalper.edge_score import EdgeScoreConfig, compute_edge_scores
from goldscalper.indicators import add_base_indicators
from goldscalper.report import compute_stats, plot_report, print_summary
from goldscalper import presets


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GoldScalper SMC backtest")
    parser.add_argument("--csv", type=str, help="Path to a historical OHLCV CSV export")
    parser.add_argument("--synthetic", action="store_true", help="Use generated synthetic data")
    parser.add_argument("--bars", type=int, default=3000, help="Bars for synthetic data")
    parser.add_argument(
        "--preset",
        choices=["trend_low_dd"],
        help="Use a validated preset config instead of --threshold/defaults (see goldscalper/presets.py)",
    )
    parser.add_argument("--threshold", type=float, default=70.0, help="Edge Score approval threshold")
    parser.add_argument("--risk-pct", type=float, default=0.01, help="Fraction of equity risked per trade")
    parser.add_argument("--out-dir", type=str, default="reports", help="Output directory for report files")
    args = parser.parse_args()

    if not args.csv and not args.synthetic:
        parser.error("Provide --csv <path> or --synthetic")

    if args.csv:
        df = load_csv(args.csv)
        print(f"Loaded {len(df)} bars from {args.csv}")
    else:
        df = generate_synthetic(n_bars=args.bars)
        print(f"Generated {len(df)} synthetic bars (pipeline smoke-test data, not real market data)")

    df = add_base_indicators(df)

    if args.preset == "trend_low_dd":
        edge_cfg = presets.TREND_LOW_DRAWDOWN_EDGE_CONFIG
        preset_bt = presets.TREND_LOW_DRAWDOWN_BACKTEST_CONFIG
        bt_cfg = BacktestConfig(
            risk_pct=args.risk_pct,
            sl_atr_mult=preset_bt.sl_atr_mult,
            tp_atr_mult=preset_bt.tp_atr_mult,
            trailing_stop_enabled=preset_bt.trailing_stop_enabled,
            trailing_activation_atr_mult=preset_bt.trailing_activation_atr_mult,
            trailing_distance_atr_mult=preset_bt.trailing_distance_atr_mult,
        )
        print("Using preset: trend_low_dd (see goldscalper/presets.py for validation notes)")
    else:
        edge_cfg = EdgeScoreConfig(approval_threshold=args.threshold)
        bt_cfg = BacktestConfig(risk_pct=args.risk_pct)

    scores = compute_edge_scores(df, edge_cfg)
    trades, equity = run_backtest(df, scores, bt_cfg)

    stats = compute_stats(trades, equity, bt_cfg.starting_equity)
    print_summary(stats)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trades_path = out_dir / "trades.csv"
    trades.to_csv(trades_path, index=False)
    print(f"\nTrade log saved to {trades_path}")

    chart_path = out_dir / "equity_curve.png"
    plot_report(trades, equity, str(chart_path))
    print(f"Equity curve saved to {chart_path}")


if __name__ == "__main__":
    main()
