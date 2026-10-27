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

    완료: done(아무도 보지 않은 완료) 진입, 또는 working → idle(PC 화면에 떠 있던 pane의 완료).
    화면에 떠 있어도 사람이 보고 있다는 보장이 없으므로 알림을 보내고, 끄기는 휴대폰 쪽이 담당.
    blocked: 승인·질문 대기 진입.
    """
    if status in ("done", "blocked") and prev_status != status:
        return status
    if status == "idle" and prev_status == "working":
        return "done"
    return None
