from pathlib import Path

import pytest

from consumer.config import Config, parse_logins


def test_parse_logins():
    assert parse_logins(" leopubcode, Other-User ,,") == frozenset({"leopubcode", "other-user"})
    assert parse_logins(" , ") == frozenset()


@pytest.fixture
def required_env(monkeypatch):
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example/queue")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_COMMENT_AUTHORS", "octocat")
    monkeypatch.delenv("PROCESSED_IDS_PATH", raising=False)


def test_processed_ids_path_defaults_to_home_state_dir(required_env):
    assert Config.from_env().processed_ids_path == Path("~/.pr-agent-flow/processed-ids").expanduser()


def test_processed_ids_path_is_configurable(required_env, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PROCESSED_IDS_PATH", str(tmp_path / "ids"))
    assert Config.from_env().processed_ids_path == tmp_path / "ids"
