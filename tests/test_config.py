from pathlib import Path

import pytest

from herdr_slack.config import load_config


def test_load_config_defaults_projects_root():
    env = {"SLACK_BOT_TOKEN": "xoxb", "SLACK_APP_TOKEN": "xapp",
           "SLACK_CHANNEL_ID": "C1", "SLACK_USER_ID": "U1"}
    cfg = load_config(env)
    assert cfg.projects_root == Path(r"C:\Users\jmlee\projects\jmlee")


def test_load_config_missing_key_names_it():
    with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
        load_config({"SLACK_BOT_TOKEN": "x", "SLACK_CHANNEL_ID": "C", "SLACK_USER_ID": "U"})
