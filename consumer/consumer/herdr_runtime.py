"""Real agent-runtime adapter: shells out to `sbx-start`, `sbx` and `herdr`.

Not unit-tested; these CLIs exist only on the Operator's host. The JSON
shapes read here (`sbx-start` output, `sbx list --json`, `herdr agent get`)
follow the spec but are unverified until run by hand against the real tools.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .agent_runtime import (
    GONE,
    AgentInfo,
    AgentRuntimeError,
    PromptTimeout,
    StartedCoordinator,
)

logger = logging.getLogger(__name__)


def default_sbx_start_command() -> list[str]:
    """`sbx-start` is a shell alias, so run it through an interactive shell that loads it.

    The branch is appended as `$1`, never interpolated into the script.
    """
    return [os.environ.get("SHELL", "/bin/zsh"), "-ic", 'sbx-start "$1"', "sbx-start"]


class HerdrSbxRuntime:
    def __init__(
        self,
        sbx_start_command: Sequence[str] | None = None,
        prompt_timeout_seconds: float = 30,
        command_timeout_seconds: float = 120,
    ):
        self._sbx_start_command = list(sbx_start_command or default_sbx_start_command())
        self._prompt_timeout_seconds = prompt_timeout_seconds
        self._command_timeout_seconds = command_timeout_seconds

    def start_coordinator(self, branch: str, clone_dir: Path) -> StartedCoordinator:
        out = self._run([*self._sbx_start_command, branch], cwd=clone_dir).stdout
        context = _last_json_object(out).get("result", {}).get("context", {})
        pane_id = context.get("focused_pane_id")
        tab_label = context.get("tab_label")
        if not pane_id or not tab_label:
            raise AgentRuntimeError(f"sbx-start output has no pane ID or tab label: {out!r}")
        return StartedCoordinator(pane_id=pane_id, tab_label=tab_label, sandbox_name=self._sandbox_named(tab_label))

    def set_secret(self, sandbox_name: str, token: str) -> None:
        self._run(["sbx", "secret", "set", "github", "--sandbox", sandbox_name, "-t", token])

    def get_agent_info(self, pane_id: str) -> AgentInfo:
        proc = self._run(["herdr", "agent", "get", pane_id], check=False)
        if proc.returncode != 0:
            # Assumed: a non-zero exit means the pane doesn't exist.
            logger.info("herdr agent get %s exited %s: %s", pane_id, proc.returncode, proc.stderr.strip())
            return GONE
        data = _last_json_object(proc.stdout)
        result = data.get("result", data)
        agent = result.get("agent", result)
        return AgentInfo(
            exists=True,
            agent_status=agent.get("agent_status"),
            tab_id=agent.get("tab_id") or result.get("tab_id"),
        )

    def prompt(self, pane_id: str, text: str) -> None:
        try:
            self._run(["herdr", "agent", "prompt", pane_id, text], timeout=self._prompt_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise PromptTimeout(f"herdr agent prompt {pane_id} timed out after {exc.timeout}s") from exc

    def stop_sandbox(self, sandbox_name: str) -> None:
        self._run(["sbx", "stop", sandbox_name])

    def close_tab(self, tab_id: str) -> None:
        self._run(["herdr", "tab", "close", tab_id])

    def _sandbox_named(self, tab_label: str) -> str:
        """The sandbox whose name matches the tab label's last word."""
        wanted = tab_label.split()[-1]
        listing = json.loads(self._run(["sbx", "list", "--json"]).stdout or "[]")
        if isinstance(listing, dict):
            listing = next((v for v in listing.values() if isinstance(v, list)), [])
        names = [item.get("name") if isinstance(item, dict) else item for item in listing]
        if wanted in names:
            return wanted
        raise AgentRuntimeError(f"no sandbox named {wanted!r} in `sbx list --json` (have {names})")

    def _run(
        self, args: list[str], cwd: Path | None = None, check: bool = True, timeout: float | None = None
    ) -> subprocess.CompletedProcess:
        try:
            proc = subprocess.run(
                args, check=False, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                timeout=timeout or self._command_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"{args[0]} not found") from exc
        if check and proc.returncode != 0:
            raise AgentRuntimeError(f"{_redact(args)} exited {proc.returncode}: {proc.stderr.strip()}")
        return proc


def _last_json_object(text: str) -> dict[str, Any]:
    """The last line of `text` that parses as a JSON object (CLIs may print chatter first)."""
    for line in reversed(text.strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise AgentRuntimeError(f"expected JSON output, got {text!r}") from exc
    if not isinstance(value, dict):
        raise AgentRuntimeError(f"expected a JSON object, got {text!r}")
    return value


def _redact(args: list[str]) -> str:
    """Hide the token in `sbx secret set ... -t <token>` from error messages."""
    shown = list(args)
    if "-t" in shown and shown.index("-t") + 1 < len(shown):
        shown[shown.index("-t") + 1] = "***"
    return " ".join(shown)
