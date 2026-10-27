from herdr_slack.channels import ChannelMap, channel_name
from herdr_slack.store import PaneRef


def test_channel_name_from_label():
    assert channel_name("re-alive", "wN6") == "herdr-re-alive"


def test_channel_name_sanitizes():
    assert channel_name("My Project.v2", "wN6") == "herdr-my-project-v2"


def test_channel_name_falls_back_to_workspace_id():
    assert channel_name("한글이름", "wN6") == "herdr-wn6"


def test_channel_name_max_80():
    assert len(channel_name("a" * 200, "w1")) == 80


def test_channel_map_persists(tmp_path):
    m = ChannelMap(tmp_path / "c.json")
    m.set_channel("wN6", "C1")
    m.set_last("wN6", PaneRef("wN6:p2", "t2"))
    m2 = ChannelMap(tmp_path / "c.json")
    assert m2.channel_of("wN6") == "C1"
    assert m2.workspace_of("C1") == "wN6"
    assert m2.last_of("wN6") == PaneRef("wN6:p2", "t2")


def test_channel_map_unknown(tmp_path):
    m = ChannelMap(tmp_path / "c.json")
    assert m.channel_of("w") is None and m.workspace_of("C9") is None and m.last_of("w") is None
