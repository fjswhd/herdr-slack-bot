import json
import re
import threading
from dataclasses import asdict
from pathlib import Path

from herdr_slack.store import PaneRef

MAX_NAME = 80  # Slack 채널 이름 길이 제한


def channel_name(label: str, workspace_id: str) -> str:
    """Slack 채널 이름 규칙(소문자·숫자·-·_)에 맞춘 workspace 채널 이름."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-")
    if not re.search(r"[a-z0-9]", slug):
        slug = workspace_id.lower()
    return f"herdr-{slug}"[:MAX_NAME]


class ChannelMap:
    """herdr workspace ↔ Slack 채널 연결과 채널별 마지막 알림 pane. 봇 재시작 후에도 유지되도록 파일에 저장."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data), encoding="utf-8")

    def set_channel(self, workspace_id: str, channel_id: str) -> None:
        with self._lock:
            self._data.setdefault(workspace_id, {})["channel"] = channel_id
            self._save()

    def set_last(self, workspace_id: str, ref: PaneRef) -> None:
        with self._lock:
            self._data.setdefault(workspace_id, {})["last"] = asdict(ref)
            self._save()

    def channel_of(self, workspace_id: str) -> str | None:
        return self._data.get(workspace_id, {}).get("channel")

    def workspace_of(self, channel_id: str) -> str | None:
        return next((ws for ws, d in self._data.items() if d.get("channel") == channel_id), None)

    def last_of(self, workspace_id: str) -> PaneRef | None:
        d = self._data.get(workspace_id, {}).get("last")
        return PaneRef.load(d) if d else None
