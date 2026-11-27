#!/usr/bin/env python3
"""PreToolUse guard for agents: turns the AGENTS.md hard rules into checks that always run.

- Bash that could print the Alpaca keys          -> deny (checked first, so it wins over the ask below)
- `live.py` / `trend_live.py` with `--submit`    -> ask the user first (places paper orders; argparse
  abbreviations such as `--sub` count)
- an edit to a .py file (outside tests) that sets the paper flag to anything but True, adds the live
  endpoint, or deletes a paper lock (the True flag or the paper endpoint) -> deny
- any error inside this script -> exit 2, which Claude Code treats as a block (fail closed)

shortcut: regex on the command text, so a determined workaround (eval, a sed edit, a new script, a glob,
a tool outside the matcher) gets past it; broker.py's own paper checks stay the real lock.
"""
import json
import os
import re
import sys

LIVE_MODULE = re.compile(r"\b(trend_)?live\b")  # live.py, -m live, import live
SUBMIT_FLAG = re.compile(r"(?<![\w-])--s\w*")  # argparse accepts any unique prefix of --submit
KEY_VAR = re.compile(r"\$\{?ALPACA_\w*(KEY|SECRET)")
START = r"(^|[;&|(`{]\s*)(sudo\s+|time\s+|command\s+|builtin\s+)*"  # start of a shell command
ENV_DUMP = re.compile(START + r"((printenv|env|set|export)\s*($|[|;&)`}])|(printenv|env)\s+(-0|ALPACA)"
                      r"|export\s+-p|(declare|typeset)\s+-\w*[xp])", re.M)
XTRACE = re.compile(r"\bset\s+(-\w*x|-o\s+xtrace)|\b(ba|z|k|da)?sh\s+(-\w+\s+)*-\w*x")  # tracing echoes sourced lines
SOURCE_KEYS = re.compile(START + r"(source|\.)\s+\S*alpaca_paper_env\b", re.M)
KEY_FILE = re.compile(r"alpaca_paper_env|\.alpaca\w*[*?\[]")  # the key file, also behind a glob
# the paper flag set to anything but a plain True (annotated too), the live host in any case, or a **{...} flag
LIVE_CODE = re.compile(r"\bpaper\s*(:\s*[\w.\[\]]+\s*)?=(?!=)(?!\s*True\s*([,)#]|$))"
                       r"|(?<!paper-)(?i:api\.alpaca\.markets)|\*\*\s*\{\s*['\"]paper['\"]", re.M)
PAPER_LOCK = re.compile(r"\bpaper\s*=\s*True\b|paper-api\.alpaca\.markets|PAPER_URL_FRAGMENT")


def guarded_py(path):
    p = os.path.normpath(path).replace("\\", "/")
    name = p.rsplit("/", 1)[-1].lower()
    return name.endswith((".py", ".pyi")) and "/tests/" not in p and not name.startswith("test_")


def decide(event):
    tool, inp = event.get("tool_name", ""), event.get("tool_input") or {}
    if tool == "Bash":
        cmd = inp.get("command", "")
        # sourcing the key file loads the keys without printing them; any other use may print them
        if (KEY_VAR.search(cmd) or ENV_DUMP.search(cmd) or KEY_FILE.search(SOURCE_KEYS.sub("", cmd))
                or (XTRACE.search(cmd) and re.search(r"alpaca_paper_env|ALPACA", cmd, re.I))):
            return "deny", "this could print the Alpaca keys (AGENTS.md: never print API keys)"
        if LIVE_MODULE.search(cmd) and SUBMIT_FLAG.search(cmd):
            return "ask", "--submit places paper orders; AGENTS.md says only when the user asks"
    elif tool in ("Edit", "Write", "MultiEdit") and guarded_py(inp.get("file_path", "")):
        pairs = [(inp.get("old_string", ""), inp.get("new_string", ""))] + [
            (e.get("old_string", ""), e.get("new_string", "")) for e in inp.get("edits", [])]
        text = "\n".join([inp.get("content", "")] + [new for _, new in pairs])
        if LIVE_CODE.search(text) or any(PAPER_LOCK.search(old) and not PAPER_LOCK.search(new) for old, new in pairs):
            return "deny", ("paper trading only: this edit sets the paper flag to something other than True, "
                            "adds the live Alpaca endpoint, or removes a paper lock")
    return None, ""


if __name__ == "__main__":
    try:
        decision, reason = decide(json.load(sys.stdin))
        if decision:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }}))
    except BaseException as e:  # fail closed: exit 2 blocks the call even without JSON on stdout
        sys.stderr.write(f"guard hook error ({e!r}); fix .claude/hooks/guard.py\n")
        sys.exit(2)
