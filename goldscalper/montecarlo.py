"""Monte Carlo robustness analysis on a realized trade sequence.

A single backtest only shows one historical path through time. If the
exact same trades had happened in a different order, drawdown and the
final return would look different -- purely from the luck of when losing
streaks happened to cluster. This resamples the realized trade returns
(not dollar PnL -- see compute_trade_returns) to build a distribution of
plausible outcomes, so a single point estimate can be checked against a
range instead of trusted blindly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_trade_returns(trades: pd.DataFrame) -> np.ndarray:
    """Per-trade return as a fraction of equity *at entry* (not a fixed
    dollar PnL) -- the portable unit for resampling, since it composes
    correctly under compounding regardless of what order trades occur in.
    """
    equity_before = trades["equity_after"] - trades["pnl"]
    return (trades["pnl"] / equity_before).to_numpy()


def simulate_equity_path(pct_returns: np.ndarray, starting_equity: float) -> tuple[np.ndarray, float, float]:
    """Compound a sequence of per-trade returns into an equity path.
    Returns (equity_path, max_drawdown_pct, total_return_pct)."""
    equity = starting_equity * np.cumprod(1 + pct_returns)
    running_max = np.maximum.accumulate(np.concatenate([[starting_equity], equity]))[1:]
    drawdown_pct = (equity - running_max) / running_max * 100
    max_dd = float(drawdown_pct.min()) if len(drawdown_pct) else 0.0
    total_return = float((equity[-1] - starting_equity) / starting_equity * 100) if len(equity) else 0.0
    return equity, max_dd, total_return


def monte_carlo_bootstrap(
    trades: pd.DataFrame,
    starting_equity: float,
    n_sims: int = 2000,
    method: str = "shuffle",
    seed: int = 42,
) -> pd.DataFrame:
    """Resample the realized per-trade returns n_sims times.

    method="shuffle": permute the existing trades' order (same multiset of
      outcomes, different sequence) -- answers "how much does drawdown
      depend on when losing streaks happened to cluster?"
    method="resample": bootstrap with replacement (can repeat/omit trades)
      -- a somewhat more aggressive test of sensitivity to the exact set
      of trades observed, not just their order.

    Returns a DataFrame with one row per simulation: max_drawdown_pct,
    return_pct.
    """
    pct_returns = compute_trade_returns(trades)
    rng = np.random.default_rng(seed)
    n = len(pct_returns)

    rows = []
    for _ in range(n_sims):
        if method == "shuffle":
            sim_returns = rng.permutation(pct_returns)
        elif method == "resample":
            sim_returns = rng.choice(pct_returns, size=n, replace=True)
        else:
            raise ValueError(f"Unknown method: {method}")
        _, max_dd, total_return = simulate_equity_path(sim_returns, starting_equity)
        rows.append({"max_drawdown_pct": max_dd, "return_pct": total_return})

    return pd.DataFrame(rows)


def summarize(sim_results: pd.DataFrame, actual_dd: float, actual_return: float) -> dict:
    """Percentile summary of the simulated distribution, plus where the
    actually-realized historical result ranks within it (0 = best possible
    ordering seen, 100 = worst)."""
    dd = sim_results["max_drawdown_pct"]
    ret = sim_results["return_pct"]

    dd_rank_pct = float((dd <= actual_dd).mean() * 100)  # % of sims with drawdown at least as bad
    ret_rank_pct = float((ret <= actual_return).mean() * 100)  # % of sims with return at least as low

    return {
        "actual_max_drawdown_pct": actual_dd,
        "actual_return_pct": actual_return,
        "sim_dd_median": float(dd.median()),
        "sim_dd_p10_best_case": float(dd.quantile(0.90)),  # shallower end (less negative)
        "sim_dd_p90_worst_case": float(dd.quantile(0.10)),  # deeper end (more negative)
        "sim_dd_p99_tail_case": float(dd.quantile(0.01)),
        "sim_return_median": float(ret.median()),
        "sim_return_p10": float(ret.quantile(0.10)),
        "sim_return_p90": float(ret.quantile(0.90)),
        "actual_dd_percentile_rank": dd_rank_pct,
        "actual_return_percentile_rank": ret_rank_pct,
    }
