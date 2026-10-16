"""PR Keys: the identity of a pull request, `owner/repo:branch` (see GLOSSARY.md)."""
from __future__ import annotations

UNKNOWN_BRANCH = "-"


def pr_key(repo_full_name: str, branch: str | None) -> str:
    """The PR Key for a repository and head branch.

    When the branch isn't known yet (a PR Comment whose branch couldn't be looked up), the
    branch is the `-` placeholder, matching the debug log's placeholder for a missing pane ID.
    Such a key only ever appears in the debug log, never in the agent file.
    """
    return f"{repo_full_name}:{branch or UNKNOWN_BRANCH}"
