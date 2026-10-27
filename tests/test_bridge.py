from dataclasses import dataclass

import pytest

from blocks_util import action_ids, agent
from herdr_slack.bridge import Bridge
from herdr_slack.herdr import HerdrError
from herdr_slack.store import PaneRef, ThreadStore


@dataclass
class Post:
    ts: str
    blocks: list
    text: str
    thread_ts: str | None


class FakeHerdr:
    def __init__(self, agents, screen="", fail_on=None):
        self.agents = agents
        self.screen = screen
        self.fail_on = fail_on
        self.calls = []

    def _rec(self, name, *args):
        if name == self.fail_on:
            raise HerdrError("agent_blocked")
        self.calls.append((name, *args))

    def calls_of(self, name):
        return [c for c in self.calls if c[0] == name]

    def list_agents(self):
        return list(self.agents)

    def read(self, pane_id, lines=120):
        return self.screen

    def prompt(self, pane_id, text):
        self._rec("prompt", pane_id, text)

    def send_keys(self, pane_id, keys):
        self._rec("send_keys", pane_id, keys)

    def send_text_enter(self, pane_id, text):
        self._rec("send_text_enter", pane_id, text)

    def create_workspace(self, cwd, label):
        self._rec("create_workspace", cwd, label)
        return "w9:p1"

    def start_agent(self, name, kind, pane_id):
        self._rec("start_agent", name, kind, pane_id)


def make_bridge(tmp_path, agents=(), screen="", fail_on=None, projects_root=None):
    herdr = FakeHerdr(list(agents), screen, fail_on)
    posts = []

    def post(blocks, text, thread_ts=None):
        p = Post(f"{len(posts) + 1}.0", blocks, text, thread_ts)
        posts.append(p)
        return p.ts

    store = ThreadStore(tmp_path / "threads.json")
    b = Bridge(herdr, store, post, projects_root or tmp_path / "projects", claude_projects_dir=tmp_path / "claude")
    return b, herdr, posts, store


def test_done_event_posts_and_records_thread(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="done")])
    b.on_status_event("p", "working")
    b.on_status_event("p", "done")
    assert len(posts) == 1 and posts[0].thread_ts is None
    assert store.get(posts[0].ts) == PaneRef("p", "t1")


def test_repeated_done_event_posts_once(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[agent(status="done")])
    b.on_status_event("p", "done")
    b.on_status_event("p", "done")
    assert len(posts) == 1


def test_idle_event_posts_nothing(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[agent(status="idle")])
    b.on_status_event("p", "idle")
    assert posts == []


def test_event_for_unknown_pane_posts_nothing(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[])
    b.on_status_event("p", "done")
    assert posts == []


def test_done_uses_claude_session_text(tmp_path):
    f = tmp_path / "claude" / "C--p" / "sid.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"세션 응답"}]}}\n', encoding="utf-8")
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[agent(status="done", session_id="sid")],
                                     screen="● 화면 응답")
    b.on_status_event("p", "done")
    assert "세션 응답" in str(posts[0].blocks) and "화면 응답" not in str(posts[0].blocks)


def test_blocked_event_has_choices(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[agent(status="blocked")],
                                     screen="Proceed?\n❯ 1. Yes\n  2. No\n")
    b.on_status_event("p", "blocked")
    assert action_ids(posts[0].blocks) == ["choice_1", "choice_2", "esc", "screen"]


def test_blocked_again_after_working_posts_again(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[agent(status="blocked")])
    b.on_status_event("p", "blocked")
    b.on_status_event("p", "working")
    b.on_status_event("p", "blocked")
    assert len(posts) == 2


def test_reply_sends_prompt_when_idle(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="idle")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "다음 작업")
    assert herdr.calls[-1] == ("prompt", "p", "다음 작업")
    assert posts[-1].thread_ts == "9.0" and "전송됨" in posts[-1].text


def test_reply_unknown_thread_is_ignored(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, agents=[agent(status="idle")])
    b.handle_reply("1.0", "hi")
    assert herdr.calls == [] and posts == []


def test_reply_when_working_posts_busy_notice_and_does_not_send(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="working")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "다음 작업")
    assert herdr.calls_of("prompt") == []
    assert "force_send" in action_ids(posts[-1].blocks)


