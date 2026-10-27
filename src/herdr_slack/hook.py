"""herdr 플러그인 이벤트 훅. pane 상태 변화 1건을 실행 중인 봇에 넘기고 바로 끝남."""

import json
import os
import socket
from datetime import datetime
from pathlib import Path

from herdr_slack.config import DEFAULT_EVENT_PORT, read_env_file

EVENT_LOG_MAX_BYTES = 200_000


def parse_event(raw: str) -> tuple[str, str] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    for d in (data, data.get("data"), data.get("payload"), data.get("event")):
        if isinstance(d, dict) and d.get("pane_id") and d.get("agent_status"):
            return d["pane_id"], d["agent_status"]
    return None


def forward(port: int, pane_id: str, status: str) -> bool:
    line = json.dumps({"pane_id": pane_id, "agent_status": status}) + "\n"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
            s.sendall(line.encode())
        return True
    except OSError:
        return False


def _log(raw: str, result: str) -> None:
    # 이벤트 형식 확인과 문제 추적용. 일정 크기를 넘으면 새로 시작.
    state = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if not state:
        return
    path = Path(state) / "events.log"
    if path.exists() and path.stat().st_size > EVENT_LOG_MAX_BYTES:
        path.unlink()
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {result} {raw}\n")


def main() -> None:
    raw = os.environ.get("HERDR_PLUGIN_EVENT_JSON", "")
    port = int(read_env_file().get("HERDR_SLACK_PORT") or DEFAULT_EVENT_PORT)
    parsed = parse_event(raw)
    if parsed is None:
        _log(raw, "skip")
        return
    _log(raw, "sent" if forward(port, *parsed) else "bot-down")


if __name__ == "__main__":
    main()
