"""The debug log: `debug.log` in PR_AGENT_FLOW_HOME, one tab-separated line per event.

Fields: UTC timestamp, PR Key, pane ID (`-` if none), event kind, detail.
Rotated at local midnight like every log file (see `log_files`).

The PR Key field always holds a PR Key built by `pr_key.pr_key`, never a PR
number. When the branch isn't known yet (a PR Comment on a repository missing
from the repo config file, so its branch can't be looked up), it is
`owner/repo:-`, and the PR number goes in the detail.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from .log_files import daily_log_handler

MISSING_REPO_CONFIG = "missing repo config"
FORK_PR_IGNORED = "fork PR ignored"
PANE_MISSING = "pane missing"
SANDBOX_ORPHANED = "sandbox orphaned"
PROMPT_TIMED_OUT = "prompt timed out"
NEVER_BECAME_IDLE = "never became idle"
TEARDOWN_SANDBOX_STOPPED = "teardown sandbox stopped"
TEARDOWN_TAB_CLOSED = "teardown tab closed"
TEARDOWN_TAB_SKIPPED = "teardown tab skipped"
TEARDOWN_FORGOTTEN = "teardown agent file line removed"
TEARDOWN_STEP_FAILED = "teardown step failed"


class DebugLog:
    def __init__(self, path: Path):
        handler = daily_log_handler(Path(path))
        handler.setFormatter(logging.Formatter("%(message)s"))
        # A private logger, outside the logging registry, so lines never reach
        # the consumer log and each DebugLog writes only to its own file.
        self._logger = logging.Logger(f"debug-log:{path}")  # noqa: LOG001
        self._logger.addHandler(handler)

    def write(self, kind: str, pr_key: str, detail: str, pane_id: str | None = None) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        detail = " ".join(detail.split())  # keep it to one line
        self._logger.warning(f"{timestamp}\t{pr_key}\t{pane_id or '-'}\t{kind}\t{detail}")
