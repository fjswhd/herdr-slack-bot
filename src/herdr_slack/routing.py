import re
from dataclasses import dataclass

_SLACK_LINK = re.compile(r"<([^<>|]+)(?:\|[^<>]*)?>")
_TARGET = re.compile(r"^\s*([a-z][a-z0-9_-]*)\s*:\s*(.*)$", re.DOTALL)

KEY_NAMES = {"esc", "escape", "enter", "tab", "up", "down", "left", "right", "ctrl+c"} | {str(d) for d in range(10)}


@dataclass
class Prompt:
    text: str


@dataclass
class Keys:
    keys: list[str]


@dataclass
class TextEnter:
    text: str


@dataclass
class Busy:
    text: str


def unescape_slack(text: str) -> str:
    """Slack이 바꿔 보낸 링크 표기와 &lt; &gt; &amp;를 사용자가 입력한 원래 글자로 되돌림."""
    text = _SLACK_LINK.sub(r"\1", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def split_target(text: str, kinds: set[str]) -> tuple[str | None, str]:
    """`codex: 내용`처럼 앞에 붙은 에이전트 이름을 떼어냄. workspace에 있는 에이전트 종류일 때만 대상 지정으로 봄."""
    m = _TARGET.match(text)
    if m and m.group(1) in kinds:
        return m.group(1), m.group(2)
    return None, text


def interpret(status: str, text: str) -> Prompt | Keys | TextEnter | Busy:
    if status == "working":
        return Busy(text)
    if status == "blocked":
        key = text.strip().lower()
        return Keys([key]) if key in KEY_NAMES else TextEnter(text)
    return Prompt(text)
