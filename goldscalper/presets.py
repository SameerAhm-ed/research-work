"""Named, validated Edge Score + backtest configurations.

Each preset here has been through the full validation pipeline: a
randomized weight search, walk-forward cross-validation across multiple
non-overlapping out-of-sample periods, a joint search over SL/TP and
trailing-stop parameters, and (for GOLD) a check against real M1 intrabar
data -- on real historical data with real spread costs. They are starting
points for further work (paper-forward testing, more data, a second
instrument), not a guarantee of future performance.

IMPORTANT -- trailing distance floor: any trailing_distance_atr_mult
below ~1.5x ATR is NOT trustworthy on H1 data. A single GOLD H1 bar's own
range averages ~1x ATR, so a tighter trailing distance sits inside one
bar's ordinary noise; the H1 backtest can't tell "stopped out mid-bar"
from "rode to the bar's extreme, then stopped" and silently assumes the
optimistic case. Verified via M1 replay (see PROJECT_LOG.md Round 12):
a 0.51x-ATR config overstated realized PnL by ~65% on real intrabar
data. All ACTIVE presets below use >=3x ATR trailing distances,
specifically chosen for this reason.
"""
from __future__ import annotations

from .backtest import BacktestConfig
from .edge_score import EdgeScoreConfig

# =============================================================================
# ACTIVE presets (trailing-distance bug fixed, Round 12)
# =============================================================================

# GOLD, trend-following + H4 confirmation gate. Higher return/Sharpe,
# somewhat deeper drawdown than TREND_LOW_DRAWDOWN_* below -- your choice
# of which to run depends on risk tolerance, same trade-off as before the
# fix, just with trustworthy numbers this time.
#
# Full 2020-01 - 2026-07 dataset: 758 trades, 42.0% win rate, profit
# factor 1.45, Sharpe 1.33, max drawdown -9.94%, +233.4% return. Holdout
# year (locked, never searched): 117 trades, 43.6% win rate, profit
# factor 1.74, Sharpe 2.40, max DD -7.50%, +40.3% return. Verified against
# real M1 data on the trades falling in the M1-covered window (2026-04 to
# 2026-07): largest single-trade discrepancy $4.54 (vs ~$50 before the
# fix), no systematic bias remaining. Requires a "trend_h4" column
# (mtf.add_multi_timeframe_trend).
#
# Note the lower win rate (42% vs the old, buggy config's 77%) is
# expected and correct -- that was never a real win rate, it was an
# artifact of a trailing stop too tight for H1 bars to simulate
# accurately. This is a normal trend-following profile: fewer, bigger
# wins.
TREND_HTF_WEIGHTS = {
    "trend_alignment": 22,
    "rsi_filter": 3,
    "fvg_confluence": 6,
    "order_block_confluence": 11,
    "liquidity_sweep": 17,
    "structure_break": 5,
    "round_number": 21,
    "session_timing": 15,
}

TREND_HTF_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_HTF_WEIGHTS,
    approval_threshold=60.0,
    require_htf_trend=("trend_h4",),
)

TREND_HTF_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=3.11,
    tp_atr_mult=7.54,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=1.29,
    trailing_distance_atr_mult=3.61,
)

TREND_HTF_MTF_RULES = {"trend_h4": "4h"}

# GOLD, conservative alternative (no HTF gate) -- shallower drawdown,
# lower return than TREND_HTF_* above.
#
# Full 2020-01 - 2026-07 dataset: 283 trades, 44.2% win rate, profit
# factor 1.61, Sharpe 1.21, max drawdown -8.97%, +157.4% return. Holdout
# year: 46 trades, 45.7% win rate, profit factor 1.74, Sharpe 1.37, max
# DD -5.44%, +18.1% return.
TREND_LOW_DRAWDOWN_WEIGHTS = {
    "trend_alignment": 23,
    "rsi_filter": 5,
    "fvg_confluence": 5,
    "order_block_confluence": 10,
    "liquidity_sweep": 15,
    "structure_break": 7,
    "round_number": 15,
    "session_timing": 20,
}

TREND_LOW_DRAWDOWN_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_LOW_DRAWDOWN_WEIGHTS,
    approval_threshold=76.0,
)

TREND_LOW_DRAWDOWN_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=2.94,
    tp_atr_mult=7.43,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=3.26,
    trailing_distance_atr_mult=3.91,
)

