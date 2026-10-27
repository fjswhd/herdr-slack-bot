import re
from dataclasses import dataclass

_SLACK_LINK = re.compile(r"<([^<>|]+)(?:\|[^<>]*)?>")

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


def interpret(status: str, text: str) -> Prompt | Keys | TextEnter | Busy:
    if status == "working":
        return Busy(text)
    if status == "blocked":
        key = text.strip().lower()
        return Keys([key]) if key in KEY_NAMES else TextEnter(text)
    return Prompt(text)
