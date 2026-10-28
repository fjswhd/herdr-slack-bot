from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = ROOT / "herdr-slack.log"
PID_FILE = ROOT / "herdr-slack.pid"
REQUIRED = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID", "SLACK_USER_ID")
DEFAULT_PROJECTS_ROOT = Path(r"C:\Users\jmlee\projects\jmlee")
DEFAULT_EVENT_PORT = 47615  # 플러그인 훅 → 봇 전달용 로컬 포트


@dataclass(frozen=True)
class Config:
    bot_token: str
    app_token: str
    channel_id: str
    user_id: str
    projects_root: Path
    event_port: int


def parse_env(text: str) -> dict[str, str]:
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def read_env_file() -> dict[str, str]:
    path = ROOT / ".env"
    return parse_env(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_config(env: Mapping[str, str]) -> Config:
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise ValueError(f"필수 환경 변수 누락: {', '.join(missing)}")
    root = env.get("PROJECTS_ROOT")
    return Config(
        bot_token=env["SLACK_BOT_TOKEN"],
        app_token=env["SLACK_APP_TOKEN"],
        channel_id=env["SLACK_CHANNEL_ID"],
        user_id=env["SLACK_USER_ID"],
        projects_root=Path(root) if root else DEFAULT_PROJECTS_ROOT,
        event_port=int(env.get("HERDR_SLACK_PORT") or DEFAULT_EVENT_PORT),
    )
