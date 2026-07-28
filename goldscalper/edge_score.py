"""Edge Score engine: combines the base trend signal with SMC confluence
factors into a single 0-100 score per direction, gated by an approval
threshold -- the same idea as the "Edge Score breakdown" panel in the
GoldScalper Pro reference screenshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field

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


def _score_direction(
    i: int, direction: str, df: pd.DataFrame, smc_data: dict, cfg: EdgeScoreConfig
) -> tuple[float, list[tuple[str, float]]]:
    w = cfg.weights
    reasons: list[tuple[str, float]] = []
    score = 0.0

    as_of = df.index[i]
    price = float(df["close"].iloc[i])
    atr_val = float(df["atr"].iloc[i]) if pd.notna(df["atr"].iloc[i]) else 0.0
    rsi_val = df["rsi"].iloc[i]
    trend_dir = df["trend_direction"].iloc[i]

    zone_dir = "bullish" if direction == "buy" else "bearish"
    trend_match = 1 if direction == "buy" else -1

    # 1. Trend alignment
    if trend_dir == trend_match:
        score += w["trend_alignment"]
        reasons.append(("trend aligned (EMA9/21)", w["trend_alignment"]))
    else:
        reasons.append(("trend not aligned", 0))

    # 2. RSI filter (avoid buying overbought / selling oversold)
    if pd.notna(rsi_val):
        if direction == "buy" and rsi_val < 70:
            score += w["rsi_filter"]
            reasons.append((f"RSI {rsi_val:.1f} not overbought", w["rsi_filter"]))
        elif direction == "sell" and rsi_val > 30:
            score += w["rsi_filter"]
            reasons.append((f"RSI {rsi_val:.1f} not oversold", w["rsi_filter"]))
        else:
            reasons.append((f"RSI {rsi_val:.1f} against direction", 0))

    # 3. Fair value gap confluence
    tol = atr_val * cfg.proximity_atr_mult
    fvgs = smc.active_zones(smc_data["fvgs"], as_of, direction=zone_dir)
    if not fvgs.empty:
        near = fvgs[(fvgs["bottom"] - tol <= price) & (fvgs["top"] + tol >= price)]
        if not near.empty:
            score += w["fvg_confluence"]
            reasons.append((f"{zone_dir} FVG confluence", w["fvg_confluence"]))

    # 4. Order block confluence
    obs = smc.active_zones(smc_data["order_blocks"], as_of, direction=zone_dir)
    if not obs.empty:
        near = obs[(obs["bottom"] - tol <= price) & (obs["top"] + tol >= price)]
        if not near.empty:
            score += w["order_block_confluence"]
            reasons.append((f"{zone_dir} order block confluence", w["order_block_confluence"]))

    # 5. Liquidity sweep (stop hunt) in the last N bars, matching direction
    sweeps = smc_data["sweeps"]
    if not sweeps.empty:
        window = sweeps[(sweeps["at"] <= as_of)]
        recent_idx = df.index.get_indexer([as_of])[0]
        cutoff = df.index[max(0, recent_idx - cfg.event_lookback_bars)]
        window = window[(window["at"] >= cutoff) & (window["direction"] == zone_dir)]
        if not window.empty:
            score += w["liquidity_sweep"]
            reasons.append((f"{zone_dir} liquidity sweep nearby", w["liquidity_sweep"]))

    # 6. Structure break (BOS/CHoCH) in the last N bars, matching direction
    breaks = smc_data["breaks"]
    if not breaks.empty:
        recent_idx = df.index.get_indexer([as_of])[0]
        cutoff = df.index[max(0, recent_idx - cfg.event_lookback_bars)]
        window = breaks[
            (breaks["at"] <= as_of) & (breaks["at"] >= cutoff) & (breaks["direction"] == zone_dir)
        ]
        if not window.empty:
            label = window.iloc[-1]["type"]
            score += w["structure_break"]
            reasons.append((f"{zone_dir} {label}", w["structure_break"]))

    # 7. Round-number proximity (key psychological S/R level)
    nearest_round = round(price / cfg.round_number_step) * cfg.round_number_step
    if abs(price - nearest_round) <= atr_val * cfg.round_number_tolerance_atr_mult:
        score += w["round_number"]
        reasons.append((f"near round number {nearest_round:g}", w["round_number"]))

    # 8. Session timing (London/NY overlap = highest-liquidity window)
    hour = as_of.hour
    lo, hi = cfg.session_high_vol_hours
    if lo <= hour < hi:
        score += w["session_timing"]
        reasons.append(("London+NY overlap session", w["session_timing"]))

    return score, reasons


def compute_edge_scores(df: pd.DataFrame, cfg: EdgeScoreConfig | None = None) -> pd.DataFrame:
    """Compute per-bar buy/sell Edge Scores and the approved direction (if any).

    Requires df to already have indicators from indicators.add_base_indicators.
    Returns a DataFrame aligned to df's index with columns:
    score_buy, score_sell, direction ('buy'/'sell'/None), score, approved (bool)
    """
    cfg = cfg or EdgeScoreConfig()
    smc_data = precompute_smc(df)

    warmup = df[["ema_9", "ema_21", "rsi", "atr"]].isna().any(axis=1)
    first_valid = warmup[~warmup].index.min() if (~warmup).any() else None

    rows = []
    for i in range(len(df)):
        if first_valid is not None and df.index[i] < first_valid:
            rows.append({"score_buy": 0.0, "score_sell": 0.0, "direction": None, "score": 0.0})
            continue
        buy_score, _ = _score_direction(i, "buy", df, smc_data, cfg)
        sell_score, _ = _score_direction(i, "sell", df, smc_data, cfg)

        if buy_score >= cfg.approval_threshold and buy_score >= sell_score:
            direction, score = "buy", buy_score
        elif sell_score >= cfg.approval_threshold and sell_score > buy_score:
            direction, score = "sell", sell_score
        else:
            direction, score = None, max(buy_score, sell_score)

        rows.append(
            {"score_buy": buy_score, "score_sell": sell_score, "direction": direction, "score": score}
        )

    result = pd.DataFrame(rows, index=df.index)
    result["approved"] = result["direction"].notna()
    return result


def explain(i: int, direction: str, df: pd.DataFrame, smc_data: dict, cfg: EdgeScoreConfig | None = None):
    """Return (score, reasons) for one bar/direction -- used for trade-log
    breakdowns, mirroring the 'Edge Score Breakdown' panel in the reference UI.
    """
    cfg = cfg or EdgeScoreConfig()
    return _score_direction(i, direction, df, smc_data, cfg)
