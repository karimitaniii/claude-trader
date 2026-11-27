"""The agent guard hook (.claude/hooks/guard.py), run the way Claude Code runs it: JSON on stdin."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "guard.py"


def run(tool, **tool_input):
    out = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else None


@pytest.mark.parametrize("cmd", [
    "python live.py --submit",
    "source ~/.alpaca_paper_env && .venv/bin/python trend_live.py --submit",
    "python3 live.py --offline --submit 2>&1 | tail",
    "python -m trend_live --submit",
    "python -c 'import live; live.main([\"--submit\"])'",
])
def test_submit_asks(cmd):
    assert run("Bash", command=cmd) == "ask"


@pytest.mark.parametrize("cmd", [
    "echo $ALPACA_API_KEY",
    "echo ${ALPACA_TREND_SECRET_KEY}",
    "printenv",
    "env | grep ALPACA",
    "printenv ALPACA_API_KEY",
    "export -p | grep ALPACA",
    "declare -x",
    "set | grep ALPACA",
    "env -0",
    "env ALPACA_API_KEY",
    "cat ~/.alpaca_paper_env",
    "source ~/.alpaca_paper_env; cat ~/.alpaca_paper_env",
])
def test_key_printing_denied(cmd):
    assert run("Bash", command=cmd) == "deny"


@pytest.mark.parametrize("cmd", [
    "python live.py",
    "source ~/.alpaca_paper_env && python live.py && python trend_live.py",
    ". ~/.alpaca_paper_env && python compare.py --strategy both",
    "env PYTHONPATH=. pytest -q",
    "pytest tests/test_live.py",
    "set -e; python live.py",
])
def test_normal_commands_allowed(cmd):
    assert run("Bash", command=cmd) is None


def test_live_edits_denied():
    assert run("Edit", file_path="/repo/broker.py", old_string="paper=True", new_string="paper=False") == "deny"
    assert run("Write", file_path="/repo/x.py", content='URL = "https://api.alpaca.markets"') == "deny"
    assert run("MultiEdit", file_path="/repo/live.py",
               edits=[{"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "paper = False"}]) == "deny"
    for value in ("0", "not True", "use_paper"):
        assert run("Edit", file_path="/repo/broker.py", old_string="x", new_string=f"TradingClient(k, s, paper={value})") == "deny"


def test_safe_edits_allowed():
    assert run("Edit", file_path="/repo/broker.py", old_string="x", new_string='"paper-api.alpaca.markets"') is None
    assert run("Edit", file_path="/repo/tests/test_live.py", old_string="x", new_string='"paper=False" not in src') is None
    assert run("Write", file_path="/repo/NOTES.md", content="never set paper=False") is None
    assert run("Read", file_path="/repo/broker.py") is None
    assert run("Edit", file_path="/repo/broker.py", old_string="x", new_string="TradingClient(k, s, paper= True)") is None
    assert run("Edit", file_path="/repo/x.py", old_string="x", new_string="if paper == expected:") is None


def test_bad_input_fails_closed():
    out = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True).stdout
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
