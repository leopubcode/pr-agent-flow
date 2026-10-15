from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from consumer.state_store import ACTIVE, CLOSED, StateStore


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()


def test_dedup(store: StateStore):
    assert not store.is_duplicate("d1")
    store.mark_processed("d1")
    assert store.is_duplicate("d1")


def test_upsert_and_get(store: StateStore):
    store.upsert(
        branch="feature/x",
        repo_full_name="org/repo",
        pr_number=1,
        session_name="feature/x",
        workspace_path="/tmp/ws",
        sandbox_name="feature/x",
        status=ACTIVE,
    )
    row = store.get("feature/x")
    assert row is not None
    assert row.repo_full_name == "org/repo"
    assert row.status == ACTIVE


def test_upsert_is_idempotent_update(store: StateStore):
    store.upsert("b", "org/repo", 1, "b", "/tmp/ws", "b", ACTIVE)
    store.upsert("b", "org/repo", 1, "b", "/tmp/ws2", "b", "provisioning")
    row = store.get("b")
    assert row.workspace_path == "/tmp/ws2"
    assert row.status == "provisioning"


def test_find_by_repo_pr(store: StateStore):
    store.upsert("b", "org/repo", 42, "b", "/tmp/ws", "b", ACTIVE)
    row = store.find_by_repo_pr("org/repo", 42)
    assert row is not None
    assert row.branch == "b"
    assert store.find_by_repo_pr("org/repo", 999) is None


def test_prune_removes_old_closed_sessions_and_deliveries(store: StateStore):
    store.upsert("b", "org/repo", 1, "b", "/tmp/ws", "b", CLOSED)
    store.mark_processed("old-delivery")

    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store._conn.execute("UPDATE branch_sessions SET last_activity_at = ? WHERE branch = 'b'", (old,))
    store._conn.execute("UPDATE processed_deliveries SET processed_at = ? WHERE delivery_id = 'old-delivery'", (old,))
    store._conn.commit()

    store.prune(retention_days=7)

    assert store.get("b") is None
    assert not store.is_duplicate("old-delivery")
