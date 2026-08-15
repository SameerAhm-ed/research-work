import numpy as np
import pandas as pd
import pytest

from goldscalper.portfolio import combine_equity_curves, portfolio_stats


def _equity_df(dates, equities):
    return pd.DataFrame({"timestamp": pd.to_datetime(dates), "equity": equities})


def test_combine_equity_curves_sums_starting_capital_and_pnl():
    gold = _equity_df(
        ["2024-01-01", "2024-01-02", "2024-01-03"], [5000.0, 5100.0, 5050.0]
    )
    eurusd = _equity_df(
        ["2024-01-01", "2024-01-02", "2024-01-03"], [5000.0, 4980.0, 5020.0]
    )
    combined = combine_equity_curves({"gold": (gold, 5000.0), "eurusd": (eurusd, 5000.0)})

    # total starting capital = 5000 + 5000 = 10000
    assert combined.iloc[0] == pytest.approx(10000.0)
    # day 2: 10000 + (5100-5000) + (4980-5000) = 10000 + 100 - 20 = 10080
    assert combined.loc["2024-01-02"] == pytest.approx(10080.0)
    # day 3: 10000 + (5050-5000) + (5020-5000) = 10000 + 50 + 20 = 10070
    assert combined.loc["2024-01-03"] == pytest.approx(10070.0)


def test_combine_equity_curves_forward_fills_gaps_between_legs():
    # gold trades every day; eurusd has no bar on day 2 (e.g. a holiday) --
    # its contribution on day 2 must be forward-filled from day 1, not
    # dropped to zero.
    gold = _equity_df(["2024-01-01", "2024-01-02", "2024-01-03"], [5000.0, 5100.0, 5200.0])
    eurusd = _equity_df(["2024-01-01", "2024-01-03"], [5000.0, 5030.0])
    combined = combine_equity_curves({"gold": (gold, 5000.0), "eurusd": (eurusd, 5000.0)})

    # day 2: gold pnl=+100, eurusd pnl carried forward from day 1 = 0
    assert combined.loc["2024-01-02"] == pytest.approx(10100.0)
    # day 3: gold pnl=+200, eurusd pnl=+30
    assert combined.loc["2024-01-03"] == pytest.approx(10230.0)


def test_combine_equity_curves_treats_a_not_yet_started_leg_as_zero_pnl():
    # eurusd's equity curve only begins on day 2 (e.g. added to the
    # portfolio partway through) -- day 1 should count its full starting
    # capital as idle (zero pnl), not exclude it or produce NaN.
    gold = _equity_df(["2024-01-01", "2024-01-02"], [5000.0, 5150.0])
    eurusd = _equity_df(["2024-01-02"], [5040.0])
    combined = combine_equity_curves({"gold": (gold, 5000.0), "eurusd": (eurusd, 5000.0)})

    assert not combined.isna().any()
    assert combined.loc["2024-01-01"] == pytest.approx(10000.0)  # eurusd idle, 0 pnl
    assert combined.loc["2024-01-02"] == pytest.approx(10190.0)  # +150 gold, +40 eurusd


def test_combine_equity_curves_daily_resample_keeps_the_last_intraday_value():
    # Two points on the same day -- the resampled daily series must reflect
    # the LAST one, not the first or an average.
    gold = _equity_df(
        ["2024-01-01 09:00", "2024-01-01 15:00", "2024-01-02 09:00"],
        [5000.0, 5080.0, 5200.0],
    )
    combined = combine_equity_curves({"gold": (gold, 5000.0)})
    assert combined.loc["2024-01-01"] == pytest.approx(5080.0)  # last value that day
    assert combined.loc["2024-01-02"] == pytest.approx(5200.0)


def test_portfolio_stats_return_and_drawdown_match_hand_computation():
    idx = pd.date_range("2024-01-01", periods=5, freq="1D")
    combined = pd.Series([10000.0, 10500.0, 9800.0, 10100.0, 11000.0], index=idx)
    stats = portfolio_stats(combined)

    assert stats["ending_equity"] == pytest.approx(11000.0)
    assert stats["return_pct"] == pytest.approx((11000.0 - 10000.0) / 10000.0 * 100)
    # peak before the trough was 10500 -> trough 9800 -> -6.666...%
    assert stats["max_drawdown_pct"] == pytest.approx((9800.0 - 10500.0) / 10500.0 * 100)


def test_portfolio_stats_sharpe_matches_manual_daily_return_calculation():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D")
    combined = pd.Series([10000.0, 10100.0, 10201.0, 10099.0], index=idx)
    stats = portfolio_stats(combined)

    daily_returns = combined.pct_change().dropna()
    expected_sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252)
    assert stats["sharpe"] == pytest.approx(expected_sharpe)


def test_portfolio_stats_flat_equity_gives_nan_sharpe_not_a_crash():
    idx = pd.date_range("2024-01-01", periods=5, freq="1D")
    combined = pd.Series([10000.0] * 5, index=idx)
    stats = portfolio_stats(combined)
    assert stats["return_pct"] == pytest.approx(0.0)
    assert stats["max_drawdown_pct"] == pytest.approx(0.0)
    assert np.isnan(stats["sharpe"])
