"""The agent-runtime port: the only way the dispatcher touches herdr or sbx.

See ADR 0001. `HerdrSbxRuntime` (in `herdr_runtime.py`) is the real adapter;
tests use `tests/fake_agent_runtime.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

IDLE = "idle"


@dataclass(frozen=True)
class StartedCoordinator:
    pane_id: str
    tab_label: str
    sandbox_name: str


@dataclass(frozen=True)
class AgentInfo:
    exists: bool
    agent_status: str | None = None
    tab_id: str | None = None


GONE = AgentInfo(exists=False)


class AgentRuntimeError(RuntimeError):
    """A herdr or sbx command failed."""


class PromptTimeout(AgentRuntimeError):
    """`herdr agent prompt` did not return in time."""


class AgentRuntime(Protocol):
    def start_coordinator(self, branch: str, clone_dir: Path) -> StartedCoordinator:
        """Run `sbx-start <branch>` from `clone_dir`."""

    def set_secret(self, sandbox_name: str, token: str) -> None:
        """`sbx secret set github --sandbox <name> -t <token>`."""

    def get_agent_info(self, pane_id: str) -> AgentInfo:
        """`herdr agent get <pane>`; `GONE` when the pane doesn't exist."""

    def prompt(self, pane_id: str, text: str) -> None:
        """`herdr agent prompt <pane> <text>`; raises `PromptTimeout`."""

    def stop_sandbox(self, sandbox_name: str) -> None:
        """`sbx stop <name>`."""

    def close_tab(self, tab_id: str) -> None:
        """`herdr tab close <tab_id>`."""
