import numpy as np
import pandas as pd

from goldscalper.data import generate_synthetic
from goldscalper.indicators import add_base_indicators
from goldscalper.edge_score import (
    EdgeScoreConfig,
    FACTOR_KEYS,
    _bar_factors,
    compute_direction_features,
    compute_edge_scores,
    precompute_smc,
    score_from_features,
)


def test_score_from_features_matches_manual_weighted_sum():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h")
    weights = {k: (i + 1) * 5 for i, k in enumerate(FACTOR_KEYS)}
    cfg = EdgeScoreConfig(weights=weights, approval_threshold=50.0)

    # Row 0: only the highest-weighted factor fires for buy -> below threshold.
    # Row 1: all factors fire for buy -> comfortably above threshold.
    # Row 2: nothing fires either direction -> not approved.
    feat_buy = pd.DataFrame(0, index=idx, columns=FACTOR_KEYS, dtype=bool)
    feat_buy.loc[idx[0], FACTOR_KEYS[-1]] = True
    feat_buy.loc[idx[1], :] = True
    feat_sell = pd.DataFrame(False, index=idx, columns=FACTOR_KEYS, dtype=bool)

    result = score_from_features(feat_buy, feat_sell, cfg)

    expected_score_0 = weights[FACTOR_KEYS[-1]]
    expected_score_1 = sum(weights.values())
    assert result["score_buy"].iloc[0] == expected_score_0
    assert result["score_buy"].iloc[1] == expected_score_1
    assert not result["approved"].iloc[0]
    assert result["approved"].iloc[1]
    assert result["direction"].iloc[1] == "buy"
    assert not result["approved"].iloc[2]
    # pandas coerces the unset None to NaN when this object-dtype column is
    # built alongside float columns -- pd.isna() covers both, which is also
    # exactly what score_from_features' own "approved" column relies on.
    assert pd.isna(result["direction"].iloc[2])


def test_score_from_features_sell_wins_only_when_strictly_greater():
    idx = pd.date_range("2024-01-01", periods=1, freq="1h")
    weights = {k: 100 / len(FACTOR_KEYS) for k in FACTOR_KEYS}
    cfg = EdgeScoreConfig(weights=weights, approval_threshold=50.0)
    feat_buy = pd.DataFrame(True, index=idx, columns=FACTOR_KEYS)
    feat_sell = pd.DataFrame(True, index=idx, columns=FACTOR_KEYS)  # tie

    result = score_from_features(feat_buy, feat_sell, cfg)
    # Tie goes to buy (sell requires strictly greater) -- documents the
    # existing tie-break rule so a refactor can't flip it silently.
    assert result["direction"].iloc[0] == "buy"


def test_htf_gate_blocks_a_high_score_against_the_higher_timeframe_trend():
    idx = pd.date_range("2024-01-01", periods=2, freq="1h")
    weights = {k: 100 / len(FACTOR_KEYS) for k in FACTOR_KEYS}
    cfg = EdgeScoreConfig(weights=weights, approval_threshold=50.0, require_htf_trend=("trend_h4",))
    feat_buy = pd.DataFrame(True, index=idx, columns=FACTOR_KEYS)  # scores 100 every bar
    feat_sell = pd.DataFrame(False, index=idx, columns=FACTOR_KEYS)
    df = pd.DataFrame({"trend_h4": [1, -1]}, index=idx)  # bar 1 disagrees with buy

    result = score_from_features(feat_buy, feat_sell, cfg, df=df)
    assert result["approved"].iloc[0]  # trend agrees -> approved
    assert not result["approved"].iloc[1]  # trend disagrees -> gate blocks it despite score=100


def test_htf_gate_requires_df_argument():
    idx = pd.date_range("2024-01-01", periods=1, freq="1h")
    cfg = EdgeScoreConfig(require_htf_trend=("trend_h4",))
    feat = pd.DataFrame(True, index=idx, columns=FACTOR_KEYS)
    try:
        score_from_features(feat, feat, cfg, df=None)
        assert False, "expected ValueError when require_htf_trend is set but df is None"
    except ValueError:
        pass


def test_vectorized_features_match_bar_loop_reference_exactly():
    """This is the regression test for the exact thing Round 0's log
    describes as verified only by a one-off manual comparison before
    trusting the fast vectorized path over the slow bar-loop original:
    'Verified zero mismatches against the old per-bar logic before
    trusting it.' Locking that check in permanently here."""
    df = add_base_indicators(generate_synthetic(n_bars=1500, seed=42))
    cfg = EdgeScoreConfig()
    smc_data = precompute_smc(df)

    for direction in ("buy", "sell"):
        vectorized = compute_direction_features(df, smc_data, direction, cfg)

        reference = pd.DataFrame(index=df.index, columns=FACTOR_KEYS, dtype=bool)
        for i in range(len(df)):
            factors = _bar_factors(i, direction, df, smc_data, cfg)
            for key in FACTOR_KEYS:
                reference.iloc[i, reference.columns.get_loc(key)] = factors[key][0]

        for key in FACTOR_KEYS:
            mismatches = (vectorized[key].to_numpy() != reference[key].to_numpy()).sum()
            assert mismatches == 0, f"{direction}/{key}: {mismatches} bars disagree with the bar-loop reference"


def test_compute_edge_scores_end_to_end_smoke():
    df = add_base_indicators(generate_synthetic(n_bars=800, seed=5))
    result = compute_edge_scores(df)
    assert len(result) == len(df)
    assert set(result.columns) >= {"score_buy", "score_sell", "direction", "score", "approved"}
    approved = result[result["approved"]]
    if not approved.empty:
        cfg = EdgeScoreConfig()
        assert (approved["score"] >= cfg.approval_threshold).all()
        assert approved["direction"].isin(["buy", "sell"]).all()
