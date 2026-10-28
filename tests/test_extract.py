from pathlib import Path

from herdr_slack.extract import (
    Choice,
    choices_from_screen,
    find_claude_session,
    last_response_from_claude_session,
    last_response_from_screen,
    tail,
)

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_codex_last_response_starts_at_last_bullet():
    r = last_response_from_screen("codex", read_fixture("codex_screen.txt"))
    assert r.startswith("• 참고할 부분이") and "Worked for" not in r and "Ran rg" not in r
    assert r.rstrip().endswith("위험이 있습니다.")


def test_codex_nested_bullets_stay_in_response():
    r = last_response_from_screen("codex", read_fixture("codex_screen.txt"))
    assert "진엔딩의 수집" in r


def test_claude_last_response_excludes_footer():
    r = last_response_from_screen("claude", read_fixture("claude_screen.txt"))
    assert r.startswith("● 아직 완료는") and "✻" not in r and "❯" not in r
    assert all(line == line.rstrip() for line in r.splitlines())


def test_unknown_kind_returns_none():
    assert last_response_from_screen("gemini", "anything") is None


def test_marker_missing_returns_none():
    assert last_response_from_screen("claude", "no markers here") is None


def test_claude_session_returns_last_assistant_text():
    assert last_response_from_claude_session(FIXTURES / "claude_session.jsonl") == "마지막 응답 첫 줄\n마지막 응답 둘째 줄"


def test_find_claude_session(tmp_path):
    f = tmp_path / "C--proj" / "abc.jsonl"
    f.parent.mkdir()
    f.write_text("")
    assert find_claude_session("abc", tmp_path) == f
    assert find_claude_session("zzz", tmp_path) is None


def test_choices_from_permission_screen():
    screen = ("Do you want to proceed?\n❯ 1. Yes\n  2. Yes, and don't ask again\n"
              "  3. No, and tell Claude what to do differently (esc)\n")
    assert choices_from_screen(screen) == [
        Choice("1", "Yes"), Choice("2", "Yes, and don't ask again"),
        Choice("3", "No, and tell Claude what to do differently (esc)")]


def test_choices_keep_only_last_group():
    screen = "1. old a\n2. old b\nsome text\n› 1. new a\n  2. new b\n"
    assert choices_from_screen(screen) == [Choice("1", "new a"), Choice("2", "new b")]


def test_tail_returns_last_lines_trimmed():
    assert tail("a  \nb\nc   \n\n", 2) == "b\nc"


def test_find_claude_session_falls_back_to_newest_in_cwd(tmp_path):
    import os
    d = tmp_path / "C--Users-me-proj"
    d.mkdir()
    old, new = d / "old.jsonl", d / "new.jsonl"
    old.write_text("")
    new.write_text("")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert find_claude_session("stale-id", tmp_path, cwd=r"C:\Users\me\proj") == new


def test_find_claude_session_prefers_exact_id(tmp_path):
    d = tmp_path / "C--Users-me-proj"
    d.mkdir()
    (d / "sid.jsonl").write_text("")
    (d / "other.jsonl").write_text("")
    assert find_claude_session("sid", tmp_path, cwd=r"C:\Users\me\proj") == d / "sid.jsonl"


def test_claude_session_interrupted_turn_has_no_new_response():
    assert last_response_from_claude_session(FIXTURES / "claude_interrupted.jsonl") is None


def test_claude_session_tool_results_do_not_hide_final_response():
    assert last_response_from_claude_session(FIXTURES / "claude_tool_turn.jsonl") == "최종 응답"
