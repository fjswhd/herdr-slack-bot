from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID", "SLACK_USER_ID")
DEFAULT_PROJECTS_ROOT = Path(r"C:\Users\jmlee\projects\jmlee")


@dataclass(frozen=True)
class Config:
    bot_token: str
    app_token: str
    channel_id: str
    user_id: str
    projects_root: Path


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
    )
