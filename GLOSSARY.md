# PR Agent Flow

Listens for review activity on GitHub pull requests and hands it to a long-lived coding agent working on that pull request's branch.

## Language

### Feedback

**Feedback**:
Any GitHub activity on a pull request that the agent should act on. It comes in exactly three kinds: PR Comment, Review and Review Comment.
_Avoid_: Comment (as the umbrella term), instruction, event

**PR Comment**:
A top-level comment in a pull request's conversation, not attached to any line of code.
_Avoid_: Issue comment

**Review**:
A submitted pull request review. It counts as Feedback only when its body has text; an empty approval or an empty review wrapper is not Feedback.

**Review Comment**:
An inline comment attached to a file and line in a pull request's diff, arriving on its own even when it belongs to a Review.
_Avoid_: Line comment, diff comment

### Pull requests

**PR Key**:
The identity of a pull request in this system: its repository plus its head branch (`owner/repo:branch`). Only pull requests whose head branch lives in the same repository are in scope; pull requests from forks are ignored.
_Avoid_: Branch name (on its own), PR number

### People

**Operator**:
The person who runs the consumer on their own machine and owns its configuration and tokens.

**Reviewer**:
A GitHub user on the allowlist whose Feedback the Coordinator acts on. Anyone else's activity is ignored, except closing a pull request.
_Avoid_: Allowed author, user

**Agent Account**:
The GitHub identity behind a repository's token, which the Coordinator and its Implementers use to read the pull request and push commits.
_Avoid_: Bot, machine user

### Agents

**Coordinator**:
The long-lived agent assigned to one pull request. It receives each piece of Feedback as it arrives and hands it to an Implementer; it never merges or closes the pull request.
_Avoid_: Orchestrator, session, pane, sandbox, container

**Implementer**:
A subagent the Coordinator starts to address exactly one piece of Feedback.
_Avoid_: Subagent (in domain language), worker
