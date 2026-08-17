"""fill_validation.py is what caught the biggest bug in this project
(Round 12's trailing-distance overstatement) -- if this module itself had
a subtle bug, it could report "no discrepancy" when there actually is
one, or vice versa, and nobody would know. These tests protect the
credibility of every future M1-validation result, not just today's.
"""
import numpy as np
import pandas as pd
import pytest

from goldscalper.backtest import BacktestConfig
from goldscalper.fill_validation import replay_trade_at_m1, validate_trades


def _m1_df(start, n, prices, spread=0.0):
    idx = pd.date_range(start, periods=n, freq="1min")
    close = np.array(prices, dtype=float)
    return pd.DataFrame(
        {
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "spread": np.full(n, spread),
        },
        index=idx,
    )


def test_replay_buy_hits_take_profit():
    cfg = BacktestConfig(sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=False)
    # entry=100, atr=1 -> sl=98, tp=102. Price climbs to 102 on bar index 3.
    m1 = _m1_df("2024-01-01 00:00", 6, [100, 100.5, 101.2, 102.3, 102.0, 101.5])

    result = replay_trade_at_m1("buy", m1.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1)
    assert result["exit_reason"] == "TP"
    assert result["exit_price"] == 102.0
    assert result["pnl_per_unit"] == pytest.approx(2.0)
    assert result["bars_used"] == 4  # 0-indexed bar 3 -> 4 bars consumed


def test_replay_buy_hits_stop_loss():
    cfg = BacktestConfig(sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=False)
    m1 = _m1_df("2024-01-01 00:00", 6, [100, 99.5, 98.7, 97.9, 98.0, 98.5])
    result = replay_trade_at_m1("buy", m1.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1)
    assert result["exit_reason"] == "SL"
    assert result["exit_price"] == 98.0
    assert result["pnl_per_unit"] == pytest.approx(-2.0)


def test_replay_sell_pays_spread_on_exit_for_both_sl_and_tp():
    cfg = BacktestConfig(sl_atr_mult=2.0, tp_atr_mult=2.0, use_spread_costs=True, point_size=0.01)
    spread_pts = 20  # -> 0.20 in price

    # TP case: sell entry=100, atr=1 -> sl=102, tp=98. Price drops to 98.
    m1_tp = _m1_df("2024-01-01 00:00", 3, [100, 99.0, 98.0], spread=spread_pts)
    r_tp = replay_trade_at_m1("sell", m1_tp.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1_tp)
    assert r_tp["exit_reason"] == "TP"
    assert r_tp["exit_price"] == pytest.approx(98.0 + 0.20)  # buying back pays the spread
    assert r_tp["pnl_per_unit"] == pytest.approx(100.0 - (98.0 + 0.20))

    # SL case: price rises to 102 instead.
    m1_sl = _m1_df("2024-01-01 00:00", 3, [100, 101.0, 102.0], spread=spread_pts)
    r_sl = replay_trade_at_m1("sell", m1_sl.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1_sl)
    assert r_sl["exit_reason"] == "SL"
    assert r_sl["exit_price"] == pytest.approx(102.0 + 0.20)


def test_replay_trailing_stop_mirrors_backtest_never_exits_via_original_tp():
    cfg = BacktestConfig(
        sl_atr_mult=5.0,
        tp_atr_mult=100.0,  # unreachable -- trailing should be what closes it
        trailing_stop_enabled=True,
        trailing_activation_atr_mult=2.0,
        trailing_distance_atr_mult=3.0,
        use_spread_costs=False,
    )
    prices = [100, 100, 110, 130, 150, 140, 130, 120]
    m1 = _m1_df("2024-01-01 00:00", len(prices), prices)
    result = replay_trade_at_m1("buy", m1.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1)

    assert "Trailing SL" in result["exit_reason"]
    # peak high was 150.05 (close 150 + the 0.05 buffer in _m1_df), trailing
    # distance 3 -> stop ratchets to at most 150.05-3=147.05, pullback must
    # not loosen it below that.
    assert result["exit_price"] <= 147.05 + 1e-9


def test_replay_returns_no_m1_data_when_window_is_empty():
    cfg = BacktestConfig()
    m1 = _m1_df("2024-01-01 00:00", 3, [100, 101, 102])
    entry_at = m1.index[-1] + pd.Timedelta(minutes=10)  # entry after all available M1 data
    result = replay_trade_at_m1("buy", entry_at, 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1)
    assert result["exit_reason"] == "no_m1_data"
    assert result["exit_at"] is None
    assert result["bars_used"] == 0


