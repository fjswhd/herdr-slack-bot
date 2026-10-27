from dataclasses import dataclass, replace
from typing import Literal

from herdr_slack.herdr import Agent


@dataclass(frozen=True)
class Event:
    kind: Literal["done", "blocked"]
    agent: Agent


def diff(prev: dict[str, Agent] | None, cur: list[Agent]) -> list[Event]:
    if prev is None:
        return []
    events = []
    for a in cur:
        old = prev.get(a.pane_id)
        if old is not None and old.terminal_id != a.terminal_id:
            old = None
        if a.status == "blocked":
            if old is None or old.status != "blocked":
                events.append(Event("blocked", a))
        elif old is not None and a.completion_seq > old.completion_seq:
            events.append(Event("done", a))
    return events


def next_snapshot(prev: dict[str, Agent] | None, cur: list[Agent]) -> dict[str, Agent]:
    """Keep the highest completion_seq seen per terminal, since herdr omits it while working."""
    snap = {}
    for a in cur:
        old = (prev or {}).get(a.pane_id)
        if old is not None and old.terminal_id == a.terminal_id and old.completion_seq > a.completion_seq:
            a = replace(a, completion_seq=old.completion_seq)
        snap[a.pane_id] = a
    return snap
