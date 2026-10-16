import json
from pathlib import Path

import pytest
from consumer.repo_config import RepoConfig, RepoConfigError, RepoEntry


def write(path: Path, data) -> RepoConfig:
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return RepoConfig(path)


def test_entry_is_read_by_owner_repo(tmp_path):
    config = write(tmp_path / "repos.json", {
        "org/repo": {"clone_path": "/clones/repo", "token": "tok-repo"},
        "org/other": {"clone_path": "/clones/other", "token": "tok-other"},
    })

    assert config.get("org/other") == RepoEntry("org/other", Path("/clones/other"), "tok-other")


def test_lookup_ignores_case_like_github(tmp_path):
    config = write(tmp_path / "repos.json", {"Org/Repo": {"clone_path": "/c", "token": "t"}})

    assert config.get("org/repo") == RepoEntry("Org/Repo", Path("/c"), "t")


def test_clone_path_expands_home(tmp_path):
    config = write(tmp_path / "repos.json", {"org/repo": {"clone_path": "~/dev/repo", "token": "t"}})

    assert config.get("org/repo").clone_path == Path("~/dev/repo").expanduser()


@pytest.mark.parametrize("entry", [
    {"clone_path": "/clones/repo"},
    {"token": "t"},
    {"clone_path": "", "token": "t"},
    {"clone_path": "/clones/repo", "token": "  "},
    {"clone_path": 3, "token": "t"},
    "not an object",
])
def test_incomplete_entry_is_not_configured(tmp_path, entry):
    config = write(tmp_path / "repos.json", {"org/repo": entry})

    assert config.get("org/repo") is None


def test_absent_repository_or_missing_file_is_not_configured(tmp_path):
    config = write(tmp_path / "repos.json", {"org/repo": {"clone_path": "/c", "token": "t"}})

    assert config.get("org/unknown") is None
    assert RepoConfig(tmp_path / "missing.json").get("org/repo") is None


@pytest.mark.parametrize("content", ["{not json", "[]", '"org/repo"'])
def test_unreadable_file_raises_so_the_message_is_retried(tmp_path, content):
    config = write(tmp_path / "repos.json", content)

    with pytest.raises(RepoConfigError):
        config.get("org/repo")


def test_edits_apply_without_restarting(tmp_path):
    path = tmp_path / "repos.json"
    config = write(path, {})
    assert config.get("org/repo") is None

    write(path, {"org/repo": {"clone_path": "/c", "token": "t"}})

    assert config.get("org/repo") is not None
