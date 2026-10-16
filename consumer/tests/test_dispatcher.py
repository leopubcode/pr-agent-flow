from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from consumer.agent_file import AgentFile
from consumer.agent_runtime import AgentRuntimeError, PromptTimeout
from consumer.debug_log import DebugLog
from consumer.dispatcher import Dispatcher
from consumer.github_client import PullRequestInfo
from consumer.processed_ids import ProcessedIds
from consumer.repo_config import RepoConfig

from .fake_agent_runtime import FakeAgentRuntime

RETENTION_DAYS = 7


class FakeGithub:
    """Fake GitHub client factory: `github_for(token)` returns a client bound to that token."""

    def __init__(self):
        self.branches: dict[tuple[str, int], str] = {("org/repo", 1): "feature/x"}
        self.lookups: list[tuple[str, int, str]] = []
        self.forks: set[tuple[str, int]] = set()

    def __call__(self, token: str):
        fake = self

        class _Client:
            def resolve_pull_request(self, repo_full_name, pr_number):
                fake.lookups.append((repo_full_name, pr_number, token))
                return PullRequestInfo(
                    branch=fake.branches[(repo_full_name, pr_number)],
                    base_branch="main",
                    clone_url=f"https://github.com/{repo_full_name}.git",
                    is_fork=(repo_full_name, pr_number) in fake.forks,
                )

        return _Client()


class Env:
    def __init__(self, tmp_path: Path, ready_timeout_seconds: float = 5):
        self.tmp = tmp_path
        self.runtime = FakeAgentRuntime()
        self.github = FakeGithub()
        self.repo_config_path = tmp_path / "repos.txt"
        self.agent_file_path = tmp_path / "agents.tsv"
        self.debug_log_path = tmp_path / "debug.log"
        self.clone = tmp_path / "clones" / "repo"
        self.other_clone = tmp_path / "clones" / "other"
        self.repo_config_path.write_text(
            "# owner/repo  clone path  token\n"
            f"org/repo\t{self.clone}\ttok-repo\n"
            f"org/other {self.other_clone} tok-other\n"
        )
        self.processed_ids_path = tmp_path / "processed-ids"
        self.dispatcher = Dispatcher(
            runtime=self.runtime,
            github_for=self.github,
            repo_config=RepoConfig(self.repo_config_path),
            agent_file=AgentFile(self.agent_file_path),
            debug_log=DebugLog(self.debug_log_path),
            processed_ids=ProcessedIds(self.processed_ids_path, retention_days=RETENTION_DAYS),
            ready_timeout_seconds=ready_timeout_seconds,
            ready_poll_interval_seconds=0,
            allowed_comment_authors=frozenset({"octocat"}),
        )

    def agent_lines(self) -> list[list[str]]:
        if not self.agent_file_path.exists():
            return []
        return [line.split("\t") for line in self.agent_file_path.read_text().splitlines()]

    def debug_lines(self) -> list[str]:
        if not self.debug_log_path.exists():
            return []
        return self.debug_log_path.read_text().splitlines()


    def processed_ids(self) -> list[str]:
        if not self.processed_ids_path.exists():
            return []
        return [line.split()[0] for line in self.processed_ids_path.read_text().splitlines()]


@pytest.fixture
def env(tmp_path: Path):
    return Env(tmp_path)


def make_comment(delivery_id="d1", branch="feature/x", repo="org/repo", body="please fix this", **overrides):
    msg = {
        "schema_version": 1,
        "delivery_id": delivery_id,
        "event_type": "pull_request_review_comment",
        "repo_full_name": repo,
        "pr_number": 1,
        "branch": branch,
        "base_branch": "main",
        "is_merged": False,
        "is_fork": False,
        "actor": "octocat",
        "body": body,
        "html_url": f"https://github.com/{repo}/pull/1#discussion_r1",
        "file_path": "src/app.py",
        "line": 12,
        "diff_hunk": "@@ -1 +1 @@",
        "received_at": "2026-01-01T00:00:00Z",
    }
    msg.update(overrides)
    return msg


