import pytest
from slack_sdk.errors import SlackApiError

from herdr_slack.slack_ops import SlackOps


def api_error(code):
    return SlackApiError(code, {"ok": False, "error": code})


class FakeClient:
    def __init__(self, taken=False, already_in=False, already_reacted=False):
        self.calls = []
        self.taken = taken
        self.already_in = already_in
        self.already_reacted = already_reacted

    def conversations_create(self, name, is_private):
        self.calls.append(("create", name, is_private))
        if self.taken:
            raise api_error("name_taken")
        return {"channel": {"id": "C-new"}}

    def conversations_list(self, types, exclude_archived, limit, cursor=None):
        self.calls.append(("list", cursor))
        if cursor is None:
            return {"channels": [{"id": "C-a", "name": "other"}], "response_metadata": {"next_cursor": "n2"}}
        return {"channels": [{"id": "C-old", "name": "herdr-proj"}], "response_metadata": {"next_cursor": ""}}

    def conversations_join(self, channel):
        self.calls.append(("join", channel))

    def conversations_invite(self, channel, users):
        self.calls.append(("invite", channel, users))
        if self.already_in:
            raise api_error("already_in_channel")

    def reactions_add(self, channel, timestamp, name):
        self.calls.append(("react", channel, timestamp, name))
        if self.already_reacted:
            raise api_error("already_reacted")


def test_ensure_channel_creates_public_and_invites_user():
    c = FakeClient()
    assert SlackOps(c, "U1").ensure_channel("herdr-proj") == "C-new"
    assert c.calls == [("create", "herdr-proj", False), ("invite", "C-new", "U1")]


def test_ensure_channel_reuses_existing_name():
    c = FakeClient(taken=True)
    assert SlackOps(c, "U1").ensure_channel("herdr-proj") == "C-old"
    assert ("join", "C-old") in c.calls and ("invite", "C-old", "U1") in c.calls


def test_ensure_channel_ignores_already_in_channel():
    assert SlackOps(FakeClient(already_in=True), "U1").ensure_channel("herdr-proj") == "C-new"


def test_react_ignores_already_reacted():
    SlackOps(FakeClient(already_reacted=True), "U1").react("C1", "1.0", "white_check_mark")


def test_other_api_errors_propagate():
    class Broken(FakeClient):
        def conversations_create(self, name, is_private):
            raise api_error("missing_scope")
    with pytest.raises(SlackApiError):
        SlackOps(Broken(), "U1").ensure_channel("herdr-proj")
