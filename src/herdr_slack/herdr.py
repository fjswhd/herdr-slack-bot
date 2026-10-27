import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[[list[str]], subprocess.CompletedProcess]


class HerdrError(Exception):
    pass


@dataclass(frozen=True)
class Agent:
    pane_id: str
    workspace_id: str
    terminal_id: str
    kind: str
    status: str
    cwd: str
    title: str
    completion_seq: int
    session_id: str | None


def _default_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8")


class Herdr:
    def __init__(self, run: Runner | None = None):
        self._run = run or _default_run

    def _call(self, *args: str) -> str:
        proc = self._run(["herdr", *args])
        if proc.returncode != 0:
            raise HerdrError((proc.stderr or proc.stdout or "").strip())
        return proc.stdout

    def _json(self, *args: str) -> dict:
        out = self._call(*args)
        return json.loads(out) if out.strip() else {}

    def list_agents(self) -> list[Agent]:
        agents = self._json("agent", "list").get("result", {}).get("agents", [])
        return [
            Agent(
                pane_id=a["pane_id"],
                workspace_id=a.get("workspace_id", ""),
                terminal_id=a.get("terminal_id", ""),
                kind=a.get("agent") or "",
                status=a.get("agent_status", "unknown"),
                cwd=a.get("cwd", ""),
                title=a.get("terminal_title_stripped") or "",
                completion_seq=a.get("completion_seq", 0),
                session_id=(a.get("agent_session") or {}).get("value"),
            )
            for a in agents
        ]

    def read(self, pane_id: str, lines: int = 120) -> str:
        return self._call("agent", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines))

    def prompt(self, pane_id: str, text: str) -> None:
        self._call("agent", "prompt", pane_id, text)

    def send_keys(self, pane_id: str, keys: list[str]) -> None:
        self._call("agent", "send-keys", pane_id, *keys)

    def send_text_enter(self, pane_id: str, text: str) -> None:
        self._call("pane", "send-text", pane_id, text)
        self._call("agent", "send-keys", pane_id, "enter")

    def create_workspace(self, cwd: Path, label: str) -> str:
        res = self._json("workspace", "create", "--cwd", str(cwd), "--label", label, "--no-focus")
        return res["result"]["root_pane"]["pane_id"]

    def start_agent(self, name: str, kind: str, pane_id: str) -> None:
        self._call("agent", "start", name, "--kind", kind, "--pane", pane_id)
