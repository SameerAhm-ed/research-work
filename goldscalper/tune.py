"""Edge Score weight/threshold tuning via randomized search with a
train/test split, so a weight set that only works on in-sample noise gets
caught before anyone trusts it.

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
from .edge_score import DEFAULT_WEIGHTS, EdgeScoreConfig, compute_edge_scores, precompute_smc
from .report import compute_stats

WEIGHT_KEYS = list(DEFAULT_WEIGHTS.keys())


@dataclass
class TuneConfig:
    n_trials: int = 200
    train_frac: float = 0.7
    min_trades: int = 15
    threshold_range: tuple = (55.0, 85.0)
    total_score_budget: float = 100.0
    seed: int = 42
    starting_equity: float = 10_000.0
    risk_pct: float = 0.01


def time_series_split(df: pd.DataFrame, train_frac: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Contiguous chronological split -- no shuffling, so the test segment
    is strictly later in time than the train segment (avoids leakage)."""
    split_i = int(len(df) * train_frac)
    return df.iloc[:split_i].copy(), df.iloc[split_i:].copy()


def sample_weights(rng: np.random.Generator, budget: float) -> dict:
    """Sample a random weight vector over the same factors as
    DEFAULT_WEIGHTS, summing to `budget`, via a Dirichlet draw."""
    fractions = rng.dirichlet(np.ones(len(WEIGHT_KEYS)))
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


def _evaluate(df_segment: pd.DataFrame, smc_data: dict, cfg: EdgeScoreConfig, tcfg: TuneConfig) -> dict:
    scores = compute_edge_scores(df_segment, cfg, smc_data=smc_data)
    bt_cfg = BacktestConfig(starting_equity=tcfg.starting_equity, risk_pct=tcfg.risk_pct)
    trades, equity = run_backtest(df_segment, scores, bt_cfg)
    return compute_stats(trades, equity, tcfg.starting_equity)


def search(df: pd.DataFrame, tcfg: TuneConfig | None = None, top_n: int = 5) -> pd.DataFrame:
    """Randomized search over Edge Score weights + approval threshold.

    df must already have indicators (indicators.add_base_indicators). Scores
    each candidate on a chronological train split, ranks by the objective,
    then re-evaluates the top `top_n` candidates on the held-out test split
    so you can see whether the "winner" actually generalizes.

    Returns a DataFrame of the top_n candidates with both train and test
    stats, sorted by train objective descending.
    """
    tcfg = tcfg or TuneConfig()
    rng = np.random.default_rng(tcfg.seed)

    train_df, test_df = time_series_split(df, tcfg.train_frac)
    train_smc = precompute_smc(train_df)
    test_smc = precompute_smc(test_df)

    candidates = []
    for _ in range(tcfg.n_trials):
        weights = sample_weights(rng, tcfg.total_score_budget)
        threshold = float(rng.uniform(*tcfg.threshold_range))
        cfg = EdgeScoreConfig(weights=weights, approval_threshold=threshold)

        train_stats = _evaluate(train_df, train_smc, cfg, tcfg)
        train_obj = objective(train_stats, tcfg.min_trades)

        candidates.append({"cfg": cfg, "train_obj": train_obj, "train_stats": train_stats})

    candidates.sort(key=lambda c: c["train_obj"], reverse=True)
    top = candidates[:top_n]

    rows = []
    for c in top:
        cfg = c["cfg"]
        test_stats = _evaluate(test_df, test_smc, cfg, tcfg)
        test_obj = objective(test_stats, tcfg.min_trades)
        row = {
            "threshold": round(cfg.approval_threshold, 1),
            **{f"w_{k}": v for k, v in cfg.weights.items()},
            "train_obj": round(c["train_obj"], 3),
            "train_trades": c["train_stats"]["n_trades"],
            "train_return_pct": round(c["train_stats"]["return_pct"], 2),
            "train_dd_pct": round(c["train_stats"]["max_drawdown_pct"], 2),
            "test_obj": round(test_obj, 3),
            "test_trades": test_stats["n_trades"],
            "test_return_pct": round(test_stats["return_pct"], 2),
            "test_dd_pct": round(test_stats["max_drawdown_pct"], 2),
        }
        rows.append(row)

    return pd.DataFrame(rows)
