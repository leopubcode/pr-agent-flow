"""The repo config file: Operator-maintained and gitignored (see ADR 0002).

One line per watched repository, whitespace-separated:

    owner/repo  /path/to/local/clone  github_pat_...

Blank lines and lines starting with `#` are ignored. A repository with a
missing clone path or token is treated as not configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if fields[0].lower() != repo_full_name.lower():
                continue
            if len(fields) != 3:
                return None
            return RepoEntry(fields[0], Path(fields[1]).expanduser(), fields[2])
        return None
