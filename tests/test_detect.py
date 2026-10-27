from herdr_slack.detect import event_kind


def test_into_done_is_done():
    assert event_kind("working", "done") == "done"


def test_into_done_without_known_previous_is_done():
    # 봇 시작 후 첫 이벤트도 상태가 바뀐 순간이므로 알림 대상
    assert event_kind(None, "done") == "done"


def test_into_idle_is_nothing():
    # idle은 사용자가 이미 본 완료
    assert event_kind("working", "idle") is None


def test_done_to_done_is_nothing():
    assert event_kind("done", "done") is None


def test_into_blocked_is_blocked():
    assert event_kind("working", "blocked") == "blocked"


def test_blocked_to_blocked_is_nothing():
    assert event_kind("blocked", "blocked") is None


def test_working_is_nothing():
    assert event_kind("done", "working") is None
