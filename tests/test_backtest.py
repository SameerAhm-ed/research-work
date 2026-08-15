from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goldscalper.backtest import BacktestConfig, run_backtest
from goldscalper import presets
from goldscalper.data import load_csv
from goldscalper.edge_score import compute_edge_scores
from goldscalper.indicators import add_base_indicators
from goldscalper.mtf import add_multi_timeframe_trend

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_CSV = REPO_ROOT / "data" / "gold_h1.csv"


def _flat_df(n, prices, spread=0.0):
    """n bars, all open/high/low/close near `prices[i]` with a tiny fixed
    range, so entries/exits are deterministic and easy to reason about by
    hand. `prices` gives each bar's close; open == previous close."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.array(prices, dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.01,
            "low": np.minimum(open_, close) - 0.01,
            "close": close,
            "atr": np.full(n, 1.0),
            "spread": np.full(n, spread),
        },
        index=idx,
    )
    return df


def _scores(n, approve_at, direction="buy"):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    approved = np.zeros(n, dtype=bool)
    approved[approve_at] = True
    direction_arr = np.full(n, None, dtype=object)
    direction_arr[approve_at] = direction
    return pd.DataFrame(
        {"approved": approved, "direction": direction_arr, "score": np.zeros(n)}, index=idx
    )


def test_entry_fills_at_next_bar_open_not_signal_bar_extremes():
    """No-lookahead check: a signal approved at bar i must fill using bar
    i+1's open, never bar i's own high/low (which wouldn't be knowable
    until that bar closes -- by which point the signal itself just fired)."""
    n = 5
    prices = [100, 100, 999, 100, 100]  # bar 2 has an extreme high/low
    df = _flat_df(n, prices)
    scores = _scores(n, approve_at=1, direction="buy")  # signal at bar 1 -> fills bar 2's open

    cfg = BacktestConfig(starting_equity=10_000, risk_pct=0.01, sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=False)
    trades, _ = run_backtest(df, scores, cfg)

    assert len(trades) >= 1
    # bar 2's open == bar 1's close == 100, NOT bar 2's own extreme (999).
    assert trades.iloc[0]["entry_price"] == pytest.approx(100.0)


def test_take_profit_hit_produces_expected_pnl():
    n = 4
    prices = [100, 100, 105, 105]
    df = _flat_df(n, prices)
    scores = _scores(n, approve_at=0, direction="buy")

    cfg = BacktestConfig(
        starting_equity=10_000, risk_pct=0.01, sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=False
    )
    trades, _ = run_backtest(df, scores, cfg)

    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["exit_reason"] == "TP"
    # risk_amount = 10000*0.01 = 100, stop_distance = sl_atr_mult*atr = 2.0
    # units = 100/2.0 = 50; tp = entry + 2.0 -> pnl = 2.0 * 50 = 100
    assert trade["pnl"] == pytest.approx(100.0)


def test_stop_loss_hit_produces_expected_pnl():
    n = 4
    prices = [100, 100, 95, 95]
    df = _flat_df(n, prices)
    scores = _scores(n, approve_at=0, direction="buy")

    cfg = BacktestConfig(
        starting_equity=10_000, risk_pct=0.01, sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=False
    )
    trades, _ = run_backtest(df, scores, cfg)

    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["exit_reason"] == "SL"
    assert trade["pnl"] == pytest.approx(-100.0)  # losing the full risked amount


def test_spread_charged_once_on_buy_entry():
    n = 4
    prices = [100, 100, 105, 105]
    spread_points = 30  # 30 points * point_size
    df = _flat_df(n, prices, spread=spread_points)
    scores = _scores(n, approve_at=0, direction="buy")

    cfg = BacktestConfig(
        starting_equity=10_000, risk_pct=0.01, sl_atr_mult=2.0, tp_atr_mult=2.0,
        use_spread_costs=True, point_size=0.01,
    )
    trades, _ = run_backtest(df, scores, cfg)
    assert len(trades) == 1
    # entry should be bar1's open + spread_price (0.01*30 = 0.30), exit at
    # the plain tp level (sells/exits don't re-pay spread on a buy's TP exit).
    entry = trades.iloc[0]["entry_price"]
    assert entry == pytest.approx(100.0 + 0.30)


def test_trailing_stop_only_ever_tightens_never_loosens():
    # Price runs up (activating + advancing the trail), then pulls back --
    # the stop must not follow it back down.
    n = 8
    prices = [100, 100, 110, 130, 150, 140, 130, 120]
    df = _flat_df(n, prices)
    scores = _scores(n, approve_at=0, direction="buy")

    cfg = BacktestConfig(
        starting_equity=10_000,
        risk_pct=0.01,
        sl_atr_mult=5.0,
        tp_atr_mult=100.0,  # effectively unreachable, so trailing is what closes it
        trailing_stop_enabled=True,
        trailing_activation_atr_mult=2.0,
        trailing_distance_atr_mult=3.0,
        use_spread_costs=False,
    )
    trades, _ = run_backtest(df, scores, cfg)
    assert len(trades) == 1
    assert "Trailing SL" in trades.iloc[0]["exit_reason"]
    # peak high was 150.01 (bar index 4's close=150 + _flat_df's +0.01
    # buffer), trailing distance 3 (atr=1 * mult 3) -> stop should have
    # ratcheted up to at most 150.01-3=147.01, and the pullback to
    # 140/130/120 must not have loosened it below that.
    assert trades.iloc[0]["exit_price"] <= 147.01 + 1e-9


def test_lot_step_quantizes_units_and_clamps_to_minimum():
    """Directly exercises the Round 15 addition -- mirrors the live EA's
    MathFloor(lots/volStep)*volStep + MathMax(volMin, ...) exactly."""
    n = 4
    prices = [100, 100, 105, 105]
    df = _flat_df(n, prices)
    scores = _scores(n, approve_at=0, direction="buy")

    # risk_amount = 10*0.01 = 0.10, stop_distance = 2.0 -> raw units = 0.05,
    # which is below lot_min=1.0 -> must clamp UP to exactly 1.0.
    cfg = BacktestConfig(
        starting_equity=10.0, risk_pct=0.01, sl_atr_mult=2.0, tp_atr_mult=2.0,
        use_spread_costs=False, lot_step=1.0, lot_min=1.0,
    )
    trades, _ = run_backtest(df, scores, cfg)
    assert len(trades) == 1
    assert trades.iloc[0]["units"] == pytest.approx(1.0)

    # A larger account should floor to a whole step rather than clamp.
    cfg2 = BacktestConfig(
        starting_equity=10_000.0, risk_pct=0.0123, sl_atr_mult=2.0, tp_atr_mult=2.0,
        use_spread_costs=False, lot_step=1.0, lot_min=1.0,
    )
    trades2, _ = run_backtest(df, scores, cfg2)
    # risk_amount = 10000*0.0123=123, stop_distance=2.0 -> raw units=61.5 -> floor to 61
    assert trades2.iloc[0]["units"] == pytest.approx(61.0)


def test_lot_step_none_by_default_leaves_units_continuous():
    n = 4
    prices = [100, 100, 105, 105]
    df = _flat_df(n, prices)
    scores = _scores(n, approve_at=0, direction="buy")
    cfg = BacktestConfig(starting_equity=10.0, risk_pct=0.01, sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=False)
    trades, _ = run_backtest(df, scores, cfg)
    assert trades.iloc[0]["units"] == pytest.approx(0.05)  # not clamped/floored


@pytest.mark.skipif(not GOLD_CSV.exists(), reason="real GOLD H1 data not present in this checkout")
def test_golden_regression_trend_htf_full_dataset():
    """Locks in the currently-validated trend_htf numbers (see
    PROJECT_LOG.md / presets.py) so a future refactor of the backtester,
    edge score, or indicators can't silently drift them without this test
    failing and forcing a deliberate look. Real market data only -- skips
    where data/gold_h1.csv isn't present (it's gitignored)."""
    df = load_csv(str(GOLD_CSV))
    df = add_base_indicators(df)
    df = add_multi_timeframe_trend(df, presets.TREND_HTF_MTF_RULES)
    scores = compute_edge_scores(df, presets.TREND_HTF_EDGE_CONFIG)
    trades, equity = run_backtest(df, scores, presets.TREND_HTF_BACKTEST_CONFIG)

    assert len(trades) == 758
    final_return_pct = (equity["equity"].iloc[-1] / presets.TREND_HTF_BACKTEST_CONFIG.starting_equity - 1) * 100
    assert final_return_pct == pytest.approx(233.40, abs=0.5)

    running_max = equity["equity"].cummax()
    max_dd_pct = ((equity["equity"] - running_max) / running_max).min() * 100
    assert max_dd_pct == pytest.approx(-9.94, abs=0.1)
