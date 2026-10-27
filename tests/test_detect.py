from herdr_slack.detect import diff, next_snapshot
from herdr_slack.herdr import Agent


def agent(status="idle", seq=0, terminal="t1", pane="p"):
    return Agent(pane_id=pane, workspace_id="w", terminal_id=terminal, kind="claude",
                 status=status, cwd="C:/x", title="", completion_seq=seq, session_id=None)


def kinds(events):
    return [e.kind for e in events]


def test_first_snapshot_emits_nothing():
    assert diff(None, [agent(status="done", seq=5)]) == []


def test_working_to_blocked_emits_blocked():
    prev = {"p": agent(status="working", seq=5)}
    assert kinds(diff(prev, [agent(status="blocked", seq=5)])) == ["blocked"]


def test_completion_seq_increase_emits_done_even_if_status_working():
    prev = {"p": agent(status="working", seq=5)}
    assert kinds(diff(prev, [agent(status="working", seq=6)])) == ["done"]


def test_blocked_stays_blocked_emits_nothing():
    prev = {"p": agent(status="blocked", seq=5)}
    assert diff(prev, [agent(status="blocked", seq=5)]) == []


def test_terminal_change_resets_baseline():
    prev = {"p": agent(status="idle", seq=50, terminal="t1")}
    assert diff(prev, [agent(status="idle", seq=1, terminal="t2")]) == []


def test_seq_increase_while_blocked_emits_only_blocked():
    prev = {"p": agent(status="working", seq=5)}
    assert kinds(diff(prev, [agent(status="blocked", seq=6)])) == ["blocked"]


def test_working_without_seq_keeps_last_seen_seq():
    # herdr omits completion_seq while working; the next completion must still count once
    snap = next_snapshot(None, [agent(status="idle", seq=139)])
    working = [agent(status="working", seq=0)]
    assert diff(snap, working) == []
    snap = next_snapshot(snap, working)
    done = [agent(status="idle", seq=140)]
    assert kinds(diff(snap, done)) == ["done"]
    snap = next_snapshot(snap, done)
    assert diff(snap, done) == []
