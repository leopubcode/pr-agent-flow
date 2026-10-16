# Herdr and `sbx-start` manage Coordinators, not tmux and worktrees

The first version ran each Coordinator as `sbx run claude` inside a tmux session, on a git worktree the consumer kept per branch, tracked in sqlite. We are replacing that with herdr: `sbx-start`, run from the repository's clone, starts a sandbox in clone mode inside a herdr pane, and the consumer only remembers one line per PR Key (pane ID, tab label, sandbox name) in a local text file. Herdr already offers an `sbx` plugin and a CLI to read, prompt and inspect agents, so the consumer no longer owns checkouts, terminal sessions or readiness heuristics.

## Consequences

- We assume herdr never reuses pane IDs. A stored pane that no longer exists means the Coordinator is gone, so a new one is started and the event is written to the debug log. The old sandbox is left running and logged as orphaned.
- `sbx-start` takes no branch, so the sandbox starts on whatever the Operator's clone has checked out. The startup prompt tells the Coordinator to fetch and check out the pull request's branch itself before acting on any Feedback, and to refuse Feedback if that fails.
- A prompt that times out is logged, and no replacement Coordinator is started. This is deliberately simple for v1, to be revisited.
