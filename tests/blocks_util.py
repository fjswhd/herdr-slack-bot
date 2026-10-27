import json

from herdr_slack.herdr import Agent


def agent(status="idle", seq=0, terminal="t1", pane="p", kind="claude", cwd="C:/p/clips", session_id=None):
    return Agent(pane_id=pane, workspace_id="w", terminal_id=terminal, kind=kind,
                 status=status, cwd=cwd, title="", completion_seq=seq, session_id=session_id)


def action_ids(blocks):
    return [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]


def text_of(blocks):
    return json.dumps(blocks, ensure_ascii=False)
