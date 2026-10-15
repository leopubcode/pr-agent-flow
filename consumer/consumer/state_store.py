from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS branch_sessions (
    branch           TEXT PRIMARY KEY,
    repo_full_name   TEXT NOT NULL,
    pr_number        INTEGER NOT NULL,
    session_name     TEXT NOT NULL,
    workspace_path   TEXT NOT NULL,
    sandbox_name     TEXT,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    last_activity_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_deliveries (
    delivery_id  TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
"""

# Valid branch_sessions.status values.
PROVISIONING = "provisioning"
ACTIVE = "active"
LOST = "lost"
CLOSING = "closing"
CLOSED = "closed"
ERROR = "error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BranchSession:
    branch: str
    repo_full_name: str
    pr_number: int
    session_name: str
    workspace_path: str
    sandbox_name: Optional[str]
    status: str
    created_at: str
    last_activity_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BranchSession":
        return cls(**{k: row[k] for k in row.keys()})


class StateStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # --- dedup ---

    def is_duplicate(self, delivery_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        return row is not None

    def mark_processed(self, delivery_id: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO processed_deliveries (delivery_id, processed_at) VALUES (?, ?)",
                (delivery_id, _now()),
            )

    # --- branch sessions ---

    def get(self, branch: str) -> Optional[BranchSession]:
        row = self._conn.execute(
            "SELECT * FROM branch_sessions WHERE branch = ?", (branch,)
        ).fetchone()
        return BranchSession.from_row(row) if row else None

    def find_by_repo_pr(self, repo_full_name: str, pr_number: int) -> Optional[BranchSession]:
        row = self._conn.execute(
            "SELECT * FROM branch_sessions WHERE repo_full_name = ? AND pr_number = ?",
            (repo_full_name, pr_number),
        ).fetchone()
        return BranchSession.from_row(row) if row else None

    def all_active(self) -> list[BranchSession]:
        rows = self._conn.execute(
            "SELECT * FROM branch_sessions WHERE status NOT IN (?, ?)", (CLOSED, LOST)
        ).fetchall()
        return [BranchSession.from_row(r) for r in rows]

    def upsert(
        self,
        branch: str,
        repo_full_name: str,
        pr_number: int,
        session_name: str,
        workspace_path: str,
        sandbox_name: Optional[str],
        status: str,
    ) -> None:
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO branch_sessions
                    (branch, repo_full_name, pr_number, session_name, workspace_path, sandbox_name, status, created_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(branch) DO UPDATE SET
                    repo_full_name = excluded.repo_full_name,
                    pr_number = excluded.pr_number,
                    session_name = excluded.session_name,
                    workspace_path = excluded.workspace_path,
                    sandbox_name = excluded.sandbox_name,
                    status = excluded.status,
                    last_activity_at = excluded.last_activity_at
                """,
                (branch, repo_full_name, pr_number, session_name, workspace_path, sandbox_name, status, now, now),
            )

    def set_status(self, branch: str, status: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE branch_sessions SET status = ?, last_activity_at = ? WHERE branch = ?",
                (status, _now(), branch),
            )

    def touch_last_activity(self, branch: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE branch_sessions SET last_activity_at = ? WHERE branch = ?", (_now(), branch)
            )

    # --- housekeeping ---

    def prune(self, retention_days: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._cursor() as cur:
            cur.execute("DELETE FROM processed_deliveries WHERE processed_at < ?", (cutoff,))
            cur.execute(
                "DELETE FROM branch_sessions WHERE status = ? AND last_activity_at < ?",
                (CLOSED, cutoff),
            )
