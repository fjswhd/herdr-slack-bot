import logging
import re
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from herdr_slack import blocks
from herdr_slack.channels import ChannelMap, channel_name
from herdr_slack.detect import Event, event_kind
from herdr_slack.extract import (
    choices_from_screen,
    find_claude_session,
    last_response_from_claude_session,
    last_response_from_screen,
    tail,
)
from herdr_slack.herdr import Agent, Herdr, HerdrError
from herdr_slack.routing import Busy, Keys, Prompt, TextEnter, interpret, split_target
from herdr_slack.store import PaneRef, ThreadStore

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")  # herdr 에이전트 이름 규칙과 동일
ERROR_CHARS = 1000
SENT = "white_check_mark"
WORKING = "hourglass_flowing_sand"
NOTIFY_DELAY = 15  # 끝난 뒤 이 시간 안에 다시 작업을 시작하면 알리지 않음(백그라운드 작업 대기 후 재개 등)
GONE = "이 pane은 더 이상 없음. `/herdr list`로 확인해 주세요."

log = logging.getLogger(__name__)


class Slack(Protocol):
    def post(self, channel: str, blocks: list[dict], text: str, thread_ts: str | None = None) -> str: ...
    def react(self, channel: str, ts: str, name: str) -> None: ...
    def unreact(self, channel: str, ts: str, name: str) -> None: ...
    def ensure_channel(self, name: str) -> str: ...


def _start_timer(delay: float, fn: Callable[[], None]) -> None:
    t = threading.Timer(delay, fn)
    t.daemon = True
    t.start()


def _text_blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


