# herdr Slack 브리지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PC의 herdr pane 상태 변화(완료, 판단 필요)를 Slack `#herdr` 채널로 알리고, 알림 스레드 답장·버튼·`/herdr` 명령으로 pane을 제어하는 상시 실행 봇.

**Architecture:** herdr CLI를 subprocess로 호출하는 얇은 클라이언트 위에, 순수 함수 모듈(상태 변화 감지, 응답 추출, 답장 해석, Slack 블록 생성)을 두고, `app.py`가 slack_bolt Socket Mode와 2초 주기 폴링 스레드로 이를 묶음. Windows용 Python에는 AF_UNIX가 없어(`hasattr(socket, "AF_UNIX") == False` 확인) herdr 소켓 이벤트 구독 대신 `herdr agent list` 폴링 사용.

**Tech Stack:** Python 3.13, uv, slack_bolt(Socket Mode), pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-herdr-slack-bridge-design.md`

## Global Constraints

- Windows 11, herdr 0.9.5. herdr 제어는 `herdr` CLI만 사용. 모든 호출은 JSON 출력 파싱(`agent read`는 텍스트).
- 외부 인바운드 포트 금지. Slack은 Socket Mode만.
- 처리 대상 Slack 사용자는 `SLACK_USER_ID` 1명. 다른 사용자 입력은 무시(응답도 하지 않음).
- 토큰·ID는 환경 변수(`.env`, git 제외)로만: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_CHANNEL_ID`, `SLACK_USER_ID`, 선택 `PROJECTS_ROOT`(기본 `C:\Users\jmlee\projects\jmlee`).
- 파괴적 herdr 조작(pane close, workspace close, server stop) 금지.
- 문서·주석·커밋 메시지: 개조식, 명사형 어미, em-dash 금지(사용자 CLAUDE.md).
- 패키지 경로: `src/herdr_slack/`, 테스트: `tests/`. 실행: `uv run pytest`, `uv run python -m herdr_slack`.

## Review Focus

1. 봇 시작 직후 이미 `done`/`blocked`인 pane: 시작 시 알림 폭주 없이 조용히 기준 상태로 삼아야 함 → Task 3 `test_first_snapshot_emits_nothing`.
2. herdr 재시작 등으로 같은 `pane_id`가 다른 터미널을 가리킴: 옛 스레드 답장이 새 pane으로 가면 안 됨 → Task 6 `test_reply_rejected_when_terminal_changed`.
3. 폴링 사이(2초)에 working → done → working이 지나감: 완료 알림을 놓치지 않아야 함(`completion_seq` 증가로 감지) → Task 3 `test_completion_seq_increase_emits_done_even_if_status_working`.
4. 4000자 넘는 응답: Slack 블록 3000자 제한으로 게시 실패하면 안 됨 → Task 5 `test_full_text_split_under_limit`.
5. `herdr` 호출 실패(서버 꺼짐, pane 사라짐): 봇이 죽지 않고 스레드에 오류를 알려야 함 → Task 2 `test_cli_error_raises_herdr_error`, Task 6 `test_reply_reports_herdr_error`.

---

### Task 1: 프로젝트 골격과 설정

**Files:**
- Create: `pyproject.toml`, `src/herdr_slack/__init__.py`, `src/herdr_slack/config.py`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Config: bot_token: str; app_token: str; channel_id: str; user_id: str; projects_root: Path`; `def load_config(env: Mapping[str, str]) -> Config`. 필수 값 누락 시 `ValueError`(누락 키 이름 포함).

- [ ] **Step 1: `uv init --package --name herdr-slack`로 골격 생성, `uv add slack_bolt`, `uv add --dev pytest`.** `src/herdr_slack/__init__.py` 유지. `.env.example`에 5개 변수 이름 기재.
- [ ] **Step 2: 실패 테스트 작성**

```python
def test_load_config_defaults_projects_root():
    env = {"SLACK_BOT_TOKEN": "xoxb", "SLACK_APP_TOKEN": "xapp",
           "SLACK_CHANNEL_ID": "C1", "SLACK_USER_ID": "U1"}
    cfg = load_config(env)
    assert cfg.projects_root == Path(r"C:\Users\jmlee\projects\jmlee")