def test_first_feedback_starts_a_coordinator_then_delivers_startup_prompt_and_feedback(env):
    env.dispatcher.handle_message(make_comment(body="rename this variable"))

    assert env.runtime.started() == [("start_coordinator", "feature/x", env.clone)]
    assert env.runtime.secrets == {"sbx-1": "tok-repo"}
    assert env.runtime.call_names() == ["start_coordinator", "set_secret", "prompt", "prompt"]
    assert env.agent_lines() == [["org/repo:feature/x", "pane-1", "feature/x sbx-1", "sbx-1"]]

    startup, feedback = env.runtime.prompts["pane-1"]
    assert "org/repo" in startup and "#1" in startup
    assert "git push origin HEAD:feature/x" in startup
    assert "rename this variable" in feedback
    assert "src/app.py:12" in feedback


def test_new_coordinator_is_not_prompted_until_it_reports_idle(env):
    env.runtime.starting_statuses = ("starting", "working", "working")
    env.dispatcher.handle_message(make_comment())

    calls = [c[0] for c in env.runtime.calls]
    first_prompt = calls.index("prompt")
    assert calls[:first_prompt].count("get_agent_info") == 4  # three busy, then idle


def test_later_feedback_prompts_the_existing_coordinator(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1", body="first"))
    env.runtime.panes["pane-1"] = ["working"]  # busy agents are still prompted

    env.dispatcher.handle_message(make_comment(delivery_id="d2", body="second"))

    assert len(env.runtime.started()) == 1
    assert len(env.runtime.prompts["pane-1"]) == 3
    assert "second" in env.runtime.prompts["pane-1"][-1]
    assert len(env.agent_lines()) == 1


def test_feedback_for_a_coordinator_whose_pane_is_gone_starts_a_new_one(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1", body="first"))
    env.runtime.remove_pane("pane-1")

    env.dispatcher.handle_message(make_comment(delivery_id="d2", body="second"))

    assert len(env.runtime.started()) == 2
    startup, feedback = env.runtime.prompts["pane-2"]
    assert "HEAD:feature/x" in startup
    assert "second" in feedback
    assert env.agent_lines() == [["org/repo:feature/x", "pane-2", "feature/x sbx-2", "sbx-2"]]


def test_replacing_a_gone_pane_logs_it_and_leaves_the_old_sandbox_running_as_orphaned(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    env.runtime.remove_pane("pane-1")

    env.dispatcher.handle_message(make_comment(delivery_id="d2"))

    assert "stop_sandbox" not in env.runtime.call_names()
    lines = [line.split("\t") for line in env.debug_lines()]
    assert [(pr_key, pane, kind) for _, pr_key, pane, kind, _ in lines] == [
        ("org/repo:feature/x", "pane-1", "pane missing"),
        ("org/repo:feature/x", "pane-1", "sandbox orphaned"),
    ]
    assert "sbx-1" in lines[1][4]


@pytest.mark.parametrize("status", ["idle", "working", "blocked", "done", "unknown"])
def test_coordinator_whose_pane_exists_is_never_replaced_whatever_its_status(env, status):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    env.runtime.panes["pane-1"] = [status]

    env.dispatcher.handle_message(make_comment(delivery_id="d2", body="second"))

    assert len(env.runtime.started()) == 1
    assert "second" in env.runtime.prompts["pane-1"][-1]
    assert env.agent_lines() == [["org/repo:feature/x", "pane-1", "feature/x sbx-1", "sbx-1"]]
    assert env.debug_lines() == []


def test_same_branch_in_two_repositories_gets_separate_coordinators(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1", repo="org/repo"))
    env.dispatcher.handle_message(make_comment(delivery_id="d2", repo="org/other"))

    assert env.runtime.started() == [
        ("start_coordinator", "feature/x", env.clone),
        ("start_coordinator", "feature/x", env.other_clone),
    ]
    assert env.runtime.secrets == {"sbx-1": "tok-repo", "sbx-2": "tok-other"}
    assert [line[:2] for line in env.agent_lines()] == [
        ["org/repo:feature/x", "pane-1"],
        ["org/other:feature/x", "pane-2"],
    ]


@pytest.mark.parametrize("config_line", [None, "org/unknown\t/clones/unknown", "org/unknown"])
def test_repository_without_clone_path_and_token_gets_no_coordinator(env, config_line):
    if config_line:
        env.repo_config_path.write_text(env.repo_config_path.read_text() + config_line + "\n")

    env.dispatcher.handle_message(make_comment(repo="org/unknown"))

    assert env.runtime.calls == []
    assert env.agent_lines() == []
    [line] = env.debug_lines()
    _timestamp, pr_key, pane_id, kind, detail = line.split("\t")
    assert (pr_key, pane_id, kind) == ("org/unknown:feature/x", "-", "missing repo config")
    assert "org/unknown" in detail


def test_pr_comment_branch_is_resolved_with_the_repos_own_token(env):
    env.github.branches[("org/other", 1)] = "fix/y"
    env.dispatcher.handle_message(
        make_comment(event_type="issue_comment", repo="org/other", branch=None, file_path=None, line=None)
    )

    assert env.github.lookups == [("org/other", 1, "tok-other")]
    assert env.runtime.started() == [("start_coordinator", "fix/y", env.other_clone)]
    assert env.agent_lines()[0][0] == "org/other:fix/y"


def test_pr_comment_on_unconfigured_repository_is_logged_and_not_looked_up(env):
    env.dispatcher.handle_message(make_comment(event_type="issue_comment", repo="org/unknown", branch=None))

    assert env.github.lookups == []
    assert env.runtime.calls == []
    assert env.debug_lines()[0].split("\t")[3] == "missing repo config"


def test_feedback_from_non_reviewer_is_ignored(env):
    env.dispatcher.handle_message(make_comment(actor="leopubcode-agent"))

    assert env.runtime.calls == []
    assert env.agent_lines() == []


def test_reviewer_allowlist_is_case_insensitive(env):
    env.dispatcher.handle_message(make_comment(actor="OctoCat"))

    assert len(env.runtime.started()) == 1


def test_duplicate_delivery_is_delivered_once(env):
    env.dispatcher.handle_message(make_comment(delivery_id="dup"))
    env.dispatcher.handle_message(make_comment(delivery_id="dup"))

    assert len(env.runtime.started()) == 1
    assert len(env.runtime.prompts["pane-1"]) == 2


def test_empty_allowlist_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        Dispatcher(
            processed_ids=ProcessedIds(tmp_path / "p", RETENTION_DAYS), runtime=FakeAgentRuntime(), github_for=FakeGithub(),
            repo_config=RepoConfig(tmp_path / "r"), agent_file=AgentFile(tmp_path / "a"),
            debug_log=DebugLog(tmp_path / "d"), ready_timeout_seconds=5,
            allowed_comment_authors=frozenset(),
        )


def test_feedback_from_non_reviewer_is_still_recorded_as_processed(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1", actor="stranger"))

    assert env.processed_ids() == ["d1"]


def test_delivery_already_in_processed_ids_file_is_skipped(env):
    recent = datetime.now(UTC) - timedelta(hours=1)
    env.processed_ids_path.write_text(f"seen-1 {recent.isoformat()}\n")

    env.dispatcher.handle_message(make_comment(delivery_id="seen-1", branch=None))

    assert env.runtime.calls == []
    assert env.github.lookups == []


def test_handled_delivery_is_recorded_with_timestamp(env):
    before = datetime.now(UTC)

    env.dispatcher.handle_message(make_comment(delivery_id="d1"))

    [line] = env.processed_ids_path.read_text().splitlines()
    delivery_id, stamp = line.split()
    assert delivery_id == "d1"
    assert before <= datetime.fromisoformat(stamp) <= datetime.now(UTC)


def test_entries_older_than_retention_are_pruned(env):
    now = datetime.now(UTC)
    stale = now - timedelta(days=RETENTION_DAYS, hours=1)
    fresh = now - timedelta(days=RETENTION_DAYS - 1)
    env.processed_ids_path.write_text(f"old-1 {stale.isoformat()}\nkept-1 {fresh.isoformat()}\n")

    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    assert env.processed_ids() == ["kept-1", "d1"]

    env.dispatcher.handle_message(make_comment(delivery_id="old-1", body="handled again"))
    assert "handled again" in env.runtime.prompts["pane-1"][-1]


def test_message_that_raises_is_not_recorded_and_is_handled_again_on_redelivery(tmp_path):
    env = Env(tmp_path, ready_timeout_seconds=0)
    env.runtime.starting_statuses = ("starting",)  # not idle by the (zero) deadline
    with pytest.raises(AgentRuntimeError):
        env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    assert env.processed_ids() == []

    env.runtime.starting_statuses = ()
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    assert env.processed_ids() == ["d1"]


@pytest.mark.parametrize("event_type", ["pull_request_review", "pull_request_review_comment"])
def test_feedback_on_fork_pr_is_skipped_and_logged(env, event_type):
    env.dispatcher.handle_message(make_comment(event_type=event_type, is_fork=True))

    assert env.runtime.calls == []
    assert env.agent_lines() == []
    [line] = env.debug_lines()
    _timestamp, pr_key, pane_id, kind, _detail = line.split("\t")
    assert (pr_key, pane_id, kind) == ("org/repo:feature/x", "-", "fork PR ignored")


def test_pr_comment_on_fork_pr_is_resolved_through_github_then_skipped_and_logged(env):
    env.github.forks.add(("org/repo", 1))

    env.dispatcher.handle_message(make_comment(event_type="issue_comment", branch=None, file_path=None, line=None))

    assert env.github.lookups == [("org/repo", 1, "tok-repo")]
    assert env.runtime.calls == []
    assert env.agent_lines() == []
    [line] = env.debug_lines()
    assert line.split("\t")[1:4] == ["org/repo:feature/x", "-", "fork PR ignored"]


def test_review_without_fork_status_is_checked_through_github(env):
    env.github.forks.add(("org/repo", 1))
    msg = make_comment(event_type="pull_request_review", file_path=None, line=None)
    del msg["is_fork"]  # sent by a webhook that predates fork detection

    env.dispatcher.handle_message(msg)

    assert env.github.lookups == [("org/repo", 1, "tok-repo")]
    assert env.runtime.calls == []
    assert env.debug_lines()[0].split("\t")[3] == "fork PR ignored"


def test_prompt_timeout_on_existing_coordinator_is_logged_and_raised_without_starting_another(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    env.runtime.timing_out_panes.add("pane-1")

    with pytest.raises(PromptTimeout):
        env.dispatcher.handle_message(make_comment(delivery_id="d2", body="second"))

    assert len(env.runtime.started()) == 1
    assert env.processed_ids() == ["d1"]
    [line] = env.debug_lines()
    _, pr_key, pane_id, kind, _ = line.split("\t")
    assert (pr_key, pane_id, kind) == ("org/repo:feature/x", "pane-1", "prompt timed out")


def test_startup_prompt_timeout_is_logged_and_redelivery_reuses_the_same_coordinator(env):
    env.runtime.timing_out_panes.add("pane-1")

    with pytest.raises(PromptTimeout):
        env.dispatcher.handle_message(make_comment(delivery_id="d1"))

    assert env.processed_ids() == []
    [line] = env.debug_lines()
    assert line.split("\t")[2:4] == ["pane-1", "prompt timed out"]

    env.runtime.timing_out_panes.clear()
    env.dispatcher.handle_message(make_comment(delivery_id="d1", body="redelivered"))

    assert len(env.runtime.started()) == 1
    assert "redelivered" in env.runtime.prompts["pane-1"][-1]
    assert env.processed_ids() == ["d1"]


def test_new_coordinator_that_never_becomes_idle_is_logged_and_raised(tmp_path):
    env = Env(tmp_path, ready_timeout_seconds=0)
    env.runtime.starting_statuses = ("starting",)

    with pytest.raises(AgentRuntimeError):
        env.dispatcher.handle_message(make_comment(delivery_id="d1"))

    assert env.runtime.prompts["pane-1"] == []
    assert env.processed_ids() == []
    [line] = env.debug_lines()
    _, pr_key, pane_id, kind, _ = line.split("\t")
    assert (pr_key, pane_id, kind) == ("org/repo:feature/x", "pane-1", "never became idle")


def make_close(delivery_id="c1", branch="feature/x", repo="org/repo", **overrides):
    msg = {
        "schema_version": 1,
        "delivery_id": delivery_id,
        "event_type": "pull_request",
        "repo_full_name": repo,
        "pr_number": 1,
        "branch": branch,
        "base_branch": "main",
        "is_merged": False,
        "actor": "octocat",
        "received_at": "2026-01-01T00:00:00Z",
    }
    msg.update(overrides)
    return msg


@pytest.mark.parametrize("is_merged", [False, True])
def test_closing_a_pr_stops_its_sandbox_closes_its_tab_and_forgets_it(env, is_merged):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))

    env.dispatcher.handle_message(make_close(is_merged=is_merged))

    assert env.runtime.call_names()[-2:] == ["stop_sandbox", "close_tab"]
    assert ("stop_sandbox", "sbx-1") in env.runtime.calls
    assert ("close_tab", "tab-1") in env.runtime.calls
    assert env.agent_lines() == []


def test_teardown_runs_when_a_non_reviewer_closes_the_pr(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))

    env.dispatcher.handle_message(make_close(actor="stranger"))

    assert ("stop_sandbox", "sbx-1") in env.runtime.calls
    assert env.agent_lines() == []


def test_missing_pane_skips_the_tab_step_but_still_stops_sandbox_and_forgets_it(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    env.runtime.remove_pane("pane-1")  # the Operator closed it by hand

    env.dispatcher.handle_message(make_close())

    assert ("stop_sandbox", "sbx-1") in env.runtime.calls
    assert "close_tab" not in env.runtime.call_names()
    assert env.agent_lines() == []
    kinds = [line.split("\t")[1:4] for line in env.debug_lines()]
    assert ["org/repo:feature/x", "pane-1", "teardown tab skipped"] in kinds


@pytest.mark.parametrize("failing_step", ["stop_sandbox", "close_tab"])
def test_a_failing_teardown_step_is_logged_and_later_steps_still_run(env, failing_step):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    env.runtime.failing.add(failing_step)

    env.dispatcher.handle_message(make_close())

    assert env.runtime.call_names()[-2:] == ["stop_sandbox", "close_tab"]
    assert env.agent_lines() == []
    failures = [line.split("\t") for line in env.debug_lines() if line.split("\t")[3] == "teardown step failed"]
    assert len(failures) == 1
    assert failing_step in failures[0][4]
    assert env.processed_ids()[-1] == "c1"


def test_closing_a_pr_with_no_recorded_coordinator_does_nothing(env, caplog):
    with caplog.at_level("INFO"):
        env.dispatcher.handle_message(make_close())

    assert env.runtime.calls == []
    assert env.debug_lines() == []
    assert "org/repo:feature/x" in caplog.text
    assert env.processed_ids() == ["c1"]


def test_feedback_after_close_starts_a_fresh_coordinator(env):
    env.dispatcher.handle_message(make_comment(delivery_id="d1"))
    env.dispatcher.handle_message(make_close())

    env.dispatcher.handle_message(make_comment(delivery_id="d2", body="after reopen"))

    assert len(env.runtime.started()) == 2
    assert env.agent_lines() == [["org/repo:feature/x", "pane-2", "feature/x sbx-2", "sbx-2"]]
    assert "after reopen" in env.runtime.prompts["pane-2"][-1]
