"""herdr 플러그인의 start·stop·status 동작. herdr가 시작될 때 봇 서버를 함께 띄우기 위함."""

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from herdr_slack.config import DEFAULT_EVENT_PORT, ROOT, read_env_file

PID_FILE = ROOT / "herdr-slack.pid"
LOG_FILE = ROOT / "herdr-slack.log"


def is_running(port: int) -> bool:
    """봇은 훅 이벤트 포트를 열고 있으므로, 그 포트가 응답하면 실행 중으로 봄."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _spawn_bot() -> int:
    # 콘솔 창 없이(pythonw), herdr 훅 프로세스와 분리해 띄움. 훅이 끝나도 봇은 계속 동작.
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    kwargs = dict(cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  close_fds=True)
    try:
        # herdr가 훅을 Windows job에 묶어 두었다면 job이 닫힐 때 같이 종료되지 않도록 빠져나옴
        proc = subprocess.Popen([str(pythonw), "-m", "herdr_slack"],
                                creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        proc = subprocess.Popen([str(pythonw), "-m", "herdr_slack"], creationflags=flags, **kwargs)
    return proc.pid


def start(port: int, pid_file: Path, spawn: Callable[[], int] = _spawn_bot, timeout: float = 15) -> str:
    if is_running(port):
        return "봇이 이미 실행 중"
    pid = spawn()
    pid_file.write_text(str(pid))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(port):
            return f"봇 시작 (pid {pid})"
        time.sleep(0.2)
    return f"봇 시작 실패: {timeout:g}초 안에 포트 {port}가 열리지 않음. {LOG_FILE} 확인"


def stop(pid_file: Path, kill: Callable[[int], None] = lambda pid: os.kill(pid, signal.SIGTERM)) -> str:
    if not pid_file.exists():
        return "봇이 실행 중이 아님(pid 파일 없음)"
    pid = int(pid_file.read_text())
    try:
        kill(pid)
    except OSError:
        pass  # 이미 종료된 프로세스
    pid_file.unlink()
    return f"봇 중지 (pid {pid})"


def status(port: int, pid_file: Path) -> str:
    pid = pid_file.read_text() if pid_file.exists() else "알 수 없음"
    return f"봇 실행 중 (pid {pid})" if is_running(port) else "봇이 실행 중이 아님"


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    port = int(read_env_file().get("HERDR_SLACK_PORT") or DEFAULT_EVENT_PORT)
    if command == "start":
        msg = start(port, PID_FILE)
    elif command == "stop":
        msg = stop(PID_FILE)
    else:
        msg = status(port, PID_FILE)
    print(msg)
    if "실패" in msg:
        sys.exit(1)


if __name__ == "__main__":
    main()
