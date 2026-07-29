"""Named, validated Edge Score + backtest configurations.

Each preset here has been through the full validation pipeline: a
randomized weight search, walk-forward cross-validation across multiple
non-overlapping out-of-sample periods, and (where noted) a joint search
over SL/TP and trailing-stop parameters -- on real GOLD H1 data with real
spread costs. They are starting points for further work (paper-forward
testing, more data, a second instrument), not a guarantee of future
performance.
"""
from __future__ import annotations

from .backtest import BacktestConfig
from .edge_score import EdgeScoreConfig

# ACTIVE preset (chosen 2026-07-29): trend-following + H4 trend
# confirmation gate. Weights/SL/TP/trailing were re-searched with the H4
# gate active throughout (not bolted onto a config tuned without it --
# see PROJECT_LOG.md Round 7/8), then validated on the full continuous
# 2020-01 - 2026-07 dataset and a locked, never-searched holdout year.
#
# Deliberately chosen over TREND_LOW_DRAWDOWN_* below: higher return and
# Sharpe in exchange for somewhat deeper (but still shallow) drawdown.
# Full dataset: 1,797 trades, 77.0% win rate, profit factor 1.56, Sharpe
# 2.27, max drawdown -7.63%, +263.3% total return (~21.9% CAGR).
# Profitable in every calendar year 2020-2026 (see PROJECT_LOG.md Round 9
# for the year-by-year breakdown). Requires a "trend_h4" column on the
# input df -- see mtf.add_multi_timeframe_trend().
TREND_HTF_WEIGHTS = {
    "trend_alignment": 19,
    "rsi_filter": 3,
    "fvg_confluence": 6,
    "order_block_confluence": 11,
    "liquidity_sweep": 20,
    "structure_break": 5,
    "round_number": 19,
    "session_timing": 17,
}

TREND_HTF_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_HTF_WEIGHTS,
    approval_threshold=59.0,
    require_htf_trend=("trend_h4",),
)

TREND_HTF_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=3.09,
    tp_atr_mult=5.10,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=0.46,
    trailing_distance_atr_mult=0.53,
)

TREND_HTF_MTF_RULES = {"trend_h4": "4h"}

# Conservative alternative (no HTF gate) -- kept available, not removed.
# Lower return/Sharpe, shallower drawdown. "Direction B": trend-following,
# low-drawdown, chosen over the round-number-heavy "Direction A"
# alternative (higher return, but -20% to -25% worst-fold drawdowns) for
# being consistently profitable across every walk-forward fold with a
# much shallower worst case.
#
# Validation history:
#   v1 (weights + threshold only, fixed 2.0x/2.5x SL/TP): full-dataset
#     profit factor 1.03, Sharpe 0.17, max DD -20% to -25%.
#   v2 (+ SL/TP jointly searched, 3.79x/6.30x): full-dataset profit
#     factor 1.54, Sharpe 0.98, max DD -5.3%. Walk-forward: positive in
#     every fold, worst-fold objective +0.661.
#   v3, THIS ONE (+ trailing stop jointly searched, dev-set-only search
#     with the most recent ~15% of data held out and never touched by
#     any search): walk-forward on the dev set: worst-fold objective
#     +1.29 to +1.75 across the top candidates. Then checked ONCE against
#     the untouched holdout (2025-07 to 2026-07, 5,756 bars): 160 trades,
#     83.8% win rate, profit factor 1.94, Sharpe 3.25, max DD -3.95%,
#     +29.3% return -- genuinely unseen data, held up cleanly.
#   Full 2020-01 - 2026-07 dataset (dev+holdout combined) with this
#     config: 826 trades, 80.3% win rate, profit factor 1.66, Sharpe
#     2.18, max DD -5.71%, +197.45% total return.
TREND_LOW_DRAWDOWN_WEIGHTS = {
    "trend_alignment": 21,
    "rsi_filter": 3,
    "fvg_confluence": 5,
    "order_block_confluence": 11,
    "liquidity_sweep": 19,
    "structure_break": 7,
    "round_number": 18,
    "session_timing": 16,
}

TREND_LOW_DRAWDOWN_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_LOW_DRAWDOWN_WEIGHTS,
    approval_threshold=68.4,
)

TREND_LOW_DRAWDOWN_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=2.42,
    tp_atr_mult=5.11,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=0.65,
    trailing_distance_atr_mult=0.51,
)

# Superseded by TREND_LOW_DRAWDOWN_* above (kept for reference/comparison).
# No trailing stop; fixed SL/TP only.
TREND_LOW_DRAWDOWN_V1_WEIGHTS = {
    "trend_alignment": 23,
    "rsi_filter": 3,
    "fvg_confluence": 5,
    "order_block_confluence": 13,
    "liquidity_sweep": 15,
    "structure_break": 5,
    "round_number": 20,
    "session_timing": 16,
}

TREND_LOW_DRAWDOWN_V1_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_LOW_DRAWDOWN_V1_WEIGHTS,
    approval_threshold=81.8,
)

TREND_LOW_DRAWDOWN_V1_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=3.79,
    tp_atr_mult=6.30,
)
