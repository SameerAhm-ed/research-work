import numpy as np
import pandas as pd

from goldscalper.indicators import add_base_indicators, atr, ema, rsi


def test_ema_matches_pandas_ewm_reference():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    result = ema(series, period=3)
    expected = series.ewm(span=3, adjust=False).mean()
    pd.testing.assert_series_equal(result, expected)


def test_rsi_all_gains_saturates_near_100():
    series = pd.Series(np.arange(1.0, 40.0))  # strictly increasing
    result = rsi(series, period=14)
    assert (result.dropna() > 99.0).all()


def test_rsi_all_losses_saturates_near_zero():
    series = pd.Series(np.arange(40.0, 1.0, -1.0))  # strictly decreasing
    result = rsi(series, period=14)
    assert (result.dropna() < 1.0).all()


def test_rsi_stays_within_bounds_on_noisy_series():
    rng = np.random.default_rng(0)
    series = pd.Series(100 + np.cumsum(rng.standard_normal(500)))
    result = rsi(series, period=14).dropna()
    assert (result >= 0.0).all() and (result <= 100.0).all()


def test_atr_matches_hand_computed_true_range():
    # 4 bars, period=1 so ATR == that bar's own True Range (no smoothing lag
    # to reason about) except the ewm min_periods warmup on bar 0.
    df = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [12.0, 13.0, 9.0, 11.0],
            "low": [9.0, 10.5, 7.0, 10.0],
            "close": [11.0, 11.0, 8.0, 10.5],
        }
    )
    result = atr(df, period=1)

    # bar 0: no prev_close -> TR = high-low = 3.0
    assert result.iloc[0] == 3.0
    # bar 1: TR = max(13-10.5=2.5, |13-11|=2, |10.5-11|=0.5) = 2.5
    assert result.iloc[1] == 2.5
    # bar 2: TR = max(9-7=2, |9-11|=2, |7-11|=4) = 4.0
    assert result.iloc[2] == 4.0
    # bar 3: TR = max(11-10=1, |11-8|=3, |10-8|=2) = 3.0
    assert result.iloc[3] == 3.0
    assert (result >= 0).all()


def test_add_base_indicators_produces_expected_columns_and_trend_values():
    rng = np.random.default_rng(1)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = 100 + np.cumsum(rng.standard_normal(n))
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 100.0),
        },
        index=idx,
    )

    out = add_base_indicators(df)
    for col in ["ema_9", "ema_21", "rsi", "atr", "trend_direction"]:
        assert col in out.columns
    assert set(out["trend_direction"].unique()) <= {-1, 0, 1}
    # trend_direction must agree with the EMA comparison it's derived from
    fast, slow = out["ema_9"], out["ema_21"]
    expected = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    np.testing.assert_array_equal(out["trend_direction"].to_numpy(), expected)
