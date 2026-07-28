"""Edge Score engine: combines the base trend signal with SMC confluence
factors into a single 0-100 score per direction, gated by an approval
threshold -- the same idea as the "Edge Score breakdown" panel in the
GoldScalper Pro reference screenshots.

Scoring is split into two stages so weight tuning is cheap:
  1. compute_direction_features() -- walks the bars once and records which
     boolean factors fire (trend aligned, FVG confluence, etc). This does
     the expensive SMC-zone lookups and depends only on *structural*
     settings (proximity/lookback/session windows), not on weights.
  2. score_from_features() -- a vectorized weights-dot-features matmul.
     Re-scoring with a new weight vector or threshold is just this step,
     so a weight search doesn't repeat the per-bar lookups per trial.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import smc

DEFAULT_WEIGHTS = {
    "trend_alignment": 15,
    "rsi_filter": 10,
    "fvg_confluence": 15,
    "order_block_confluence": 15,
    "liquidity_sweep": 15,
    "structure_break": 15,
    "round_number": 10,
    "session_timing": 5,
}  # sums to 100

FACTOR_KEYS = list(DEFAULT_WEIGHTS.keys())


@dataclass
class EdgeScoreConfig:
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    approval_threshold: float = 70.0
    proximity_atr_mult: float = 1.0
    event_lookback_bars: int = 5
    round_number_step: float = 10.0
    round_number_tolerance_atr_mult: float = 0.5
    # London 07-16 UTC, NY 12-21 UTC -> overlap 12-16 UTC is highest-liquidity
    session_high_vol_hours: tuple = (12, 16)


def precompute_smc(df: pd.DataFrame) -> dict:
    """Run all SMC detectors once so per-bar scoring can just filter them."""
    return {
        "fvgs": smc.find_fair_value_gaps(df),
        "order_blocks": smc.find_order_blocks(df, df["atr"]),
        "sweeps": smc.find_liquidity_sweeps(df),
        "breaks": smc.find_structure_breaks(df),
    }


def _bar_factors(
    i: int, direction: str, df: pd.DataFrame, smc_data: dict, cfg: EdgeScoreConfig
) -> dict[str, tuple[bool, str]]:
    """Which confluence factors fire for one bar/direction, independent of
    weights. Returns {factor_key: (is_active, human-readable reason)}."""
    as_of = df.index[i]
    price = float(df["close"].iloc[i])
    atr_val = float(df["atr"].iloc[i]) if pd.notna(df["atr"].iloc[i]) else 0.0
    rsi_val = df["rsi"].iloc[i]
    trend_dir = df["trend_direction"].iloc[i]

    zone_dir = "bullish" if direction == "buy" else "bearish"
    trend_match = 1 if direction == "buy" else -1
    tol = atr_val * cfg.proximity_atr_mult

    factors: dict[str, tuple[bool, str]] = {}

    # 1. Trend alignment
    factors["trend_alignment"] = (trend_dir == trend_match, "trend aligned (EMA9/21)")

    # 2. RSI filter (avoid buying overbought / selling oversold)
    if pd.notna(rsi_val):
        if direction == "buy":
            factors["rsi_filter"] = (rsi_val < 70, f"RSI {rsi_val:.1f} not overbought")
        else:
            factors["rsi_filter"] = (rsi_val > 30, f"RSI {rsi_val:.1f} not oversold")
    else:
        factors["rsi_filter"] = (False, "RSI unavailable")

    # 3. Fair value gap confluence
    fvgs = smc.active_zones(smc_data["fvgs"], as_of, direction=zone_dir)
    near_fvg = False
    if not fvgs.empty:
        near = fvgs[(fvgs["bottom"] - tol <= price) & (fvgs["top"] + tol >= price)]
        near_fvg = not near.empty
    factors["fvg_confluence"] = (near_fvg, f"{zone_dir} FVG confluence")

    # 4. Order block confluence
    obs = smc.active_zones(smc_data["order_blocks"], as_of, direction=zone_dir)
    near_ob = False
    if not obs.empty:
        near = obs[(obs["bottom"] - tol <= price) & (obs["top"] + tol >= price)]
        near_ob = not near.empty
    factors["order_block_confluence"] = (near_ob, f"{zone_dir} order block confluence")

    # 5. Liquidity sweep (stop hunt) in the last N bars, matching direction
    sweeps = smc_data["sweeps"]
    has_sweep = False
    if not sweeps.empty:
        recent_idx = df.index.get_indexer([as_of])[0]
        cutoff = df.index[max(0, recent_idx - cfg.event_lookback_bars)]
        window = sweeps[
            (sweeps["at"] <= as_of) & (sweeps["at"] >= cutoff) & (sweeps["direction"] == zone_dir)
        ]
        has_sweep = not window.empty
    factors["liquidity_sweep"] = (has_sweep, f"{zone_dir} liquidity sweep nearby")

    # 6. Structure break (BOS/CHoCH) in the last N bars, matching direction
    breaks = smc_data["breaks"]
    has_break = False
    break_label = "structure break"
    if not breaks.empty:
        recent_idx = df.index.get_indexer([as_of])[0]
        cutoff = df.index[max(0, recent_idx - cfg.event_lookback_bars)]
        window = breaks[
            (breaks["at"] <= as_of) & (breaks["at"] >= cutoff) & (breaks["direction"] == zone_dir)
        ]
        has_break = not window.empty
        if has_break:
            break_label = window.iloc[-1]["type"]
    factors["structure_break"] = (has_break, f"{zone_dir} {break_label}")

    # 7. Round-number proximity (key psychological S/R level)
    nearest_round = round(price / cfg.round_number_step) * cfg.round_number_step
    near_round = abs(price - nearest_round) <= atr_val * cfg.round_number_tolerance_atr_mult
    factors["round_number"] = (near_round, f"near round number {nearest_round:g}")

    # 8. Session timing (London/NY overlap = highest-liquidity window)
    hour = as_of.hour
    lo, hi = cfg.session_high_vol_hours
    factors["session_timing"] = (lo <= hour < hi, "London+NY overlap session")

    return factors


def compute_direction_features(
    df: pd.DataFrame, smc_data: dict, direction: str, cfg: EdgeScoreConfig | None = None
) -> pd.DataFrame:
    """Boolean feature matrix (bars x FACTOR_KEYS) for one direction.

    This is the expensive step (per-bar SMC zone lookups) and is
    weight-independent -- compute it once per (data, direction) pair and
    reuse it across an arbitrary number of weight/threshold trials via
    score_from_features().
    """
    cfg = cfg or EdgeScoreConfig()
    rows = []
    for i in range(len(df)):
        factors = _bar_factors(i, direction, df, smc_data, cfg)
        rows.append({k: v[0] for k, v in factors.items()})
    return pd.DataFrame(rows, index=df.index, columns=FACTOR_KEYS)


def score_from_features(
    feat_buy: pd.DataFrame, feat_sell: pd.DataFrame, cfg: EdgeScoreConfig
) -> pd.DataFrame:
    """Vectorized scoring: weights . features, per bar, for both directions.
    This is the cheap step -- safe to call many times in a weight search."""
    w = np.array([cfg.weights[k] for k in FACTOR_KEYS], dtype=float)

    score_buy = feat_buy[FACTOR_KEYS].to_numpy(dtype=float) @ w
    score_sell = feat_sell[FACTOR_KEYS].to_numpy(dtype=float) @ w

    buy_wins = (score_buy >= cfg.approval_threshold) & (score_buy >= score_sell)
    sell_wins = (score_sell >= cfg.approval_threshold) & (score_sell > score_buy)

    direction = np.full(len(feat_buy), None, dtype=object)
    direction[buy_wins] = "buy"
    direction[sell_wins] = "sell"

    score = np.maximum(score_buy, score_sell)
    score = np.where(buy_wins, score_buy, np.where(sell_wins, score_sell, score))

    result = pd.DataFrame(
        {
            "score_buy": score_buy,
            "score_sell": score_sell,
            "direction": direction,
            "score": score,
        },
        index=feat_buy.index,
    )
    result["approved"] = result["direction"].notna()
    return result


def compute_edge_scores(
    df: pd.DataFrame, cfg: EdgeScoreConfig | None = None, smc_data: dict | None = None
) -> pd.DataFrame:
    """Compute per-bar buy/sell Edge Scores and the approved direction (if any).

    Requires df to already have indicators from indicators.add_base_indicators.
    `smc_data` (from precompute_smc) can be passed in and reused across many
    calls. For scoring the *same* structural cfg against many different
    weight vectors (a tuning search), prefer computing features once via
    compute_direction_features() and calling score_from_features() directly.
    Returns a DataFrame aligned to df's index with columns:
    score_buy, score_sell, direction ('buy'/'sell'/None), score, approved (bool)
    """
    cfg = cfg or EdgeScoreConfig()
    smc_data = smc_data if smc_data is not None else precompute_smc(df)

    feat_buy = compute_direction_features(df, smc_data, "buy", cfg)
    feat_sell = compute_direction_features(df, smc_data, "sell", cfg)
    return score_from_features(feat_buy, feat_sell, cfg)


def explain(i: int, direction: str, df: pd.DataFrame, smc_data: dict, cfg: EdgeScoreConfig | None = None):
    """Return (score, reasons) for one bar/direction -- used for trade-log
    breakdowns, mirroring the 'Edge Score Breakdown' panel in the reference UI.
    """
    cfg = cfg or EdgeScoreConfig()
    factors = _bar_factors(i, direction, df, smc_data, cfg)
    score = 0.0
    reasons = []
    for key, (active, label) in factors.items():
        points = cfg.weights[key] if active else 0
        score += points
        reasons.append((label if active else f"{label} (not met)", points))
    return score, reasons
