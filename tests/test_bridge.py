from dataclasses import dataclass

import pytest

from blocks_util import action_ids, agent
from herdr_slack.bridge import Bridge
from herdr_slack.channels import ChannelMap
from herdr_slack.herdr import HerdrError
from herdr_slack.store import PaneRef, ThreadStore


@dataclass
class Post:
    channel: str
    ts: str
    blocks: list
    text: str
    thread_ts: str | None


class FakeSlack:
    def __init__(self, fail_create=False):
        self.posts: list[Post] = []
        self.reactions: list[tuple] = []
        self.unreactions: list[tuple] = []
        self.created: list[str] = []
        self.fail_create = fail_create

    def post(self, channel, blocks, text, thread_ts=None):
        p = Post(channel, f"{len(self.posts) + 1}.0", blocks, text, thread_ts)
        self.posts.append(p)
        return p.ts

    def react(self, channel, ts, name):
        self.reactions.append((channel, ts, name))

    def unreact(self, channel, ts, name):
        self.unreactions.append((channel, ts, name))

    def ensure_channel(self, name):
        if self.fail_create:
            raise RuntimeError("no scope")
        self.created.append(name)
        return f"C-{name}"


class FakeHerdr:
    def __init__(self, agents, screen="", fail_on=None, labels=None):
        self.agents = agents
        self.screen = screen
        self.fail_on = fail_on
        self.labels = labels or {"w": "proj"}
        self.calls = []

    def _rec(self, name, *args):
        if name == self.fail_on:
            raise HerdrError("agent_blocked")
        self.calls.append((name, *args))

    def calls_of(self, name):
        return [c for c in self.calls if c[0] == name]

    def list_agents(self):
        return list(self.agents)

    def workspace_labels(self):
        return dict(self.labels)

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
        self.labels["w9"] = label
        return "w9:p1"

    def start_agent(self, name, kind, pane_id):
        self._rec("start_agent", name, kind, pane_id)
        self.agents.append(agent(pane=pane_id, terminal="t9", kind=kind, ws="w9"))


def run_now(delay, fn):
    fn()


def make_bridge(tmp_path, agents=(), screen="", fail_on=None, projects_root=None, fail_create=False, schedule=run_now):
    herdr = FakeHerdr(list(agents), screen, fail_on)
    slack = FakeSlack(fail_create)
    store = ThreadStore(tmp_path / "threads.json")
    channels = ChannelMap(tmp_path / "channels.json")
    b = Bridge(herdr, store, channels, slack, "C-default", projects_root or tmp_path / "projects",
               claude_projects_dir=tmp_path / "claude", schedule=schedule)
    return b, herdr, slack, store, channels


# --- 알림 ---

def test_done_event_creates_workspace_channel_and_posts_there(tmp_path):
    b, herdr, slack, store, channels = make_bridge(tmp_path, agents=[agent(status="done")])
    b.on_status_event("p", "done")
    assert slack.created == ["herdr-proj"]
    [p] = slack.posts
    assert p.channel == "C-herdr-proj" and p.thread_ts is None
    assert store.get(p.ts) == PaneRef("p", "t1")
    assert channels.last_of("w") == PaneRef("p", "t1")


def test_second_event_reuses_channel(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done")])
    b.on_status_event("p", "done")
    b.on_status_event("p", "working")
    b.on_status_event("p", "done")
    assert slack.created == ["herdr-proj"] and len(slack.posts) == 2


def test_channel_create_failure_falls_back_to_default(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done")], fail_create=True)
    b.on_status_event("p", "done")
    assert slack.posts[0].channel == "C-default"


def test_repeated_done_event_posts_once(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done")])
    b.on_status_event("p", "done")
    b.on_status_event("p", "done")
    assert len(slack.posts) == 1


def test_idle_event_posts_nothing(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="idle")])
    b.on_status_event("p", "idle")
    assert slack.posts == []


def test_event_for_unknown_pane_posts_nothing(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[])
    b.on_status_event("p", "done")
    assert slack.posts == []


def test_done_uses_claude_session_text(tmp_path):
    f = tmp_path / "claude" / "C--p" / "sid.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"세션 응답"}]}}\n', encoding="utf-8")
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done", session_id="sid")], screen="● 화면 응답")
    b.on_status_event("p", "done")
    assert "세션 응답" in str(slack.posts[0].blocks) and "화면 응답" not in str(slack.posts[0].blocks)


def test_blocked_event_has_choices(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="blocked")], screen="Proceed?\n❯ 1. Yes\n  2. No\n")
    b.on_status_event("p", "blocked")
    assert action_ids(slack.posts[0].blocks) == ["choice_1", "choice_2", "esc", "screen"]


def test_failing_body_still_posts_headline(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="done")])

    def bad_read(pane_id, lines=120):
        raise RuntimeError("bad")
    herdr.read = bad_read
    b.on_status_event("p", "done")
    assert len(slack.posts) == 1 and store.get(slack.posts[0].ts)


# --- 채널 메시지 ---

