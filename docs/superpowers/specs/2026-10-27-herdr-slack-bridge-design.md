# herdr Slack 브리지 설계

작성일: 2026-10-27

## 1. 목적

- PC(Windows)의 herdr에서 돌아가는 코딩 에이전트들을 휴대폰 Slack으로 이어서 다루기 위한 상시 실행 봇.
- 배경: Termux + SSH로 herdr TUI에 붙는 방식은 휴대폰 화면에서 줄바꿈 깨짐, 특수키 입력, 스크롤 확인이 불편함.
- 휴대폰에서 Claude 계정이나 Claude 앱을 쓰지 않음. 에이전트 종류(claude, codex 등)와 무관하게 herdr를 통해서만 명령을 주고받음.

### 사용 흐름 (사용자 기준)

1. PC의 에이전트가 작업을 마치거나 판단(승인·질문)을 요청함.
2. 휴대폰에 Slack 푸시 알림이 옴.
3. Slack에서 마지막 응답 또는 질문을 읽음.
4. 해당 workspace 채널에 메시지를 쓰거나 버튼을 눌러 다음 작업을 지시함.

## 2. 목표 / 비목표 / 실패 기준

### 목표
- herdr pane의 상태 변화(완료, 판단 필요)를 Slack 메시지로 알림.
- 알림 메시지 스레드의 답장을 해당 pane에 프롬프트로 전달.
- 판단 필요 상태에서 버튼으로 키 입력(허용, 거절 등) 전달.
- 휴대폰에서 새 폴더 + 새 에이전트 시작.
- herdr가 인식하는 모든 에이전트 종류에서 동작(최소한 화면 텍스트 기반 동작).

### 비목표
- PC 사용 여부에 따른 알림 끄기·켜기. 알림 조절은 휴대폰(안드로이드 모드, Slack 채널 음소거)이 담당.
- 여러 사용자 지원. 사용자 1명 전용.
- 여러 PC(herdr `--machine`) 지원.
- Remote Control, Claude 모바일 앱 연동.
- pane 닫기, workspace 삭제 등 파괴적 조작.

### 실패 기준 (동작해도 실패로 보는 경우)
- herdr가 인식한 완료·판단 필요 상태의 알림이 누락됨(사용자가 PC로 돌아와서야 알게 됨). herdr가 인식하지 못한 판단 필요 화면은 제외(4.3.1).
- 답장이 엉뚱한 pane으로 전달됨.
- 허용된 Slack 사용자 외의 입력이 PC에 전달됨.
- 휴대폰에서 읽을 수 없을 정도로 깨진 텍스트만 옴(대체 수단인 "화면 보기"도 못 읽는 수준).

## 3. 제약

- 실행 환경: Windows 11, 사용자 PC. herdr 0.9.5(protocol 22), 소켓 `C:\Users\jmlee\AppData\Roaming\herdr\herdr.sock`.
- Python 3.13, uv 사용 가능.
- Slack: 사용자가 새로 만드는 개인 워크스페이스. 관리자 권한 있음.
- 외부에서 PC로 들어오는 포트 개방 금지. Slack Socket Mode 사용.
- herdr 제어는 herdr CLI 또는 herdr 소켓 API만 사용. 에이전트 프로세스에 직접 붙지 않음.

## 4. 결정된 사항

### 4.1 Slack 구성 (workspace별 채널)
- 변경 이력: 처음에는 채널 1개 + 알림 스레드 답장(A안). 모든 에이전트 대화가 한 채널에 섞여 맥락을 잃어 workspace별 채널로 변경.
- herdr workspace 1개 = 공개 채널 1개(`#herdr-<workspace 이름>`). 봇이 자동 생성하고 사용자를 초대.
  - 생성 시점: 그 workspace의 첫 알림 또는 `/herdr new`.
  - 같은 이름 채널이 있으면 참여해서 사용. 생성 실패 시 기본 채널(`SLACK_CHANNEL_ID`)로 알림.
  - workspace를 닫아도 채널은 그대로 둠.
  - workspace ↔ 채널 연결은 `channels.json`에 저장.
