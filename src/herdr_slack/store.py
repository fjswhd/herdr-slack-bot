import json
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_ENTRIES = 500


@dataclass
class PaneRef:
    pane_id: str
    terminal_id: str


class ThreadStore:
    """Slack 알림 메시지 ts → pane 연결. 봇 재시작 후에도 옛 알림 스레드 답장이 동작하도록 파일에 저장."""

    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def put(self, ts: str, ref: PaneRef) -> None:
        self._data[ts] = asdict(ref)
        while len(self._data) > MAX_ENTRIES:
            del self._data[next(iter(self._data))]
        self._path.write_text(json.dumps(self._data), encoding="utf-8")

    def get(self, ts: str) -> PaneRef | None:
        d = self._data.get(ts)
        return PaneRef(**d) if d else None
