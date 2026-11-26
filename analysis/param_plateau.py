"""Parameter plateau check: is the default 252/21/8 on a broad plateau or a narrow spike?

Pre-registered (DECISIONS.md checklist, written before the first run):
- Hypothesis: a parameter choice that sits on a plateau (neighbours roughly as good) is less likely to be a lucky
  in-sample spike. Diagnostic only; nothing here selects a new parameter.
- Grid: the walk-forward values, lookback {63,126,189,252} x top_n {4,6,8,10}, skip fixed at 21 (the default). No
  new values.
- Metric: full-sample excess Sharpe on the PIT universe, 2014-02..2026-11, costs on (fees + slippage always).
- Plateau rule: the default cell is on a plateau if every grid neighbour (adjacent lookback or adjacent top_n)
  is within 0.10 Sharpe of it. Otherwise it is a spike.
- Baselines: QQQ buy-and-hold excess Sharpe (0.78 full sample) for reference only.

Run from the repo root: python -m analysis.param_plateau
Writes report/param_plateau_pit.png.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from backtest import sharpe, simulate  # noqa: E402
from data import BENCHMARK, load_prices, load_risk_free  # noqa: E402
from signals import target_weights  # noqa: E402
from universe import load_universe  # noqa: E402
from walkforward import DEFAULT, GRID  # noqa: E402

SKIP = 21
PLATEAU_TOLERANCE = 0.10
OUT_DIR = Path(__file__).resolve().parent.parent / "report"


def plateau_table(scores: dict[tuple[int, int], float]) -> pd.DataFrame:
    """Lookback (rows) x top_n (columns) table of excess Sharpe from {(lookback, top_n): sharpe}."""
    s = pd.Series(scores)
    s.index.names = ["lookback", "top_n"]
    return s.unstack("top_n")


def default_neighbours(table: pd.DataFrame, default: tuple[int, int]) -> dict[tuple[int, int], float]:
    """Scores of the grid neighbours of the default cell (adjacent lookback or adjacent top_n)."""
    lb, n = default
    rows, cols = list(table.index), list(table.columns)
    i, j = rows.index(lb), cols.index(n)
    out = {}
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if 0 <= i + di < len(rows) and 0 <= j + dj < len(cols):
            out[(rows[i + di], cols[j + dj])] = float(table.iloc[i + di, j + dj])
    return out


def is_plateau(table: pd.DataFrame, default: tuple[int, int], tol: float = PLATEAU_TOLERANCE) -> bool:
    centre = float(table.loc[default[0], default[1]])
    return all(abs(v - centre) <= tol for v in default_neighbours(table, default).values())


def run(universe: str = "pit") -> None:
    stocks, eligible = load_universe(universe)
    bench = load_prices([BENCHMARK])[BENCHMARK].ffill()
    rf = load_risk_free()

    # Same start as analysis/common.py: first day the default weights are valid (2014+, after the 252d lookback).
    start = target_weights(stocks, lookback=DEFAULT[0], skip=SKIP, top_n=DEFAULT[2], eligible=eligible).first_valid_index()
    scores: dict[tuple[int, int], float] = {}
    for lb in GRID["lookback"]:
        for n in GRID["top_n"]:
            w = target_weights(stocks, lookback=lb, skip=SKIP, top_n=n, eligible=eligible)
            scores[(lb, n)] = sharpe(simulate(stocks, w).returns().loc[start:], rf)
    table = plateau_table(scores)
    qqq = sharpe(bench.pct_change().loc[start:].dropna(), rf)

    print(f"Universe: {universe}, skip {SKIP}, sample {start.date()}..{stocks.index[-1].date()}, costs on")
    print("Excess Sharpe (rows: lookback, cols: top_n)\n")
    print(table.round(2).to_string())
    print(f"\nDefault {DEFAULT[0]}/{DEFAULT[2]}: {table.loc[DEFAULT[0], DEFAULT[2]]:.2f}")
    print("Neighbours: " + ", ".join(f"{k[0]}/{k[1]}={v:.2f}" for k, v in default_neighbours(table, (DEFAULT[0], DEFAULT[2])).items()))
    verdict = "PLATEAU" if is_plateau(table, (DEFAULT[0], DEFAULT[2])) else "SPIKE"
    print(f"Verdict (pre-registered rule, tolerance {PLATEAU_TOLERANCE}): {verdict}")
    print(f"Grid range {table.min().min():.2f}..{table.max().max():.2f}, median {table.stack().median():.2f}; QQQ {qqq:.2f}")

    OUT_DIR.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 4))
    im = ax.imshow(table.values, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(table.columns)), [str(c) for c in table.columns])
    ax.set_yticks(range(len(table.index)), [str(r) for r in table.index])
    ax.set_xlabel("top_n")
    ax.set_ylabel("lookback (days)")
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            ax.text(j, i, f"{table.iloc[i, j]:.2f}", ha="center", va="center", color="white", fontsize=9)
    ax.set_title(f"Excess Sharpe, skip {SKIP}, {universe} (QQQ {qqq:.2f})", fontsize=10)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    out = OUT_DIR / f"param_plateau_{universe}.png"
    fig.savefig(out, dpi=150)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    run()
