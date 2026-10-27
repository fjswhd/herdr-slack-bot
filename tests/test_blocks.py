import json

from blocks_util import action_ids, agent, text_of
from herdr_slack.blocks import agent_list, busy_notice, new_agent_modal, notification, split_text
from herdr_slack.detect import Event
from herdr_slack.extract import Choice


def test_blocked_notification_has_choice_and_esc_buttons():
    blocks = notification(Event("blocked", agent(kind="claude", cwd="C:\\p\\clips")), "Proceed?", [Choice("1", "Yes")])
    assert action_ids(blocks) == ["choice_1", "esc", "screen"]
    assert "⚠️ 판단 필요" in text_of(blocks) and "clips · claude" in text_of(blocks)


def test_done_notification_truncates_preview():
    blocks = notification(Event("done", agent()), "x" * 1000, [])
    assert action_ids(blocks) == ["full", "screen"]
    assert "x" * 601 not in text_of(blocks) and "…" in text_of(blocks)


def test_button_values_carry_pane_id():
    blocks = notification(Event("done", agent(pane="w:p9")), "hi", [])
    values = [e["value"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert values == ["w:p9", "w:p9"]


def test_full_text_split_under_limit():
    parts = split_text("a" * 7000)
    assert len(parts) == 3 and all(len(p) <= 2900 for p in parts) and "".join(parts) == "a" * 7000


def test_split_text_prefers_newline():
    parts = split_text("a" * 2000 + "\n" + "b" * 2000)
    assert parts == ["a" * 2000 + "\n", "b" * 2000]


def test_busy_notice_has_force_send_with_text():
    blocks = busy_notice("w:p1", "다음 작업")
    [btn] = [e for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert btn["action_id"] == "force_send"
    assert json.loads(btn["value"]) == {"pane_id": "w:p1", "text": "다음 작업"}


def test_agent_list_shows_each_pane():
    t = text_of(agent_list([agent(pane="w:p1", status="working"), agent(pane="w:p2", kind="codex", cwd="C:/p/game")]))
    assert "clips · claude" in t and "working" in t and "game · codex" in t


def test_new_agent_modal_fields():
    m = new_agent_modal()
    ids = [b["block_id"] for b in m["blocks"]]
    assert m["callback_id"] == "new_agent" and ids == ["name", "kind", "prompt"]


def test_headline_for_push_text():
    from herdr_slack.blocks import headline
    assert headline(Event("done", agent(kind="codex", cwd="C:/p/game"))) == "✅ 완료 game · codex"
