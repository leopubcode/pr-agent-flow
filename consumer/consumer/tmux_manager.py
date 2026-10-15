from __future__ import annotations

import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import libtmux

logger = logging.getLogger(__name__)


class SessionNotReadyError(RuntimeError):
    pass


class TmuxManager:
    """Owns the one tmux session per PR branch.

    Evolved from the original prototype (root `libtmux.py`), which had a
    real bug: it was named the same as the `libtmux` pip package it
    imports, so it shadowed the library on `sys.path`. Renamed here, and
    switched from one-shot `claude -p "..."` (exits after a single turn)
    to a long-lived interactive REPL that receives follow-up instructions
    over the life of the PR.
    """

    def __init__(self):
        self._server = libtmux.Server()

    def has_session(self, session_name: str) -> bool:
        return self._server.find_where({"session_name": session_name}) is not None

    def ensure_session(self, session_name: str, workspace_path: str, foreground_command: str) -> None:
        """Create the session if it doesn't exist and launch `foreground_command` in it.

        Does nothing if the session already exists -- callers should check
        `has_session` first if they need to distinguish "already running"
        from "just created".
        """
        session = self._server.find_where({"session_name": session_name})
        if session:
            return

        session = self._server.new_session(session_name=session_name, start_directory=workspace_path)
        pane = session.active_window.active_pane
        pane.send_keys(foreground_command, enter=True)
        logger.info("Launched session '%s' in %s: %s", session_name, workspace_path, foreground_command)

    def wait_until_ready(self, session_name: str, timeout_seconds: int = 60, poll_interval: float = 2.0) -> bool:
        """Poll the pane until its output stabilizes, as a proxy for "REPL has booted".

        There is no structured ready signal from `sbx run`/`claude` today,
        so this is a known-fragile heuristic (stable captured output for
        two consecutive polls) rather than a real readiness check. Revisit
        if the CLI ever exposes something better (a log line, a socket).
        """
        pane = self._get_pane(session_name)
        if pane is None:
            return False

        deadline = time.monotonic() + timeout_seconds
        previous: Optional[list[str]] = None
        while time.monotonic() < deadline:
            current = pane.capture_pane()
            if current and current == previous:
                return True
            previous = current
            time.sleep(poll_interval)
        return False

    def send_instruction(self, session_name: str, text: str) -> None:
        """Deliver `text` to the session's running REPL.

        Uses `load-buffer` + `paste-buffer` rather than `send_keys` with an
        embedded multi-line string -- `send_keys` on a live REPL is
        fragile with newlines/special characters since the terminal may
        interpret them before they reach the program's stdin.
        """
        pane = self._get_pane(session_name)
        if pane is None:
            raise SessionNotReadyError(f"No tmux session found for '{session_name}'")

        buffer_name = f"pr-agent-{uuid.uuid4().hex}"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            tmp_path = f.name

        try:
            pane.cmd("load-buffer", "-b", buffer_name, tmp_path)
            pane.cmd("paste-buffer", "-b", buffer_name, "-t", pane.pane_id, "-d")
            pane.send_keys("", enter=True)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def kill_session(self, session_name: str) -> None:
        session = self._server.find_where({"session_name": session_name})
        if session:
            session.kill_session()
            logger.info("Killed session '%s'", session_name)

    def live_session_names(self) -> set[str]:
        return {s.session_name for s in self._server.sessions}

    def _get_pane(self, session_name: str):
        session = self._server.find_where({"session_name": session_name})
        if not session:
            return None
        return session.active_window.active_pane
