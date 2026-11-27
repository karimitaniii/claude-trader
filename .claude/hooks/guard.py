#!/usr/bin/env python3
"""PreToolUse guard for agents: turns the AGENTS.md hard rules into checks that always run.

- `live.py` / `trend_live.py` with `--submit`  -> ask the user first (places paper orders)
- Bash that prints the Alpaca keys              -> deny
- an edit to a .py file (outside tests) setting `paper=` to anything but True, or adding the live endpoint -> deny
- any error inside this script -> deny (fail closed)

shortcut: regex on the command text, so a determined workaround (eval, a sed edit, a new script) gets past it;
broker.py's own paper checks stay the real lock.
"""
import json
import re
import sys

LIVE_MODULE = re.compile(r"\b(trend_)?live\b")  # live.py, -m live, import live
SUBMIT_FLAG = re.compile(r"--submit\b")
KEY_VAR = re.compile(r"\$\{?ALPACA_\w*(KEY|SECRET)")
ENV_DUMP = re.compile(r"(^|[;&|(]\s*)((printenv|env|set)\s*($|[|;&)])|(printenv|env)\s+(-0|ALPACA)"
                      r"|export\s+-p|declare\s+-\w*[xp])")
SOURCE_KEYS = re.compile(r"(^|[;&|(]\s*)(source|\.)\s+\S*alpaca_paper_env\b")
LIVE_CODE = re.compile(r"\bpaper\s*=(?!=)(?!\s*True\b)|(?<!paper-)api\.alpaca\.markets")  # any paper= but True


def decide(event):
    tool, inp = event.get("tool_name", ""), event.get("tool_input") or {}
    if tool == "Bash":
        cmd = inp.get("command", "")
        if LIVE_MODULE.search(cmd) and SUBMIT_FLAG.search(cmd):
            return "ask", "--submit places paper orders; AGENTS.md says only when the user asks"
        # `source ~/.alpaca_paper_env` loads the keys without printing them; any other use may print them
        if KEY_VAR.search(cmd) or ENV_DUMP.search(cmd) or "alpaca_paper_env" in SOURCE_KEYS.sub("", cmd):
            return "deny", "this could print the Alpaca keys (AGENTS.md: never print API keys)"
    elif tool in ("Edit", "Write", "MultiEdit"):
        path = inp.get("file_path", "")
        name = path.rsplit("/", 1)[-1]
        if path.endswith(".py") and "/tests/" not in path and not name.startswith("test_"):
            text = "\n".join([inp.get("content", ""), inp.get("new_string", "")]
                             + [e.get("new_string", "") for e in inp.get("edits", [])])
            if LIVE_CODE.search(text):
                return "deny", "paper trading only: this edit sets paper= to something other than True, or adds the live Alpaca endpoint"
    return None, ""


if __name__ == "__main__":
    try:
        decision, reason = decide(json.load(sys.stdin))
    except Exception as e:  # fail closed: a crashing guard must not let the call through
        decision, reason = "deny", f"guard hook error ({e!r}); fix .claude/hooks/guard.py"
    if decision:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}))