- 알림 1건 = 해당 workspace 채널의 새 봇 메시지 1개.
- 메시지 머리: 상태 표시(완료 / 판단 필요) + 위치(작업 폴더 이름 · 에이전트 종류).
- 사용자 입력은 채널 메시지(스레드 아님).
  - 기본 대상: 그 채널에 마지막으로 알림을 보낸 에이전트.
  - `codex: 내용`처럼 workspace에 있는 에이전트 종류를 앞에 붙이면 그 에이전트. 이후 기본 대상도 변경. (Claude의 판단)
  - 기본 대상이 없거나 사라졌고 에이전트가 1개면 그 에이전트, 여러 개면 이름을 붙이라고 안내.
  - 전달되면 메시지에 ✅ 반응. 채널에 "전송됨" 메시지를 쓰지 않기 위함. (Claude의 판단)
- 알림 메시지 스레드 답장도 그 알림의 pane으로 전달(이전 방식 유지).
- 대상 pane 확인: 기록된 pane에 같은 터미널이 있거나, 같은 종류의 에이전트가 있으면 전달. herdr 재시작으로 터미널 ID만 바뀐 경우를 허용하기 위함. 종류가 기록되지 않은 예전 알림은 터미널 ID로만 판단.
- [전체 보기]·[화면 보기] 결과는 알림 메시지 스레드에 게시. 알림 내용을 펼치는 것이라 채널 흐름을 끊지 않기 위함. (Claude의 판단)

### 4.1.1 사용자 입력 해석 (pane 현재 상태 기준)
- `idle` / `done`: 텍스트를 프롬프트로 전송.
- `working`: 전송하지 않음. "지금 작업 중" 안내와 [그래도 보내기] 버튼 게시. 버튼을 누르면 전송.
  - why: PC에서 이미 다음 작업을 시킨 상태에서 휴대폰의 옛 지시가 끼어드는 것을 막기 위함.
- `blocked`:
  - 키 이름 하나(`1`, `esc`, `enter` 등)면 키로 전송. (Claude의 판단)
  - 그 외 문장은 그대로 입력 후 Enter 전송. Claude 질문 화면의 직접 입력용. (Claude의 판단)

### 4.2 완료 알림
- 대상: 4.3.2의 완료 기준.
- 본문: 마지막 응답의 앞부분.
  - Claude 대화 기록에서 읽은 응답: Slack `markdown` 블록으로 보내 제목·표·코드 블록이 렌더링됨. 미리보기 3000자. (Claude의 판단)
  - 화면에서 잘라낸 텍스트: 코드 블록. 터미널 줄바꿈·들여쓰기가 섞여 Markdown으로 렌더링하면 깨지기 때문. 미리보기 600자.
- 버튼:
  - [전체 보기]: 응답 전문을 스레드에 게시.
  - [화면 보기]: 터미널 화면 마지막 N줄을 그대로 스레드에 게시. 응답 추출 실패 시 대체 수단.

### 4.3 판단 필요 알림
- 대상: pane 상태가 `blocked`로 바뀐 경우.
- 본문: 질문·승인 요청 화면 부분.
- 버튼: 모든 에이전트(Claude 포함)에서 화면의 번호 선택지를 읽어 버튼 생성. [거절(Esc)]은 항상 추가. (Claude의 판단)
  - why: Claude 판단 화면은 도구 승인 외에도 질문·계획 승인 등 선택지 수와 의미가 매번 달라, 고정 버튼은 잘못된 선택을 누를 수 있음.
- 선택지 읽기 실패: [거절(Esc)]만 두고 스레드 답장(4.1.1)으로 처리.
- 버튼을 누르기 전 무엇을 승인하는지 본문에서 보여야 함.

### 4.3.1 herdr가 `blocked`를 인식하지 못한 경우
- 낯선 승인·질문 화면은 herdr가 `blocked`로 인식하지 못함. 이때 pane은 계속 `working`으로 보여 알림이 나가지 않음.
- 이 누락은 허용. 봇은 herdr 상태 변화만 보고 화면 멈춤 감지는 하지 않음.

