"""Event-driven backtester: consumes Edge Score signals bar-by-bar, opens
positions on the *next* bar's open (no lookahead), manages ATR-based SL/TP,
and sizes positions by fixed fractional risk.

The loop is inherently sequential (position state depends on prior bars),
so it can't be vectorized away -- but it reads from plain numpy arrays
rather than pandas .iloc row-by-row, which is what actually made this
usable at real-data scale (df.iloc[i]/scores.iloc[i] per bar, multiplied
by hundreds of tuning trials, dominated runtime before this).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestConfig:
    starting_equity: float = 10_000.0
    risk_pct: float = 0.01  # fraction of equity risked per trade
    sl_atr_mult: float = 2.0
    tp_atr_mult: float = 2.5
    max_concurrent_positions: int = 1  # only 1 supported in this version
    point_size: float = 0.01  # price per broker "point" (e.g. GOLD: 2 digits -> 0.01)
    use_spread_costs: bool = True  # charge the historical spread if df has one
    # Trailing stop: once a trade is up `trailing_activation_atr_mult` x the
    # ATR-at-entry, the fixed take-profit is dropped and the stop instead
    # trails `trailing_distance_atr_mult` x that same ATR behind the best
    # price seen since entry -- so a trend can run past the original target
    # instead of being capped there. Off by default (identical to the
    # original fixed SL/TP behavior).
    trailing_stop_enabled: bool = False
    trailing_activation_atr_mult: float = 2.0
    trailing_distance_atr_mult: float = 2.0


def run_backtest(df: pd.DataFrame, scores: pd.DataFrame, cfg: BacktestConfig | None = None):
    """Run the backtest. Returns (trades_df, equity_df).

    trades_df columns: entry_at, exit_at, direction, entry_price, exit_price,
                        units, pnl, exit_reason, score, equity_after
    equity_df columns: timestamp, equity
    """
    cfg = cfg or BacktestConfig()
    n = len(df)
    idx = df.index

    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    atr_arr = df["atr"].to_numpy(dtype=float)

    if cfg.use_spread_costs and "spread" in df.columns:
        spread_price = df["spread"].to_numpy(dtype=float) * cfg.point_size
    else:
        spread_price = np.zeros(n, dtype=float)

    approved = scores["approved"].to_numpy(dtype=bool)
    direction_arr = scores["direction"].to_numpy()
    score_arr = scores["score"].to_numpy(dtype=float)

    equity = cfg.starting_equity
    equity_curve = np.empty(n, dtype=float)
    trades: list[dict] = []

    has_position = False
    pos_direction = ""
    pos_entry_price = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_units = 0.0
    pos_entry_at = None
    pos_score = 0.0
    pos_entry_atr = 0.0
    pos_extreme = 0.0
    pos_trailing_active = False

    has_pending = False
    pending_direction = ""
    pending_atr = 0.0
    pending_score = 0.0

    for i in range(n):
        date = idx[i]

        # 1. Fill any pending signal at this bar's open. OHLC is bid-basis
        # (standard for MT4/5 exports): a buy fills at the ask (bid+spread),
        # a sell fills at the bid directly -- so the spread cost is charged
        # once per trade, on whichever leg is the "buy" (entry for a long,
        # exit for a short).
        if has_pending and not has_position:
            direction = pending_direction
            atr_val = pending_atr
            entry_price = open_[i] + spread_price[i] if direction == "buy" else open_[i]

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
                    has_position = True
                    pos_direction = direction
                    pos_entry_price = entry_price
                    pos_sl = sl
                    pos_tp = tp
                    pos_units = units
                    pos_entry_at = date
                    pos_score = pending_score
                    pos_entry_atr = atr_val
                    pos_extreme = entry_price
                    pos_trailing_active = False
            has_pending = False

        # 2. Check exit on open position using this bar's range
        if has_position:
            if pos_direction == "buy":
                hit_sl = low[i] <= pos_sl
                hit_tp = high[i] >= pos_tp
            else:
                hit_sl = high[i] >= pos_sl
                hit_tp = low[i] <= pos_tp

            sl_label = "Trailing SL" if pos_trailing_active else "SL"
            exit_price = None
            reason = None
            if hit_sl and hit_tp:
                # Conservative: assume the adverse side was touched first.
                exit_price, reason = pos_sl, f"{sl_label} (ambiguous same-bar)"
            elif hit_sl:
                exit_price, reason = pos_sl, sl_label
            elif hit_tp:
                exit_price, reason = pos_tp, "TP"

            if exit_price is not None:
                if pos_direction == "buy":
                    pnl = (exit_price - pos_entry_price) * pos_units
                else:
                    # Closing a short buys back at the ask.
                    exit_price = exit_price + spread_price[i]
                    pnl = (pos_entry_price - exit_price) * pos_units
                equity += pnl
                trades.append(
                    {
                        "entry_at": pos_entry_at,
                        "exit_at": date,
                        "direction": pos_direction,
                        "entry_price": pos_entry_price,
                        "exit_price": exit_price,
                        "units": pos_units,
                        "pnl": pnl,
                        "exit_reason": reason,
                        "score": pos_score,
                        "equity_after": equity,
                    }
                )
                has_position = False

        # 3. If still open, update the trailing stop from this bar's range
        # -- based on the bar that just closed, so it only affects future
        # exit checks, never this bar's own (no lookahead).
        if has_position and cfg.trailing_stop_enabled and pos_entry_atr > 0:
            if pos_direction == "buy":
                pos_extreme = max(pos_extreme, high[i])
                profit_atr = (pos_extreme - pos_entry_price) / pos_entry_atr
            else:
                pos_extreme = min(pos_extreme, low[i])
                profit_atr = (pos_entry_price - pos_extreme) / pos_entry_atr

            if not pos_trailing_active and profit_atr >= cfg.trailing_activation_atr_mult:
                pos_trailing_active = True
                # Fixed target is dropped once trailing takes over.
                pos_tp = math.inf if pos_direction == "buy" else -math.inf

            if pos_trailing_active:
                if pos_direction == "buy":
                    candidate_sl = pos_extreme - cfg.trailing_distance_atr_mult * pos_entry_atr
                    pos_sl = max(pos_sl, candidate_sl)
                else:
                    candidate_sl = pos_extreme + cfg.trailing_distance_atr_mult * pos_entry_atr
                    pos_sl = min(pos_sl, candidate_sl)

        equity_curve[i] = equity

        # 4. Generate a new signal from this bar's close, to fill next bar
        if not has_position and not has_pending and approved[i]:
            has_pending = True
            pending_direction = direction_arr[i]
            atr_val = atr_arr[i]
            pending_atr = atr_val if not math.isnan(atr_val) else 0.0
            pending_score = score_arr[i]

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame({"timestamp": idx, "equity": equity_curve})
    return trades_df, equity_df
