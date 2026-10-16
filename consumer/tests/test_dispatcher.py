from pathlib import Path
from unittest.mock import MagicMock

import pytest

from datetime import datetime, timedelta, timezone

from consumer.dispatcher import Dispatcher, SandboxExitedError
from consumer.github_client import PullRequestInfo
from consumer.processed_ids import ProcessedIds
from consumer.state_store import ACTIVE, CLOSED, ERROR, StateStore

RETENTION_DAYS = 7


@pytest.fixture
def state(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture
def processed_ids_path(tmp_path: Path) -> Path:
    return tmp_path / "processed-ids"


@pytest.fixture
def dispatcher(state: StateStore, tmp_path: Path, processed_ids_path: Path):
    tmux = MagicMock()
    tmux.has_session.return_value = False
    tmux.wait_until_ready.return_value = True

    github = MagicMock()
    github.resolve_pull_request.return_value = PullRequestInfo(
        branch="feature/x", base_branch="main", clone_url="https://github.com/org/repo.git"
    )

    workspace = MagicMock()
    workspace.ensure_branch_checkout.return_value = tmp_path / "worktree"

    d = Dispatcher(
        state=state, tmux=tmux, github=github, workspace=workspace,
        processed_ids=ProcessedIds(processed_ids_path, retention_days=RETENTION_DAYS),
        session_ready_timeout_seconds=5, allowed_comment_authors=frozenset({"octocat"}),
    )
    return d, tmux, github, workspace


def make_comment(delivery_id="d1", branch="feature/x"):
    return {
        "schema_version": 1,
        "delivery_id": delivery_id,
        "event_type": "issue_comment",
        "repo_full_name": "org/repo",
        "pr_number": 1,
        "branch": branch,
        "base_branch": "main",
        "is_merged": False,
        "actor": "octocat",
        "body": "please fix this",
        "html_url": "https://github.com/org/repo/pull/1#issuecomment-1",
        "file_path": None,
        "line": None,
        "diff_hunk": None,
        "received_at": "2026-01-01T00:00:00Z",
    }


def test_new_comment_provisions_session(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    d.handle_message(make_comment())

    row = state.get("feature/x")
    assert row is not None
    assert row.status == ACTIVE
    tmux.ensure_session.assert_called_once()
    assert tmux.send_instruction.call_count == 2  # initial system prompt + followup


def test_duplicate_delivery_is_skipped(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    msg = make_comment(delivery_id="dup-1")
    d.handle_message(msg)
    tmux.reset_mock()

    d.handle_message(msg)
    tmux.ensure_session.assert_not_called()
    tmux.send_instruction.assert_not_called()


def test_comment_with_existing_session_reuses_it(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    d.handle_message(make_comment(delivery_id="d1"))
    tmux.has_session.return_value = True
    tmux.reset_mock()
    tmux.has_session.return_value = True

    d.handle_message(make_comment(delivery_id="d2"))
    tmux.ensure_session.assert_not_called()
    tmux.send_instruction.assert_called_once()


def test_branch_resolved_lazily_when_missing(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    msg = make_comment(delivery_id="d1", branch=None)
    d.handle_message(msg)
    github.resolve_pull_request.assert_called()
    assert state.get("feature/x") is not None


def test_pull_request_closed_tears_down(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    d.handle_message(make_comment(delivery_id="d1"))

    close_msg = {
        **make_comment(delivery_id="d2"),
        "event_type": "pull_request",
        "is_merged": True,
    }
    d.handle_message(close_msg)

    row = state.get("feature/x")
    assert row.status == CLOSED
    tmux.kill_session.assert_called_once_with("feature/x")
    workspace.cleanup.assert_called_once_with("org/repo", "feature/x")


def test_sandbox_exit_during_startup_raises_with_output(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    tmux.wait_until_ready.return_value = False
    tmux.has_session.return_value = False
    tmux.last_output.return_value = "zsh: command not found: sbx"

    with pytest.raises(SandboxExitedError, match="command not found: sbx"):
        d.handle_message(make_comment())

    tmux.send_instruction.assert_not_called()
    assert state.get("feature/x").status == ERROR


def test_message_that_raises_is_handled_again_on_redelivery(dispatcher):
    d, tmux, github, workspace = dispatcher
    tmux.wait_until_ready.return_value = False
    tmux.has_session.return_value = False
    with pytest.raises(SandboxExitedError):
        d.handle_message(make_comment(delivery_id="d1"))

    tmux.reset_mock()
    tmux.wait_until_ready.return_value = True
    d.handle_message(make_comment(delivery_id="d1"))

    tmux.ensure_session.assert_called_once()
    assert tmux.send_instruction.call_count == 2


def test_comment_from_non_allowlisted_author_is_ignored(dispatcher, state: StateStore, processed_ids_path: Path):
    d, tmux, github, workspace = dispatcher
    d.handle_message({**make_comment(delivery_id="d1"), "actor": "leopubcode-agent"})

    tmux.ensure_session.assert_not_called()
    tmux.send_instruction.assert_not_called()
    assert state.get("feature/x") is None
    assert processed_ids_path.read_text().split()[0] == "d1"


def test_allowlist_is_case_insensitive(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    d.handle_message({**make_comment(), "actor": "OctoCat"})
    assert state.get("feature/x") is not None


def test_pr_close_by_non_allowlisted_author_still_tears_down(dispatcher, state: StateStore):
    d, tmux, github, workspace = dispatcher
    d.handle_message(make_comment(delivery_id="d1"))
    d.handle_message({
        **make_comment(delivery_id="d2"), "event_type": "pull_request",
        "is_merged": True, "actor": "someone-else",
    })
    assert state.get("feature/x").status == CLOSED


def test_empty_allowlist_is_rejected(state: StateStore):
    with pytest.raises(ValueError):
        Dispatcher(
            state=state, tmux=MagicMock(), github=MagicMock(), workspace=MagicMock(),
            processed_ids=MagicMock(),
            session_ready_timeout_seconds=5, allowed_comment_authors=frozenset(),
        )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_delivery_already_in_processed_ids_file_is_skipped(dispatcher, processed_ids_path: Path):
    d, tmux, github, workspace = dispatcher
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    processed_ids_path.write_text(f"seen-1 {_iso(recent)}\n")

    d.handle_message(make_comment(delivery_id="seen-1"))

    tmux.ensure_session.assert_not_called()
    tmux.send_instruction.assert_not_called()
    github.resolve_pull_request.assert_not_called()


def test_handled_delivery_is_recorded_with_timestamp(dispatcher, processed_ids_path: Path):
    d, tmux, github, workspace = dispatcher
    before = datetime.now(timezone.utc)

    d.handle_message(make_comment(delivery_id="d1"))

    [line] = processed_ids_path.read_text().splitlines()
    delivery_id, stamp = line.split()
    assert delivery_id == "d1"
    assert before <= datetime.fromisoformat(stamp) <= datetime.now(timezone.utc)


def test_entries_older_than_retention_are_pruned(dispatcher, processed_ids_path: Path):
    d, tmux, github, workspace = dispatcher
    now = datetime.now(timezone.utc)
    stale = now - timedelta(days=RETENTION_DAYS, hours=1)
    fresh = now - timedelta(days=RETENTION_DAYS - 1)
    processed_ids_path.write_text(f"old-1 {_iso(stale)}\nkept-1 {_iso(fresh)}\n")

    d.handle_message(make_comment(delivery_id="d1"))

    ids = [line.split()[0] for line in processed_ids_path.read_text().splitlines()]
    assert ids == ["kept-1", "d1"]

    tmux.reset_mock()
    d.handle_message(make_comment(delivery_id="old-1"))
    tmux.send_instruction.assert_called()
