from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def run_command() -> str:
    """The foreground command to launch inside the tmux pane.

    Run from the branch's worktree in direct mode: the sandbox works on the
    worktree in place, so commits land on the host as they're made. (Clone
    mode is not an option: `sbx` refuses `--clone` inside a git worktree.)
    Left as a long-lived interactive REPL (no `-p`) so it can receive
    follow-up comments.
    """
    return "sbx run claude"


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
