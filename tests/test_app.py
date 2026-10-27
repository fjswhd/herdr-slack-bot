from herdr_slack.app import parse_env


def test_parse_env_reads_key_values_and_skips_comments():
    text = "# comment\nSLACK_BOT_TOKEN=xoxb-1\n\nPROJECTS_ROOT = C:\\p \nBAD LINE\n"
    assert parse_env(text) == {"SLACK_BOT_TOKEN": "xoxb-1", "PROJECTS_ROOT": "C:\\p"}
