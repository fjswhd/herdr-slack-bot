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

1. Slack에서 `#herdr` 채널 생성. 공개·비공개 모두 가능(manifest에 두 종류의 권한 포함).
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

- Slack 앱 설치 후 `#herdr` 채널 알림을 **모든 새 메시지**로 설정.
- 회사 근처 모드 등에서 알림을 끄려면 안드로이드 모드에 Slack 알림 끄기 추가.

## 사용법

- `#herdr`에 오는 알림 메시지의 스레드에 답장 → 해당 pane에 전달.
  - pane이 작업 중이면 보내지 않고 [그래도 보내기] 버튼 표시.
  - 판단 필요 상태에서 `1`, `esc`, `enter` 같은 키 이름 하나만 쓰면 키로 전달. 그 외 문장은 입력 후 Enter.
- `/herdr list`: pane 목록과 상태.
- `/herdr new`: 입력 창에서 폴더 이름, 에이전트, 첫 프롬프트 입력 → 새 폴더·workspace·에이전트 시작.
