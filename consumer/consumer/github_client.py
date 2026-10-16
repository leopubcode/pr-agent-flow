from __future__ import annotations

from dataclasses import dataclass

from github import Github


@dataclass
class PullRequestInfo:
    branch: str
    base_branch: str
    clone_url: str


class GithubClient:
    """Thin wrapper used only for read-side lookups.

    Pushing commits happens from inside the sandbox using its own
    injected git credentials -- this client never touches the push path.
    """

    def __init__(self, token: str):
        """`token` is the repository's own fine-grained token from the repo config file."""
        self._gh = Github(token)

    def resolve_pull_request(self, repo_full_name: str, pr_number: int) -> PullRequestInfo:
        repo = self._gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        return PullRequestInfo(
            branch=pr.head.ref,
            base_branch=pr.base.ref,
            clone_url=repo.clone_url,
        )
