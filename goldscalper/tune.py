"""Edge Score weight/threshold tuning via randomized search with
walk-forward validation, so a weight set that only works on in-sample
noise -- or got lucky on one particular train/test split -- gets caught
before anyone trusts it.

IMPORTANT: optimizing against synthetic (random-walk) data finds whatever
pattern that particular random seed happens to contain -- it is not a real
edge and the resulting weights should not be trusted for live/paper trading.
This module is meant to be pointed at real historical data; running it on
synthetic data is only useful as a smoke test of the search machinery.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .edge_score import (
    DEFAULT_WEIGHTS,
    FACTOR_KEYS,
    EdgeScoreConfig,
    compute_direction_features,
    precompute_smc,
    score_from_features,
)
from .report import compute_stats

WEIGHT_KEYS = FACTOR_KEYS


@dataclass
class TuneConfig:
    n_trials: int = 200
    n_folds: int = 4  # walk-forward folds; data is split into n_folds+1 chronological chunks
    min_trades: int = 15
    threshold_range: tuple = (55.0, 85.0)
    total_score_budget: float = 100.0
    seed: int = 42
    starting_equity: float = 10_000.0
    # risk_pct is deliberately NOT searched: doubling it roughly doubles
    # both PnL and drawdown in dollar terms, so return% and drawdown% (and
    # therefore the return/drawdown objective) stay about the same -- it's
    # a leverage dial, not something that changes the strategy's shape. Set
    # it after picking a config, based on how much drawdown you can accept.
    risk_pct: float = 0.01
    # SL/TP *do* change the strategy's shape (win rate, whipsaw exits, how
    # far winners are allowed to run) -- searched jointly with the weights
    # when tune_sl_tp=True.
    tune_sl_tp: bool = False
    sl_atr_mult_range: tuple = (1.0, 4.0)
    tp_atr_mult_range: tuple = (1.5, 6.0)
    # Trailing stop, searched jointly with everything else when
    # tune_trailing=True (forces trailing_stop_enabled=True for every
    # trial in this search -- it's a dedicated "does trailing help" run,
    # not a per-trial coin flip).
    tune_trailing: bool = False
    trailing_activation_atr_mult_range: tuple = (0.5, 3.0)
    trailing_distance_atr_mult_range: tuple = (0.5, 3.0)
    # Volatility regime filter, searched jointly when tune_vol_filter=True
    # (forces vol_filter_enabled=True for every trial in this search).
    # vol_lookback is fixed, not searched -- one more free dimension isn't
    # worth it for a parameter this insensitive.
    tune_vol_filter: bool = False
    vol_ratio_max_range: tuple = (1.1, 2.5)
    vol_reduction_mult_range: tuple = (0.2, 0.8)
    vol_lookback: int = 100
    # Multi-timeframe trend gate: fixed for the whole search (not sampled
    # per-trial -- it's a structural on/off decision, like tune_sl_tp),
    # e.g. ("trend_h4",) or ("trend_h4","trend_d1"). df passed to search()
    # must already have these columns (mtf.add_multi_timeframe_trend).
    require_htf_trend: tuple = ()
    # Optional focused-search bias: sample weight vectors clustered around
    # `anchor_weights` (a dict like DEFAULT_WEIGHTS) instead of uniformly
    # over the whole simplex. `concentration` controls how tight the
    # cluster is -- higher stays closer to the anchor, lower explores more
    # broadly around it. None (default) is the original unbiased search.
    anchor_weights: dict | None = None
    concentration: float = 3.0


def walk_forward_folds(n_bars: int, n_folds: int) -> list[tuple[slice, slice]]:
    """Chronological expanding-window walk-forward folds.

    Splits the data into n_folds+1 equal-size chronological chunks. Fold k
    trains on chunks[0..k-1] (an expanding window from the start) and tests
    on chunk k -- so every fold's test segment is strictly later in time
    than everything in its train segment, and no two folds share a test
    segment. Returns (train_slice, test_slice) integer-position pairs.
    """
    n_chunks = n_folds + 1
    edges = np.linspace(0, n_bars, n_chunks + 1, dtype=int)
    folds = []
    for k in range(1, n_chunks):
        train = slice(0, edges[k])
        test = slice(edges[k], edges[k + 1])
        if test.stop > test.start:
            folds.append((train, test))
    return folds


def sample_weights(
    rng: np.random.Generator,
    budget: float,
    anchor: dict | None = None,
    concentration: float = 3.0,
) -> dict:
    """Sample a random weight vector over the same factors as
    DEFAULT_WEIGHTS, summing to `budget`, via a Dirichlet draw.

    With no anchor, this is uniform over the whole simplex (the original
    unbiased search). With an anchor (a weights dict from a promising prior
    result), samples cluster around that composition instead -- a "focused"
    search of the neighborhood around a candidate that already looked good,
    rather than re-exploring the whole 8-factor space from scratch.
    """
    if anchor is None:
        alpha = np.ones(len(WEIGHT_KEYS))
    else:
        # +1 floor so a factor the anchor set to 0 can still occasionally
        # come up nonzero -- otherwise it'd be permanently excluded.
        alpha = np.array([anchor.get(k, 0.0) + 1.0 for k in WEIGHT_KEYS]) * concentration

    fractions = rng.dirichlet(alpha)
    raw = fractions * budget
    weights = {k: float(round(v)) for k, v in zip(WEIGHT_KEYS, raw)}
    # Rounding can drift the sum by a point or two; correct on the largest weight.
    drift = budget - sum(weights.values())
    top_key = max(weights, key=weights.get)
    weights[top_key] += drift
    return weights


def objective(stats: dict, min_trades: int) -> float:
    """Return-to-drawdown ratio, heavily penalized below a minimum trade
    count so a config that got lucky on 2 trades can't win the search."""
    if stats["n_trades"] < min_trades:
        return -1e9 + stats["n_trades"]  # still orders too-few candidates among themselves
    dd = abs(stats["max_drawdown_pct"]) + 1.0
    return stats["return_pct"] / dd


