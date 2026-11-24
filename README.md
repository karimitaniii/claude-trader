# tech_momentum

First pipeline: data -> signal -> backtest (with costs) for a US tech momentum strategy.

```
tech_momentum/
├── data.py          # download + cache adjusted closes (yfinance)
├── signals.py       # 12-1 momentum -> monthly target weights (no look-ahead)
├── backtest.py      # vectorbt backtest vs QQQ, sub-period stats, equity plot
└── requirements.txt
```

Run: `pip install -r requirements.txt && python backtest.py`
(vectorbt can be picky about numpy/numba versions; use a fresh venv, Python 3.10-3.11.)

Next steps: point-in-time universe, walk-forward parameter testing, risk layer
(position caps, drawdown kill switch), Alpaca paper trading, then the LLM feature layer.
