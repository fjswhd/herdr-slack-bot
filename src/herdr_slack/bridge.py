import json
import re
from collections.abc import Callable
from pathlib import Path

from herdr_slack import blocks
from herdr_slack.detect import Event, diff, next_snapshot
from herdr_slack.extract import (
    choices_from_screen,
    find_claude_session,
    last_response_from_claude_session,
    last_response_from_screen,
    tail,
)
from herdr_slack.herdr import Agent, Herdr, HerdrError
from herdr_slack.routing import Busy, Keys, Prompt, TextEnter, interpret
from herdr_slack.store import PaneRef, ThreadStore

# post(blocks, text, thread_ts) -> 게시된 메시지 ts
Post = Callable[[list[dict], str, str | None], str]

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")  # herdr 에이전트 이름 규칙과 동일


def _text_blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


class Bridge:
    def __init__(self, herdr: Herdr, store: ThreadStore, post: Post, projects_root: Path,
                 claude_projects_dir: Path = Path.home() / ".claude" / "projects"):
        self._herdr = herdr
        self._store = store
        self._post = post
        self._projects_root = projects_root
        self._claude_dir = claude_projects_dir
        self._snap: dict[str, Agent] | None = None

    def _say(self, thread_ts: str | None, text: str) -> str:
        return self._post(_text_blocks(text), text, thread_ts)

    def _response(self, a: Agent, screen: str) -> str:
        if a.kind == "claude" and a.session_id:
            path = find_claude_session(a.session_id, self._claude_dir)
            text = last_response_from_claude_session(path) if path else None
            if text:
                return text
        return last_response_from_screen(a.kind, screen) or tail(screen)

    def poll_once(self) -> None:
        agents = self._herdr.list_agents()
        events = diff(self._snap, agents)
        self._snap = next_snapshot(self._snap, agents)
        for e in events:
            self._notify(e)

    def _notify(self, e: Event) -> None:
        a = e.agent
        try:
            screen = self._herdr.read(a.pane_id)
        except HerdrError:
            screen = ""
        if e.kind == "blocked":
            body, choices = tail(screen, 25), choices_from_screen(screen)
        else:
            body, choices = self._response(a, screen), []
        ts = self._post(blocks.notification(e, body, choices), blocks.headline(e), None)
        self._store.put(ts, PaneRef(a.pane_id, a.terminal_id))

    def _resolve(self, thread_ts: str) -> Agent | None:
        """스레드가 가리키는 pane이 아직 같은 터미널일 때만 그 Agent를 돌려줌. 없으면 스레드에 안내."""
        ref = self._store.get(thread_ts)
        if ref is None:
            return None
        a = next((a for a in self._herdr.list_agents() if a.pane_id == ref.pane_id), None)
        if a is None or a.terminal_id != ref.terminal_id:
            self._say(thread_ts, "이 pane은 더 이상 없음. `/herdr list`로 확인해 주세요.")
            return None
        return a

    def handle_reply(self, thread_ts: str, text: str) -> None:
        try:
            a = self._resolve(thread_ts)
            if a is None:
                return
            action = interpret(a.status, text)
            match action:
                case Busy():
                    self._post(blocks.busy_notice(a.pane_id, text), "지금 작업 중", thread_ts)
                    return
                case Prompt():
                    self._herdr.prompt(a.pane_id, action.text)
                case Keys():
                    self._herdr.send_keys(a.pane_id, action.keys)
                case TextEnter():
                    self._herdr.send_text_enter(a.pane_id, action.text)
            self._say(thread_ts, "전송됨 · 작업 중")
        except HerdrError as err:
            self._say(thread_ts, f"⚠️ herdr 오류: {err}")

    def handle_action(self, thread_ts: str, action_id: str, value: str) -> None:
        try:
            a = self._resolve(thread_ts)
            if a is None:
                return
            if action_id == "full":
                for part in blocks.split_text(self._response(a, self._herdr.read(a.pane_id))):
                    self._post(_text_blocks(f"```{part}```"), part[:100], thread_ts)
            elif action_id == "screen":
                self._say(thread_ts, f"```{tail(self._herdr.read(a.pane_id), 60)}```")
            elif action_id == "esc":
                self._herdr.send_keys(a.pane_id, ["esc"])
                self._say(thread_ts, "Esc 전송됨")
            elif action_id.startswith("choice_"):
                key = action_id.removeprefix("choice_")
                self._herdr.send_keys(a.pane_id, [key])
                self._say(thread_ts, f"{key} 전송됨")
            elif action_id == "force_send":
                self._herdr.prompt(a.pane_id, json.loads(value)["text"])
                self._say(thread_ts, "전송됨 · 작업 중")
        except HerdrError as err:
            self._say(thread_ts, f"⚠️ herdr 오류: {err}")

    def check_new(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise ValueError("이름은 영문 소문자로 시작하고 소문자·숫자·-·_ 만 사용 (최대 32자)")
        folder = self._projects_root / name
        if folder.exists():
            raise ValueError(f"이미 있는 폴더: {folder}")
        return folder

    def start_new(self, name: str, kind: str, prompt: str) -> str:
        folder = self.check_new(name)
        folder.mkdir(parents=True)
        pane_id = self._herdr.create_workspace(folder, name)
        self._herdr.start_agent(name, kind, pane_id)
        if prompt.strip():
            self._herdr.prompt(pane_id, prompt)
        return f"`{name}` 시작 ({kind}, `{folder}`)"
