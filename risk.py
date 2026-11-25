"""Risk layer: deterministic limits applied after the strategy, able to override it.

The strategy proposes target weights; this module decides what is actually allowed:

1. Kill switch (daily): if equity falls `kill_drawdown` below its all-time high-water mark at a
   close, liquidate at the next close. Default is a hard stop: stay in cash until a human calls
   `KillSwitch.reset()` after reviewing what went wrong. With `kill_manual_reset=False` it instead
   re-arms automatically after `kill_cooldown_days` once the benchmark is above trend, resetting
   the high-water mark (caps each episode, not total drawdown).
2. Position cap: no single name above `max_position` (excess goes to cash, not redistributed).
3. Group caps: semis + semi equipment at most 50%, hardware (incl. storage) at most 35% of equity
   (scaled pro rata).
4. Sell-off rule: if the benchmark closed below its `trend_window`-day average on the signal
   day, gross exposure is cut to `selloff_gross`.
5. Gross cap: total long exposure at most `max_gross` (no leverage).

Rules 2-5 apply at rebalances only (between rebalances positions drift). The same
`apply_limits` and `KillSwitch` are meant to be reused unchanged by live paper trading.

Timing follows the project rule: anything decided from day t's close trades at day t+1's close.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

EPS = 1e-12


@dataclass(frozen=True)
class RiskLimits:
    max_position: float = 0.15
    max_gross: float = 1.0
    # hardware 35% (incl. storage): a priori, between the in-sample best 25% and a non-binding 50%
    group_caps: tuple[tuple[str, float], ...] = (("semis", 0.50), ("hardware", 0.35))
    trend_window: int = 200
    selloff_gross: float = 0.50
    kill_drawdown: float = 0.25
    kill_cooldown_days: int = 21
    kill_manual_reset: bool = True  # hard stop: no automatic re-entry after the kill switch fires

    def __post_init__(self) -> None:
        for name in ("max_position", "max_gross", "selloff_gross", "kill_drawdown"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.kill_cooldown_days < 0 or self.trend_window < 1:
            raise ValueError("kill_cooldown_days must be >= 0 and trend_window >= 1")


NO_LIMITS = RiskLimits(
    max_position=1.0, max_gross=1.0, group_caps=(), selloff_gross=1.0, kill_drawdown=1.0, kill_cooldown_days=0
)


def trend_ok(bench: pd.Series, window: int) -> pd.Series:
    """True where the benchmark close is at or above its trailing `window`-day mean (uses data to t only).

    Before `window` days of history the rule has no information and returns True (no restriction).
    """
    sma = bench.rolling(window, min_periods=window).mean()
    return (bench >= sma) | sma.isna()


def apply_limits(
    targets: pd.Series, groups: pd.Series, limits: RiskLimits, trend_is_ok: bool = True
) -> tuple[pd.Series, list[str]]:
    """Apply position, group, sell-off and gross limits to one row of target weights.

    Long-only: negative or NaN targets are treated as 0. Anything cut goes to cash.
    Returns (allowed weights, list of fired rules for logging).
    """
    w = targets.fillna(0.0).clip(lower=0.0).astype(float)
    fired: list[str] = []

    over = w.index[w > limits.max_position + EPS]
    if len(over):
        w[over] = limits.max_position
        fired.append(f"position_cap {limits.max_position:.0%}: {', '.join(over)}")

    g = groups.reindex(w.index).fillna("other")
    for group, cap in limits.group_caps:
        in_group = g == group
        total = w[in_group].sum()
        if total > cap + EPS:
            w[in_group] *= cap / total
            fired.append(f"group_cap {group} {total:.0%} -> {cap:.0%}")

    if not trend_is_ok and w.sum() > limits.selloff_gross + EPS:
        fired.append(f"selloff benchmark below trend: gross {w.sum():.0%} -> {limits.selloff_gross:.0%}")
        w *= limits.selloff_gross / w.sum()

    if w.sum() > limits.max_gross + EPS:
        fired.append(f"gross_cap {w.sum():.0%} -> {limits.max_gross:.0%}")
        w *= limits.max_gross / w.sum()

    return w, fired


@dataclass
class KillSwitch:
    """Drawdown kill switch with a cooldown and a trend condition for re-arming."""

    limits: RiskLimits
    peak: float = np.nan
    killed: bool = False
    days_killed: int = 0

    def update(self, equity: float, trend_is_ok: bool) -> str | None:
        """Feed one daily closing equity value. Returns "kill", "rearm" or None."""
        if self.killed:
            self.days_killed += 1
            if self.limits.kill_manual_reset:
                return None
            if self.days_killed >= self.limits.kill_cooldown_days and trend_is_ok:
                self.killed, self.days_killed, self.peak = False, 0, equity
                return "rearm"
            return None
        self.peak = equity if np.isnan(self.peak) else max(self.peak, equity)
        if self.limits.kill_drawdown < 1 and equity <= self.peak * (1 - self.limits.kill_drawdown):
            self.killed, self.days_killed = True, 0
            return "kill"
        return None

    def reset(self, equity: float) -> None:
        """Manual re-arm after a human review: trading resumes and the high-water mark restarts at `equity`."""
        self.killed, self.days_killed, self.peak = False, 0, equity


@dataclass
class RiskRun:
    orders: pd.DataFrame          # target weights actually sent (NaN = no order); feed to backtest.simulate
    equity: pd.Series             # equity from this module's own simulation (used for kill-switch decisions)
    events: pd.DataFrame = field(default_factory=pd.DataFrame)  # date, rule, detail


def run_with_risk(
    close: pd.DataFrame,
    targets: pd.DataFrame,
    groups: pd.Series,
    bench: pd.Series,
    limits: RiskLimits,
    cost_rate: float,
    init_cash: float = 100_000.0,
) -> RiskRun:
    """Walk forward day by day, applying the risk layer to the strategy's target rows.

    `targets` follows the strategy convention: a non-NaN row on day i is an order to trade at
    day i's close, computed from day i-1's close. The risk layer therefore uses day i-1's trend
    state for those rows. Costs (fees + slippage) are charged on traded notional at `cost_rate`.
    """
    px = close.to_numpy(dtype=float)
    tgt = targets.reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
    trend = trend_ok(bench.reindex(close.index).ffill(), limits.trend_window).to_numpy()
    shares = np.zeros(close.shape[1])
    cash = init_cash
    ks = KillSwitch(limits)
    liquidate_next = False
    orders = np.full(close.shape, np.nan)
    equity = np.empty(len(close))
    events: list[tuple[pd.Timestamp, str, str]] = []

    for i, day in enumerate(close.index):
        prices = np.nan_to_num(px[i])
        value = cash + float(shares @ prices)
        new_w = None
        if liquidate_next:
            new_w, liquidate_next = np.zeros(close.shape[1]), False
            events.append((day, "liquidate", "kill switch fired at previous close"))
        elif not ks.killed and not np.isnan(tgt[i]).all():
            prev_trend = bool(trend[i - 1]) if i > 0 else True
            allowed, fired = apply_limits(
                pd.Series(tgt[i], index=close.columns), groups, limits, prev_trend
            )
            new_w = allowed.to_numpy()
            events += [(day, f.split(" ")[0], f) for f in fired]
        if new_w is not None:
            new_w = np.where(prices > 0, new_w, 0.0)
            desired = np.divide(new_w * value, prices, out=np.zeros_like(prices), where=prices > 0)
            cost = float(np.abs(desired - shares) @ prices) * cost_rate
            cash = value - float(desired @ prices) - cost
            shares = desired
            orders[i] = new_w
        equity[i] = cash + float(shares @ prices)
        state = ks.update(equity[i], bool(trend[i]))
        if state == "kill":
            liquidate_next = True
            events.append((day, "kill", f"equity {equity[i]:,.0f} <= {1 - limits.kill_drawdown:.0%} of peak"))
        elif state == "rearm":
            events.append((day, "rearm", "cooldown over and benchmark above trend; re-enter at next rebalance"))

    return RiskRun(
        orders=pd.DataFrame(orders, index=close.index, columns=close.columns),
        equity=pd.Series(equity, index=close.index),
        events=pd.DataFrame(events, columns=["date", "rule", "detail"]),
    )