def two_agents():
    return [agent(pane="w:p1", terminal="t1", kind="claude", status="idle"),
            agent(pane="w:p2", terminal="t2", kind="codex", status="idle")]


def test_channel_message_goes_to_last_notified_pane(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=two_agents())
    channels.set_channel("w", "C1")
    channels.set_last("w", PaneRef("w:p2", "t2"))
    b.handle_message("C1", "50.0", "다음 작업")
    assert herdr.calls[-1] == ("prompt", "w:p2", "다음 작업")
    assert ("C1", "50.0", "white_check_mark") in slack.reactions


def test_channel_message_with_kind_prefix_targets_that_agent(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=two_agents())
    channels.set_channel("w", "C1")
    channels.set_last("w", PaneRef("w:p2", "t2"))
    b.handle_message("C1", "50.0", "claude: 리뷰해줘")
    assert herdr.calls[-1] == ("prompt", "w:p1", "리뷰해줘")
    assert channels.last_of("w") == PaneRef("w:p1", "t1")


def test_single_agent_without_last_is_default_target(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="idle")])
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "hi")
    assert herdr.calls[-1] == ("prompt", "w:p1", "hi")


def test_ambiguous_target_asks_for_prefix(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=two_agents())
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "hi")
    assert herdr.calls == [] and "claude:" in slack.posts[-1].text and slack.posts[-1].channel == "C1"


def test_message_in_unmapped_channel_is_ignored(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=two_agents())
    b.handle_message("C-other", "50.0", "hi")
    assert herdr.calls == [] and slack.posts == []


def test_channel_message_when_working_posts_busy_notice(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="working")])
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "다음 작업")
    assert herdr.calls_of("prompt") == []
    assert slack.posts[-1].channel == "C1" and slack.posts[-1].thread_ts is None
    assert "force_send" in action_ids(slack.posts[-1].blocks)


def test_force_send_prompts_pending_text(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="working")])
    channels.set_channel("w", "C1")
    long_text = "x" * 3000
    b.handle_message("C1", "50.0", long_text)
    [btn] = [e for blk in slack.posts[-1].blocks if blk["type"] == "actions" for e in blk["elements"]]
    assert len(btn["value"]) < 100
    b.handle_action("C1", slack.posts[-1].ts, "force_send", btn["value"])
    assert herdr.calls[-1] == ("prompt", "w:p1", long_text)


def test_force_send_unknown_key_reports_expired(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="working")])
    b.handle_action("C1", "9.0", "force_send", "nope")
    assert herdr.calls == [] and "만료" in slack.posts[-1].text


def test_channel_message_when_blocked_sends_key(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="blocked")])
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "1")
    assert herdr.calls[-1] == ("send_keys", "w:p1", ["1"])


def test_last_pane_with_changed_terminal_is_not_used(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=two_agents())
    channels.set_channel("w", "C1")
    channels.set_last("w", PaneRef("w:p2", "old"))
    b.handle_message("C1", "50.0", "hi")
    assert herdr.calls == [] and "claude:" in slack.posts[-1].text


def test_thread_reply_still_routes_to_notification_pane(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="idle")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_message("C1", "50.0", "다음 작업", thread_ts="9.0")
    assert herdr.calls[-1] == ("prompt", "p", "다음 작업")


def test_thread_reply_rejected_when_terminal_changed(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="idle", terminal="t2")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_message("C1", "50.0", "hi", thread_ts="9.0")
    assert herdr.calls_of("prompt") == [] and "더 이상 없음" in slack.posts[-1].text


def test_message_reports_herdr_error(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="idle")], fail_on="prompt")
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "hi")
    assert slack.posts[-1].text.startswith("⚠️ herdr 오류")


def test_message_reports_internal_error(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="idle")])
    channels.set_channel("w", "C1")

    def boom(*a):
        raise RuntimeError("x")
    herdr.prompt = boom
    b.handle_message("C1", "50.0", "hi")
    assert "내부 오류" in slack.posts[-1].text


# --- 버튼 ---

def test_action_choice_sends_key_and_reacts(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="blocked")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("C1", "9.0", "choice_2", "p")
    assert herdr.calls[-1] == ("send_keys", "p", ["2"])
    assert ("C1", "9.0", "white_check_mark") in slack.reactions


def test_action_esc_sends_esc(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="blocked")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("C1", "9.0", "esc", "p")
    assert herdr.calls[-1] == ("send_keys", "p", ["esc"])


def test_action_full_posts_split_response_in_thread(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="idle")], screen="● " + "a" * 5000)
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("C1", "9.0", "full", "p")
    assert len(slack.posts) == 2 and all(p.thread_ts == "9.0" and p.channel == "C1" for p in slack.posts)


def test_action_screen_splits_long_screen(tmp_path):
    screen = "\n".join("y" * 500 for _ in range(60))
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="idle")], screen=screen)
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("C1", "9.0", "screen", "p")
    sections = [blk["text"]["text"] for p in slack.posts for blk in p.blocks if blk["type"] == "section"]
    assert len(slack.posts) > 1 and all(len(t) <= 3000 for t in sections)


