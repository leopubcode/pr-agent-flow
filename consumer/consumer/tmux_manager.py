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


def tmux_session_name(name: str) -> str:
    # tmux silently rewrites '.' and ':' to '_' in session names, so a branch
    # like `release/1.2` must be looked up by its rewritten name.
    return name.replace(".", "_").replace(":", "_")


class TmuxManager:
    """Owns the one tmux session per PR branch.

    Sessions are addressed by branch name; translation to a valid tmux
    session name happens here so callers never deal with it. The session
    runs a long-lived interactive REPL that receives follow-up
    instructions over the life of the PR.
    """

    def __init__(self, server: Optional[libtmux.Server] = None):
        self._server = server or libtmux.Server()

    def has_session(self, session_name: str) -> bool:
        """True only if the session exists and its command is still running."""
        return self._get_pane(session_name) is not None

    def ensure_session(self, session_name: str, workspace_path: str, foreground_command: str) -> None:
        """Make sure a live session runs `foreground_command`, replacing a dead one.

        The command is the pane's own process rather than something typed into
        a shell: if it exits there is no shell left behind to receive pasted
        comment text.
        """
        session = self._find(session_name)
        if session:
            pane = session.active_window.active_pane
            if self._is_alive(pane):
                return
            logger.error(
                "Session '%s' command exited; last output:\n%s", session_name, self.last_output(session_name)
            )
            session.kill()

        session = self._server.new_session(
            session_name=tmux_session_name(session_name),
            start_directory=workspace_path,
            window_command=foreground_command,
        )
        # Keep the pane after the command exits so its output can be inspected.
        self._server.cmd("set-option", "-w", "-t", session.active_window.window_id, "remain-on-exit", "on")
        logger.info("Launched session '%s' in %s: %s", session_name, workspace_path, foreground_command)

    def wait_until_ready(self, session_name: str, timeout_seconds: int = 60, poll_interval: float = 2.0) -> bool:
        """Poll the pane until its output stabilizes, as a proxy for "REPL has booted".

        There is no structured ready signal from `sbx run`/`claude`, so this
        is a heuristic (identical captured output on two consecutive polls).
        """
        deadline = time.monotonic() + timeout_seconds
        previous: Optional[list[str]] = None
        while time.monotonic() < deadline:
            pane = self._get_pane(session_name)
            if pane is None:
                return False
            current = pane.capture_pane()
            if current and current == previous:
                return True
            previous = current
            time.sleep(poll_interval)
        return False

    def send_instruction(self, session_name: str, text: str) -> None:
        """Deliver `text` to the session's running REPL as a single paste, then submit it."""
        pane = self._get_pane(session_name)
        if pane is None:
            raise SessionNotReadyError(f"No tmux session found for '{session_name}'")

        buffer_name = f"pr-agent-{uuid.uuid4().hex}"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            tmp_path = f.name

        try:
            # Server.cmd, not Pane.cmd: Pane.cmd injects `-t <pane>`, which
            # load-buffer would misread as a target client.
            self._server.cmd("load-buffer", "-b", buffer_name, tmp_path)
            # -p = bracketed paste, so the REPL treats embedded newlines as part
            # of one message instead of pressing Enter at each line.
            self._server.cmd("paste-buffer", "-p", "-d", "-b", buffer_name, "-t", pane.pane_id)
            # Give the REPL a moment to finish ingesting the paste before Enter.
            time.sleep(0.5)
            pane.send_keys("", enter=True)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def last_output(self, session_name: str, lines: int = 40) -> Optional[str]:
        """The pane's recent output, including for a pane whose command has exited."""
        session = self._find(session_name)
        if not session:
            return None
        return "\n".join(session.active_window.active_pane.capture_pane(start=-lines))

    def kill_session(self, session_name: str) -> None:
        session = self._find(session_name)
        if session:
            session.kill()
            logger.info("Killed session '%s'", session_name)

    def _find(self, session_name: str) -> Optional[libtmux.Session]:
        return self._server.sessions.get(session_name=tmux_session_name(session_name), default=None)

    def _get_pane(self, session_name: str) -> Optional[libtmux.Pane]:
        """The session's pane, or None if the session is missing or its command has exited."""
        session = self._find(session_name)
        if not session:
            return None
        pane = session.active_window.active_pane
        return pane if self._is_alive(pane) else None

    def _is_alive(self, pane: libtmux.Pane) -> bool:
        # Query tmux directly; libtmux's cached pane_dead attribute can be stale.
        result = self._server.cmd("display-message", "-p", "-t", pane.pane_id, "#{pane_dead}")
        return result.stdout == ["0"]
