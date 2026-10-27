import json
import logging
import socketserver
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


def serve(port: int, on_event: Callable[[str, str], None]) -> socketserver.ThreadingTCPServer:
    """플러그인 훅이 보내는 상태 변화 줄(JSON)을 받는 서버를 백그라운드로 시작. 이 PC 안(127.0.0.1)에서만 접속 가능."""

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile:
                try:
                    msg = json.loads(line)
                    on_event(msg["pane_id"], msg["agent_status"])
                except Exception:
                    log.exception("훅 이벤트 처리 실패: %r", line[:200])

    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