def _fold_stats(
    df: pd.DataFrame, scores: pd.DataFrame, sl: slice, bt_cfg: BacktestConfig, starting_equity: float
) -> dict:
    trades, equity = run_backtest(df.iloc[sl], scores.iloc[sl], bt_cfg)
    return compute_stats(trades, equity, starting_equity)


def search(df: pd.DataFrame, tcfg: TuneConfig | None = None, top_n: int = 5) -> pd.DataFrame:
    """Randomized search over Edge Score weights + approval threshold,
    validated by walk-forward cross-validation rather than a single
    train/test split.

    df must already have indicators (indicators.add_base_indicators). SMC
    features are computed once over the full series (so detectors have
    real history at every bar, not reset at fold boundaries), then sliced
    per fold -- every trial after that is just a weights-dot-features
    matmul plus a handful of fast backtest runs, so hundreds of trials
    stay fast even on years of real data.

    Ranks candidates by their average objective across all folds' *train*
    windows (each an expanding window from the start of the data), then
    re-evaluates the top `top_n` on every fold's held-out *test* window --
    so a "winner" has to hold up across multiple, non-overlapping, later
    time periods, not just one lucky split.

    Returns a DataFrame of the top_n candidates sorted by avg_train_obj
    descending, with per-fold-averaged train/test stats.
    """
    tcfg = tcfg or TuneConfig()
    rng = np.random.default_rng(tcfg.seed)
    n = len(df)

    smc_data = precompute_smc(df)
    # Structural cfg (proximity/lookback/session settings) is fixed for this
    # search -- only weights + threshold vary -- so features are computed once.
    structural_cfg = EdgeScoreConfig()
    feat_buy = compute_direction_features(df, smc_data, "buy", structural_cfg)
    feat_sell = compute_direction_features(df, smc_data, "sell", structural_cfg)

    folds = walk_forward_folds(n, tcfg.n_folds)
    if not folds:
        raise ValueError(f"Not enough bars ({n}) for {tcfg.n_folds} walk-forward folds")

    candidates = []
    for _ in range(tcfg.n_trials):
        weights = sample_weights(rng, tcfg.total_score_budget, tcfg.anchor_weights, tcfg.concentration)
        # Weights are always whole integers (see sample_weights), so
        # achievable scores are sums of a subset of them -- a small
        # discrete set, not a continuum. A continuous-valued threshold can
        # land a fraction of a point from one of those achievable sums,
        # making "approved" flip on essentially arbitrary precision (found
        # the hard way: threshold=70.02 vs 70.00 nearly doubled the trade
        # count because these particular weights have a subset summing to
        # exactly 70). Sampling the threshold as an integer too removes
        # that knife-edge fragility instead of just papering over it.
        threshold = float(rng.integers(int(tcfg.threshold_range[0]), int(tcfg.threshold_range[1]) + 1))
        cfg = EdgeScoreConfig(weights=weights, approval_threshold=threshold, require_htf_trend=tcfg.require_htf_trend)

        if tcfg.tune_sl_tp:
            sl_mult = float(rng.uniform(*tcfg.sl_atr_mult_range))
            tp_mult = float(rng.uniform(*tcfg.tp_atr_mult_range))
        else:
            sl_mult, tp_mult = BacktestConfig().sl_atr_mult, BacktestConfig().tp_atr_mult

        if tcfg.tune_trailing:
            trail_enabled = True
            trail_activation = float(rng.uniform(*tcfg.trailing_activation_atr_mult_range))
            trail_distance = float(rng.uniform(*tcfg.trailing_distance_atr_mult_range))
        else:
            trail_enabled = False
            trail_activation = BacktestConfig().trailing_activation_atr_mult
            trail_distance = BacktestConfig().trailing_distance_atr_mult

        if tcfg.tune_vol_filter:
            vol_enabled = True
            vol_ratio_max = float(rng.uniform(*tcfg.vol_ratio_max_range))
            vol_reduction = float(rng.uniform(*tcfg.vol_reduction_mult_range))
        else:
            vol_enabled = False
            vol_ratio_max = BacktestConfig().vol_ratio_max
            vol_reduction = BacktestConfig().vol_reduction_mult

        bt_cfg = BacktestConfig(
            starting_equity=tcfg.starting_equity,
            risk_pct=tcfg.risk_pct,
            sl_atr_mult=sl_mult,
            tp_atr_mult=tp_mult,
            trailing_stop_enabled=trail_enabled,
            trailing_activation_atr_mult=trail_activation,
            trailing_distance_atr_mult=trail_distance,
            vol_filter_enabled=vol_enabled,
            vol_ratio_max=vol_ratio_max,
            vol_reduction_mult=vol_reduction,
            vol_lookback=tcfg.vol_lookback,
        )

        scores = score_from_features(feat_buy, feat_sell, cfg, df)
        train_objs = [
            objective(_fold_stats(df, scores, train_sl, bt_cfg, tcfg.starting_equity), tcfg.min_trades)
            for train_sl, _ in folds
        ]
        avg_train_obj = float(np.mean(train_objs))
        candidates.append({"cfg": cfg, "bt_cfg": bt_cfg, "avg_train_obj": avg_train_obj})

    candidates.sort(key=lambda c: c["avg_train_obj"], reverse=True)
    top = candidates[:top_n]

    rows = []
    for c in top:
        cfg = c["cfg"]
        bt_cfg = c["bt_cfg"]
        scores = score_from_features(feat_buy, feat_sell, cfg, df)

        test_objs, test_trades, test_returns, test_dds = [], [], [], []
        for _, test_sl in folds:
            stats = _fold_stats(df, scores, test_sl, bt_cfg, tcfg.starting_equity)
            test_objs.append(objective(stats, tcfg.min_trades))
            test_trades.append(stats["n_trades"])
            test_returns.append(stats["return_pct"])
            test_dds.append(stats["max_drawdown_pct"])

        rows.append(
            {
                "threshold": round(cfg.approval_threshold, 1),
                "sl_atr_mult": round(bt_cfg.sl_atr_mult, 2),
                "tp_atr_mult": round(bt_cfg.tp_atr_mult, 2),
                "trail_active": bt_cfg.trailing_stop_enabled,
                "trail_activation": round(bt_cfg.trailing_activation_atr_mult, 2),
                "trail_distance": round(bt_cfg.trailing_distance_atr_mult, 2),
                "vol_active": bt_cfg.vol_filter_enabled,
                "vol_ratio_max": round(bt_cfg.vol_ratio_max, 2),
                "vol_reduction": round(bt_cfg.vol_reduction_mult, 2),
                **{f"w_{k}": v for k, v in cfg.weights.items()},
                "avg_train_obj": round(c["avg_train_obj"], 3),
                "avg_test_obj": round(float(np.mean(test_objs)), 3),
                "worst_fold_test_obj": round(float(np.min(test_objs)), 3),
                "total_test_trades": int(np.sum(test_trades)),
                "avg_test_return_pct": round(float(np.mean(test_returns)), 2),
                "worst_fold_test_dd_pct": round(float(np.min(test_dds)), 2),
            }
        )

    return pd.DataFrame(rows)
