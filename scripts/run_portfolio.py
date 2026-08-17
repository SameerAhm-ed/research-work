#!/usr/bin/env python3
"""CLI entry point: run the GOLD + EURUSD combined portfolio and compare
against GOLD alone, to see the diversification benefit directly.

Usage:
    python scripts/run_portfolio.py --gold-csv data/gold_h1.csv --eurusd-csv data/eurusd_h1.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldscalper.backtest import BacktestConfig, run_backtest
from goldscalper.data import load_csv
from goldscalper.edge_score import compute_edge_scores
from goldscalper.indicators import add_base_indicators
from goldscalper.mtf import add_multi_timeframe_trend
from goldscalper.portfolio import combine_equity_curves, portfolio_stats
from goldscalper import presets


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the combined GOLD+EURUSD portfolio")
    parser.add_argument("--gold-csv", type=str, required=True)
    parser.add_argument("--eurusd-csv", type=str, required=True)
    parser.add_argument("--risk-pct", type=float, default=0.01, help="Risk per trade, per leg")
    parser.add_argument("--starting-equity-per-leg", type=float, default=5000.0)
    args = parser.parse_args()

    df_g = load_csv(args.gold_csv)
    df_g = add_base_indicators(df_g)
    df_g = add_multi_timeframe_trend(df_g, presets.TREND_HTF_MTF_RULES)
    bt_g = BacktestConfig(
        sl_atr_mult=presets.TREND_HTF_BACKTEST_CONFIG.sl_atr_mult,
        tp_atr_mult=presets.TREND_HTF_BACKTEST_CONFIG.tp_atr_mult,
        trailing_stop_enabled=True,
        trailing_activation_atr_mult=presets.TREND_HTF_BACKTEST_CONFIG.trailing_activation_atr_mult,
        trailing_distance_atr_mult=presets.TREND_HTF_BACKTEST_CONFIG.trailing_distance_atr_mult,
        risk_pct=args.risk_pct,
        starting_equity=args.starting_equity_per_leg,
    )
    scores_g = compute_edge_scores(df_g, presets.TREND_HTF_EDGE_CONFIG)
    trades_g, equity_g = run_backtest(df_g, scores_g, bt_g)

    df_e = load_csv(args.eurusd_csv)
    df_e = add_base_indicators(df_e)
    df_e = add_multi_timeframe_trend(df_e, presets.EURUSD_MTF_RULES)
    bt_e = BacktestConfig(
        sl_atr_mult=presets.EURUSD_BACKTEST_CONFIG.sl_atr_mult,
        tp_atr_mult=presets.EURUSD_BACKTEST_CONFIG.tp_atr_mult,
        trailing_stop_enabled=True,
        trailing_activation_atr_mult=presets.EURUSD_BACKTEST_CONFIG.trailing_activation_atr_mult,
        trailing_distance_atr_mult=presets.EURUSD_BACKTEST_CONFIG.trailing_distance_atr_mult,
        point_size=presets.EURUSD_BACKTEST_CONFIG.point_size,
        risk_pct=args.risk_pct,
        starting_equity=args.starting_equity_per_leg,
    )
    scores_e = compute_edge_scores(df_e, presets.EURUSD_EDGE_CONFIG)
    trades_e, equity_e = run_backtest(df_e, scores_e, bt_e)

    combined = combine_equity_curves({"gold": (equity_g, args.starting_equity_per_leg),
                                       "eurusd": (equity_e, args.starting_equity_per_leg)})
    stats = portfolio_stats(combined)

    print(f"GOLD leg: {len(trades_g)} trades, EURUSD leg: {len(trades_e)} trades")
    print(f"Combined portfolio (risk_pct={args.risk_pct} per leg, "
          f"${args.starting_equity_per_leg:.0f} starting capital per leg):")
    print(f"  Return:       {stats['return_pct']:.2f}%")
    print(f"  Max drawdown: {stats['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe:       {stats['sharpe']:.2f}")
    print(f"  Ending equity: ${stats['ending_equity']:.2f}")


if __name__ == "__main__":
    main()
