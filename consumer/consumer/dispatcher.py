from __future__ import annotations

import logging
from typing import Any

from . import prompts, sandbox
from .github_client import GithubClient
from .state_store import ACTIVE, CLOSED, ERROR, StateStore
from .tmux_manager import TmuxManager
from .workspace import Workspace

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(
        self,
        state: StateStore,
        tmux: TmuxManager,
        github: GithubClient,
        workspace: Workspace,
        session_ready_timeout_seconds: int,
    ):
        self._state = state
        self._tmux = tmux
        self._github = github
        self._workspace = workspace
        self._session_ready_timeout_seconds = session_ready_timeout_seconds

    def handle_message(self, msg: dict[str, Any]) -> None:
        delivery_id = msg["delivery_id"]
        if self._state.is_duplicate(delivery_id):
            logger.info("Skipping already-processed delivery %s", delivery_id)
            return

        if msg["event_type"] == "pull_request":
            # The webhook Lambda only ever emits event_type "pull_request" for
            # the closed action (see webhook/handler.py normalize()) -- every
            # other tracked event type is a comment/review.
            self._teardown(msg)
        else:
            self._dispatch_comment(msg)

        self._state.mark_processed(delivery_id)

    def _teardown(self, msg: dict[str, Any]) -> None:
        repo_full_name = msg["repo_full_name"]
        pr_number = msg["pr_number"]
        row = self._state.find_by_repo_pr(repo_full_name, pr_number)
        if row is None:
            logger.info("No tracked session for %s#%s, nothing to tear down", repo_full_name, pr_number)
            return

        logger.info("Tearing down session for %s#%s (branch %s)", repo_full_name, pr_number, row.branch)
        self._tmux.kill_session(row.session_name)
        sandbox.stop(row.sandbox_name)
        self._workspace.cleanup(repo_full_name, row.branch)
        self._state.set_status(row.branch, CLOSED)

    def _dispatch_comment(self, msg: dict[str, Any]) -> None:
        repo_full_name = msg["repo_full_name"]
        pr_number = msg["pr_number"]
        branch = msg.get("branch")

        if not branch:
            pr_info = self._github.resolve_pull_request(repo_full_name, pr_number)
            branch = pr_info.branch
            msg = {**msg, "branch": branch, "base_branch": pr_info.base_branch}

        row = self._state.get(branch)
        if row is None or not self._tmux.has_session(row.session_name):
            self._provision_session(msg, branch)

        self._tmux.send_instruction(branch, prompts.followup_prompt(msg))
        self._state.touch_last_activity(branch)

    def _provision_session(self, msg: dict[str, Any], branch: str) -> None:
        repo_full_name = msg["repo_full_name"]
        pr_number = msg["pr_number"]
        pr_info = self._github.resolve_pull_request(repo_full_name, pr_number)

        workspace_path = self._workspace.ensure_branch_checkout(repo_full_name, pr_info.clone_url, branch)
        session_name = branch

        self._state.upsert(
            branch=branch,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            session_name=session_name,
            workspace_path=str(workspace_path),
            sandbox_name=session_name,
            status="provisioning",
        )

        command = sandbox.run_command(branch)
        self._tmux.ensure_session(session_name, str(workspace_path), command)

        if not self._tmux.wait_until_ready(session_name, self._session_ready_timeout_seconds):
            logger.warning("Session '%s' did not stabilize within timeout; proceeding anyway", session_name)
            self._state.set_status(branch, ERROR)
        else:
            self._state.set_status(branch, ACTIVE)

        self._tmux.send_instruction(
            session_name, prompts.initial_system_prompt(repo_full_name, pr_number, branch)
        )
