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


def _is_user_input(entry: dict) -> bool:
    """사람이 입력한 프롬프트나 중단 표시. 도구 실행 결과만 담긴 user 항목은 제외."""
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(c.get("type") == "text" for c in content)


def last_response_from_claude_session(path: Path) -> str | None:
    """마지막 턴의 응답. 마지막 사용자 입력 뒤에 응답이 없으면(Esc로 중단 등) None."""
    result = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if _is_user_input(entry):
                result = None
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


def find_claude_session(session_id: str, projects_dir: Path = Path.home() / ".claude" / "projects",
                        cwd: str | None = None) -> Path | None:
    """세션 ID의 대화 기록. herdr가 옛 세션 ID를 들고 있어 파일이 없으면, 그 작업 폴더의 가장 최근 대화 기록."""
    exact = next(projects_dir.glob(f"*/{session_id}.jsonl"), None)
    if exact or not cwd:
        return exact
    # Claude Code는 작업 폴더 경로의 영문·숫자 외 문자를 '-'로 바꾼 이름의 폴더에 기록함
    folder = projects_dir / re.sub(r"[^A-Za-z0-9]", "-", cwd)
    return max(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, default=None)


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
