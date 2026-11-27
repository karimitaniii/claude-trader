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
    "python live.py --sub",  # argparse abbreviations
    "python trend_live.py --s",
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
    "python live.py --submit; echo $ALPACA_API_KEY",  # deny wins over the submit ask
    "set -x; source ~/.alpaca_paper_env",
    "set -ex; source ~/.alpaca_paper_env && python live.py",
    "set -o xtrace; . ~/.alpaca_paper_env",
    "bash -x -c 'source ~/.alpaca_paper_env'",
    "zsh -xic 'python live.py'  # ALPACA keys from zshrc",
    "export",
    "export | grep ALPACA",
    "typeset -x",
    "typeset -p",
    "echo hi\nprintenv",
    "echo `printenv`",
    "{ env; }",
    "sudo env",
    "time printenv",
    "cat ~/.alpaca_p*",
    "cat ~/.alpaca_paper_en?",
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
    "set -e; source ~/.alpaca_paper_env && python live.py",
    "zsh -ic 'coderabbit review --base main'",
    "set -x; pytest -q",
    "python live.py --offline",
    "python live.py --reset-kill-switch",
    "export PYTHONPATH=. && pytest -q",
    "git commit -m 'set env vars'",
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
    for new in ("def __init__(self, paper: bool = False):", "TradingClient(k, s, paper=True if ok else False)",
                'TradingClient(k, s, **{"paper": False})', 'URL = "https://API.ALPACA.MARKETS"'):
        assert run("Edit", file_path="/repo/broker.py", old_string="x", new_string=new) == "deny", new
    # path tricks: upper-case suffix, a tests/.. detour, a stub file
    for path in ("/repo/broker.PY", "/repo/tests/../broker.py", "/repo/broker.pyi"):
        assert run("Write", file_path=path, content="paper=False") == "deny", path
    # deleting the paper lock is as bad as flipping it
    assert run("Edit", file_path="/repo/broker.py", old_string=", paper=True)", new_string=")") == "deny"
    assert run("Edit", file_path="/repo/broker.py", old_string='URL = "paper-api.alpaca.markets"',
               new_string="URL = None") == "deny"


def test_safe_edits_allowed():
    assert run("Edit", file_path="/repo/broker.py", old_string="x", new_string='"paper-api.alpaca.markets"') is None
    assert run("Edit", file_path="/repo/tests/test_live.py", old_string="x", new_string='"paper=False" not in src') is None
    assert run("Write", file_path="/repo/NOTES.md", content="never set paper=False") is None
    assert run("Read", file_path="/repo/broker.py") is None
    assert run("Edit", file_path="/repo/broker.py", old_string="x", new_string="TradingClient(k, s, paper= True)") is None
    assert run("Edit", file_path="/repo/x.py", old_string="x", new_string="if paper == expected:") is None
    assert run("Edit", file_path="/repo/broker.py", old_string="x",
               new_string="TradingClient(k, s, paper=True)  # never change") is None
    assert run("Edit", file_path="/repo/broker.py", old_string="paper=True)", new_string="paper=True, raw=False)") is None
    assert run("Edit", file_path="/repo/broker.py", old_string="x",
               new_string='assert "paper-api.alpaca.markets" in base, "not api.alpaca.markets"') == "deny"  # live host named


def test_partial_edits_checked_against_file(tmp_path):
    f = tmp_path / "broker.py"
    f.write_text('"""`paper=True` is hard-coded."""\nURL = "paper-api.alpaca.markets"\nc = TradingClient(k, s, paper=True)\n')
    assert run("Edit", file_path=str(f), old_string="paper=True)", new_string="paper=True)  # ok") is None
    assert run("Edit", file_path=str(f), old_string="URL", new_string="BASE") is None  # docstring match predates the edit
    assert run("Edit", file_path=str(f), old_string="True)", new_string="False)") == "deny"
    assert run("Edit", file_path=str(f), old_string="paper-api", new_string="api") == "deny"
    assert run("MultiEdit", file_path=str(f), edits=[{"old_string": "c = ", "new_string": "d = "},
                                                     {"old_string": "True)", "new_string": "flag)"}]) == "deny"
    assert run("Write", file_path=str(f), content=f.read_text().replace("paper=True)", "paper=flag)")) == "deny"


@pytest.mark.parametrize("stdin", ["not json", "[]", '{"tool_name": "Bash", "tool_input": "str"}',
                                   '{"tool_name": "MultiEdit", "tool_input": {"file_path": "/r/a.py", "edits": null}}'])
def test_bad_input_fails_closed(stdin):
    # exit 2 is Claude Code's blocking code; it does not depend on stdout being parsed
    assert subprocess.run([sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True).returncode == 2


def test_wiring_matches_settings():
    """settings.json runs this guard with /usr/bin/python3 on Bash and file edits; that interpreter must run it."""
    settings = json.loads((GUARD.parents[1] / "settings.json").read_text())
    (entry,) = settings["hooks"]["PreToolUse"]
    assert set(entry["matcher"].split("|")) >= {"Bash", "Edit", "Write", "MultiEdit"}
    cmd = entry["hooks"][0]["command"]
    assert cmd.startswith("/usr/bin/python3 ") and cmd.endswith('/.claude/hooks/guard.py"')
    if not Path("/usr/bin/python3").exists():
        pytest.skip("no /usr/bin/python3 here")
    out = subprocess.run(["/usr/bin/python3", str(GUARD)], capture_output=True, text=True, check=True,
                         input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "printenv"}})).stdout
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
