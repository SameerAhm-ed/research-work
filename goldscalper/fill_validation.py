"""Validate H1-bar SL/TP/trailing-stop fill simulation against real M1
intrabar price paths.

The H1 backtest only sees each bar's open/high/low/close, not the actual
sequence price moved through -- so when both the stop and target are
touched within one bar, it has to guess (conservatively, assuming the
adverse side first). This replays the same trades (same entry, same
SL/TP/trailing config) bar-by-bar through 1-minute data instead, to check
whether that H1 approximation is materially wrong.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .backtest import BacktestConfig


def replay_trade_at_m1(
    direction: str,
    entry_at: pd.Timestamp,
    entry_price: float,
    atr_at_entry: float,
    cfg: BacktestConfig,
    m1_df: pd.DataFrame,
    max_bars: int = 20_000,
) -> dict:
    """Re-simulate one trade's exit using M1 bars instead of the H1 bar's
    open/high/low/close, starting from the same entry price/time. Mirrors
    backtest.run_backtest's SL/TP/trailing logic exactly, just driven by
    minute bars.

    Returns {"exit_at", "exit_price", "exit_reason", "pnl", "bars_used"}.
    """
    if direction == "buy":
        sl = entry_price - cfg.sl_atr_mult * atr_at_entry
        tp = entry_price + cfg.tp_atr_mult * atr_at_entry
    else:
        sl = entry_price + cfg.sl_atr_mult * atr_at_entry
        tp = entry_price - cfg.tp_atr_mult * atr_at_entry

    window = m1_df.loc[m1_df.index >= entry_at]
    if window.empty:
        return {"exit_at": None, "exit_price": None, "exit_reason": "no_m1_data", "pnl": None, "bars_used": 0}

    idx = window.index
    high = window["high"].to_numpy(dtype=float)
    low = window["low"].to_numpy(dtype=float)
    spread = window["spread"].to_numpy(dtype=float) if "spread" in window.columns else np.zeros(len(window))
    spread_price = spread * cfg.point_size

    extreme = entry_price
    trailing_active = False
    n = min(len(window), max_bars)

    for i in range(n):
        if direction == "buy":
            hit_sl = low[i] <= sl
            hit_tp = high[i] >= tp
        else:
            hit_sl = high[i] >= sl
            hit_tp = low[i] <= tp

        if hit_sl or hit_tp:
            # M1 bars are short enough that both-in-one-bar is rare, but
            # keep the same conservative tie-break as the H1 backtest.
            if hit_sl and hit_tp:
                exit_price, reason = sl, "Trailing SL" if trailing_active else "SL (ambiguous same-bar)"
            elif hit_sl:
                exit_price, reason = sl, "Trailing SL" if trailing_active else "SL"
            else:
                exit_price, reason = tp, "TP"

            if direction == "sell":
                exit_price = exit_price + spread_price[i]
                pnl_per_unit = entry_price - exit_price
            else:
                pnl_per_unit = exit_price - entry_price

            return {
                "exit_at": idx[i],
                "exit_price": exit_price,
                "exit_reason": reason,
                "pnl_per_unit": pnl_per_unit,
                "bars_used": i + 1,
            }

        if cfg.trailing_stop_enabled and atr_at_entry > 0:
            if direction == "buy":
                extreme = max(extreme, high[i])
                profit_atr = (extreme - entry_price) / atr_at_entry
            else:
                extreme = min(extreme, low[i])
                profit_atr = (entry_price - extreme) / atr_at_entry

            if not trailing_active and profit_atr >= cfg.trailing_activation_atr_mult:
                trailing_active = True
                tp = math.inf if direction == "buy" else -math.inf

            if trailing_active:
                if direction == "buy":
                    candidate_sl = extreme - cfg.trailing_distance_atr_mult * atr_at_entry
                    sl = max(sl, candidate_sl)
                else:
                    candidate_sl = extreme + cfg.trailing_distance_atr_mult * atr_at_entry
                    sl = min(sl, candidate_sl)

    return {"exit_at": None, "exit_price": None, "exit_reason": "ran_out_of_m1_data", "pnl_per_unit": None, "bars_used": n}


def validate_trades(
    trades: pd.DataFrame, h1_df: pd.DataFrame, m1_df: pd.DataFrame, cfg: BacktestConfig
) -> pd.DataFrame:
    """Re-check every trade in `trades` (from backtest.run_backtest on H1
    data) against the M1 path, for whichever trades fall fully inside
    m1_df's date range. Returns a comparison DataFrame."""
    m1_start, m1_end = m1_df.index.min(), m1_df.index.max()
    in_window = trades[(trades["entry_at"] >= m1_start) & (trades["exit_at"] <= m1_end)].copy()

    rows = []
    for _, t in in_window.iterrows():
        pos = h1_df.index.get_indexer([t["entry_at"]])[0]
        atr_at_entry = float(h1_df["atr"].iloc[pos - 1])

        m1_result = replay_trade_at_m1(
            t["direction"], t["entry_at"], t["entry_price"], atr_at_entry, cfg, m1_df
        )
        h1_pnl_per_unit = t["pnl"] / t["units"] if t["units"] else 0.0

        rows.append(
            {
                "entry_at": t["entry_at"],
                "direction": t["direction"],
                "h1_exit_at": t["exit_at"],
                "h1_exit_reason": t["exit_reason"],
                "h1_pnl_per_unit": h1_pnl_per_unit,
                "m1_exit_at": m1_result["exit_at"],
                "m1_exit_reason": m1_result["exit_reason"],
                "m1_pnl_per_unit": m1_result["pnl_per_unit"],
                "m1_bars_used": m1_result["bars_used"],
            }
        )

    return pd.DataFrame(rows)
