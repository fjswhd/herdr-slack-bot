# Slack 설정과 실행

herdr-bot을 처음 설치할 때 사용자가 직접 하는 절차.

## 1. 워크스페이스와 앱

1. https://slack.com/get-started 에서 개인 워크스페이스 생성.
2. https://api.slack.com/apps → **Create New App** → **From a manifest** → 워크스페이스 선택.
3. 저장소의 `slack-manifest.yaml` 내용 붙여넣기 → 생성.
4. **Basic Information** → **App-Level Tokens** → **Generate Token and Scopes**:
   - 이름 자유, 스코프 `connections:write` 추가 → 생성.
   - `xapp-...` 토큰을 `SLACK_APP_TOKEN`으로 사용.
5. **Install App** → 워크스페이스에 설치.
   - **Bot User OAuth Token**(`xoxb-...`)을 `SLACK_BOT_TOKEN`으로 사용.

## 2. 채널과 ID

1. Slack에서 기본 채널 `#herdr` 생성. 공개·비공개 모두 가능(manifest에 두 종류의 권한 포함).
   - workspace별 채널은 봇이 따로 만듦. 기본 채널은 채널 생성 실패 시 알림과 `/herdr new` 결과용.
   - manifest를 바꾼 뒤에는 **Install App**에서 다시 설치해야 새 권한이 적용됨.
2. 채널에서 `/invite @herdr-bot`.
3. 채널 ID: 채널 이름 클릭 → 맨 아래 `C...` 값 → `SLACK_CHANNEL_ID`.
4. 내 사용자 ID: 내 프로필 → 더보기(⋮) → **멤버 ID 복사**(`U...`) → `SLACK_USER_ID`.

## 3. 설정 파일

저장소 루트에 `.env` 작성(`.env.example` 참고, git 제외 대상).

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_CHANNEL_ID=C...
SLACK_USER_ID=U...
```

- 새 에이전트 폴더 위치를 바꾸려면 `PROJECTS_ROOT` 추가. 기본값 `C:\Users\jmlee\projects\jmlee`.

## 4. herdr 플러그인 연결

봇은 herdr 플러그인 이벤트로 pane 상태 변화를 받음. 최초 1회:

```
uv sync
herdr plugin link C:\Users\jmlee\projects\jmlee\ai-integration
```

- 확인: `herdr plugin list`에 `jmlee.herdr-slack ... enabled`.
- 훅 실행 기록: `herdr plugin log list --plugin jmlee.herdr-slack`.
- 훅이 받은 이벤트 기록: `%LOCALAPPDATA%\herdr\plugins\jmlee.herdr-slack\events.log`. `bot-down`이면 봇이 꺼져 있었다는 뜻.
- 훅 → 봇 포트 기본값 47615. 바꾸려면 `.env`에 `HERDR_SLACK_PORT` 추가.

## 5. 실행

```
uv run python -m herdr_slack
```

- herdr가 실행 중이어야 함.
- 로그: 저장소 루트 `herdr-slack.log`.
- 알림 메시지와 pane 연결 정보: 저장소 루트 `threads.json`.

## 6. Windows 로그인 시 자동 실행

작업 스케줄러에 등록(PowerShell):

```powershell
$repo = "C:\Users\jmlee\projects\jmlee\ai-integration"
$action = New-ScheduledTaskAction -Execute "uv.exe" -Argument "run python -m herdr_slack" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "herdr-slack" -Action $action -Trigger $trigger
```

- 콘솔 창이 보이는 것이 싫으면 `uv.exe` 대신 `pythonw`로 `.venv\Scripts\pythonw.exe -m herdr_slack` 실행.

## 7. 휴대폰 알림

- workspace 채널(`#herdr-...`)이 생기면 채널 알림을 **모든 새 메시지**로 설정.
- 회사 근처 모드 등에서 알림을 끄려면 안드로이드 모드에 Slack 알림 끄기 추가.

## 사용법

- herdr workspace마다 공개 채널 `#herdr-<workspace 이름>`을 봇이 자동 생성하고 사용자를 초대.
  - 생성 시점: 그 workspace의 첫 알림, 또는 `/herdr new`.
  - 같은 이름의 채널이 이미 있으면 그 채널을 사용.
  - 채널을 만들 수 없으면 기본 채널(`SLACK_CHANNEL_ID`)에 알림.
  - workspace를 닫아도 채널은 그대로 둠.
- 채널에 메시지를 쓰면 에이전트에게 전달. 전달되면 메시지에 ✅, 에이전트가 작업하는 동안 ⏳ 반응.
  - 기본 대상: 그 채널에 마지막으로 알림을 보낸 에이전트.
  - 다른 에이전트: `codex: 내용`처럼 앞에 에이전트 종류를 붙임. 이후 기본 대상도 그 에이전트로 바뀜.
  - 에이전트가 작업 중이면 보내지 않고 [그래도 보내기] 버튼 표시.
  - 판단 필요 상태에서 `1`, `esc`, `enter` 같은 키 이름 하나만 쓰면 키로 전달. 그 외 문장은 입력 후 Enter.
- 알림 메시지의 스레드에 답장해도 그 알림의 에이전트에게 전달.
- 완료·판단 필요 알림은 상태가 바뀐 뒤 15초 동안 다시 작업이 시작되지 않을 때 게시.
- [전체 보기]·[화면 보기] 결과는 알림 메시지의 스레드에 표시.
- `/herdr list`: pane 목록과 상태.
- `/herdr new`: 입력 창에서 폴더 이름, 에이전트, 첫 프롬프트 입력 → 새 폴더·workspace·에이전트·채널 생성.
