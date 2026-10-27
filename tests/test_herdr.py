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


def test_read_falls_back_to_visible_when_not_idle():
    calls = []

    def run(args):
        calls.append(args)
        if "recent-unwrapped" in args:
            return subprocess.CompletedProcess(args, 1, "", '{"error":{"code":"agent_not_idle"}}')
        return subprocess.CompletedProcess(args, 0, "visible screen", "")
    assert Herdr(run=run).read("w:p1") == "visible screen"
    assert calls[-1] == ["herdr", "agent", "read", "w:p1", "--source", "visible"]


def test_os_error_becomes_herdr_error():
    def run(args):
        raise FileNotFoundError("herdr not found")
    with pytest.raises(HerdrError, match="herdr not found"):
        Herdr(run=run).list_agents()


def test_timeout_becomes_herdr_error():
    def run(args):
        raise subprocess.TimeoutExpired(args, 60)
    with pytest.raises(HerdrError):
        Herdr(run=run).prompt("w:p1", "hi")


def test_bad_json_becomes_herdr_error():
    with pytest.raises(HerdrError):
        Herdr(run=fake_run(stdout="not json")).list_agents()


def test_create_workspace_missing_pane_becomes_herdr_error():
    with pytest.raises(HerdrError):
        Herdr(run=fake_run(stdout='{"result":{}}')).create_workspace(Path("C:/x"), "x")



def test_workspace_labels():
    out = '{"result":{"workspaces":[{"workspace_id":"wN6","label":"re-alive"},{"workspace_id":"wN7","label":"ai"}]}}'
    assert Herdr(run=fake_run(stdout=out)).workspace_labels() == {"wN6": "re-alive", "wN7": "ai"}