### 4.3.2 상태 변화 감지 (herdr 플러그인 이벤트)
- 저장소 루트의 `herdr-plugin.toml`을 herdr 플러그인으로 연결(`herdr plugin link`).
- herdr가 `pane.agent_status_changed` 이벤트마다 훅(`herdr_slack.hook`)을 실행. 훅은 pane ID와 상태를 `127.0.0.1`의 봇 포트(기본 47615)로 넘기고 종료.
- 알림 기준:
  - 완료: 상태가 `done`이 되거나 `working` → `idle`이 될 때. PC 화면에 떠 있는 pane은 완료가 바로 `idle`로 처리되는데, 사람이 보고 있다는 보장이 없으므로 알림. 끄기는 휴대폰 쪽이 담당.
  - 판단 필요: 상태가 `blocked`가 될 때.
  - 끝난 뒤 15초 안에 다시 작업을 시작하면 알리지 않음. 응답을 끝냈다가 백그라운드 작업 결과로 곧바로 재개하는 경우를 거르기 위함. 대신 알림이 15초 늦음.
- 새 응답이 없는 완료는 알리지 않음(이전 응답이 새 답처럼 보이는 문제 방지):
  - Claude: 대화 기록에서 마지막 사용자 입력(프롬프트, `[Request interrupted by user]` 중단 표시) 뒤에 응답이 없으면 생략. Esc로 바로 중단한 경우.
  - 화면에서 읽는 에이전트: 직전 알림과 본문이 같으면 생략. 같은 답이 연달아 나오는 드문 경우도 생략됨.
  - 중단 알림은 보내지 않음. PC에서 직접 Esc를 누른 경우 불필요한 알림이 되기 때문. ⏳ 반응만 제거. (Claude의 판단)
- 진행 표시: Slack에서 보낸 메시지에 전달 확인 ✅와 작업 중 ⏳ 반응. 에이전트가 다시 멈추면(완료·판단 필요 알림 시점) ⏳ 제거. PC에서 시작한 작업은 표시 없음.
- Claude 응답 본문: herdr가 주는 세션 ID의 대화 기록을 읽음. herdr가 옛 세션 ID를 들고 있어 파일이 없으면 그 작업 폴더의 가장 최근 대화 기록을 읽음(같은 폴더에 Claude가 둘 이상이면 틀릴 수 있음).
- 훅은 이벤트마다 따로 실행되어 도착 순서가 바뀔 수 있음. 그래서 직전 상태 종류는 따지지 않고 같은 상태 반복만 거름.
- 봇이 꺼져 있는 동안의 이벤트는 버림. 훅 기록(`<herdr 플러그인 상태 폴더>/events.log`)에 `bot-down`으로 남음.
- 대안 검토: herdr Windows named pipe에 Python으로 직접 연결 시도는 실패(이름 형식 오류 123).

### 4.4 응답 추출
- 기본: herdr 화면 텍스트(`agent read --source recent-unwrapped`)에서 마지막 응답만 잘라냄. 에이전트별 응답 시작 표시를 기준으로 자름.
  - 확인된 표시: Claude `●`, Codex `•`. Codex는 `Worked for ...` 줄로 응답 끝을 알 수 있음.
- Claude: herdr가 주는 세션 ID(`agent_session.value`)로 `~/.claude/projects/<프로젝트>/<세션ID>.jsonl`에서 마지막 응답을 정확히 읽음. 화면 텍스트에는 표 테두리·긴 공백·줄 붙음이 섞여 휴대폰에서 읽기 어려움이 확인됨.
- 그 외 에이전트: 화면 텍스트에 터미널 흔적이 일부 섞여도 허용. 사용하며 조정.
- 잘라내기 실패: 마지막 N줄을 그대로 게시.

