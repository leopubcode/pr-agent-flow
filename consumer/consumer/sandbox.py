from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def run_command(branch: str) -> str:
    """The foreground command to launch inside the tmux pane.

    Left as a long-lived interactive REPL (no `-p`, no inline prompt) --
    the orchestrator needs to stay alive to receive follow-up comments.
    """
    return f"sbx run claude --branch {branch}"


def stop(sandbox_name: str | None) -> None:
    """Best-effort teardown of the sandbox for a closed/merged PR.

    The `sbx stop`/`sbx rm` subcommand used here is unverified against the
    real CLI -- this is deliberately defensive (log and continue) rather
    than failing the whole teardown path if the subcommand turns out to be
    named differently or the sandbox is already gone.
    """
    if not sandbox_name:
        return
    try:
        subprocess.run(["sbx", "stop", sandbox_name], check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("Failed to stop sandbox %s (continuing teardown anyway): %s", sandbox_name, exc)
