#!/usr/bin/env python3
"""CLI entry point: randomized search over Edge Score weights + threshold,
validated by walk-forward cross-validation (multiple chronological
train/test folds) to flag overfitting or a merely-lucky split.

Usage:
    python scripts/tune_edge_score.py --csv data/xauusd_h1.csv --trials 300
    python scripts/tune_edge_score.py --synthetic --bars 4000 --trials 100

NOTE: run against --synthetic data this only smoke-tests the search code --
it is fitting to random-walk noise, not finding a real trading edge. Point
it at real historical data before trusting any output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from goldscalper.data import generate_synthetic, load_csv
from goldscalper.indicators import add_base_indicators
from goldscalper.tune import TuneConfig, search


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune Edge Score weights via randomized search")
    parser.add_argument("--csv", type=str, help="Path to a historical OHLCV CSV export")
    parser.add_argument("--synthetic", action="store_true", help="Use generated synthetic data")
    parser.add_argument("--bars", type=int, default=4000, help="Bars for synthetic data")
    parser.add_argument("--trials", type=int, default=200, help="Number of random weight sets to try")
    parser.add_argument(
        "--folds", type=int, default=4, help="Walk-forward folds (data split into folds+1 chronological chunks)"
    )
    parser.add_argument("--min-trades", type=int, default=15, help="Min trades per fold for a candidate to count")
    parser.add_argument("--top-n", type=int, default=5, help="How many top candidates to report")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="reports/tuning_results.csv")
    args = parser.parse_args()

    if not args.csv and not args.synthetic:
        parser.error("Provide --csv <path> or --synthetic")

    if args.csv:
        df = load_csv(args.csv)
        print(f"Loaded {len(df)} bars from {args.csv}")
    else:
        df = generate_synthetic(n_bars=args.bars)
        print(
            f"Generated {len(df)} synthetic bars.\n"
            "WARNING: tuning against synthetic data only validates the search "
            "code -- results below are fitting to noise, not a real edge."
        )

    df = add_base_indicators(df)

    tcfg = TuneConfig(
        n_trials=args.trials,
        n_folds=args.folds,
        min_trades=args.min_trades,
        seed=args.seed,
    )

    print(f"Running {args.trials} trials across {tcfg.n_folds} walk-forward folds...")
    results = search(df, tcfg, top_n=args.top_n)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 30)
    print("\n=== Top candidates (ranked by avg train objective across folds) ===")
    print(results.to_string(index=False))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_path, index=False)
    print(f"\nFull results saved to {out_path}")

    if not results.empty:
        best = results.iloc[0]
        degrades = (
            best["avg_test_obj"] < best["avg_train_obj"] * 0.5
            or best["worst_fold_test_obj"] < 0
            or best["total_test_trades"] < args.min_trades * tcfg.n_folds
        )
        if degrades:
            print(
                "\nNote: the top train candidate performs notably worse out-of-sample, or "
                "has at least one losing/too-thin fold -- treat it as overfit, not a "
                "validated edge, even though its train-side numbers look good."
            )


if __name__ == "__main__":
    main()
