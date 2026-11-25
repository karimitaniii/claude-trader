"""Visual report: what the strategy did, versus just holding QQQ, in $ terms.

Writes PNGs to report/ and prints a $100k summary. Same data, costs and rules as backtest.py.
Run: python report.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mt
import pandas as pd

from analysis.common import HARD_STOP, LIVE_RULES, NO_RISK, REARMED, Runs, build_runs
from backtest import INIT_CASH
from data import BENCHMARK
from risk import apply_limits
from signals import targets_from_signal_day
from universe import load_universe

OUT = Path(__file__).parent / "report"
# Validated reference palette (dataviz skill): series 1-3 plus a neutral for the benchmark.
COLORS = {NO_RISK: "#257de0", HARD_STOP: "#f47230", REARMED: "#00b894", BENCHMARK: "#666666"}
INK, MUTED, GRID = "#191919", "#666666", "#e6e6e6"
GROUP_COLORS = {"semis": "#257de0", "hardware": "#f47230", "software": "#00b894", "internet_platform": "#f2a600",
                "it_services": "#6a4ce2", "ecommerce": "#ee7fac", "streaming": "#008a17", "other": "#9c9c9c", "cash": "#e6e6e6"}


def style(ax, title: str, subtitle: str = "") -> None:
    ax.set_title(title, loc="left", fontsize=13, color=INK, fontweight="bold", pad=22 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=MUTED)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_axisbelow(True)


def dollars(x, _):
    return f"${x / 1000:,.0f}k" if x < 1e6 else f"${x / 1e6:.1f}M"


def save(fig, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=160, facecolor="white")
    plt.close(fig)


def growth(runs: Runs) -> pd.DataFrame:
    return (1 + runs.returns).cumprod() * INIT_CASH


def plot_growth(g: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax, log in zip(axes, (False, True)):
        for name in g.columns:
            ax.plot(g.index, g[name], color=COLORS[name], lw=2 if name != BENCHMARK else 2.2, label=name,
                    ls="--" if name == BENCHMARK else "-")
            ax.annotate(f" {dollars(g[name].iloc[-1], None)}", (g.index[-1], g[name].iloc[-1]), color=INK, fontsize=9, va="center")
        if log:
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(mt.FuncFormatter(dollars))
            ax.yaxis.set_minor_formatter(mt.NullFormatter())
        else:
            ax.yaxis.set_major_formatter(mt.FuncFormatter(dollars))
        style(ax, "Growth of $100,000" + (" (log scale)" if log else ""), "after fees and slippage" if not log else "same, log axis: equal slopes = equal % growth")
        ax.set_xlim(g.index[0], g.index[-1] + pd.Timedelta(days=330))
    axes[0].legend(frameon=False, fontsize=9, loc="upper left")
    save(fig, "1_growth.png")


def plot_drawdown(g: pd.DataFrame) -> None:
    dd = g / g.cummax() - 1
    fig, ax = plt.subplots(figsize=(14, 4.5))
    for name in g.columns:
        ax.plot(dd.index, dd[name], color=COLORS[name], lw=1.6, ls="--" if name == BENCHMARK else "-", label=f"{name} (worst {dd[name].min():.0%})")
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    style(ax, "Drawdown: how far below its previous peak each strategy sat", "the pain you would have had to sit through")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    save(fig, "2_drawdown.png")


def plot_annual(runs: Runs) -> None:
    ann = (1 + runs.returns).groupby(runs.returns.index.year).prod() - 1
    cols = [NO_RISK, REARMED, BENCHMARK]
    fig, ax = plt.subplots(figsize=(14, 4.8))
    w = 0.27
    for i, c in enumerate(cols):
        ax.bar(ann.index + (i - 1) * w, ann[c], width=w - 0.03, color=COLORS[c], label=c)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    ax.set_xticks(ann.index)
    style(ax, "Calendar-year returns", "the strategy swings harder than QQQ in both directions; 2026 is year-to-date")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    save(fig, "3_annual.png")


def start_date_table(g: pd.DataFrame) -> pd.DataFrame:
    """For each month-end start, the value of $100k held to the end of the data."""
    starts = g.resample("ME").last().index[:-12]
    rows = {d: g.iloc[-1] / g.loc[:d].iloc[-1] * INIT_CASH for d in starts}
    return pd.DataFrame(rows).T


def plot_start_dates(g: pd.DataFrame) -> pd.DataFrame:
    t = start_date_table(g)
    fig, ax = plt.subplots(figsize=(14, 5))
    for name in (NO_RISK, REARMED, BENCHMARK):
        ax.plot(t.index, t[name], color=COLORS[name], lw=2, ls="--" if name == BENCHMARK else "-", label=name)
    ax.yaxis.set_major_formatter(mt.FuncFormatter(dollars))
    style(ax, "What $100,000 is worth today, by the month you started",
          "each point = invest $100k at the end of that month and hold to the last data date; starts in the last year are omitted")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    save(fig, "4_start_dates.png")
    return t


def plot_holdings(runs: Runs) -> None:
    pf = runs.portfolios[REARMED]
    value = pf.value()
    sh = pf.asset_value(group_by=False).div(value, axis=0).loc[runs.start:]
    by_group = sh.T.groupby(runs.groups.reindex(sh.columns).fillna("other")).sum().T
    by_group["cash"] = (1 - by_group.sum(axis=1)).clip(lower=0)
    cols = [c for c in GROUP_COLORS if c in by_group.columns and by_group[c].max() > 0.001]
    fig, ax = plt.subplots(figsize=(14, 4.8))
    ax.stackplot(by_group.index, [by_group[c] for c in cols], colors=[GROUP_COLORS[c] for c in cols], labels=cols, edgecolor="white", linewidth=0.3)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    style(ax, "What the strategy holds, by group (with risk layer, re-armed)", "share of the portfolio; light gray = cash (sell-off rule and caps push money here)")
    ax.legend(frameon=False, fontsize=9, ncol=len(cols), loc="upper center", bbox_to_anchor=(0.5, -0.08))
    save(fig, "5_holdings.png")


def plot_current(runs: Runs) -> pd.DataFrame:
    close, eligible = load_universe("pit")
    day = close.index[-1]
    raw = targets_from_signal_day(close, day, eligible=eligible)
    trend_ok = bool(runs.bench.iloc[-1] >= runs.bench.rolling(200).mean().iloc[-1])
    allowed, fired = apply_limits(raw, runs.groups, LIVE_RULES, trend_ok)
    df = pd.DataFrame({"raw": raw, "allowed": allowed})
    df = df[df.raw > 0].sort_values("raw", ascending=False)
    df["group"] = runs.groups.reindex(df.index)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    x = range(len(df))
    ax.bar(x, df.raw, color="#cce3fd", label="strategy target")
    ax.bar(x, df.allowed, color="#257de0", width=0.55, label="after risk layer")
    ax.set_xticks(list(x), [f"{t}\n{g}" for t, g in zip(df.index, df.group)], fontsize=8)
    ax.yaxis.set_major_formatter(mt.PercentFormatter(1.0, decimals=0))
    style(ax, f"Today's momentum picks (signal from close {day.date()})",
          f"QQQ {'above' if trend_ok else 'BELOW'} its 200-day average -> {'no' if trend_ok else '50% gross'} sell-off cut")
    ax.set_ylim(0, 0.16)
    ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    save(fig, "6_current_picks.png")
    return df


def main() -> None:
    runs = build_runs()
    g = growth(runs)
    plot_growth(g)
    plot_drawdown(g)
    plot_annual(runs)
    t = plot_start_dates(g)
    plot_holdings(runs)
    picks = plot_current(runs)

    print(f"\n$100,000 from {runs.start.date()} to {g.index[-1].date()} (costs on)")
    yrs = (g.index[-1] - runs.start).days / 365.25
    for c in g.columns:
        print(f"  {c:<28} ${g[c].iloc[-1]:>10,.0f}   CAGR {(g[c].iloc[-1] / INIT_CASH) ** (1 / yrs) - 1:.1%}")
    print("\nStart-date sensitivity (value today of $100k, by start year; first month of each year):")
    first = t.groupby(t.index.year).head(1)
    print(first.round(0).astype(int).rename(index=lambda d: d.year).to_string())
    for name in (NO_RISK, REARMED):
        print(f"{name}: beats QQQ from {(t[name] > t[BENCHMARK]).mean():.0%} of monthly start dates")
    print("\nCurrent picks:\n", picks.round(3).to_string())
    print(f"\nPNGs in {OUT}/")


if __name__ == "__main__":
    main()