# EURUSD generalization check: an independent search (own random seed, own
# 85/15 dev/holdout split) on a completely different instrument, anchored
# on the same trend-following hypothesis. Found the same weight signature
# GOLD did (moderate-high trend_alignment + round_number + session_timing,
# low structure_break) without being told to -- the generalization check
# passed (see PROJECT_LOG.md Round 11).
#
# Full 2020-01 - 2026-07 dataset: 142 trades, 57.7% win rate, profit
# factor 1.44, Sharpe 0.73, max drawdown -4.67%, +27.3% return. Holdout
# year: 19 trades, 63.2% win rate, profit factor 2.20, Sharpe 1.37, max DD
# -2.99%, +7.6% return -- smaller numbers than gold (EURUSD is much
# lower-volatility) but positive and consistent. Requires a "trend_h4"
# column AND EURUSD-scale structural settings (5-digit quoting) -- see
# EURUSD_BACKTEST_CONFIG.point_size and EURUSD_EDGE_CONFIG.round_number_step,
# which differ from GOLD's.
EURUSD_WEIGHTS = {
    "trend_alignment": 17,
    "rsi_filter": 4,
    "fvg_confluence": 8,
    "order_block_confluence": 12,
    "liquidity_sweep": 15,
    "structure_break": 6,
    "round_number": 18,
    "session_timing": 20,
}

EURUSD_EDGE_CONFIG = EdgeScoreConfig(
    weights=EURUSD_WEIGHTS,
    approval_threshold=71.0,
    require_htf_trend=("trend_h4",),
    round_number_step=0.01,
    round_number_tolerance_atr_mult=0.5,
)

EURUSD_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=3.77,
    tp_atr_mult=3.52,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=3.15,
    trailing_distance_atr_mult=3.31,
    point_size=0.00001,
)

EURUSD_MTF_RULES = {"trend_h4": "4h"}

# Combining GOLD (TREND_HTF_*) and EURUSD (EURUSD_*) into one portfolio,
# each at its normal full risk_pct on its own half of total capital (see
# goldscalper/portfolio.py), measurably reduces drawdown versus either
# alone -- genuine diversification, not just an average of the two legs.
# Numbers need re-checking with the corrected configs above (the
# combination check in Round 11 used the pre-fix, invalidated configs);
# see PROJECT_LOG.md Round 12 for the current status.


# =============================================================================
# INVALIDATED -- kept for historical reference only, do not use.
#
# Everything below used a trailing_distance_atr_mult in the 0.46-0.53x
# ATR range, inside a single H1 bar's own noise. Confirmed via M1 replay
# (Round 12) that this overstates realized PnL by ~65% and is not a
# reliable simulation. Superseded by the ACTIVE presets above.
# =============================================================================

TREND_HTF_INVALIDATED_WEIGHTS = {
    "trend_alignment": 19,
    "rsi_filter": 3,
    "fvg_confluence": 6,
    "order_block_confluence": 11,
    "liquidity_sweep": 20,
    "structure_break": 5,
    "round_number": 19,
    "session_timing": 17,
}

TREND_HTF_INVALIDATED_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_HTF_INVALIDATED_WEIGHTS,
    approval_threshold=59.0,
    require_htf_trend=("trend_h4",),
)

TREND_HTF_INVALIDATED_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=3.09,
    tp_atr_mult=5.10,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=0.46,
    trailing_distance_atr_mult=0.53,
)

TREND_LOW_DRAWDOWN_V2_INVALIDATED_WEIGHTS = {
    "trend_alignment": 21,
    "rsi_filter": 3,
    "fvg_confluence": 5,
    "order_block_confluence": 11,
    "liquidity_sweep": 19,
    "structure_break": 7,
    "round_number": 18,
    "session_timing": 16,
}

TREND_LOW_DRAWDOWN_V2_INVALIDATED_EDGE_CONFIG = EdgeScoreConfig(
    weights=TREND_LOW_DRAWDOWN_V2_INVALIDATED_WEIGHTS,
    approval_threshold=68.4,
)

TREND_LOW_DRAWDOWN_V2_INVALIDATED_BACKTEST_CONFIG = BacktestConfig(
    sl_atr_mult=2.42,
    tp_atr_mult=5.11,
    trailing_stop_enabled=True,
    trailing_activation_atr_mult=0.65,
    trailing_distance_atr_mult=0.51,
)

# v1: no trailing stop at all (fixed SL/TP only), so unaffected by the
# trailing-distance bug -- kept as-is, not invalidated, just superseded
# by the better-performing configs above.
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
