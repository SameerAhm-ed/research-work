"""Backtest reporting: summary stats + equity curve / drawdown charts."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def compute_stats(trades: pd.DataFrame, equity: pd.DataFrame, starting_equity: float) -> dict:
    if trades.empty:
        return {
            "n_trades": 0,
            "win_rate": float("nan"),
            "profit_factor": float("nan"),
            "total_pnl": 0.0,
            "ending_equity": starting_equity,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": float("nan"),
            "avg_win": float("nan"),
            "avg_loss": float("nan"),
        }

    wins = trades.loc[trades["pnl"] > 0, "pnl"]
    losses = trades.loc[trades["pnl"] < 0, "pnl"]

    win_rate = len(wins) / len(trades)
    gross_win = wins.sum()
    gross_loss = -losses.sum()
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    total_pnl = trades["pnl"].sum()
    ending_equity = starting_equity + total_pnl
    return_pct = total_pnl / starting_equity * 100

    eq = equity.set_index("timestamp")["equity"]
    running_max = eq.cummax()
    drawdown_pct = (eq - running_max) / running_max * 100
    max_drawdown_pct = drawdown_pct.min()

    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    if len(daily) > 1 and daily.std() > 0:
        sharpe = daily.mean() / daily.std() * np.sqrt(252)
    else:
        sharpe = float("nan")

    return {
        "n_trades": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "ending_equity": ending_equity,
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe": sharpe,
        "avg_win": wins.mean() if len(wins) else float("nan"),
        "avg_loss": losses.mean() if len(losses) else float("nan"),
    }


def print_summary(stats: dict) -> None:
    print("=== Backtest Summary ===")
    print(f"Trades:          {stats['n_trades']}")
    print(f"Win rate:        {stats['win_rate']:.1%}" if stats["n_trades"] else "Win rate:        n/a")
    pf = stats["profit_factor"]
    print(f"Profit factor:   {pf:.2f}" if pf == pf else "Profit factor:   n/a")
    print(f"Total PnL:       ${stats['total_pnl']:.2f}")
    print(f"Ending equity:   ${stats['ending_equity']:.2f}")
    print(f"Return:          {stats['return_pct']:.2f}%")
    print(f"Max drawdown:    {stats['max_drawdown_pct']:.2f}%")
    sharpe = stats["sharpe"]
    print(f"Sharpe (approx): {sharpe:.2f}" if sharpe == sharpe else "Sharpe (approx): n/a")
    print(f"Avg win / loss:  ${stats['avg_win']:.2f} / ${stats['avg_loss']:.2f}" if stats["n_trades"] else "")


def plot_report(trades: pd.DataFrame, equity: pd.DataFrame, out_path: str) -> None:
    eq = equity.set_index("timestamp")["equity"]
    running_max = eq.cummax()
    drawdown_pct = (eq - running_max) / running_max * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, height_ratios=[2, 1])

    ax1.plot(eq.index, eq.values, color="#2563eb", linewidth=1.2)
    if not trades.empty:
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        ax1.scatter(wins["exit_at"], wins["equity_after"], color="#16a34a", s=14, zorder=3, label="win")
        ax1.scatter(losses["exit_at"], losses["equity_after"], color="#dc2626", s=14, zorder=3, label="loss")
        ax1.legend(loc="upper left")
    ax1.set_title("Equity Curve")
    ax1.set_ylabel("Equity ($)")
    ax1.grid(alpha=0.3)

    ax2.fill_between(drawdown_pct.index, drawdown_pct.values, 0, color="#dc2626", alpha=0.4)
    ax2.set_title("Drawdown")
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
