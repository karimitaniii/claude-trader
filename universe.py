"""Point-in-time universe: Nasdaq-100 members on each date, filtered to tech-like names.

Membership source: jmccarrell/n100tickers (MIT), pinned to one commit for reproducibility.
It stores, per year, the members on Jan 1 plus dated changes (effective dates from Nasdaq
announcements), using the ticker that actually traded on that date (FB, not META).

Known residual bias (free data): yfinance has no prices for most delisted names (acquired
companies like XLNX, CTXS, ATVI). Members without price data cannot be traded and are
excluded; `coverage_report` measures how much of the member history that removes.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd
import yaml

DATA_DIR = Path(__file__).parent / "universe_data"
MEMBERSHIP_FILE = DATA_DIR / "ndx_membership.csv"
SECTOR_MAP_FILE = DATA_DIR / "ndx_sector_map.csv"

SOURCE_REPO = "jmccarrell/n100tickers"
SOURCE_COMMIT = "4ce85254b67f27540abedbb93a109687eafe39f0"
SOURCE_URL = (
    f"https://raw.githubusercontent.com/{SOURCE_REPO}/{SOURCE_COMMIT}"
    "/src/nasdaq_100_ticker_history/n100-ticker-changes-{year}.yaml"
)

# Contemporaneous ticker -> symbol that yfinance has full history under (same company).
PRICE_ALIASES: dict[str, str] = {
    "FB": "META",     # renamed 2022-06-09
    "GOOG": "GOOGL",  # one company: hold Alphabet once, priced via class A
    "SYMC": "GEN",    # Symantec -> NortonLifeLock (2019) -> Gen Digital (2022)
    "NLOK": "GEN",
}


def parse_years(years: dict[int, dict]) -> pd.DataFrame:
    """Turn {year: {"tickers_on_Jan_1": [...], "changes": {date: {union, difference}}}}
    into membership intervals [start, end) with columns ticker, start, end (end NaT = still in).

    Raises if applying a year's changes does not reproduce the next year's Jan-1 list.
    """
    ys = sorted(years)
    members = set(years[ys[0]]["tickers_on_Jan_1"])
    open_since = {t: pd.Timestamp(year=ys[0], month=1, day=1) for t in members}
    rows = []
    for y in ys:
        if set(years[y]["tickers_on_Jan_1"]) != members:
            raise ValueError(f"{y}: Jan-1 snapshot does not match the previous year's changes")
        for date in sorted(years[y].get("changes") or {}):
            when = pd.Timestamp(date)
            change = years[y]["changes"][date]
            for t in change.get("difference") or []:
                rows.append((t, open_since.pop(t), when))
                members.discard(t)
            for t in change.get("union") or []:
                if t not in members:
                    members.add(t)
                    open_since[t] = when
    rows += [(t, start, pd.NaT) for t, start in open_since.items()]
    return pd.DataFrame(rows, columns=["ticker", "start", "end"]).sort_values(["ticker", "start"]).reset_index(drop=True)


def refresh_membership(first_year: int = 2012, last_year: int | None = None) -> pd.DataFrame:
    """Download the pinned yearly YAML files and write universe_data/ndx_membership.csv."""
    last_year = last_year or pd.Timestamp.today().year
    years = {}
    for y in range(first_year, last_year + 1):
        with urllib.request.urlopen(SOURCE_URL.format(year=y), timeout=30) as resp:
            # BaseLoader keeps every value a string: YAML 1.1 would turn ticker "ON" into True.
            years[y] = yaml.load(resp.read().decode(), Loader=yaml.BaseLoader)
    intervals = parse_years(years)
    DATA_DIR.mkdir(exist_ok=True)
    intervals.to_csv(MEMBERSHIP_FILE, index=False)
    return intervals


def load_membership() -> pd.DataFrame:
    if not MEMBERSHIP_FILE.exists():
        return refresh_membership()
    return pd.read_csv(MEMBERSHIP_FILE, parse_dates=["start", "end"], keep_default_na=False, na_values=[""])


def load_sector_map() -> pd.DataFrame:
    return pd.read_csv(SECTOR_MAP_FILE, keep_default_na=False, dtype={"tech_like": int})


RISK_GROUPS = {"semis": "semis", "semi_equipment": "semis"}  # category -> risk group


def symbol_groups(symbols, sector_map: pd.DataFrame | None = None) -> pd.Series:
    """Risk group per price symbol (semis + semi equipment -> "semis"; other categories as-is).

    Symbols not in the sector map (e.g. CRM, NOW in the static list) get "other".
    """
    sector_map = load_sector_map() if sector_map is None else sector_map
    by_ticker = sector_map.set_index("ticker")["category"]
    by_symbol = {PRICE_ALIASES.get(t, t): c for t, c in by_ticker.items()}
    return pd.Series(
        {s: RISK_GROUPS.get(by_symbol.get(s, "other"), by_symbol.get(s, "other")) for s in symbols}, name="group"
    )


def tech_intervals(intervals: pd.DataFrame, sector_map: pd.DataFrame) -> pd.DataFrame:
    """Keep tech-like members and add the price symbol. Fails loudly on unclassified tickers."""
    unknown = set(intervals["ticker"]) - set(sector_map["ticker"])
    if unknown:
        raise ValueError(f"tickers missing from {SECTOR_MAP_FILE.name}, classify them: {sorted(unknown)}")
    tech = set(sector_map.loc[sector_map["tech_like"] == 1, "ticker"])
    out = intervals[intervals["ticker"].isin(tech)].copy()
    out["symbol"] = out["ticker"].map(lambda t: PRICE_ALIASES.get(t, t))
    return out.reset_index(drop=True)


def membership_matrix(intervals: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Boolean date x symbol frame: True if the symbol is a member at the close of that date.

    Intervals are [start, end): a name removed effective date D is no longer a member on D.
    """
    out = pd.DataFrame(False, index=index, columns=sorted(intervals["symbol"].unique()))
    for row in intervals.itertuples():
        end = row.end if pd.notna(row.end) else index[-1] + pd.Timedelta(days=1)
        out.loc[(index >= row.start) & (index < end), row.symbol] = True
    return out


def load_universe(kind: str = "pit", refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Return (forward-filled closes, eligibility mask or None).

    kind="pit":    point-in-time Nasdaq-100 tech-like members (mask = membership).
    kind="static": the old hand-picked 24-name list, always eligible (survivorship-biased).
    """
    from data import UNIVERSE, load_prices

    if kind == "static":
        return load_prices(UNIVERSE, refresh=refresh)[UNIVERSE].ffill(), None
    if kind != "pit":
        raise ValueError(f"unknown universe {kind!r}")
    tech = tech_intervals(load_membership(), load_sector_map())
    close = load_prices(sorted(tech["symbol"].unique()), refresh=refresh)
    close = close.loc[:, close.notna().any()]  # drop names yfinance has no data for
    members = membership_matrix(tech[tech["symbol"].isin(close.columns)], close.index)
    return close.ffill(), members.reindex(columns=close.columns, fill_value=False)


def coverage_report(members: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Per symbol: member-days, member-days with a price, and the share missing."""
    has_price = close.reindex(index=members.index, columns=members.columns).notna()
    member_days = members.sum()
    priced_days = (members & has_price).sum()
    report = pd.DataFrame({"member_days": member_days, "priced_days": priced_days})
    report["missing_share"] = 1 - report["priced_days"] / report["member_days"].where(report["member_days"] > 0)
    return report.sort_values("missing_share", ascending=False)
