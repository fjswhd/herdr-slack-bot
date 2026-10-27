from herdr_slack.detect import event_kind


def test_into_done_is_done():
    assert event_kind("working", "done") == "done"


def test_into_done_without_known_previous_is_done():
    # 봇 시작 후 첫 이벤트도 상태가 바뀐 순간이므로 알림 대상
    assert event_kind(None, "done") == "done"


def test_working_to_idle_is_done():
    # PC 화면에 떠 있던 pane의 완료도 알림(알림 끄기는 휴대폰이 담당)
    assert event_kind("working", "idle") == "done"


def test_done_to_idle_is_nothing():
    # 이미 알린 완료를 PC에서 확인한 것
    assert event_kind("done", "idle") is None


def test_done_to_done_is_nothing():
    assert event_kind("done", "done") is None


def test_into_blocked_is_blocked():
    assert event_kind("working", "blocked") == "blocked"


def test_blocked_to_blocked_is_nothing():
    assert event_kind("blocked", "blocked") is None


def test_working_is_nothing():
    assert event_kind("done", "working") is None
