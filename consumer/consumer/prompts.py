from __future__ import annotations

from typing import Any

STARTUP_PROMPT_TEMPLATE = """\
You are the Coordinator for pull request #{pr_number} in {repo_full_name} \
(branch `{branch}`). Feedback on this pull request (PR comments, reviews and \
inline review comments) will be sent to you here, as new messages, as it arrives.

For each piece of Feedback:
- Hand it to exactly one Implementer: launch a subagent with the Task tool \
dedicated to that one piece of Feedback. Run Implementers one at a time, never \
in parallel.
- When that Implementer finishes, commit its changes and push them with \
`git push origin HEAD:{branch}` before starting the next one.
- Git credentials for this repository are already injected into this sandbox. \
Rely on them; do not run `gh auth login` or look for a token.
- Never merge or close this pull request.

More Feedback will keep arriving over time. Wait for the next message.
"""

FEEDBACK_TEMPLATE = """\
New {event_type} on PR #{pr_number} from @{actor}:

{body}
{location}
Link: {html_url}

Address this with one Implementer, per your instructions.
"""


def startup_prompt(repo_full_name: str, pr_number: int, branch: str) -> str:
    return STARTUP_PROMPT_TEMPLATE.format(repo_full_name=repo_full_name, pr_number=pr_number, branch=branch)


def feedback_prompt(msg: dict[str, Any]) -> str:
    location = ""
    if msg.get("file_path"):
        location = f"File: {msg['file_path']}:{msg.get('line')}\n"
        if msg.get("diff_hunk"):
            location += f"Diff context:\n{msg['diff_hunk']}\n"

    return FEEDBACK_TEMPLATE.format(
        event_type=msg["event_type"],
        pr_number=msg["pr_number"],
        actor=msg["actor"],
        body=msg["body"] or "(no comment body)",
        location=location,
        html_url=msg["html_url"],
    )