def test_load_config_missing_key_names_it():
    with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
        load_config({"SLACK_BOT_TOKEN": "x", "SLACK_CHANNEL_ID": "C", "SLACK_USER_ID": "U"})
```

- [ ] **Step 3: `uv run pytest tests/test_config.py -v` → FAIL(import 오류)**
- [ ] **Step 4: `load_config` 구현**
- [ ] **Step 5: 테스트 PASS 확인**
- [ ] **Step 6: Commit** `feat: 프로젝트 골격과 설정 로딩 추가`

### Task 2: herdr CLI 클라이언트

**Files:**
- Create: `src/herdr_slack/herdr.py`
- Test: `tests/test_herdr.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Agent: pane_id: str; workspace_id: str; terminal_id: str; kind: str; status: str; cwd: str; title: str; completion_seq: int; session_id: str | None`
  - `class HerdrError(Exception)`
  - `class Herdr: def __init__(self, run: Callable[[list[str]], subprocess.CompletedProcess] | None = None)` (기본값: `subprocess.run([... ], capture_output=True, text=True, encoding="utf-8")`로 `herdr`를 호출하는 함수)
  - 메서드: `list_agents() -> list[Agent]`, `read(pane_id: str, lines: int = 120) -> str`(`--source recent-unwrapped`), `prompt(pane_id: str, text: str) -> None`(`--wait` 없이), `send_keys(pane_id: str, keys: list[str]) -> None`, `send_text_enter(pane_id: str, text: str) -> None`(`pane send-text` 후 `agent send-keys <pane> enter`), `create_workspace(cwd: Path, label: str) -> str`(`workspace create --cwd --label --no-focus`, 반환 `.result.root_pane.pane_id`), `start_agent(name: str, kind: str, pane_id: str) -> None`(`agent start <name> --kind <kind> --pane <pane_id>`)
- `Agent` 필드 매핑: `agent`→`kind`, `agent_status`→`status`, `terminal_title_stripped`→`title`, `completion_seq` 없으면 0, `agent_session.value` 없으면 None.
- 0이 아닌 종료 코드: `HerdrError(stderr 내용)`.

- [ ] **Step 1: 실패 테스트 작성.** 가짜 `run`이 받은 인자를 기록하고 정해진 stdout을 돌려줌.

```python
LIST_JSON = '{"result":{"agents":[{"agent":"codex","agent_status":"idle","cwd":"C:\\\\p\\\\re-alive2","pane_id":"wN6:p2","terminal_id":"t2","terminal_title_stripped":"game","workspace_id":"wN6","completion_seq":132}]}}'

def test_list_agents_parses_fields():
    h = Herdr(run=fake_run(stdout=LIST_JSON))
    [a] = h.list_agents()
    assert (a.pane_id, a.kind, a.status, a.completion_seq, a.session_id) == ("wN6:p2", "codex", "idle", 132, None)

def test_send_text_enter_calls_send_text_then_enter():
    calls = []
    h = Herdr(run=fake_run(stdout="{}", record=calls))
    h.send_text_enter("w:p1", "hello")
    assert calls == [["herdr", "pane", "send-text", "w:p1", "hello"],
                     ["herdr", "agent", "send-keys", "w:p1", "enter"]]

def test_create_workspace_returns_root_pane():
    h = Herdr(run=fake_run(stdout='{"result":{"root_pane":{"pane_id":"w9:p1"}}}'))
    assert h.create_workspace(Path("C:/x"), "x") == "w9:p1"

def test_cli_error_raises_herdr_error():
    h = Herdr(run=fake_run(returncode=1, stderr='{"error":"agent_blocked"}'))
    with pytest.raises(HerdrError, match="agent_blocked"):
        h.prompt("w:p1", "hi")