def test_action_rejected_when_terminal_changed(tmp_path):
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="blocked", terminal="t2")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_action("C1", "9.0", "esc", "p")
    assert herdr.calls == [] and "더 이상 없음" in slack.posts[-1].text


# --- 새 에이전트 ---

def test_start_new_creates_folder_workspace_agent_channel_and_prompt(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, projects_root=tmp_path)
    b.start_new("idea", "codex", "구상하자")
    assert (tmp_path / "idea").is_dir()
    assert [c[0] for c in herdr.calls] == ["create_workspace", "start_agent", "prompt"]
    assert herdr.calls[1] == ("start_agent", "idea", "codex", "w9:p1")
    assert channels.channel_of("w9") == "C-herdr-idea"
    assert channels.last_of("w9") == PaneRef("w9:p1", "t9")
    assert slack.posts[-1].channel == "C-herdr-idea"


def test_start_new_rejects_existing_folder(tmp_path):
    (tmp_path / "idea").mkdir()
    b, *_ = make_bridge(tmp_path, projects_root=tmp_path)
    with pytest.raises(ValueError):
        b.start_new("idea", "claude", "")


def test_start_new_rejects_bad_name(tmp_path):
    b, *_ = make_bridge(tmp_path, projects_root=tmp_path)
    with pytest.raises(ValueError):
        b.start_new("Bad Name", "claude", "")


def test_start_new_failure_removes_empty_folder(tmp_path):
    b, *_ = make_bridge(tmp_path, projects_root=tmp_path, fail_on="start_agent")
    with pytest.raises(HerdrError):
        b.start_new("idea", "claude", "")
    assert not (tmp_path / "idea").exists()


# --- 알림 대기와 진행 표시 ---

def test_resume_within_delay_cancels_notification(tmp_path):
    timers = []
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done")],
                                        schedule=lambda d, fn: timers.append(fn))
    b.on_status_event("p", "working")
    b.on_status_event("p", "done")
    b.on_status_event("p", "working")
    for fn in timers:
        fn()
    assert slack.posts == []


def test_notification_fires_after_delay_when_still_done(tmp_path):
    timers = []
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done")],
                                        schedule=lambda d, fn: timers.append((d, fn)))
    b.on_status_event("p", "working")
    b.on_status_event("p", "done")
    [(delay, fn)] = timers
    assert delay == 15
    fn()
    assert len(slack.posts) == 1


def test_working_to_idle_notifies(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="idle")])
    b.on_status_event("p", "working")
    b.on_status_event("p", "idle")
    assert len(slack.posts) == 1


def test_sent_message_shows_hourglass_until_completion(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="idle")])
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "작업해줘")
    assert ("C1", "50.0", "white_check_mark") in slack.reactions
    assert ("C1", "50.0", "hourglass_flowing_sand") in slack.reactions
    b.on_status_event("w:p1", "working")
    assert slack.unreactions == []
    b.on_status_event("w:p1", "idle")
    assert slack.unreactions == [("C1", "50.0", "hourglass_flowing_sand")]


def test_hourglass_removed_on_blocked(tmp_path):
    b, herdr, slack, _, channels = make_bridge(tmp_path, agents=[agent(pane="w:p1", status="idle")])
    channels.set_channel("w", "C1")
    b.handle_message("C1", "50.0", "작업해줘")
    b.on_status_event("w:p1", "working")
    b.on_status_event("w:p1", "blocked")
    assert slack.unreactions == [("C1", "50.0", "hourglass_flowing_sand")]


def test_claude_stale_session_uses_newest_transcript_in_cwd(tmp_path):
    f = tmp_path / "claude" / "C--p-clips" / "real.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"최신 응답"}]}}\n', encoding="utf-8")
    a = agent(status="done", session_id="stale", cwd="C:/p/clips")
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[a], screen="● 화면 응답")
    b.on_status_event("p", "done")
    assert "최신 응답" in str(slack.posts[0].blocks)


def test_claude_session_response_is_sent_as_markdown(tmp_path):
    f = tmp_path / "claude" / "C--p" / "sid.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"**응답**"}]}}' + chr(10), encoding="utf-8")
    b, herdr, slack, store, _ = make_bridge(tmp_path, agents=[agent(status="done", session_id="sid")])
    b.on_status_event("p", "done")
    assert {"type": "markdown", "text": "**응답**"} in slack.posts[0].blocks
    b.handle_action("C-herdr-proj", slack.posts[0].ts, "full", "p")
    assert slack.posts[-1].blocks == [{"type": "markdown", "text": "**응답**"}]


def test_screen_response_stays_code_block(tmp_path):
    b, herdr, slack, _, _ = make_bridge(tmp_path, agents=[agent(status="done", kind="codex")], screen="• 화면 응답")
    b.on_status_event("p", "done")
    assert not [blk for blk in slack.posts[0].blocks if blk["type"] == "markdown"]
