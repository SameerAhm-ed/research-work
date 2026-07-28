"""Event-driven backtester: consumes Edge Score signals bar-by-bar, opens
positions on the *next* bar's open (no lookahead), manages ATR-based SL/TP,
and sizes positions by fixed fractional risk.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestConfig:
    starting_equity: float = 10_000.0
    risk_pct: float = 0.01  # fraction of equity risked per trade
    sl_atr_mult: float = 2.0
    tp_atr_mult: float = 2.5
    max_concurrent_positions: int = 1  # only 1 supported in this version


@dataclass
class _Position:
    direction: str
    entry_price: float
    sl: float
    tp: float
    units: float
    entry_at: pd.Timestamp
    score: float


def run_backtest(df: pd.DataFrame, scores: pd.DataFrame, cfg: BacktestConfig | None = None):
    """Run the backtest. Returns (trades_df, equity_df).

    trades_df columns: entry_at, exit_at, direction, entry_price, exit_price,
                        units, pnl, exit_reason, score, equity_after
    equity_df columns: timestamp, equity
    """
    cfg = cfg or BacktestConfig()
    equity = cfg.starting_equity
    position: _Position | None = None
    pending: dict | None = None

    trades: list[dict] = []
    equity_curve: list[dict] = []

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]

        # 1. Fill any pending signal at this bar's open
        if pending is not None and position is None:
            direction = pending["direction"]
            atr_val = pending["atr"]
            entry_price = float(row["open"])

            if atr_val and atr_val > 0:
                if direction == "buy":
                    sl = entry_price - cfg.sl_atr_mult * atr_val
                    tp = entry_price + cfg.tp_atr_mult * atr_val
                else:
                    sl = entry_price + cfg.sl_atr_mult * atr_val
                    tp = entry_price - cfg.tp_atr_mult * atr_val

                stop_distance = abs(entry_price - sl)
                risk_amount = equity * cfg.risk_pct
                units = risk_amount / stop_distance if stop_distance > 0 else 0.0

                if units > 0:
                    position = _Position(
                        direction=direction,
                        entry_price=entry_price,
                        sl=sl,
                        tp=tp,
                        units=units,
                        entry_at=date,
                        score=pending["score"],
                    )
            pending = None

        # 2. Check exit on open position using this bar's range
        if position is not None:
            if position.direction == "buy":
                hit_sl = row["low"] <= position.sl
                hit_tp = row["high"] >= position.tp
            else:
                hit_sl = row["high"] >= position.sl
                hit_tp = row["low"] <= position.tp

            exit_price = None
            reason = None
            if hit_sl and hit_tp:
                # Conservative: assume the adverse side was touched first.
                exit_price, reason = position.sl, "SL (ambiguous same-bar)"
            elif hit_sl:
                exit_price, reason = position.sl, "SL"
            elif hit_tp:
                exit_price, reason = position.tp, "TP"

            if exit_price is not None:
                if position.direction == "buy":
                    pnl = (exit_price - position.entry_price) * position.units
                else:
                    pnl = (position.entry_price - exit_price) * position.units
                equity += pnl
                trades.append(
                    {
                        "entry_at": position.entry_at,
                        "exit_at": date,
                        "direction": position.direction,
                        "entry_price": position.entry_price,
                        "exit_price": exit_price,
                        "units": position.units,
                        "pnl": pnl,
                        "exit_reason": reason,
                        "score": position.score,
                        "equity_after": equity,
                    }
                )
                position = None

        equity_curve.append({"timestamp": date, "equity": equity})

        # 3. Generate a new signal from this bar's close, to fill next bar
        if position is None and pending is None:
            score_row = scores.iloc[i]
            if bool(score_row["approved"]):
                pending = {
                    "direction": score_row["direction"],
                    "atr": float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
                    "score": float(score_row["score"]),
                }

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve)
    return trades_df, equity_df