```

- [ ] **Step 2: FAIL 확인** `uv run pytest tests/test_herdr.py -v`
- [ ] **Step 3: `Herdr` 구현**
- [ ] **Step 4: PASS 확인**
- [ ] **Step 5: 실제 herdr로 읽기 전용 확인:** `uv run python -c "from herdr_slack.herdr import Herdr; print(Herdr().list_agents())"` → 현재 pane 목록 출력
- [ ] **Step 6: Commit** `feat: herdr CLI 클라이언트 추가`

### Task 3: 상태 변화 감지

**Files:**
- Create: `src/herdr_slack/detect.py`
- Test: `tests/test_detect.py`

**Interfaces:**
- Consumes: `Agent`(Task 2)
- Produces: `@dataclass(frozen=True) class Event: kind: Literal["done", "blocked"]; agent: Agent`; `def diff(prev: dict[str, Agent] | None, cur: list[Agent]) -> list[Event]`
- 규칙:
  - `prev is None`(첫 스냅샷): 빈 목록.
  - `blocked`: 이전 상태가 `blocked`가 아니고 현재 `blocked`.
  - `done`: 같은 `terminal_id`에서 `completion_seq`가 증가. 현재 상태가 `blocked`면 `blocked`만 발생.
  - 새로 나타난 pane 또는 `terminal_id`가 바뀐 pane: 이전 값 없음으로 보고 현재 `blocked`일 때만 `blocked`.

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_first_snapshot_emits_nothing():
    assert diff(None, [agent(status="done", seq=5)]) == []

def test_working_to_blocked_emits_blocked():
    prev = {"p": agent(status="working", seq=5)}
    assert [e.kind for e in diff(prev, [agent(status="blocked", seq=5)])] == ["blocked"]

def test_completion_seq_increase_emits_done_even_if_status_working():
    prev = {"p": agent(status="working", seq=5)}
    assert [e.kind for e in diff(prev, [agent(status="working", seq=6)])] == ["done"]

def test_blocked_stays_blocked_emits_nothing():
    prev = {"p": agent(status="blocked", seq=5)}
    assert diff(prev, [agent(status="blocked", seq=5)]) == []

def test_terminal_change_resets_baseline():
    prev = {"p": agent(status="idle", seq=50, terminal="t1")}
    assert diff(prev, [agent(status="idle", seq=1, terminal="t2")]) == []
```

(`agent(...)`는 테스트 파일의 `Agent` 생성 도우미. pane_id 기본 `"p"`.)

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: `diff` 구현**
- [ ] **Step 4: PASS 확인**
- [ ] **Step 5: Commit** `feat: pane 상태 변화 감지 추가`

### Task 4: 응답·선택지 추출

**Files:**
- Create: `src/herdr_slack/extract.py`
- Test: `tests/test_extract.py`, `tests/fixtures/claude_screen.txt`, `tests/fixtures/codex_screen.txt`, `tests/fixtures/claude_session.jsonl`

**Interfaces:**
- Produces:
  - `def last_response_from_screen(kind: str, screen: str) -> str | None`
  - `def last_response_from_claude_session(path: Path) -> str | None`
  - `def find_claude_session(session_id: str, projects_dir: Path = Path.home() / ".claude" / "projects") -> Path | None` (`projects_dir.glob(f"*/{session_id}.jsonl")` 첫 결과)
  - `@dataclass(frozen=True) class Choice: key: str; label: str`; `def choices_from_screen(screen: str) -> list[Choice]`
  - `def tail(screen: str, n: int = 40) -> str`
- 화면 규칙:
  - `claude`: 줄을 `strip()`했을 때 `● `로 시작하는 마지막 줄부터, 그 뒤 `✻ ` 또는 `❯`로 시작하는 첫 줄 전까지.
  - `codex`: `• `로 시작하는 마지막 줄부터, 그 뒤 `Worked for` 포함 줄 또는 `›`로 시작하는 첫 줄 전까지.
  - 그 외 kind 또는 표시를 못 찾으면 None.
  - 결과는 각 줄 끝 공백 제거, 앞뒤 빈 줄 제거.
