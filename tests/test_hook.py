import json
import socket
import threading

from herdr_slack.hook import forward, parse_event
from herdr_slack.listener import serve


def test_parse_event_top_level_fields():
    raw = json.dumps({"pane_id": "w:p1", "workspace_id": "w", "agent_status": "done"})
    assert parse_event(raw) == ("w:p1", "done")


def test_parse_event_nested_data():
    raw = json.dumps({"event": "pane.agent_status_changed", "data": {"pane_id": "w:p1", "agent_status": "blocked"}})
    assert parse_event(raw) == ("w:p1", "blocked")


def test_parse_event_missing_fields_is_none():
    assert parse_event(json.dumps({"event": "x"})) is None
    assert parse_event("not json") is None


def test_forward_reaches_listener():
    got = []
    done = threading.Event()

    def on_event(pane_id, status):
        got.append((pane_id, status))
        done.set()

    server = serve(0, on_event)
    port = server.server_address[1]
    try:
        assert forward(port, "w:p1", "done") is True
        assert done.wait(2)
        assert got == [("w:p1", "done")]
    finally:
        server.shutdown()
        server.server_close()


def test_forward_without_listener_returns_false():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert forward(port, "w:p1", "done") is False


def test_parse_event_real_herdr_shape():
    # herdr 0.9.5 플러그인 훅이 실제로 넘긴 HERDR_PLUGIN_EVENT_JSON
    raw = ('{"event":"pane_agent_status_changed","data":{"type":"pane_agent_status_changed",'
           '"pane_id":"wN7:p1","workspace_id":"wN7","agent_status":"done","agent":"claude"}}')
    assert parse_event(raw) == ("wN7:p1", "done")