### 4.5 슬래시 명령
- `/herdr list`: 전체 pane의 상태 목록.
- `/herdr new <이름> [에이전트]` + 둘째 줄부터 첫 프롬프트:
  1. `C:\Users\jmlee\projects\jmlee\<이름>` 폴더 생성.
  2. herdr에 새 workspace 생성, 그 폴더에서 에이전트 시작(`herdr agent start --kind`).
  3. 에이전트 생략 시 claude.
  4. 첫 프롬프트 전송.
  5. 이후 흐름은 다른 pane과 동일.
- 용도: 밖에서 새 아이디어 구상을 시작할 때.

### 4.6 알림 조절
- 봇은 완료·판단 필요가 생길 때마다 항상 메시지를 올림.
- 끄기·켜기는 휴대폰 쪽(안드로이드 모드, Slack 앱 알림 설정)이 담당. 봇에 알림 토글 명령 없음.

### 4.7 보안
- 지정한 Slack 사용자 ID 1개의 입력만 처리. 나머지는 무시.
- Slack 토큰은 코드 밖(환경 변수 또는 git에서 제외한 설정 파일)에 둠.

### 4.8 위치
- 코드와 문서: `C:\Users\jmlee\projects\jmlee\ai-integration`. (Claude의 판단)

## 5. 확인된 herdr 기능 (0.9.5 기준)

- `herdr agent list`: JSON. `agent`, `agent_status`(idle/working/blocked/done/unknown), `cwd`, `pane_id`, `workspace_id`, `terminal_title`, Claude는 `agent_session.value`.
- `herdr agent prompt <대상> <텍스트> [--wait] [--until] [--timeout]`: 이미 `blocked`면 `agent_blocked`로 거부. `--wait`는 작업 단위를 추적하지 않음.
- `herdr agent read <대상> --source visible|recent|recent-unwrapped|detection --lines N`.
- `herdr agent send-keys <대상> <키>...`: `esc`, `enter`, `ctrl+c` 등 논리 키 이름.
- `herdr agent wait`, `herdr agent start <이름> --kind <종류> --pane <ID>`: 종류 24가지(claude, codex, gemini 등).
- `herdr workspace create`, `herdr pane split`: 생성 결과에서 ID를 읽음.
- 소켓 API `events.subscribe`: `pane_agent_status_changed` 이벤트(pane_id, workspace_id, agent_status, agent 등) 제공. 전체 스키마는 `herdr api schema --json`.
- `idle`과 `done`: 둘 다 입력 대기. `done`은 사용자가 아직 보지 않은 완료.
- `blocked`: herdr가 승인·질문 화면을 인식한 경우. 낯선 승인 화면은 인식 못 할 수 있음.

## 6. 빌더에게 맡기는 부분

- 언어·라이브러리 선택. (Claude의 기본안: Python + slack_bolt Socket Mode, uv로 관리)
- herdr와 통신 방식: 소켓 API 직접 연결 또는 CLI 호출. Windows에서 `herdr.sock` 연결 방식(Python AF_UNIX 지원 여부 포함) 확인 필요. 이벤트 구독이 어려우면 `agent list` 주기적 확인으로 대체 가능.
- 알림 메시지 ↔ pane 연결 정보 저장 방식(메모리, 파일 등). 봇 재시작 후에도 최근 알림의 스레드 답장이 동작하면 좋음.
- 상태 변화 중 알림 대상 판단 규칙(예: working → done/idle/blocked만 알림, 짧은 시간 내 반복 변화 묶기).
- 봇 시작 시 이미 `done`/`blocked`인 pane의 알림 여부.
- herdr 재시작 등으로 pane ID가 다른 pane을 가리킬 때 잘못 전달하지 않도록 막는 방법(`terminal_id`, `agent_session` 비교 등).
- `/herdr new`의 여러 줄 입력 방식(슬래시 명령 또는 입력 창), 폴더가 이미 있을 때 처리.
- 봇 자동 시작 방법(Windows 로그인 시 실행 등).
- 응답 본문 길이 제한, Slack 메시지 분할 기준.
- 에이전트별 응답 잘라내기 규칙의 구체 구현.
- Slack 앱 생성·설치 절차 문서화(사용자가 직접 수행).