- 세션 규칙: `type == "assistant"`이고 `message.content`에 `type == "text"` 블록이 있는 마지막 줄의 text 블록들을 `\n`으로 연결. 깨진 JSON 줄은 건너뜀.
- 선택지 규칙: 화면 마지막 30줄에서 정규식 `^\s*(?:[❯›>]\s*)?(\d)\.\s+(.+?)\s*$`에 맞는 줄. 같은 key가 여러 번이면 마지막 묶음만.

- [ ] **Step 1: 픽스처 작성.** 이 PC의 실제 pane에서 `herdr agent read <pane> --source recent-unwrapped --lines 60`으로 Claude·Codex 화면 하나씩 저장. 개인 정보가 있으면 내용만 바꾸고 구조(`●`, `•`, `✻`, `Worked for`, `❯`, `›` 줄)는 유지. 세션 jsonl은 `user`, `assistant(thinking)`, `assistant(text)`, `system` 줄로 손으로 작성.
- [ ] **Step 2: 실패 테스트 작성**

```python
def test_codex_last_response_starts_at_last_bullet():
    r = last_response_from_screen("codex", read_fixture("codex_screen.txt"))
    assert r.startswith("• ") and "Worked for" not in r

def test_claude_last_response_excludes_footer():
    r = last_response_from_screen("claude", read_fixture("claude_screen.txt"))
    assert r.startswith("● ") and "✻" not in r and "❯" not in r

def test_unknown_kind_returns_none():
    assert last_response_from_screen("gemini", "anything") is None

def test_claude_session_returns_last_assistant_text():
    assert last_response_from_claude_session(FIXTURES / "claude_session.jsonl") == "<픽스처의 마지막 assistant text>"

def test_choices_from_permission_screen():
    screen = "Do you want to proceed?\n❯ 1. Yes\n  2. Yes, and don't ask again\n  3. No, and tell Claude what to do differently (esc)\n"
    assert choices_from_screen(screen) == [Choice("1", "Yes"), Choice("2", "Yes, and don't ask again"),
                                           Choice("3", "No, and tell Claude what to do differently (esc)")]
```

- [ ] **Step 3: FAIL 확인**
- [ ] **Step 4: 구현**
- [ ] **Step 5: PASS 확인**
- [ ] **Step 6: Commit** `feat: 응답과 선택지 추출 추가`

### Task 5: Slack 메시지 블록

**Files:**
- Create: `src/herdr_slack/blocks.py`
- Test: `tests/test_blocks.py`

**Interfaces:**
- Consumes: `Event`(Task 3), `Choice`(Task 4)
- Produces:
  - `def notification(event: Event, body: str, choices: list[Choice]) -> list[dict]`
  - `def busy_notice(pane_id: str, text: str) -> list[dict]`
  - `def agent_list(agents: list[Agent]) -> list[dict]`
  - `def split_text(text: str, limit: int = 2900) -> list[str]`
  - `def new_agent_modal() -> dict`
  - 상수 `PREVIEW_CHARS = 600`
