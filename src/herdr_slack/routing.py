from dataclasses import dataclass

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


def interpret(status: str, text: str) -> Prompt | Keys | TextEnter | Busy:
    if status == "working":
        return Busy(text)
    if status == "blocked":
        key = text.strip().lower()
        return Keys([key]) if key in KEY_NAMES else TextEnter(text)
    return Prompt(text)
