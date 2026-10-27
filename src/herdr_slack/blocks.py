from pathlib import PureWindowsPath

from herdr_slack.detect import Event
from herdr_slack.extract import Choice
from herdr_slack.herdr import Agent

PREVIEW_CHARS = 600
BLOCKED_PREVIEW_CHARS = 1500
_HEAD = {"done": "✅ 완료", "blocked": "⚠️ 판단 필요"}
KINDS = ("claude", "codex", "gemini")


def location(a: Agent) -> str:
    return f"{PureWindowsPath(a.cwd).name} · {a.kind}"


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(text: str, action_id: str, value: str) -> dict:
    return {"type": "button", "text": {"type": "plain_text", "text": text[:75]},
            "action_id": action_id, "value": value}


def _code(text: str) -> str:
    return f"```{text}```" if text.strip() else "_(내용 없음)_"


def headline(event: Event) -> str:
    return f"{_HEAD[event.kind]} {location(event.agent)}"


def notification(event: Event, body: str, choices: list[Choice]) -> list[dict]:
    a = event.agent
    if event.kind == "blocked":
        # 질문과 선택지는 화면 맨 아래에 있으므로 끝부분을 남김
        preview = body if len(body) <= BLOCKED_PREVIEW_CHARS else "…" + body[-BLOCKED_PREVIEW_CHARS:]
    else:
        preview = body if len(body) <= PREVIEW_CHARS else body[:PREVIEW_CHARS] + "…"
    if event.kind == "blocked":
        buttons = [_button(f"{c.key} {c.label[:20]}", f"choice_{c.key}", a.pane_id) for c in choices]
        buttons += [_button("거절(Esc)", "esc", a.pane_id), _button("화면 보기", "screen", a.pane_id)]
    else:
        buttons = [_button("전체 보기", "full", a.pane_id), _button("화면 보기", "screen", a.pane_id)]
    return [
        _section(f"*{_HEAD[event.kind]}*  `{location(a)}`"),
        _section(_code(preview)),
        {"type": "actions", "elements": buttons},
    ]


def busy_notice(key: str) -> list[dict]:
    # 버튼 value는 2000자 제한이 있어 답장 원문 대신 보관 키만 담음
    return [
        _section("지금 작업 중이라 보내지 않았습니다."),
        {"type": "actions", "elements": [_button("그래도 보내기", "force_send", key)]},
    ]


def agent_list(agents: list[Agent]) -> list[dict]:
    if not agents:
        return [_section("실행 중인 에이전트가 없습니다.")]
    lines = [f"`{a.pane_id}`  {location(a)}  *{a.status}*  {a.title}".rstrip() for a in agents]
    return [_section("\n".join(lines))]


def split_text(text: str, limit: int = 2900) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit) + 1 or limit
        parts.append(text[:cut])
        text = text[cut:]
    if text:
        parts.append(text)
    return parts


def new_agent_modal() -> dict:
    options = [{"text": {"type": "plain_text", "text": k}, "value": k} for k in KINDS]
    return {
        "type": "modal",
        "callback_id": "new_agent",
        "title": {"type": "plain_text", "text": "새 에이전트"},
        "submit": {"type": "plain_text", "text": "시작"},
        "blocks": [
            {"type": "input", "block_id": "name", "label": {"type": "plain_text", "text": "폴더 이름"},
             "element": {"type": "plain_text_input", "action_id": "value"}},
            {"type": "input", "block_id": "kind", "label": {"type": "plain_text", "text": "에이전트"},
             "element": {"type": "static_select", "action_id": "value", "options": options,
                         "initial_option": options[0]}},
            {"type": "input", "block_id": "prompt", "optional": True,
             "label": {"type": "plain_text", "text": "첫 프롬프트"},
             "element": {"type": "plain_text_input", "action_id": "value", "multiline": True}},
        ],
    }
