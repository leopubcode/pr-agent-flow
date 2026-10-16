"""The debug log: a gitignored text file, one tab-separated line per event.

Fields: UTC timestamp, PR Key, pane ID (`-` if none), event kind, detail.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

MISSING_REPO_CONFIG = "missing repo config"


class DebugLog:
    def __init__(self, path: Path):
        self._path = Path(path)

    def write(self, kind: str, pr_key: str, detail: str, pane_id: str | None = None) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        detail = " ".join(detail.split())  # keep it to one line
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(f"{timestamp}\t{pr_key}\t{pane_id or '-'}\t{kind}\t{detail}\n")
