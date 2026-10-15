from __future__ import annotations

from typing import Any

SYSTEM_PROMPT_TEMPLATE = """\
You are the orchestrator agent for pull request #{pr_number} in {repo_full_name} \
(branch `{branch}`). You will receive a stream of messages over this session, each \
describing a new PR comment or review that needs addressing.

For each incoming comment:
- Use the Task tool to launch a subagent dedicated to that one comment.
- Once the currently outstanding comments are addressed, commit your changes and \
push them with `git push origin HEAD:{branch}`. Git credentials are already \
configured in this sandbox -- do not attempt `gh auth login` or look for a token.
- Never merge or close this pull request yourself.

Wait for the first comment below.
"""

FOLLOWUP_TEMPLATE = """\
New {event_type} on PR #{pr_number} from @{actor}:

{body}
{location}
Link: {html_url}

Address this with a dedicated subagent, per your instructions.
"""


def initial_system_prompt(repo_full_name: str, pr_number: int, branch: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(repo_full_name=repo_full_name, pr_number=pr_number, branch=branch)


def followup_prompt(msg: dict[str, Any]) -> str:
    location = ""
    if msg.get("file_path"):
        location = f"File: {msg['file_path']}:{msg.get('line')}\n"
        if msg.get("diff_hunk"):
            location += f"Diff context:\n{msg['diff_hunk']}\n"

    return FOLLOWUP_TEMPLATE.format(
        event_type=msg["event_type"],
        pr_number=msg["pr_number"],
        actor=msg["actor"],
        body=msg["body"] or "(no comment body)",
        location=location,
        html_url=msg["html_url"],
    )
