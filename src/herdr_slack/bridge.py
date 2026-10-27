import logging
import re
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from herdr_slack import blocks
from herdr_slack.detect import Event, event_kind
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
ERROR_CHARS = 1000

log = logging.getLogger(__name__)


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
        self._last: dict[str, str] = {}  # pane별 마지막으로 받은 상태
        self._lock = threading.Lock()  # 훅 이벤트가 여러 연결에서 동시에 들어옴
        self._pending: dict[str, str] = {}  # [그래도 보내기]용 보류 답장. 키 → 원문

    def _say(self, thread_ts: str | None, text: str) -> str:
        return self._post(_text_blocks(text), text, thread_ts)

    def _say_code(self, thread_ts: str, text: str) -> None:
        for part in blocks.split_text(text):
            self._post(_text_blocks(f"```{part}```"), part[:100], thread_ts)

    def _report(self, thread_ts: str, err: Exception) -> None:
        if isinstance(err, HerdrError):
            self._say(thread_ts, f"⚠️ herdr 오류: {str(err)[:ERROR_CHARS]}")
            return
        log.exception("처리 실패")
        try:
            self._say(thread_ts, f"⚠️ 내부 오류: {type(err).__name__}. 로그를 확인해 주세요.")
        except Exception:
            log.exception("오류 안내 게시 실패")

    def _response(self, a: Agent, screen: str) -> str:
        if a.kind == "claude" and a.session_id:
            path = find_claude_session(a.session_id, self._claude_dir)
            text = last_response_from_claude_session(path) if path else None
            if text:
                return text
        return last_response_from_screen(a.kind, screen) or tail(screen)

    def on_status_event(self, pane_id: str, status: str) -> None:
        """herdr 플러그인 훅이 전달한 pane 상태 변화 1건 처리."""
        with self._lock:
            kind = event_kind(self._last.get(pane_id), status)
            self._last[pane_id] = status
        if kind is None:
            return
        a = next((a for a in self._herdr.list_agents() if a.pane_id == pane_id), None)
        if a is not None:
            self._notify(Event(kind, a))

    def _notify(self, e: Event) -> None:
        a = e.agent
        try:
            screen = self._herdr.read(a.pane_id)
            if e.kind == "blocked":
                body, choices = tail(screen, 25), choices_from_screen(screen)
            else:
                body, choices = self._response(a, screen), []
            note = blocks.notification(e, body, choices)
        except Exception:
            # 본문을 만들지 못해도 알림 자체는 보냄. 내용은 [화면 보기]로 확인.
            log.exception("알림 본문 생성 실패: %s", a.pane_id)
            note = blocks.notification(e, "(본문을 읽지 못함)", [])
        try:
            ts = self._post(note, blocks.headline(e), None)
        except Exception:
            log.exception("알림 게시 실패: %s", a.pane_id)
            return
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
                    key = uuid.uuid4().hex[:12]
                    self._pending[key] = text
                    self._post(blocks.busy_notice(key), "지금 작업 중", thread_ts)
                    return
                case Prompt():
                    self._herdr.prompt(a.pane_id, action.text)
                case Keys():
                    self._herdr.send_keys(a.pane_id, action.keys)
                case TextEnter():
                    self._herdr.send_text_enter(a.pane_id, action.text)
            self._say(thread_ts, "전송됨 · 작업 중")
        except Exception as err:
            self._report(thread_ts, err)

    def handle_action(self, thread_ts: str, action_id: str, value: str) -> None:
        try:
            a = self._resolve(thread_ts)
            if a is None:
                return
            if action_id == "full":
                self._say_code(thread_ts, self._response(a, self._herdr.read(a.pane_id)))
            elif action_id == "screen":
                self._say_code(thread_ts, tail(self._herdr.read(a.pane_id), 60))
            elif action_id == "esc":
                self._herdr.send_keys(a.pane_id, ["esc"])
                self._say(thread_ts, "Esc 전송됨")
            elif action_id.startswith("choice_"):
                key = action_id.removeprefix("choice_")
                self._herdr.send_keys(a.pane_id, [key])
                self._say(thread_ts, f"{key} 전송됨")
            elif action_id == "force_send":
                text = self._pending.pop(value, None)
                if text is None:
                    self._say(thread_ts, "보류한 답장이 만료됨(봇 재시작 등). 다시 답장해 주세요.")
                    return
                self._herdr.prompt(a.pane_id, text)
                self._say(thread_ts, "전송됨 · 작업 중")
        except Exception as err:
            self._report(thread_ts, err)

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
        try:
            pane_id = self._herdr.create_workspace(folder, name)
            self._herdr.start_agent(name, kind, pane_id)
        except Exception:
            # 같은 이름으로 다시 시도할 수 있게 빈 폴더는 지움
            if not any(folder.iterdir()):
                folder.rmdir()
            raise
        if prompt.strip():
            self._herdr.prompt(pane_id, prompt)
        return f"`{name}` 시작 ({kind}, `{folder}`)"
