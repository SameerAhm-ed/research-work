"""Combine multiple instruments' equity curves into one portfolio equity
curve, to measure real diversification benefit (not just each leg's own
numbers) -- two uncorrelated positive-expectancy strategies combined can
have a shallower drawdown than either alone, since a bad stretch in one
tends not to coincide with a bad stretch in the other.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def combine_equity_curves(
    legs: dict[str, tuple[pd.DataFrame, float]], resample_rule: str = "1D"
) -> pd.Series:
    """Combine per-leg equity curves (each from backtest.run_backtest) into
    one portfolio equity series.

    `legs` maps a label to (equity_df, starting_equity) for that leg.
    Each leg's dollar PnL (equity - its own starting_equity) is resampled
    onto a common index and forward-filled (so instruments trading on
    different calendars -- e.g. gold vs forex holiday schedules -- still
    combine sensibly), then summed. The combined starting capital is the
    sum of each leg's starting_equity.
    """
    pnl_series = {}
    for label, (equity_df, starting_equity) in legs.items():
        pnl = (equity_df.set_index("timestamp")["equity"] - starting_equity).resample(resample_rule).last().ffill()
        pnl_series[label] = pnl

    combined_idx = pnl_series[next(iter(pnl_series))].index
    for pnl in pnl_series.values():
        combined_idx = combined_idx.union(pnl.index)

    total_starting_equity = sum(starting_equity for _, starting_equity in legs.values())
    combined = pd.Series(total_starting_equity, index=combined_idx)
    for pnl in pnl_series.values():
        combined = combined.add(pnl.reindex(combined_idx).ffill().fillna(0.0))

    return combined


def portfolio_stats(combined_equity: pd.Series) -> dict:
    """Return-and-drawdown summary for a combined equity series (same
    metrics as report.compute_stats, but for a pre-combined curve rather
    than a single backtest's trades/equity)."""
    start = combined_equity.iloc[0]
    end = combined_equity.iloc[-1]
    running_max = combined_equity.cummax()
    drawdown_pct = (combined_equity - running_max) / running_max * 100

    daily = combined_equity.resample("1D").last().dropna().pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else float("nan")

    return {
        "return_pct": float((end - start) / start * 100),
        "max_drawdown_pct": float(drawdown_pct.min()),
        "sharpe": sharpe,
        "ending_equity": float(end),
    }
