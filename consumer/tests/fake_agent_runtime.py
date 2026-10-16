"""In-memory stand-in for the agent-runtime port.

Each started Coordinator gets a pane in `self.panes`. A new pane reports
`starting_statuses` (one per `get_agent_info` call) before settling on idle.
Everything asked of the runtime is recorded in `self.calls`, and prompts per
pane in `self.prompts`. Name a method in `self.failing` to make it raise
`AgentRuntimeError` (after recording the call).
"""
from __future__ import annotations

from pathlib import Path

from consumer.agent_runtime import (
    GONE,
    IDLE,
    AgentInfo,
    AgentRuntimeError,
    PromptTimeout,
    StartedCoordinator,
)


class FakeAgentRuntime:
    def __init__(self, starting_statuses: tuple[str, ...] = ("working",)):
        self.starting_statuses = starting_statuses
        self.calls: list[tuple] = []
        self.panes: dict[str, list[str]] = {}  # pane_id -> statuses still to report
        self.tabs: dict[str, str] = {}  # pane_id -> tab_id
        self.secrets: dict[str, str] = {}  # sandbox_name -> token
        self.prompts: dict[str, list[str]] = {}
        self.timing_out_panes: set[str] = set()  # prompts to these raise PromptTimeout
        self.failing: set[str] = set()  # method names that raise AgentRuntimeError
        self._started = 0

    def start_coordinator(self, clone_dir: Path) -> StartedCoordinator:
        self._started += 1
        n = self._started
        self.calls.append(("start_coordinator", Path(clone_dir)))
        pane_id = f"pane-{n}"
        sandbox_name = f"sbx-{n}"
        self.panes[pane_id] = list(self.starting_statuses)
        self.tabs[pane_id] = f"tab-{n}"
        self.prompts[pane_id] = []
        return StartedCoordinator(pane_id=pane_id, tab_label=f"tab {sandbox_name}", sandbox_name=sandbox_name)

    def set_secret(self, sandbox_name: str, token: str) -> None:
        self.calls.append(("set_secret", sandbox_name, token))
        self._maybe_fail("set_secret")
        self.secrets[sandbox_name] = token

    def get_agent_info(self, pane_id: str) -> AgentInfo:
        self.calls.append(("get_agent_info", pane_id))
        self._maybe_fail("get_agent_info")
        if pane_id not in self.panes:
            return GONE
        pending = self.panes[pane_id]
        status = pending.pop(0) if pending else IDLE
        return AgentInfo(exists=True, agent_status=status, tab_id=self.tabs[pane_id])

    def prompt(self, pane_id: str, text: str) -> None:
        self.calls.append(("prompt", pane_id, text))
        if pane_id in self.timing_out_panes:
            raise PromptTimeout(f"prompt to {pane_id} timed out")
        self.prompts.setdefault(pane_id, []).append(text)

    def stop_sandbox(self, sandbox_name: str) -> None:
        self.calls.append(("stop_sandbox", sandbox_name))
        self._maybe_fail("stop_sandbox")

    def close_tab(self, tab_id: str) -> None:
        self.calls.append(("close_tab", tab_id))
        self._maybe_fail("close_tab")

    def _maybe_fail(self, method: str) -> None:
        if method in self.failing:
            raise AgentRuntimeError(f"{method} failed (fake)")

    # -- helpers for arranging scenarios --

    def remove_pane(self, pane_id: str) -> None:
        """Simulate a pane that was closed outside the consumer (its sandbox keeps running)."""
        del self.panes[pane_id]

    # -- helpers for assertions --

    def call_names(self) -> list[str]:
        return [c[0] for c in self.calls if c[0] != "get_agent_info"]

    def started(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "start_coordinator"]
