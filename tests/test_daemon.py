import socket

from herdr_slack.daemon import is_running, start, status, stop


def listening_socket():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_is_running_true_when_port_listens():
    s = listening_socket()
    try:
        assert is_running(s.getsockname()[1]) is True
    finally:
        s.close()


def test_is_running_false_when_nothing_listens():
    assert is_running(free_port()) is False


def test_start_skips_when_already_running(tmp_path):
    s = listening_socket()
    spawned = []
    try:
        msg = start(s.getsockname()[1], tmp_path / "bot.pid", spawn=lambda: spawned.append(1) or 123)
    finally:
        s.close()
    assert spawned == [] and "이미 실행 중" in msg


def test_start_spawns_writes_pid_and_waits_for_port(tmp_path):
    port = free_port()
    holder = {}

    def spawn():
        holder["s"] = s = socket.socket()
        s.bind(("127.0.0.1", port))
        s.listen()
        return 4242

    try:
        msg = start(port, tmp_path / "bot.pid", spawn=spawn, timeout=2)
    finally:
        holder["s"].close()
    assert (tmp_path / "bot.pid").read_text() == "4242" and "시작" in msg


def test_start_reports_failure_when_port_never_opens(tmp_path):
    msg = start(free_port(), tmp_path / "bot.pid", spawn=lambda: 1, timeout=0.3)
    assert "실패" in msg


def test_stop_kills_pid_and_removes_file(tmp_path):
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("4242")
    killed = []
    msg = stop(pid_file, kill=killed.append)
    assert killed == [4242] and not pid_file.exists() and "중지" in msg


def test_stop_without_pid_file(tmp_path):
    assert "실행 중이 아님" in stop(tmp_path / "bot.pid", kill=lambda pid: None)


def test_status_reports_pid(tmp_path):
    s = listening_socket()
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("77")
    try:
        assert "실행 중" in status(s.getsockname()[1], pid_file) and "77" in status(s.getsockname()[1], pid_file)
    finally:
        s.close()
