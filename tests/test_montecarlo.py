import numpy as np
import pandas as pd
import pytest

from goldscalper.montecarlo import (
    compute_trade_returns,
    monte_carlo_bootstrap,
    simulate_equity_path,
    summarize,
)


def _trades(pnls, equities_after):
    return pd.DataFrame({"pnl": pnls, "equity_after": equities_after})


def test_compute_trade_returns_is_pnl_over_equity_before():
    # equity_before = equity_after - pnl, by construction.
    trades = _trades(pnls=[100.0, -50.0, 25.0], equities_after=[10100.0, 10050.0, 10075.0])
    returns = compute_trade_returns(trades)
    expected = np.array([100.0 / 10000.0, -50.0 / 10100.0, 25.0 / 10050.0])
    np.testing.assert_allclose(returns, expected)


def test_simulate_equity_path_compounds_and_computes_drawdown_by_hand():
    # 100 -> +10% -> 110 -> -20% -> 88 -> +10% -> 96.8
    returns = np.array([0.10, -0.20, 0.10])
    equity, max_dd, total_return = simulate_equity_path(returns, starting_equity=100.0)

    np.testing.assert_allclose(equity, [110.0, 88.0, 96.8])
    # running max after the peak of 110 stays 110 -> trough 88 is -20% off it
    assert max_dd == pytest.approx(-20.0)
    assert total_return == pytest.approx(-3.2)


def test_simulate_equity_path_monotonic_gains_have_zero_drawdown():
    returns = np.array([0.05, 0.03, 0.02, 0.01])
    _, max_dd, total_return = simulate_equity_path(returns, starting_equity=1000.0)
    assert max_dd == pytest.approx(0.0)
    assert total_return > 0


def test_simulate_equity_path_empty_returns_are_neutral():
    equity, max_dd, total_return = simulate_equity_path(np.array([]), starting_equity=500.0)
    assert len(equity) == 0
    assert max_dd == 0.0
    assert total_return == 0.0


def test_monte_carlo_shuffle_preserves_total_return_across_all_sims():
    """Compounding is commutative -- shuffling the ORDER of a fixed set of
    trade returns can only change the shape of the equity path (and hence
    drawdown), never the final equity. If a future change broke this
    property (e.g. accidentally resampling with replacement under the
    'shuffle' method), every sim would stop landing on the same return."""
    trades = _trades(
        pnls=[200.0, -100.0, 150.0, -50.0, 80.0],
        equities_after=[10200.0, 10100.0, 10250.0, 10200.0, 10280.0],
    )
    sims = monte_carlo_bootstrap(trades, starting_equity=10_000.0, n_sims=200, method="shuffle", seed=1)

    assert len(sims) == 200
    # every shuffle ends at the same equity, up to floating-point order-of-
    # operations noise (multiplication is commutative in exact arithmetic,
    # not bit-for-bit in float) -- so compare by tolerance, not nunique().
    assert sims["return_pct"].std() < 1e-9
    assert sims["return_pct"].iloc[0] == pytest.approx(sims["return_pct"].mean(), abs=1e-9)
    # drawdown DOES vary with order -- otherwise this whole analysis would be pointless
    assert sims["max_drawdown_pct"].nunique() > 1


def test_monte_carlo_resample_can_vary_both_return_and_drawdown():
    trades = _trades(
        pnls=[200.0, -100.0, 150.0, -50.0, 80.0],
        equities_after=[10200.0, 10100.0, 10250.0, 10200.0, 10280.0],
    )
    sims = monte_carlo_bootstrap(trades, starting_equity=10_000.0, n_sims=200, method="resample", seed=1)
    assert len(sims) == 200
    # bootstrap-with-replacement can pick a different multiset each time
    assert sims["return_pct"].nunique() > 1


def test_monte_carlo_is_deterministic_given_a_seed():
    trades = _trades(pnls=[100.0, -50.0, 75.0], equities_after=[10100.0, 10050.0, 10125.0])
    a = monte_carlo_bootstrap(trades, starting_equity=10_000.0, n_sims=50, method="shuffle", seed=7)
    b = monte_carlo_bootstrap(trades, starting_equity=10_000.0, n_sims=50, method="shuffle", seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_monte_carlo_rejects_unknown_method():
    trades = _trades(pnls=[100.0], equities_after=[10100.0])
    with pytest.raises(ValueError):
        monte_carlo_bootstrap(trades, starting_equity=10_000.0, n_sims=5, method="bogus")


def test_summarize_percentile_ranks_and_quantiles_match_manual_computation():
    sim_results = pd.DataFrame(
        {
            "max_drawdown_pct": [-5.0, -10.0, -15.0, -20.0, -25.0],
            "return_pct": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    summary = summarize(sim_results, actual_dd=-15.0, actual_return=30.0)

    assert summary["actual_max_drawdown_pct"] == -15.0
    assert summary["actual_return_pct"] == 30.0
    assert summary["sim_dd_median"] == pytest.approx(-15.0)
    assert summary["sim_return_median"] == pytest.approx(30.0)
    # 3 of 5 sims have drawdown <= -15.0 (as bad or worse) -> 60%
    assert summary["actual_dd_percentile_rank"] == pytest.approx(60.0)
    # 3 of 5 sims have return <= 30.0 -> 60%
    assert summary["actual_return_percentile_rank"] == pytest.approx(60.0)
