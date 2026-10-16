from pathlib import Path

import pytest

from consumer.agent_file import AgentFile
from consumer.debug_log import DebugLog
from consumer.dispatcher import Dispatcher
from consumer.github_client import PullRequestInfo
from consumer.repo_config import RepoConfig
from consumer.state_store import StateStore

from .fake_agent_runtime import FakeAgentRuntime


class FakeGithub:
    """Fake GitHub client factory: `github_for(token)` returns a client bound to that token."""

    def __init__(self):
        self.branches: dict[tuple[str, int], str] = {("org/repo", 1): "feature/x"}
        self.lookups: list[tuple[str, int, str]] = []

    def __call__(self, token: str):
        fake = self

        class _Client:
            def resolve_pull_request(self, repo_full_name, pr_number):
                fake.lookups.append((repo_full_name, pr_number, token))
                return PullRequestInfo(
                    branch=fake.branches[(repo_full_name, pr_number)],
                    base_branch="main",
                    clone_url=f"https://github.com/{repo_full_name}.git",
                )

        return _Client()


class Env:
    def __init__(self, tmp_path: Path):
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
        self.state = StateStore(tmp_path / "state.db")
        self.dispatcher = Dispatcher(
            state=self.state,
            runtime=self.runtime,
            github_for=self.github,
            repo_config=RepoConfig(self.repo_config_path),
            agent_file=AgentFile(self.agent_file_path),
            debug_log=DebugLog(self.debug_log_path),
            ready_timeout_seconds=5,
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


@pytest.fixture
def env(tmp_path: Path):
    e = Env(tmp_path)
    yield e
    e.state.close()


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
            state=StateStore(tmp_path / "s.db"), runtime=FakeAgentRuntime(), github_for=FakeGithub(),
            repo_config=RepoConfig(tmp_path / "r"), agent_file=AgentFile(tmp_path / "a"),
            debug_log=DebugLog(tmp_path / "d"), ready_timeout_seconds=5,
            allowed_comment_authors=frozenset(),
        )
