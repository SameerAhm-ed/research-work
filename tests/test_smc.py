import numpy as np
import pandas as pd

from goldscalper.smc import (
    active_zones,
    find_fair_value_gaps,
    find_liquidity_sweeps,
    find_order_blocks,
    find_structure_breaks,
    find_swings,
)
from goldscalper.data import generate_synthetic
from goldscalper.indicators import add_base_indicators


def test_find_swings_detects_a_hand_crafted_peak():
    # A clean up-down-up "V-upside-down" shape: bar 2 is a swing high,
    # bar 0 is a swing low relative to its right side only (edge, skip).
    highs = [10, 12, 15, 12, 10]
    lows = [8, 9, 10, 9, 8]
    idx = pd.date_range("2024-01-01", periods=5, freq="1h")
    df = pd.DataFrame(
        {"open": highs, "high": highs, "low": lows, "close": highs}, index=idx, dtype=float
    )
    out = find_swings(df, lookback=2)
    assert out["swing_high"].iloc[2] == True  # noqa: E712
    assert not out["swing_high"].iloc[0]
    assert not out["swing_high"].iloc[4]


def test_find_fair_value_gaps_detects_hand_crafted_bullish_gap():
    # bar0 high=10, bar1 anything, bar2 low=15 > bar0 high=10 -> bullish FVG
    idx = pd.date_range("2024-01-01", periods=3, freq="1h")
    df = pd.DataFrame(
        {
            "open": [9.0, 11.0, 16.0],
            "high": [10.0, 13.0, 17.0],
            "low": [8.0, 10.5, 15.0],
            "close": [9.5, 12.0, 16.5],
        },
        index=idx,
    )
    events = find_fair_value_gaps(df)
    assert len(events) == 1
    ev = events.iloc[0]
    assert ev["direction"] == "bullish"
    assert ev["top"] == 15.0
    assert ev["bottom"] == 10.0
    assert ev["confirmed_at"] == idx[2]
    assert pd.isna(ev["mitigated_at"])  # nothing trades back into the gap


def test_find_fair_value_gaps_detects_hand_crafted_bearish_gap():
    # bar0 low=15, bar2 high=10 < bar0 low=15 -> bearish FVG
    idx = pd.date_range("2024-01-01", periods=3, freq="1h")
    df = pd.DataFrame(
        {
            "open": [16.0, 13.0, 9.0],
            "high": [17.0, 14.0, 10.0],
            "low": [15.0, 11.0, 8.0],
            "close": [16.5, 12.0, 9.0],
        },
        index=idx,
    )
    events = find_fair_value_gaps(df)
    assert len(events) == 1
    ev = events.iloc[0]
    assert ev["direction"] == "bearish"
    assert ev["top"] == 15.0
    assert ev["bottom"] == 10.0


def test_fvg_mitigation_marks_the_first_bar_that_trades_back_in():
    idx = pd.date_range("2024-01-01", periods=5, freq="1h")
    df = pd.DataFrame(
        {
            # bar2 vs bar0 -> bullish FVG (top=15, bottom=10) confirmed at bar2.
            # bar3 dips low=11 back into (10,15) -> mitigates it, without
            # itself forming a new gap against bar1 (low=10.5, high=13).
            # bar4 stays clear of forming a new gap against bar2.
            "open": [9.0, 11.0, 16.0, 16.0, 13.0],
            "high": [10.0, 13.0, 17.0, 16.0, 15.5],
            "low": [8.0, 10.5, 15.0, 11.0, 12.0],
            "close": [9.5, 12.0, 16.5, 12.0, 13.0],
        },
        index=idx,
    )
    events = find_fair_value_gaps(df)
    assert len(events) == 1
    assert events.iloc[0]["mitigated_at"] == idx[3]


def test_active_zones_respects_confirmed_and_mitigated_boundaries():
    idx = pd.date_range("2024-01-01", periods=5, freq="1h")
    events = pd.DataFrame(
        {
            "confirmed_at": [idx[1]],
            "direction": ["bullish"],
            "top": [15.0],
            "bottom": [10.0],
            "mitigated_at": [idx[3]],
        }
    )
    assert active_zones(events, idx[0]).empty  # before confirmation
    assert not active_zones(events, idx[1]).empty  # exactly at confirmation
    assert not active_zones(events, idx[2]).empty  # while live
    assert active_zones(events, idx[3]).empty  # exactly at mitigation -> no longer live
    assert active_zones(events, idx[0], direction="bearish").empty  # wrong direction


def test_order_blocks_smoke_on_synthetic_data():
    df = add_base_indicators(generate_synthetic(n_bars=1000, seed=11))
    events = find_order_blocks(df, df["atr"])
    assert set(["confirmed_at", "origin_at", "direction", "top", "bottom", "mitigated_at"]) <= set(
        events.columns
    ) or events.empty
    if not events.empty:
        assert events["direction"].isin(["bullish", "bearish"]).all()
        assert (events["top"] >= events["bottom"]).all()


def test_liquidity_sweeps_smoke_on_synthetic_data():
    df = generate_synthetic(n_bars=1000, seed=11)
    events = find_liquidity_sweeps(df)
    if not events.empty:
        assert events["direction"].isin(["bullish", "bearish"]).all()


def test_structure_breaks_smoke_on_synthetic_data():
    df = generate_synthetic(n_bars=1000, seed=11)
    events = find_structure_breaks(df)
    if not events.empty:
        assert events["direction"].isin(["bullish", "bearish"]).all()
        assert events["type"].isin(["BOS", "CHoCH"]).all()