def test_replay_returns_ran_out_of_m1_data_when_neither_level_is_touched():
    cfg = BacktestConfig(sl_atr_mult=10.0, tp_atr_mult=10.0)  # far away, never reached
    m1 = _m1_df("2024-01-01 00:00", 5, [100, 100.1, 99.9, 100.2, 100.0])
    result = replay_trade_at_m1("buy", m1.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1)
    assert result["exit_reason"] == "ran_out_of_m1_data"
    assert result["exit_at"] is None
    assert result["bars_used"] == 5


def test_replay_respects_max_bars_cap():
    cfg = BacktestConfig(sl_atr_mult=10.0, tp_atr_mult=10.0)
    m1 = _m1_df("2024-01-01 00:00", 50, [100.0] * 50)
    result = replay_trade_at_m1("buy", m1.index[0], 100.0, atr_at_entry=1.0, cfg=cfg, m1_df=m1, max_bars=7)
    assert result["exit_reason"] == "ran_out_of_m1_data"
    assert result["bars_used"] == 7


def test_validate_trades_uses_atr_from_the_bar_before_entry_not_the_entry_bar():
    """This is the one subtle detail that would be very easy to get wrong
    in a refactor: the ATR used for SL/TP must be the value known AT
    SIGNAL TIME (the bar before entry, matching backtest.py's pending-
    signal mechanics), not the entry bar's own ATR. Prove it by giving the
    two bars deliberately different ATR values and checking which one the
    replayed SL distance actually reflects."""
    h1_idx = pd.date_range("2024-01-01 00:00", periods=4, freq="1h")
    h1_df = pd.DataFrame(
        {"atr": [1.0, 2.0, 999.0, 1.0]},  # bar at pos=1 (entry-1) has atr=2.0; bar at pos=2 (entry) has atr=999
        index=h1_idx,
    )
    entry_at = h1_idx[2]  # pos=2 -> "atr from bar before entry" should read pos=1's atr=2.0

    cfg = BacktestConfig(sl_atr_mult=2.0, tp_atr_mult=100.0, use_spread_costs=False)
    # If atr_at_entry were (wrongly) 999.0, sl would be 100-2*999 (never
    # reached by this price path). With the correct atr=2.0, sl=96, which
    # IS reached at bar index 2 (price 95).
    m1 = _m1_df("2024-01-01 02:00", 4, [100, 98, 95, 94])

    trades = pd.DataFrame(
        {
            "entry_at": [entry_at],
            "exit_at": [m1.index[-1]],  # must fall inside the m1 window to pass validate_trades' filter
            "direction": ["buy"],
            "entry_price": [100.0],
            "units": [1.0],
            "pnl": [0.0],
            "exit_reason": ["SL"],
        }
    )

    result = validate_trades(trades, h1_df, m1, cfg)
    assert len(result) == 1
    assert result.iloc[0]["m1_exit_reason"] == "SL"


def test_validate_trades_filters_to_trades_fully_inside_the_m1_window():
    h1_idx = pd.date_range("2024-01-01 00:00", periods=5, freq="1h")
    h1_df = pd.DataFrame({"atr": [1.0, 1.0, 1.0, 1.0, 1.0]}, index=h1_idx)

    m1 = _m1_df("2024-01-01 02:00", 120, [100.0] * 120)  # covers roughly hours 02:00-04:00

    trades = pd.DataFrame(
        {
            "entry_at": [h1_idx[0], h1_idx[2]],  # first is BEFORE m1 coverage starts
            "exit_at": [h1_idx[1], h1_idx[3]],
            "direction": ["buy", "buy"],
            "entry_price": [100.0, 100.0],
            "units": [1.0, 1.0],
            "pnl": [0.0, 0.0],
            "exit_reason": ["SL", "SL"],
        }
    )
    cfg = BacktestConfig(sl_atr_mult=10.0, tp_atr_mult=10.0)
    result = validate_trades(trades, h1_df, m1, cfg)
    assert len(result) == 1
    assert result.iloc[0]["entry_at"] == h1_idx[2]


def test_validate_trades_h1_pnl_per_unit_matches_recorded_trade():
    h1_idx = pd.date_range("2024-01-01 00:00", periods=3, freq="1h")
    h1_df = pd.DataFrame({"atr": [1.0, 1.0, 1.0]}, index=h1_idx)
    m1 = _m1_df("2024-01-01 01:00", 60, [100.0] * 60)

    trades = pd.DataFrame(
        {
            "entry_at": [h1_idx[1]],
            "exit_at": [m1.index[-1]],  # must fall inside the m1 window to pass validate_trades' filter
            "direction": ["buy"],
            "entry_price": [100.0],
            "units": [4.0],
            "pnl": [40.0],  # 10 per unit * 4 units
            "exit_reason": ["TP"],
        }
    )
    cfg = BacktestConfig(sl_atr_mult=10.0, tp_atr_mult=10.0)
    result = validate_trades(trades, h1_df, m1, cfg)
    assert result.iloc[0]["h1_pnl_per_unit"] == pytest.approx(10.0)
