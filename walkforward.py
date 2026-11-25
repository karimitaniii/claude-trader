"""Walk-forward validation of the momentum strategy with a small parameter sweep.

For each yearly test window, pick the parameter combo with the best excess Sharpe on the
preceding TRAIN_YEARS (rolling), then trade that combo's weights during the test window.
The test windows are stitched into one out-of-sample (OOS) weight path and backtested once,
so the cost of switching parameters between folds is included.

Each combo is backtested once over the full sample. Slicing its returns to a train window
is valid because signals and the portfolio path only use data up to each date.
"""
from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest import metrics, sharpe, simulate
from data import BENCHMARK, load_prices, load_risk_free
from signals import equal_weights, target_weights
from universe import load_universe

Params = tuple[int, int, int]  # (lookback, skip, top_n)

GRID: dict[str, list[int]] = {
    "lookback": [63, 126, 189, 252],
    "skip": [0, 5, 21],
    "top_n": [4, 6, 8, 10],
}
DEFAULT: Params = (252, 21, 8)
TRAIN_YEARS = 3
TEST_YEARS = 1


@dataclass(frozen=True)
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def param_grid(grid: dict[str, list[int]] = GRID) -> list[Params]:
    return list(itertools.product(grid["lookback"], grid["skip"], grid["top_n"]))


def make_folds(
    first_date: pd.Timestamp,
    last_date: pd.Timestamp,
    train_years: int = TRAIN_YEARS,
    test_years: int = TEST_YEARS,
) -> list[Fold]:
    """Rolling calendar-year folds: train on the `train_years` before Jan 1 of the test year.

    The first train window is clipped to start at `first_date` (so it may be slightly short).
    The last test window is clipped to `last_date`.
    """
    folds = []
    year = first_date.year + train_years
    while pd.Timestamp(year=year, month=1, day=1) <= last_date:
        test_start = pd.Timestamp(year=year, month=1, day=1)
        test_end = min(pd.Timestamp(year=year + test_years, month=1, day=1) - pd.Timedelta(days=1), last_date)
        train_start = max(pd.Timestamp(year=year - train_years, month=1, day=1), first_date)
        folds.append(Fold(train_start, test_start - pd.Timedelta(days=1), test_start, test_end))
        year += test_years
    return folds


def select_params(
    returns_by_params: dict[Params, pd.Series], fold: Fold, rf: pd.Series
) -> tuple[Params, float]:
    """Best excess Sharpe over the fold's train window. Ties go to the first combo in grid order."""
    best, best_score = None, -np.inf
    for p, r in returns_by_params.items():
        score = sharpe(r.loc[fold.train_start : fold.train_end], rf)
        if score > best_score:
            best, best_score = p, score
    return best, best_score


def stitch_weights(
    weights_by_params: dict[Params, pd.DataFrame], folds: list[Fold], choices: list[Params]
) -> pd.DataFrame:
    """OOS weight path: each test window uses the rows of the combo chosen for that fold."""
    template = next(iter(weights_by_params.values()))
    out = pd.DataFrame(np.nan, index=template.index, columns=template.columns)
    for fold, p in zip(folds, choices):
        window = weights_by_params[p].loc[fold.test_start : fold.test_end]
        if window.empty or window.iloc[0].isna().all():
            raise ValueError(f"test window {fold.test_start.date()} does not start on a rebalance row")
        out.loc[window.index] = window
    return out


def run(universe: str = "pit") -> None:
    stocks, eligible = load_universe(universe)
    bench = load_prices([BENCHMARK])[BENCHMARK].ffill()
    rf = load_risk_free()

    combos = param_grid()
    weights = {
        p: target_weights(stocks, lookback=p[0], skip=p[1], top_n=p[2], eligible=eligible) for p in combos
    }
    returns = {p: simulate(stocks, w).returns() for p, w in weights.items()}

    # All combos must be trading before the first train window starts.
    first_date = max(w.first_valid_index() for w in weights.values())
    folds = make_folds(first_date, stocks.index[-1])

    rows, choices = [], []
    for fold in folds:
        p, train_score = select_params(returns, fold, rf)
        choices.append(p)
        test = slice(fold.test_start, fold.test_end)
        test_scores = pd.Series({q: sharpe(r.loc[test], rf) for q, r in returns.items()})
        rows.append(
            {
                "test year": fold.test_start.year,
                "train": f"{fold.train_start.date()}..{fold.train_end.date()}",
                "chosen (lb,skip,n)": p,
                "train Sh": train_score,
                "test Sh chosen": test_scores[p],
                "test Sh default": test_scores[DEFAULT],
                "test Sh median combo": test_scores.median(),
                "chosen rank": int(test_scores.rank(ascending=False)[p]),
            }
        )

    oos_start = folds[0].test_start
    oos_weights = stitch_weights(weights, folds, choices)
    oos = {
        "Walk-forward": simulate(stocks, oos_weights).returns().loc[oos_start:],
        "Default 252/21/8": returns[DEFAULT].loc[oos_start:],
        "EW universe": simulate(
            stocks, equal_weights(stocks, lookback=DEFAULT[0], skip=DEFAULT[1], eligible=eligible)
        ).returns().loc[oos_start:],
        BENCHMARK: bench.pct_change().loc[oos_start:],
    }

    print(f"Universe: {universe}")
    print(f"Grid: {len(combos)} combos {GRID} | train {TRAIN_YEARS}y rolling, test {TEST_YEARS}y")
    print(f"Selection metric: excess Sharpe (vs 13w T-bill) on the train window; costs on\n")
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    print(f"\n(chosen rank is out of {len(combos)} combos on the test window; 1 = best)")

    print(f"\n=== Out-of-sample {oos_start.date()}..{stocks.index[-1].date()} ===")
    print(pd.DataFrame({k: metrics(r, rf) for k, r in oos.items()}).round(3).to_string())

    all_oos = pd.Series({p: sharpe(r.loc[oos_start:], rf) for p, r in returns.items()})
    wf = sharpe(oos["Walk-forward"], rf)
    print(
        f"\nOOS excess Sharpe across all {len(combos)} fixed combos: "
        f"min {all_oos.min():.3f}, median {all_oos.median():.3f}, max {all_oos.max():.3f} "
        f"(best fixed in hindsight: {tuple(int(x) for x in all_oos.idxmax())})"
    )
    print(f"Walk-forward beats {(all_oos < wf).sum()} of {len(combos)} fixed combos OOS")

    curves = pd.DataFrame({k: (1 + r).cumprod() for k, r in oos.items()})
    curves.plot(logy=True, title=f"Out-of-sample growth of $1, {universe} universe (log, after costs)")
    plt.tight_layout()
    plt.savefig(f"walkforward_oos_{universe}.png", dpi=150)
    print(f"\nSaved walkforward_oos_{universe}.png")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "pit")
