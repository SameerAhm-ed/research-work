#!/usr/bin/env python3
"""CLI entry point: Monte Carlo trade-sequence robustness analysis.

A single backtest shows one historical path through time. This resamples
the realized trade returns to check whether the reported drawdown/return
are typical outcomes for this strategy, or a lucky/unlucky specific
ordering -- and estimates the tail risk (e.g. "1% chance of this bad a
drawdown") that a single historical run can't show on its own.

Usage:
    python scripts/monte_carlo_analysis.py --csv data/gold_h1.csv --preset trend_htf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from goldscalper.backtest import BacktestConfig, run_backtest
from goldscalper.data import load_csv
from goldscalper.edge_score import compute_edge_scores
from goldscalper.indicators import add_base_indicators
from goldscalper.montecarlo import monte_carlo_bootstrap, summarize
from goldscalper.mtf import add_multi_timeframe_trend
from goldscalper.report import compute_stats
from goldscalper import presets


def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo trade-sequence robustness analysis")
    parser.add_argument("--csv", type=str, required=True, help="Path to a historical OHLCV CSV export")
    parser.add_argument("--preset", choices=["trend_htf", "trend_low_dd"], default="trend_htf")
    parser.add_argument("--n-sims", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=str, default="reports")
    args = parser.parse_args()

    df = load_csv(args.csv)
    print(f"Loaded {len(df)} bars from {args.csv}")
    df = add_base_indicators(df)

    if args.preset == "trend_htf":
        df = add_multi_timeframe_trend(df, presets.TREND_HTF_MTF_RULES)
        edge_cfg = presets.TREND_HTF_EDGE_CONFIG
        bt_cfg = presets.TREND_HTF_BACKTEST_CONFIG
    else:
        edge_cfg = presets.TREND_LOW_DRAWDOWN_EDGE_CONFIG
        bt_cfg = presets.TREND_LOW_DRAWDOWN_BACKTEST_CONFIG

    scores = compute_edge_scores(df, edge_cfg)
    trades, equity = run_backtest(df, scores, bt_cfg)
    actual = compute_stats(trades, equity, bt_cfg.starting_equity)
    print(f"Preset: {args.preset} -- {len(trades)} trades, "
          f"actual DD={actual['max_drawdown_pct']:.2f}%, actual return={actual['return_pct']:.1f}%")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for method in ["shuffle", "resample"]:
        sims = monte_carlo_bootstrap(trades, bt_cfg.starting_equity, n_sims=args.n_sims, method=method, seed=args.seed)
        s = summarize(sims, actual["max_drawdown_pct"], actual["return_pct"])
        results[method] = (sims, s)
        print(f"\n=== method={method} (n={args.n_sims}) ===")
        print(f"  Drawdown: median={s['sim_dd_median']:.2f}%  "
              f"10-90% range=[{s['sim_dd_p90_worst_case']:.2f}%, {s['sim_dd_p10_best_case']:.2f}%]  "
              f"worst 1% tail={s['sim_dd_p99_tail_case']:.2f}%")
        print(f"  Return:   median={s['sim_return_median']:.1f}%  "
              f"10-90% range=[{s['sim_return_p10']:.1f}%, {s['sim_return_p90']:.1f}%]")
        print(f"  Actual drawdown percentile rank: {s['actual_dd_percentile_rank']:.1f} "
              "(0=best-case ordering ever seen, 100=worst)")
        print(f"  Actual return percentile rank:   {s['actual_return_percentile_rank']:.1f} (0=worst, 100=best)")
        sims.to_csv(out_dir / f"montecarlo_{args.preset}_{method}.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    shuffle_sims, _ = results["shuffle"]
    resample_sims, _ = results["resample"]

    axes[0].hist(shuffle_sims["max_drawdown_pct"], bins=50, color="#dc2626", alpha=0.6, label="shuffle (reordered)")
    axes[0].hist(resample_sims["max_drawdown_pct"], bins=50, color="#2563eb", alpha=0.5, label="bootstrap resample")
    axes[0].axvline(actual["max_drawdown_pct"], color="black", linestyle="--", linewidth=2,
                     label=f"actual realized ({actual['max_drawdown_pct']:.2f}%)")
    axes[0].set_title(f"Max Drawdown Distribution ({args.n_sims} simulations)")
    axes[0].set_xlabel("Max Drawdown (%)")
    axes[0].legend(fontsize=8)

    axes[1].hist(resample_sims["return_pct"], bins=50, color="#16a34a", alpha=0.6, label="bootstrap resample")
    axes[1].axvline(actual["return_pct"], color="black", linestyle="--", linewidth=2,
                     label=f"actual realized ({actual['return_pct']:.1f}%)")
    axes[1].set_title("Total Return Distribution\n(shuffle return is order-invariant, not shown)")
    axes[1].set_xlabel("Total Return (%)")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    chart_path = out_dir / f"montecarlo_{args.preset}.png"
    fig.savefig(chart_path, dpi=140)
    print(f"\nChart saved to {chart_path}")


if __name__ == "__main__":
    main()
