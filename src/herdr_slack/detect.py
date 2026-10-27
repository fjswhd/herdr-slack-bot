from dataclasses import dataclass
from typing import Literal

from herdr_slack.herdr import Agent

Kind = Literal["done", "blocked"]


@dataclass(frozen=True)
class Event:
    kind: Kind
    agent: Agent


def event_kind(prev_status: str | None, status: str) -> Kind | None:
    """herdr 상태 변화 이벤트 중 알림 대상만 고름.

    done은 아직 아무도 보지 않은 완료(PC에서 보고 있었다면 idle이 됨), blocked는 승인·질문 대기.
    훅 프로세스가 이벤트마다 따로 떠서 순서가 바뀌어 도착할 수 있으므로 직전 상태가 무엇이었는지는 따지지 않음.
    """
    if status in ("done", "blocked") and prev_status != status:
        return status
    return None
