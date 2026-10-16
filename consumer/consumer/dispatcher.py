from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from . import prompts
from .agent_file import AgentFile, AgentRecord
from .agent_runtime import IDLE, AgentRuntime, AgentRuntimeError, PromptTimeout
from .debug_log import (
    FORK_PR_IGNORED,
    MISSING_REPO_CONFIG,
    NEVER_BECAME_IDLE,
    PANE_MISSING,
    PROMPT_TIMED_OUT,
    SANDBOX_ORPHANED,
    TEARDOWN_FORGOTTEN,
    TEARDOWN_SANDBOX_STOPPED,
    TEARDOWN_STEP_FAILED,
    TEARDOWN_TAB_CLOSED,
    TEARDOWN_TAB_SKIPPED,
    DebugLog,
)
from .github_client import GithubClient
from .processed_ids import ProcessedIds
from .repo_config import RepoConfig, RepoEntry

logger = logging.getLogger(__name__)


class CoordinatorNotReadyError(AgentRuntimeError):
    """A newly started Coordinator didn't report `idle` within the ready timeout."""


class Dispatcher:
    def __init__(
        self,
        runtime: AgentRuntime,
        github_for: Callable[[str], GithubClient],
        repo_config: RepoConfig,
        agent_file: AgentFile,
        debug_log: DebugLog,
        processed_ids: ProcessedIds,
        ready_timeout_seconds: float,
        allowed_comment_authors: frozenset[str],
        ready_poll_interval_seconds: float = 2.0,
    ):
        if not allowed_comment_authors:
            raise ValueError("allowed_comment_authors must not be empty")
        self._runtime = runtime
        self._github_for = github_for
        self._repo_config = repo_config
        self._agent_file = agent_file
        self._debug_log = debug_log
        self._processed_ids = processed_ids
        self._ready_timeout_seconds = ready_timeout_seconds
        self._ready_poll_interval_seconds = ready_poll_interval_seconds
        self._allowed_comment_authors = allowed_comment_authors

    def handle_message(self, msg: dict[str, Any]) -> None:
        delivery_id = msg["delivery_id"]
        if self._processed_ids.contains(delivery_id):
            logger.info("Skipping already-processed delivery %s", delivery_id)
            return

        if msg["event_type"] == "pull_request":
            # The webhook Lambda only ever emits event_type "pull_request" for
            # the closed action (see webhook/handler.py normalize()). Teardown
            # runs whoever closed it, so it sits before the Reviewer check.
            self._tear_down(msg)
        elif (msg.get("actor") or "").lower() not in self._allowed_comment_authors:
            # Covers both strangers on public repos and the Agent Account,
            # whose comments would otherwise loop back into the queue.
            logger.info(
                "Ignoring %s on %s#%s from non-allowlisted author @%s",
                msg["event_type"], msg["repo_full_name"], msg["pr_number"], msg.get("actor"),
            )
        else:
            self._deliver_feedback(msg)

        self._processed_ids.record(delivery_id)

    def _tear_down(self, msg: dict[str, Any]) -> None:
        pr_key = f"{msg['repo_full_name']}:{msg['branch']}"
        record = self._agent_file.get(pr_key)
        if record is None:
            logger.info("PR %s closed with no recorded Coordinator; nothing to tear down", pr_key)
            return

        def log(kind: str, detail: str) -> None:
            self._debug_log.write(kind, pr_key, detail, pane_id=record.pane_id)

        def stop_sandbox() -> None:
            self._runtime.stop_sandbox(record.sandbox_name)
            log(TEARDOWN_SANDBOX_STOPPED, f"stopped sandbox {record.sandbox_name}")

        def close_tab() -> None:
            # The tab ID is looked up now: tabs can be renumbered while the
            # Coordinator lives, so the one known at start may be stale.
            info = self._runtime.get_agent_info(record.pane_id)
            if not info.exists:
                log(TEARDOWN_TAB_SKIPPED, f"pane {record.pane_id} is gone; no tab to close")
                return
            self._runtime.close_tab(info.tab_id)
            log(TEARDOWN_TAB_CLOSED, f"closed tab {info.tab_id}")

        def forget() -> None:
            self._agent_file.remove(pr_key)
            log(TEARDOWN_FORGOTTEN, "removed agent file line")

        # Each step is best effort: a failure is logged and the rest still run.
        for step in (stop_sandbox, close_tab, forget):
            try:
                step()
            except (AgentRuntimeError, OSError) as e:
                log(TEARDOWN_STEP_FAILED, f"{step.__name__}: {e}")

    def _deliver_feedback(self, msg: dict[str, Any]) -> None:
        repo_full_name = msg["repo_full_name"]
        pr_number = msg["pr_number"]
        branch = msg.get("branch")
        is_fork = msg.get("is_fork")

        if not branch or is_fork is None:
            # PR Comments carry no branch or fork status; resolving them needs the repo's token.
            repo = self._require_repo_config(repo_full_name, f"{repo_full_name}#{pr_number}")
            if repo is None:
                return
            pr = self._github_for(repo.token).resolve_pull_request(repo_full_name, pr_number)
            branch, is_fork = pr.branch, pr.is_fork

        pr_key = f"{repo_full_name}:{branch}"
        if is_fork:
            # sbx-start <branch> and pushing to origin can't reach a fork's branch.
            self._debug_log.write(FORK_PR_IGNORED, pr_key, f"{repo_full_name}#{pr_number} comes from a fork; no Coordinator used")
            return

        record = self._agent_file.get(pr_key)
        if record is not None and not self._runtime.get_agent_info(record.pane_id).exists:
            # Herdr never reuses pane IDs, so a missing pane means this Coordinator is gone.
            self._log_gone_coordinator(record)
            record = None
        if record is None:
            repo = self._require_repo_config(repo_full_name, pr_key)
            if repo is None:
                return
            record = self._start_coordinator(pr_key, repo, pr_number, branch)

        self._prompt(pr_key, record.pane_id, prompts.feedback_prompt(msg))

    def _prompt(self, pr_key: str, pane_id: str, text: str) -> None:
        """Prompt a Coordinator; a timeout is logged and re-raised so the message is redelivered."""
        try:
            self._runtime.prompt(pane_id, text)
        except PromptTimeout as exc:
            self._debug_log.write(PROMPT_TIMED_OUT, pr_key, str(exc), pane_id=pane_id)
            raise

    def _require_repo_config(self, repo_full_name: str, pr_key: str) -> RepoEntry | None:
        repo = self._repo_config.get(repo_full_name)
        if repo is None:
            self._debug_log.write(
                MISSING_REPO_CONFIG, pr_key,
                f"{repo_full_name} has no clone path and token in the repo config file; no Coordinator started",
            )
        return repo

    def _log_gone_coordinator(self, record: AgentRecord) -> None:
        self._debug_log.write(
            PANE_MISSING, record.pr_key,
            f"herdr reports no pane {record.pane_id}; starting a new Coordinator",
            pane_id=record.pane_id,
        )
        self._debug_log.write(
            SANDBOX_ORPHANED, record.pr_key,
            f"sandbox {record.sandbox_name} left running; stop it by hand",
            pane_id=record.pane_id,
        )

    def _start_coordinator(self, pr_key: str, repo: RepoEntry, pr_number: int, branch: str) -> AgentRecord:
        started = self._runtime.start_coordinator(branch, repo.clone_path)
        self._runtime.set_secret(started.sandbox_name, repo.token)
        self._wait_until_idle(pr_key, started.pane_id)

        record = AgentRecord(pr_key, started.pane_id, started.tab_label, started.sandbox_name)
        self._agent_file.put(record)
        self._prompt(pr_key, record.pane_id, prompts.startup_prompt(repo.repo_full_name, pr_number, branch))
        return record

    def _wait_until_idle(self, pr_key: str, pane_id: str) -> None:
        deadline = time.monotonic() + self._ready_timeout_seconds
        while True:
            info = self._runtime.get_agent_info(pane_id)
            if info.exists and info.agent_status == IDLE:
                return
            if time.monotonic() >= deadline:
                detail = f"pane {pane_id} not idle after {self._ready_timeout_seconds}s (last status: {info.agent_status})"
                self._debug_log.write(NEVER_BECAME_IDLE, pr_key, detail, pane_id=pane_id)
                raise CoordinatorNotReadyError(detail)
            time.sleep(self._ready_poll_interval_seconds)
