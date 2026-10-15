from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class Workspace:
    """Manages one local clone per repo, with a git worktree per branch.

    `sbx run claude --branch BRANCH_NAME` mounts the invoking shell's cwd,
    so the consumer must have a real checkout of the branch on disk before
    launching the sandbox.
    """

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _repo_dir(self, repo_full_name: str) -> Path:
        return self._root / "repos" / repo_full_name.replace("/", "__")

    def _worktree_dir(self, repo_full_name: str, branch: str) -> Path:
        safe_branch = branch.replace("/", "__")
        return self._root / "worktrees" / repo_full_name.replace("/", "__") / safe_branch

    def ensure_branch_checkout(self, repo_full_name: str, clone_url: str, branch: str) -> Path:
        """Ensure a bare-ish clone of the repo exists and return a worktree path checked out to `branch`."""
        repo_dir = self._repo_dir(repo_full_name)
        if not repo_dir.exists():
            repo_dir.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Cloning %s into %s", repo_full_name, repo_dir)
            subprocess.run(["git", "clone", clone_url, str(repo_dir)], check=True)
        else:
            subprocess.run(["git", "-C", str(repo_dir), "fetch", "origin"], check=True)

        worktree_dir = self._worktree_dir(repo_full_name, branch)
        if not worktree_dir.exists():
            worktree_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "-C", str(repo_dir), "worktree", "add", str(worktree_dir), f"origin/{branch}"],
                check=True,
            )
        else:
            subprocess.run(["git", "-C", str(worktree_dir), "fetch", "origin"], check=True)
            subprocess.run(
                ["git", "-C", str(worktree_dir), "reset", "--hard", f"origin/{branch}"], check=True
            )

        return worktree_dir

    def cleanup(self, repo_full_name: str, branch: str) -> None:
        repo_dir = self._repo_dir(repo_full_name)
        worktree_dir = self._worktree_dir(repo_full_name, branch)
        if worktree_dir.exists():
            subprocess.run(
                ["git", "-C", str(repo_dir), "worktree", "remove", "--force", str(worktree_dir)],
                check=False,
            )