class Bridge:
    def __init__(self, herdr: Herdr, store: ThreadStore, channels: ChannelMap, slack: Slack,
                 default_channel: str, projects_root: Path,
                 claude_projects_dir: Path = Path.home() / ".claude" / "projects",
                 schedule: Callable[[float, Callable[[], None]], None] | None = None):
        self._herdr = herdr
        self._store = store
        self._channels = channels
        self._slack = slack
        self._default_channel = default_channel
        self._projects_root = projects_root
        self._claude_dir = claude_projects_dir
        self._last: dict[str, str] = {}  # pane별 마지막으로 받은 상태
        self._lock = threading.Lock()  # 훅 이벤트가 여러 연결에서 동시에 들어옴
        self._pending: dict[str, tuple[PaneRef, str]] = {}  # [그래도 보내기]용 보류 답장. 키 → (pane, 원문)
        self._gen: dict[str, int] = {}  # pane별 상태 변화 횟수. 대기 중인 알림이 아직 유효한지 판단
        self._waiting: dict[str, tuple[str, str]] = {}  # ⏳ 반응을 단 사용자 메시지. pane → (채널, ts)
        self._schedule = schedule or _start_timer
        self._notified: dict[str, str] = {}  # pane별 마지막으로 알린 응답. 같은 응답 반복 알림 방지

    # --- Slack 출력 ---

    def _say(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        return self._slack.post(channel, _text_blocks(text), text, thread_ts)

    def _say_code(self, channel: str, thread_ts: str, text: str) -> None:
        for part in blocks.split_text(text):
            self._slack.post(channel, _text_blocks(f"```{part}```"), part[:100], thread_ts)

    def _report(self, channel: str, thread_ts: str | None, err: Exception) -> None:
        if isinstance(err, HerdrError):
            self._say(channel, f"⚠️ herdr 오류: {str(err)[:ERROR_CHARS]}", thread_ts)
            return
        log.exception("처리 실패")
        try:
            self._say(channel, f"⚠️ 내부 오류: {type(err).__name__}. 로그를 확인해 주세요.", thread_ts)
        except Exception:
            log.exception("오류 안내 게시 실패")

    def _channel_for(self, workspace_id: str) -> str:
        """workspace 채널. 없으면 만들고, 만들 수 없으면 기본 채널."""
        channel = self._channels.channel_of(workspace_id)
        if channel:
            return channel
        try:
            label = self._herdr.workspace_labels().get(workspace_id, "")
            channel = self._slack.ensure_channel(channel_name(label, workspace_id))
        except Exception:
            log.exception("workspace 채널 생성 실패: %s", workspace_id)
            return self._default_channel
        self._channels.set_channel(workspace_id, channel)
        return channel

    # --- 알림 ---

    def _response(self, a: Agent, screen: str) -> tuple[str, bool] | None:
        """마지막 응답과 Markdown 여부. 대화 기록의 응답은 Markdown, 화면에서 잘라낸 텍스트는 아님.

        Claude 대화 기록에 마지막 입력 뒤 응답이 없으면(Esc로 중단 등) None.
        """
        if a.kind == "claude":
            path = find_claude_session(a.session_id or "", self._claude_dir, a.cwd)
            if path:
                text = last_response_from_claude_session(path)
                return (text, True) if text else None
        return last_response_from_screen(a.kind, screen) or tail(screen), False

    def on_status_event(self, pane_id: str, status: str) -> None:
        """herdr 플러그인 훅이 전달한 pane 상태 변화 1건 처리."""
        with self._lock:
            kind = event_kind(self._last.get(pane_id), status)
            self._last[pane_id] = status
            gen = self._gen[pane_id] = self._gen.get(pane_id, 0) + 1
        if kind is not None:
            self._schedule(NOTIFY_DELAY, lambda: self._fire(pane_id, kind, gen))

    def _fire(self, pane_id: str, kind: str, gen: int) -> None:
        with self._lock:
            if self._gen.get(pane_id) != gen:
                return  # 기다리는 동안 상태가 다시 바뀜
            waiting = self._waiting.pop(pane_id, None)
        try:
            if waiting:
                self._slack.unreact(*waiting, WORKING)
            a = next((a for a in self._herdr.list_agents() if a.pane_id == pane_id), None)
            if a is not None:
                self._notify(Event(kind, a))
        except Exception:
            log.exception("알림 처리 실패: %s", pane_id)

    def _notify(self, e: Event) -> None:
        a = e.agent
        try:
            screen = self._herdr.read(a.pane_id)
            if e.kind == "blocked":
                body, choices, md = tail(screen, 25), choices_from_screen(screen), False
            else:
                response = self._response(a, screen)
                # 새 응답이 없거나(중단) 직전에 알린 응답과 같으면 이전 응답이 새 답처럼 보이므로 알리지 않음
                if response is None or self._notified.get(a.pane_id) == response[0]:
                    return
                (body, md), choices = response, []
                self._notified[a.pane_id] = body
            note = blocks.notification(e, body, choices, markdown=md)
        except Exception:
            # 본문을 만들지 못해도 알림 자체는 보냄. 내용은 [화면 보기]로 확인.
            log.exception("알림 본문 생성 실패: %s", a.pane_id)
            note = blocks.notification(e, "(본문을 읽지 못함)", [])
        ref = PaneRef(a.pane_id, a.terminal_id)
        try:
            ts = self._slack.post(self._channel_for(a.workspace_id), note, blocks.headline(e), None)
        except Exception:
            log.exception("알림 게시 실패: %s", a.pane_id)
            return
        self._store.put(ts, ref)
        self._channels.set_last(a.workspace_id, ref)

    # --- 사용자 입력 ---

    def _live(self, ref: PaneRef | None, agents: list[Agent]) -> Agent | None:
        """기록된 pane이 아직 같은 터미널일 때만 그 Agent."""
        if ref is None:
            return None
        return next((a for a in agents if a.pane_id == ref.pane_id and a.terminal_id == ref.terminal_id), None)

    def _pick_target(self, channel: str, text: str) -> tuple[Agent | None, str]:
        """채널 메시지의 대상 에이전트와 보낼 본문. 정할 수 없으면 채널에 안내하고 None."""
        ws = self._channels.workspace_of(channel)
        if ws is None:
            return None, text
        agents = [a for a in self._herdr.list_agents() if a.workspace_id == ws]
        if not agents:
            self._say(channel, "이 workspace에 연결된 에이전트가 없음. `/herdr list`로 확인해 주세요.")
            return None, text
        kind, body = split_target(text, {a.kind for a in agents})
        if kind:
            same = [a for a in agents if a.kind == kind]
            if len(same) > 1:
                self._say(channel, f"`{kind}` 에이전트가 {len(same)}개라 대상을 정할 수 없음.")
                return None, text
            self._channels.set_last(ws, PaneRef(same[0].pane_id, same[0].terminal_id))
            return same[0], body
        target = self._live(self._channels.last_of(ws), agents)
        if target is None and len(agents) == 1:
            target = agents[0]
        if target is None:
            names = ", ".join(f"`{a.kind}:`" for a in agents)
            self._say(channel, f"어느 에이전트에게 보낼지 앞에 이름을 붙여 주세요: {names}")
        return target, body

    def handle_message(self, channel: str, ts: str, text: str, thread_ts: str | None = None) -> None:
        try:
            if thread_ts:
                ref = self._store.get(thread_ts)
                if ref is None:
                    return
                a = self._live(ref, self._herdr.list_agents())
                if a is None:
                    self._say(channel, GONE, thread_ts)
                    return
            else:
                a, text = self._pick_target(channel, text)
                if a is None:
                    return
            action = interpret(a.status, text)
            match action:
                case Busy():
                    key = uuid.uuid4().hex[:12]
                    self._pending[key] = (PaneRef(a.pane_id, a.terminal_id), text)
                    self._slack.post(channel, blocks.busy_notice(key), "지금 작업 중", thread_ts)
                    return
                case Prompt():
                    self._herdr.prompt(a.pane_id, action.text)
                case Keys():
                    self._herdr.send_keys(a.pane_id, action.keys)
                case TextEnter():
                    self._herdr.send_text_enter(a.pane_id, action.text)
            self._mark_sent(a.pane_id, channel, ts)
        except Exception as err:
            self._report(channel, thread_ts, err)

    def handle_action(self, channel: str, message_ts: str, action_id: str, value: str) -> None:
        """버튼 처리. 알림 버튼은 그 알림의 pane, [그래도 보내기]는 보류해 둔 pane이 대상."""
        try:
            if action_id == "force_send":
                pending = self._pending.pop(value, None)
                if pending is None:
                    self._say(channel, "보류한 답장이 만료됨(봇 재시작 등). 다시 보내 주세요.", message_ts)
                    return
                ref, text = pending
            else:
                ref, text = self._store.get(message_ts), ""
                if ref is None:
                    return
            a = self._live(ref, self._herdr.list_agents())
            if a is None:
                self._say(channel, GONE, message_ts)
                return
            if action_id == "full":
                text, md = self._response(a, self._herdr.read(a.pane_id)) or ("(새 응답 없음)", False)
                if md:
                    for part in blocks.split_text(text, blocks.MARKDOWN_PART_CHARS):
                        self._slack.post(channel, [blocks.markdown_block(part)], part[:100], message_ts)
                else:
                    self._say_code(channel, message_ts, text)
                return
            if action_id == "screen":
                self._say_code(channel, message_ts, tail(self._herdr.read(a.pane_id), 60))
                return
            if action_id == "esc":
                self._herdr.send_keys(a.pane_id, ["esc"])
            elif action_id.startswith("choice_"):
                self._herdr.send_keys(a.pane_id, [action_id.removeprefix("choice_")])
            elif action_id == "force_send":
                self._herdr.prompt(a.pane_id, text)
            self._mark_sent(a.pane_id, channel, message_ts)
        except Exception as err:
            self._report(channel, message_ts, err)

    def _mark_sent(self, pane_id: str, channel: str, ts: str) -> None:
        """전달 완료 ✅, 에이전트가 다시 멈출 때까지 ⏳."""
        self._slack.react(channel, ts, SENT)
        self._slack.react(channel, ts, WORKING)
        with self._lock:
            previous = self._waiting.get(pane_id)
            self._waiting[pane_id] = (channel, ts)
        if previous and previous != (channel, ts):
            self._slack.unreact(*previous, WORKING)

    # --- 새 에이전트 ---

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
        ws = pane_id.split(":")[0]
        channel = self._channel_for(ws)
        a = next((a for a in self._herdr.list_agents() if a.pane_id == pane_id), None)
        if a is not None:
            self._channels.set_last(ws, PaneRef(a.pane_id, a.terminal_id))
        self._say(channel, f"`{name}` 시작 ({kind}, `{folder}`). 이 채널에 메시지를 쓰면 에이전트에게 전달됩니다.")
        if prompt.strip():
            self._herdr.prompt(pane_id, prompt)
        return f"`{name}` 시작 ({kind}) → <#{channel}>"