def test_reply_when_blocked_sends_key(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="blocked")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "1")
    assert herdr.calls[-1] == ("send_keys", "p", ["1"])


def test_reply_rejected_when_terminal_changed(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="idle", terminal="t2")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "hi")
    assert herdr.calls_of("prompt") == [] and "더 이상 없음" in posts[-1].text


def test_reply_reports_herdr_error(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="idle")], fail_on="prompt")
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "hi")
    assert posts[-1].text.startswith("⚠️ herdr 오류")


def test_action_choice_sends_key(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="blocked")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("9.0", "choice_2", "p")
    assert herdr.calls[-1] == ("send_keys", "p", ["2"])


def test_action_esc_sends_esc(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="blocked")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("9.0", "esc", "p")
    assert herdr.calls[-1] == ("send_keys", "p", ["esc"])


def test_action_force_send_prompts_pending_text(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="working")])
    store.put("9.0", PaneRef("p", "t1"))
    long_text = "x" * 3000
    b.handle_reply("9.0", long_text)
    [btn] = [e for blk in posts[-1].blocks if blk["type"] == "actions" for e in blk["elements"]]
    assert len(btn["value"]) < 100
    b.handle_action("9.0", "force_send", btn["value"])
    assert herdr.calls[-1] == ("prompt", "p", long_text)


def test_action_force_send_unknown_key_reports_expired(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="working")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("9.0", "force_send", "nope")
    assert herdr.calls == [] and "만료" in posts[-1].text


def test_action_screen_splits_long_screen(tmp_path):
    screen = "\n".join("y" * 500 for _ in range(60))
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="idle")], screen=screen)
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("9.0", "screen", "p")
    sections = [blk["text"]["text"] for p in posts for blk in p.blocks if blk["type"] == "section"]
    assert len(posts) > 1 and all(len(t) <= 3000 for t in sections)


def test_reply_reports_internal_error(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="idle")])
    store.put("9.0", PaneRef("p", "t1"))

    def boom(*a):
        raise RuntimeError("x")
    herdr.prompt = boom
    b.handle_reply("9.0", "hi")
    assert "내부 오류" in posts[-1].text


def test_failing_body_still_posts_headline(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="done")])

    def bad_read(pane_id, lines=120):
        raise RuntimeError("bad")
    herdr.read = bad_read
    b.on_status_event("p", "done")
    assert len(posts) == 1 and store.get(posts[0].ts)


def test_start_new_failure_removes_empty_folder(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, projects_root=tmp_path, fail_on="start_agent")
    with pytest.raises(HerdrError):
        b.start_new("idea", "claude", "")
    assert not (tmp_path / "idea").exists()


def test_action_full_posts_split_response(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="idle")], screen="● " + "a" * 5000)
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("9.0", "full", "p")
    assert len(posts) == 2 and all(p.thread_ts == "9.0" for p in posts)


def test_action_rejected_when_terminal_changed(tmp_path):
    b, herdr, posts, store = make_bridge(tmp_path, agents=[agent(status="blocked", terminal="t2")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("9.0", "esc", "p")
    assert herdr.calls == [] and "더 이상 없음" in posts[-1].text


def test_start_new_creates_folder_workspace_agent_and_prompt(tmp_path):
    b, herdr, posts, _ = make_bridge(tmp_path, projects_root=tmp_path)
    b.start_new("idea", "codex", "구상하자")
    assert (tmp_path / "idea").is_dir()
    assert [c[0] for c in herdr.calls] == ["create_workspace", "start_agent", "prompt"]
    assert herdr.calls[1] == ("start_agent", "idea", "codex", "w9:p1")


def test_start_new_rejects_existing_folder(tmp_path):
    (tmp_path / "idea").mkdir()
    b, *_ = make_bridge(tmp_path, projects_root=tmp_path)
    with pytest.raises(ValueError):
        b.start_new("idea", "claude", "")


def test_start_new_rejects_bad_name(tmp_path):
    b, *_ = make_bridge(tmp_path, projects_root=tmp_path)
    with pytest.raises(ValueError):
        b.start_new("Bad Name", "claude", "")
