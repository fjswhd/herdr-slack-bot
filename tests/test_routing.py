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
