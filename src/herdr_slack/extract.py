import json
import re
from dataclasses import dataclass
from pathlib import Path

# 에이전트별 응답 시작 표시와 끝 판단. 표시는 들여쓰기 없이 줄 맨 앞에 있을 때만 인정(중첩 목록과 구분).
_START = {"claude": "● ", "codex": "• "}
_END = {
    "claude": lambda line: line.startswith(("✻ ", "❯")),
    "codex": lambda line: "Worked for" in line or line.startswith("›"),
}
_CHOICE = re.compile(r"^\s*(?:[❯›>]\s*)?(\d)\.\s+(.+?)\s*$")


@dataclass(frozen=True)
class Choice:
    key: str
    label: str


def _trim(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def last_response_from_screen(kind: str, screen: str) -> str | None:
    start, is_end = _START.get(kind), _END.get(kind)
    if start is None:
        return None
    lines = screen.splitlines()
    begin = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].startswith(start)), None)
    if begin is None:
        return None
    end = next((i for i in range(begin + 1, len(lines)) if is_end(lines[i])), len(lines))
    return _trim(lines[begin:end]) or None


def last_response_from_claude_session(path: Path) -> str | None:
    result = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            texts = [c["text"] for c in content if c.get("type") == "text"]
            if texts:
                result = "\n".join(texts)
    return result


def find_claude_session(session_id: str, projects_dir: Path = Path.home() / ".claude" / "projects") -> Path | None:
    return next(projects_dir.glob(f"*/{session_id}.jsonl"), None)


def choices_from_screen(screen: str) -> list[Choice]:
    groups: list[list[Choice]] = []
    for line in screen.splitlines()[-30:]:
        m = _CHOICE.match(line)
        if not m:
            continue
        choice = Choice(m.group(1), m.group(2))
        if not groups or any(c.key == choice.key for c in groups[-1]):
            groups.append([])
        groups[-1].append(choice)
    return groups[-1] if groups else []


def tail(screen: str, n: int = 40) -> str:
    lines = [line.rstrip() for line in screen.rstrip().splitlines()]
    return "\n".join(lines[-n:])
