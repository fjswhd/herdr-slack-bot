from herdr_slack.routing import Busy, Keys, Prompt, TextEnter, interpret


def test_interpret_idle_is_prompt():
    assert interpret("idle", "next") == Prompt("next")


def test_interpret_done_is_prompt():
    assert interpret("done", "next") == Prompt("next")


def test_interpret_working_is_busy():
    assert interpret("working", "next") == Busy("next")


def test_interpret_blocked_key_name():
    assert interpret("blocked", " ESC ") == Keys(["esc"])


def test_interpret_blocked_digit():
    assert interpret("blocked", "2") == Keys(["2"])


def test_interpret_blocked_sentence_is_text_enter():
    assert interpret("blocked", "use option b") == TextEnter("use option b")


def test_unescape_slack_restores_symbols_and_links():
    from herdr_slack.routing import unescape_slack
    assert unescape_slack("if a &lt; b &amp;&amp; c -&gt; d") == "if a < b && c -> d"
    assert unescape_slack("see <https://x.dev/a|x.dev> and <https://y.dev>") == "see https://x.dev/a and https://y.dev"
    assert unescape_slack("&amp;lt;") == "&lt;"


def test_split_target_known_kind():
    from herdr_slack.routing import split_target
    assert split_target("codex: 다시 정리해줘", {"claude", "codex"}) == ("codex", "다시 정리해줘")


def test_split_target_unknown_word_is_plain_text():
    from herdr_slack.routing import split_target
    assert split_target("참고: 이건 메모", {"claude", "codex"}) == (None, "참고: 이건 메모")
    assert split_target("note: x", {"claude"}) == (None, "note: x")


def test_split_target_multiline_keeps_body():
    from herdr_slack.routing import split_target
    assert split_target("claude:첫 줄\n둘째 줄", {"claude"}) == ("claude", "첫 줄\n둘째 줄")
