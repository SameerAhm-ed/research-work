"""Named, validated Edge Score + backtest configurations.

Each preset here has been through the full validation pipeline: a
randomized weight search, walk-forward cross-validation across multiple
non-overlapping out-of-sample periods, and (where noted) a joint search
over SL/TP multipliers -- on real GOLD H1 data with real spread costs.
They are starting points for further work (paper-forward testing, more
data, a second instrument), not a guarantee of future performance.
"""
from __future__ import annotations

from .backtest import BacktestConfig
from .edge_score import EdgeScoreConfig

# "Direction B": trend-following, low-drawdown. Chosen over the
# round-number-heavy "Direction A" alternative (higher return, but -20%
# to -25% worst-fold drawdowns) for being consistently profitable across
# every walk-forward fold with a much shallower worst case.
#
# On the full 2020-01 - 2026-07 real GOLD H1 dataset (38,367 bars, real
# spread costs): 144 trades, 48.6% win rate, profit factor 1.54,
# Sharpe ~0.98, max drawdown -5.3%, +49.3% total return. Walk-forward
# out-of-sample (held-out, non-overlapping folds): positive in every
# fold, worst-fold objective +0.661 (the strongest robustness margin
# found across the whole search).
TREND_LOW_DRAWDOWN_WEIGHTS = {
    "trend_alignment": 23,
    "rsi_filter": 3,
    "fvg_confluence": 5,
    "order_block_confluence": 13,
    "liquidity_sweep": 15,
    "structure_break": 5,
    "round_number": 20,
    "session_timing": 16,
}

TREND_LOW_DRAWDOWN_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_LOW_DRAWDOWN_WEIGHTS,
    approval_threshold=81.8,
)

TREND_LOW_DRAWDOWN_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=3.79,
    tp_atr_mult=6.30,
)
