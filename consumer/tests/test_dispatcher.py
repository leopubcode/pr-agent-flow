from pathlib import Path
from unittest.mock import MagicMock

import pytest

from consumer.dispatcher import Dispatcher
from consumer.github_client import PullRequestInfo
from consumer.state_store import ACTIVE, CLOSED, StateStore


@pytest.fixture
def state(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture
def dispatcher(state: StateStore, tmp_path: Path):
    tmux = MagicMock()
    tmux.has_session.return_value = False
    tmux.wait_until_ready.return_value = True

    github = MagicMock()
    github.resolve_pull_request.return_value = PullRequestInfo(
        branch="feature/x", base_branch="main", clone_url="https://github.com/org/repo.git"
    )

    workspace = MagicMock()
    workspace.ensure_branch_checkout.return_value = tmp_path / "worktree"

    d = Dispatcher(state=state, tmux=tmux, github=github, workspace=workspace, session_ready_timeout_seconds=5)
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
