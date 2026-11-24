"""Data layer: download adjusted daily closes and cache them to CSV."""
import hashlib
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / "data_cache"

# Fixed, hand-picked universe of large US tech names.
# WARNING: choosing today's winners makes this survivorship-biased. Fine for a
# first pipeline test; replace with point-in-time index membership before
# trusting any result.
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO", "ORCL",
    "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "AMAT",
    "NFLX", "INTU", "MU", "NOW", "PANW", "LRCX", "KLAC", "ADI",
]
BENCHMARK = "QQQ"

# Former members yfinance has no data for (acquired/delisted; checked 2026-11). Not downloaded,
# so daily runs stay quiet; they remain as all-NaN columns and show up in the coverage report.
KNOWN_NO_DATA = frozenset(
    "ALTR BMC BRCM CA CTXS LLTC MXIM NUAN RIMM SPLK XLNX YHOO".split()
)


def price_cache_file(tickers, start, end) -> Path:
    """Cache path keyed by the ticker set and date range, so a new universe never reuses stale data."""
    key = hashlib.sha1(f"{sorted(set(tickers))}|{start}|{end}".encode()).hexdigest()[:10]
    return CACHE_DIR / f"close_{key}.csv"


def load_prices(tickers, start="2013-01-01", end=None, refresh=False, retries: int = 2):
    """Return a DataFrame of split/dividend-adjusted closes (date x ticker).

    Tickers yfinance has no data for come back as all-NaN columns (kept, so callers can
    measure coverage).
    """
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = price_cache_file(tickers, start, end)
    if cache_file.exists() and not refresh:
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    tickers = sorted(set(tickers))
    fetch = [t for t in tickers if t not in KNOWN_NO_DATA]
    raw = yf.download(fetch, start=start, end=end, auto_adjust=True, progress=False)
    close = raw["Close"].reindex(columns=tickers)  # known-dead tickers stay as NaN columns
    # yfinance reports timeouts and "no such ticker" the same way (an all-NaN column).
    # Retry empty columns so a transient failure is not cached as "no data".
    for _ in range(retries):
        missing = [t for t in fetch if close[t].isna().all()]
        if not missing:
            break
        time.sleep(2)
        again = yf.download(missing, start=start, end=end, auto_adjust=True, progress=False)["Close"]
        close[missing] = again.reindex(index=close.index, columns=missing)
    close = close.dropna(how="all")
    close.to_csv(cache_file)
    return close


def load_risk_free(start: str = "2013-01-01", end=None, refresh: bool = False) -> pd.Series:
    """Daily risk-free rate (decimal per trading day) from the 13-week T-bill yield.

    ^IRX quotes an annualized yield in percent; approximated here as yield / 100 / 252.
    Used only for reporting (excess Sharpe) and in-sample parameter scoring.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / "irx.csv"
    if cache_file.exists() and not refresh:
        irx = pd.read_csv(cache_file, index_col=0, parse_dates=True).iloc[:, 0]
    else:
        raw = yf.download("^IRX", start=start, end=end, auto_adjust=True, progress=False)
        irx = raw["Close"].squeeze().dropna().rename("IRX")
        irx.to_csv(cache_file)
    return irx / 100 / 252
