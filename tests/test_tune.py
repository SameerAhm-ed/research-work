import numpy as np
import pytest

from goldscalper.data import generate_synthetic
from goldscalper.indicators import add_base_indicators
from goldscalper.edge_score import DEFAULT_WEIGHTS, FACTOR_KEYS
from goldscalper.tune import TuneConfig, objective, sample_weights, search, walk_forward_folds


def test_walk_forward_folds_are_chronological_with_no_test_overlap():
    folds = walk_forward_folds(n_bars=1000, n_folds=4)
    assert len(folds) == 4

    seen_test_positions = set()
    prev_train_size = -1
    for train, test in folds:
        assert train.start == 0
        assert train.stop <= test.start  # train strictly precedes test
        assert test.start < test.stop
        positions = set(range(test.start, test.stop))
        assert not (positions & seen_test_positions)  # no fold re-tests the same bars
        seen_test_positions |= positions
        assert train.stop > prev_train_size  # expanding window: each fold trains on more
        prev_train_size = train.stop


def test_walk_forward_folds_skips_a_would_be_empty_test_segment():
    # n_bars=3 with n_folds=5 -> 6 chunks of size 0 or 1; several chunk
    # boundaries collapse to zero-width -- those must be dropped, not
    # returned as a degenerate (train, empty-test) pair.
    folds = walk_forward_folds(n_bars=3, n_folds=5)
    for _, test in folds:
        assert test.stop > test.start


def test_sample_weights_sums_exactly_to_budget_with_all_keys():
    rng = np.random.default_rng(0)
    for _ in range(20):
        weights = sample_weights(rng, budget=100.0)
        assert set(weights.keys()) == set(FACTOR_KEYS)
        assert sum(weights.values()) == pytest.approx(100.0)


def test_sample_weights_is_reproducible_given_the_same_rng_state():
    a = sample_weights(np.random.default_rng(123), budget=100.0)
    b = sample_weights(np.random.default_rng(123), budget=100.0)
    assert a == b


def test_sample_weights_anchor_biases_the_average_toward_the_anchor():
    # A lopsided anchor -- one factor dominant, everything else near-zero.
    anchor = {k: (50.0 if k == "trend_alignment" else 1.0) for k in FACTOR_KEYS}
    rng = np.random.default_rng(1)
    samples = [sample_weights(rng, budget=100.0, anchor=anchor, concentration=8.0) for _ in range(300)]
    avg_trend = np.mean([s["trend_alignment"] for s in samples])
    avg_other_per_factor = np.mean(
        [s[k] for k in FACTOR_KEYS if k != "trend_alignment" for s in samples]
    )
    # the anchored factor should end up with a much larger average share
    # than any of the others, unlike an unbiased (uniform) draw.
    assert avg_trend > avg_other_per_factor * 3


def test_sample_weights_unanchored_is_roughly_uniform_across_factors():
    rng = np.random.default_rng(2)
    samples = [sample_weights(rng, budget=100.0) for _ in range(500)]
    per_factor_avg = {k: np.mean([s[k] for s in samples]) for k in FACTOR_KEYS}
    expected = 100.0 / len(FACTOR_KEYS)
    for k, avg in per_factor_avg.items():
        assert avg == pytest.approx(expected, rel=0.3)  # loose tolerance, just checking no strong bias


def test_objective_penalizes_below_min_trades_but_still_orders_the_penalized_group():
    low = objective({"n_trades": 3, "return_pct": 500.0, "max_drawdown_pct": -1.0}, min_trades=15)
    lower = objective({"n_trades": 1, "return_pct": 500.0, "max_drawdown_pct": -1.0}, min_trades=15)
    normal = objective({"n_trades": 20, "return_pct": 10.0, "max_drawdown_pct": -5.0}, min_trades=15)

    assert low < normal  # any real candidate beats an under-traded one
    assert lower < low  # fewer trades is worse, even within the penalized group


def test_objective_matches_return_over_drawdown_plus_one():
    stats = {"n_trades": 50, "return_pct": 40.0, "max_drawdown_pct": -8.0}
    result = objective(stats, min_trades=15)
    assert result == pytest.approx(40.0 / (8.0 + 1.0))


def test_search_end_to_end_smoke_on_synthetic_data():
    """Full integration smoke test -- not a source of real edge (synthetic
    data has no real pattern, per this module's own docstring warning),
    just proving the search machinery runs end-to-end without error and
    returns sane, correctly-shaped output."""
    df = add_base_indicators(generate_synthetic(n_bars=2000, seed=9))
    tcfg = TuneConfig(n_trials=15, n_folds=2, min_trades=1, seed=3)

    result = search(df, tcfg, top_n=3)

    assert len(result) <= 3
    assert not result.empty
    for k in FACTOR_KEYS:
        assert f"w_{k}" in result.columns
    # ranked descending by avg_train_obj
    assert (result["avg_train_obj"].diff().dropna() <= 1e-9).all()
    # weight columns for one row must sum back to the search's budget
    row0_weight_sum = sum(result.iloc[0][f"w_{k}"] for k in FACTOR_KEYS)
    assert row0_weight_sum == pytest.approx(tcfg.total_score_budget)


def test_search_threshold_is_always_whole_valued():
    """Regression guard for the threshold knife-edge bug: weights are
    always integers, so the threshold must be sampled as one too (a
    continuous threshold a fraction of a point from an achievable integer
    sum can flip 'approved' on essentially arbitrary precision)."""
    df = add_base_indicators(generate_synthetic(n_bars=1500, seed=4))
    tcfg = TuneConfig(n_trials=10, n_folds=2, min_trades=1, seed=1, threshold_range=(55.0, 85.0))
    result = search(df, tcfg, top_n=5)
    for t in result["threshold"]:
        assert t == pytest.approx(round(t))
