from pathlib import Path

import pytest
from consumer.config import Config, parse_logins


def test_parse_logins():
    assert parse_logins(" leopubcode, Other-User ,,") == frozenset({"leopubcode", "other-user"})
    assert parse_logins(" , ") == frozenset()


@pytest.fixture
def required_env(monkeypatch):
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example/queue")
    monkeypatch.setenv("ALLOWED_COMMENT_AUTHORS", "octocat")
    monkeypatch.delenv("PR_AGENT_FLOW_HOME", raising=False)


def test_home_defaults_to_dot_pr_agent_flow(required_env, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".pr-agent-flow").mkdir()

    assert Config.from_env().home == tmp_path / ".pr-agent-flow"


def test_every_file_lives_in_home(required_env, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PR_AGENT_FLOW_HOME", str(tmp_path))

    config = Config.from_env()

    assert config.repo_config_path == tmp_path / "repos.json"
    assert config.agent_file_path == tmp_path / "agents.tsv"
    assert config.processed_ids_path == tmp_path / "processed-ids"
    assert config.debug_log_path == tmp_path / "debug.log"
    assert config.consumer_log_path == tmp_path / "consumer.log"


def test_missing_home_stops_startup_and_points_at_the_template(required_env, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PR_AGENT_FLOW_HOME", str(tmp_path / "absent"))

    with pytest.raises(RuntimeError, match="examples/pr-agent-flow-home"):
        Config.from_env()

    assert not (tmp_path / "absent").exists()
