# Agent instructions

Read `CLAUDE.md` before doing anything: architecture, commands, rules, status and next steps. It applies to every
agent, not only Claude. `RUNBOOK.md` has the daily paper-trading steps. Read `DECISIONS.md` before running an
experiment or revisiting a decision.

Always:

- Paper trading only. Never add a path that places live orders.
- Never print or commit API keys.
- Never report a backtest without fees and slippage.
- Do not run `live.py --submit` or `trend_live.py --submit` unless asked.
- Commit or push only when asked.
