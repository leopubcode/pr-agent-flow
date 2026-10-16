"""The repo config file: `repos.json` in PR_AGENT_FLOW_HOME, Operator-maintained (see ADR 0002).

A JSON object keyed by `owner/repo`, one entry per watched repository:

    {
      "owner/repo": {"clone_path": "/path/to/local/clone", "token": "github_pat_..."}
    }

A repository that is absent, or whose entry lacks a non-empty `clone_path` or
`token`, is treated as not configured. A file that isn't a JSON object raises
`RepoConfigError`, so the message is retried once the Operator fixes it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class RepoConfigError(ValueError):
    """The repo config file exists but can't be read as a JSON object."""


@dataclass(frozen=True)
class RepoEntry:
    repo_full_name: str
    clone_path: Path
    token: str


class RepoConfig:
    def __init__(self, path: Path):
        self._path = Path(path)

    def get(self, repo_full_name: str) -> RepoEntry | None:
        """The entry for `owner/repo`, or None if it's absent or incomplete.

        Re-read on every call so the Operator can edit the file while the
        consumer runs.
        """
        if not self._path.exists():
            return None
        try:
            repos = json.loads(self._path.read_text())
        except json.JSONDecodeError as e:
            raise RepoConfigError(f"{self._path} is not valid JSON: {e}") from e
        if not isinstance(repos, dict):
            raise RepoConfigError(f"{self._path} must be a JSON object keyed by owner/repo")
        for name, entry in repos.items():
            if name.lower() != repo_full_name.lower():
                continue
            if not isinstance(entry, dict):
                return None
            clone_path, token = entry.get("clone_path"), entry.get("token")
            if not _non_empty_str(clone_path) or not _non_empty_str(token):
                return None
            return RepoEntry(name, Path(clone_path).expanduser(), token)
        return None


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