- 알림 머리: 완료 `✅ 완료`, 판단 필요 `⚠️ 판단 필요`, 뒤에 `` `<cwd 마지막 폴더 이름> · <kind>` ``.
- 본문: `body`를 `PREVIEW_CHARS`에서 자르고 잘렸으면 `…` 추가. 코드 블록(```)으로 감쌈.
- 버튼 `action_id`(Task 6이 사용):
  - 완료: `full`(전체 보기), `screen`(화면 보기)
  - 판단 필요: 선택지마다 `choice_<key>`(라벨 `<key> <label 앞 20자>`), 항상 `esc`(거절(Esc)), `screen`
  - 작업 중 안내: `force_send`
  - 모든 버튼 `value`는 `pane_id`. `force_send`의 value는 JSON `{"pane_id":..., "text":...}`.
- 모달: `callback_id="new_agent"`, 입력 `name`(plain_text), `kind`(static_select, claude 기본, claude·codex·gemini), `prompt`(multiline).

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_blocked_notification_has_choice_and_esc_buttons():
    blocks = notification(Event("blocked", agent(kind="claude", cwd=r"C:\p\clips")), "Proceed?", [Choice("1", "Yes")])
    ids = action_ids(blocks)
    assert ids == ["choice_1", "esc", "screen"]
    assert "⚠️ 판단 필요" in text_of(blocks) and "clips · claude" in text_of(blocks)

def test_done_notification_truncates_preview():
    blocks = notification(Event("done", agent()), "x" * 1000, [])
    assert action_ids(blocks) == ["full", "screen"]
    assert "x" * 601 not in text_of(blocks) and "…" in text_of(blocks)

def test_full_text_split_under_limit():
    parts = split_text("a" * 7000)
    assert len(parts) == 3 and all(len(p) <= 2900 for p in parts) and "".join(parts) == "a" * 7000
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현.** `split_text`는 가능하면 줄바꿈 위치에서 자름.
- [ ] **Step 4: PASS 확인**
- [ ] **Step 5: Commit** `feat: Slack 메시지 블록 생성 추가`

### Task 6: 답장 해석과 처리기(Slack 비의존 핵심 로직)

**Files:**
- Create: `src/herdr_slack/routing.py`, `src/herdr_slack/store.py`, `src/herdr_slack/bridge.py`
- Test: `tests/test_routing.py`, `tests/test_store.py`, `tests/test_bridge.py`

**Interfaces:**
- Consumes: `Herdr`, `Agent`, `HerdrError`(Task 2), `diff`, `Event`(Task 3), 추출 함수(Task 4), 블록 함수(Task 5)
- Produces:
  - `routing.py`: `KEY_NAMES = {"esc", "escape", "enter", "tab", "up", "down", "left", "right", "ctrl+c"} | {str(d) for d in range(10)}`; `@dataclass class Prompt: text: str`, `class Keys: keys: list[str]`, `class TextEnter: text: str`, `class Busy: text: str`; `def interpret(status: str, text: str) -> Prompt | Keys | TextEnter | Busy`
    - `idle`/`done`/`unknown` → `Prompt`; `working` → `Busy`; `blocked` → 공백 제거 후 소문자가 `KEY_NAMES`에 있으면 `Keys([그 값])`, 아니면 `TextEnter`.
  - `store.py`: `@dataclass class PaneRef: pane_id: str; terminal_id: str`; `class ThreadStore: def __init__(self, path: Path)`; `put(ts: str, ref: PaneRef) -> None`; `get(ts: str) -> PaneRef | None`. JSON 파일에 저장, 최근 500개만 유지, 파일이 없으면 빈 상태로 시작.
  - `bridge.py`: Slack 호출을 `post(blocks: list[dict], text: str, thread_ts: str | None) -> str`(반환 ts) 함수로 주입받는 `class Bridge: def __init__(self, herdr: Herdr, store: ThreadStore, post: Callable, projects_root: Path)`
    - `poll_once() -> None`: `list_agents` → `diff`(내부에 이전 스냅샷 보관) → 이벤트마다 본문 구성 후 `post`, `store.put(ts, PaneRef)`.
      - 본문: Claude이고 `session_id`가 있으면 `find_claude_session` + `last_response_from_claude_session`, 아니면 `last_response_from_screen`, 둘 다 None이면 `tail(screen)`. 판단 필요는 항상 `tail(screen, 25)`와 `choices_from_screen`.
    - `handle_reply(thread_ts: str, text: str) -> None`: `store.get` → 없으면 무시. 현재 `list_agents`에서 같은 `pane_id`를 찾고 `terminal_id`가 다르거나 없으면 스레드에 "이 pane은 더 이상 없음" 게시. 있으면 `interpret` 결과대로 `prompt` / `send_keys` / `send_text_enter` 실행 후 "전송됨" 게시, `Busy`면 `busy_notice` 게시.
    - `handle_action(thread_ts: str, action_id: str, value: str) -> None`: `full` → 전체 응답을 `split_text`로 나눠 스레드에 게시, `screen` → `tail(screen, 60)` 게시, `choice_<k>` → `send_keys([k])`, `esc` → `send_keys(["esc"])`, `force_send` → `prompt`. 버튼도 `terminal_id` 확인을 거침.
    - `start_new(name: str, kind: str, prompt: str) -> str`: 이름을 `^[a-z][a-z0-9_-]{0,31}$`로 검사(아니면 `ValueError`, herdr 에이전트 이름 규칙과 같게 하기 위함). `projects_root / name`이 이미 있으면 `ValueError`. 폴더 생성 → `create_workspace` → `start_agent` → `prompt`가 비어 있지 않으면 `prompt`. 결과 안내 문자열 반환.
    - 모든 `HerdrError`는 잡아서 스레드에 `⚠️ herdr 오류: <메시지>` 게시.

- [ ] **Step 1: 실패 테스트 작성.** `FakeHerdr`(호출 기록, 정해진 agent 목록 반환)와 `posts` 기록 리스트 사용.

```python
def test_interpret_working_is_busy():
    assert interpret("working", "next") == Busy("next")

def test_interpret_blocked_key_name():
    assert interpret("blocked", " ESC ") == Keys(["esc"])

def test_interpret_blocked_sentence_is_text_enter():
    assert interpret("blocked", "use option b") == TextEnter("use option b")

def test_store_persists_across_instances(tmp_path):
    ThreadStore(tmp_path / "s.json").put("1.0", PaneRef("w:p1", "t1"))
    assert ThreadStore(tmp_path / "s.json").get("1.0") == PaneRef("w:p1", "t1")

def test_poll_posts_done_and_records_thread():
    b, herdr, posts, store = make_bridge(agents=[agent(status="working", seq=1)])
    b.poll_once()
    herdr.agents = [agent(status="idle", seq=2)]
    b.poll_once()
    assert len(posts) == 1 and store.get(posts[0].ts) == PaneRef("p", "t1")

def test_reply_sends_prompt_when_idle():
    b, herdr, posts, store = make_bridge(agents=[agent(status="idle")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "다음 작업")
    assert herdr.calls[-1] == ("prompt", "p", "다음 작업")

def test_reply_when_working_posts_busy_notice_and_does_not_send():
    b, herdr, posts, store = make_bridge(agents=[agent(status="working")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "다음 작업")
    assert not any(c[0] == "prompt" for c in herdr.calls)
    assert "force_send" in action_ids(posts[-1].blocks)

def test_reply_rejected_when_terminal_changed():
    b, herdr, posts, store = make_bridge(agents=[agent(status="idle", terminal="t2")])
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "hi")
    assert herdr.calls_of("prompt") == [] and "더 이상 없음" in posts[-1].text

def test_reply_reports_herdr_error():
    b, herdr, posts, store = make_bridge(agents=[agent(status="idle")], fail_on="prompt")
    store.put("9.0", PaneRef("p", "t1"))
    b.handle_reply("9.0", "hi")
    assert posts[-1].text.startswith("⚠️ herdr 오류")

def test_start_new_rejects_existing_folder(tmp_path):
    (tmp_path / "idea").mkdir()
    b, *_ = make_bridge(projects_root=tmp_path)
    with pytest.raises(ValueError):
        b.start_new("idea", "claude", "")
```

- [ ] **Step 2: FAIL 확인** `uv run pytest tests/test_routing.py tests/test_store.py tests/test_bridge.py -v`
- [ ] **Step 3: `routing.py`, `store.py`, `bridge.py` 구현**
- [ ] **Step 4: PASS 확인**
- [ ] **Step 5: Commit** `feat: 답장 해석과 브리지 처리 로직 추가`

### Task 7: Slack 앱 연결과 실행

**Files:**
- Create: `src/herdr_slack/app.py`, `src/herdr_slack/__main__.py`, `docs/slack-setup.md`, `slack-manifest.yaml`
- Test: 수동 확인(아래 Step). Slack 연결 코드는 얇게 유지하고 로직은 Task 6에 둠.

**Interfaces:**
- Consumes: `load_config`(Task 1), `Herdr`(Task 2), `ThreadStore`(Task 6), `Bridge`(Task 6), `agent_list`, `new_agent_modal`(Task 5)
- Produces: `def main() -> None`

- [ ] **Step 1: `slack-manifest.yaml` 작성.** Socket Mode 사용, 봇 스코프 `chat:write`, `channels:history`, `commands`, 이벤트 구독 `message.channels`, 슬래시 명령 `/herdr`, interactivity 켬.
- [ ] **Step 2: `docs/slack-setup.md` 작성.** 사용자가 직접 하는 절차: 워크스페이스 생성 → manifest로 앱 생성 → App-Level Token(`connections:write`) 발급 → 설치 → `#herdr` 채널 생성 후 앱 초대 → 채널 ID·내 사용자 ID 확인 → `.env` 작성 → 실행 → Windows 로그인 시 자동 실행(작업 스케줄러에 `uv run python -m herdr_slack` 등록, 작업 폴더는 저장소 루트).
- [ ] **Step 3: `app.py` 구현**
  - `.env` 파일을 읽어 `os.environ`과 합친 뒤 `load_config`(.env 파서는 표준 라이브러리로 `KEY=VALUE` 줄만 처리).
  - `App(token=bot_token)`, `SocketModeHandler(app, app_token)`.
  - 폴링: 데몬 스레드에서 2초마다 `bridge.poll_once()`, 예외는 로그만 남기고 계속.
  - `message` 이벤트: `channel == channel_id`, `user == user_id`, `thread_ts`가 있고 `bot_id`가 없을 때만 `bridge.handle_reply(thread_ts, text)`.
  - 액션(`full`, `screen`, `choice_*` 정규식, `esc`, `force_send`): `ack()` 후 `body["user"]["id"] == user_id`일 때만 `handle_action(메시지의 thread_ts 또는 ts, action_id, value)`.
  - `/herdr list` → `agent_list` 블록을 응답. `/herdr new` → `views_open(new_agent_modal())`. 그 외 → 사용법 안내. 사용자 검사 동일.
  - 모달 제출(`new_agent`) → `bridge.start_new` 결과를 채널에 게시. `ValueError`는 모달 오류로 표시(`ack(response_action="errors", ...)`).
  - 로그: 표준 `logging`, `herdr-slack.log` 파일(저장소 루트, git 제외)에 기록.
- [ ] **Step 4: `.gitignore`에 `herdr-slack.log`, `threads.json` 추가.** `ThreadStore` 경로는 저장소 루트 `threads.json`.
- [ ] **Step 5: 전체 테스트** `uv run pytest -v` → 모두 PASS
- [ ] **Step 6: 수동 확인(사용자의 Slack 설정 완료 후)**
  1. `uv run python -m herdr_slack` 실행 → 로그에 연결 성공 기록.
  2. 휴대폰 Slack에서 `/herdr list` → 현재 pane 목록 표시.
  3. herdr의 한 pane에 짧은 작업을 시키고 완료 → `#herdr`에 `✅ 완료` 메시지와 푸시 알림.
  4. 그 메시지 스레드에 답장 → 해당 pane에 프롬프트 입력 확인, 스레드에 "전송됨".
  5. 승인이 필요한 작업 → `⚠️ 판단 필요` + 선택지 버튼 → 버튼으로 진행 확인.
  6. 작업 중에 답장 → [그래도 보내기] 안내 확인.
  7. `/herdr new` → 모달 → 새 폴더·workspace·에이전트 생성과 첫 프롬프트 확인.
- [ ] **Step 7: Commit** `feat: Slack 앱 연결과 설정 안내 추가`
