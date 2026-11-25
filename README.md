# [claude-trader](https://github.com/karimitaniii/claude-trader)

Momentum trading agent for US tech stocks, as a learning/engineering project (not an income plan).
A deterministic core makes every trading decision; **paper trading only** (Alpaca paper account).

Pipeline: data -> signal -> risk layer -> orders -> logging -> live vs backtest comparison.

```
claude-trader/
├── data.py          # yfinance price cache (keyed by ticker set), 13w T-bill rate
├── universe.py      # point-in-time Nasdaq-100 tech-like membership
├── signals.py       # 12-1 momentum -> monthly top-8 equal weights (no look-ahead)
├── risk.py          # position/semis caps, sell-off rule, hard-stop drawdown kill switch
├── backtest.py      # vectorbt backtest vs equal-weight universe and QQQ, costs always on
├── walkforward.py   # rolling 3y train / 1y test parameter sweep, out-of-sample report
├── broker.py        # Alpaca PAPER-only broker wrapper
├── live.py          # daily paper-trading runner with JSONL logs
├── compare.py       # live paper results vs a backtest over the same dates
├── universe_data/   # membership + hand-made sector map
└── tests/           # pytest
```

## Setup

Python 3.11 in a fresh venv (vectorbt is picky about numpy/numba):

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
```

## Use

```bash
python backtest.py             # full backtest + risk-layer report
python walkforward.py pit      # walk-forward on the point-in-time universe
python live.py                 # dry run against the paper account (needs ALPACA_API_KEY / ALPACA_SECRET_KEY)
python live.py --submit        # once per trading day, before ~15:35 ET
python compare.py              # paper results vs backtest expectations
```

## Honest status

On the point-in-time universe, after costs, the strategy has **not** beaten QQQ on a
risk-adjusted basis (excess Sharpe ~0.72 vs ~0.79), and an equal-weight hold of the same
universe does about as well. Free data misses ~10% of member history (acquired names).
See `CLAUDE.md` for rules, known limitations and the roadmap.
