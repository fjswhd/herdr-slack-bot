import subprocess
from pathlib import Path

import pytest

from herdr_slack.herdr import Herdr, HerdrError

LIST_JSON = '{"result":{"agents":[{"agent":"codex","agent_status":"idle","cwd":"C:/p/re-alive2","pane_id":"wN6:p2","terminal_id":"t2","terminal_title_stripped":"game","workspace_id":"wN6","completion_seq":132}]}}'


def fake_run(stdout="", stderr="", returncode=0, record=None):
    def run(args):
        if record is not None:
            record.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)
    return run


def test_list_agents_parses_fields():
    h = Herdr(run=fake_run(stdout=LIST_JSON))
    [a] = h.list_agents()
    assert (a.pane_id, a.kind, a.status, a.completion_seq, a.session_id) == ("wN6:p2", "codex", "idle", 132, None)


def test_list_agents_reads_claude_session_id():
    out = '{"result":{"agents":[{"agent":"claude","agent_status":"done","cwd":"C:/x","pane_id":"w:p1","terminal_id":"t1","workspace_id":"w","agent_session":{"value":"abc"}}]}}'
    [a] = Herdr(run=fake_run(stdout=out)).list_agents()
    assert (a.session_id, a.completion_seq, a.title) == ("abc", 0, "")


def test_send_text_enter_calls_send_text_then_enter():
    calls = []
    h = Herdr(run=fake_run(stdout="{}", record=calls))
    h.send_text_enter("w:p1", "hello")
    assert calls == [["herdr", "pane", "send-text", "w:p1", "hello"],
                     ["herdr", "agent", "send-keys", "w:p1", "enter"]]


def test_create_workspace_returns_root_pane():
    h = Herdr(run=fake_run(stdout='{"result":{"root_pane":{"pane_id":"w9:p1"}}}'))
    assert h.create_workspace(Path("C:/x"), "x") == "w9:p1"


def test_read_returns_text():
    calls = []
    h = Herdr(run=fake_run(stdout="screen text", record=calls))
    assert h.read("w:p1", lines=50) == "screen text"
    assert calls == [["herdr", "agent", "read", "w:p1", "--source", "recent-unwrapped", "--lines", "50"]]


def test_cli_error_raises_herdr_error():
    h = Herdr(run=fake_run(returncode=1, stderr='{"error":"agent_blocked"}'))
    with pytest.raises(HerdrError, match="agent_blocked"):
        h.prompt("w:p1", "hi")
