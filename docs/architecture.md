# Architecture

## Flow

```
GitHub PR comment/review
        |
        v
  GitHub webhook  --(HMAC-signed POST)-->  API Gateway --> Lambda (webhook/handler.py)
                                                               |
                                                               v
                                                         SQS (main queue + DLQ)
                                                               |
                                                               v
                                          consumer (long-polls SQS, runs on operator's host)
                                                               |
                     +-----------------------------------------+-----------------------------------------+
                     v                                                                                   v
          new/known branch, PR still open                                                   PR closed/merged
                     |                                                                                   |
                     v                                                                                   v
  ensure git worktree checkout -> ensure tmux session running                            kill tmux session,
  `sbx run claude` -> paste comment context                                              stop sandbox,
  into the pane as a follow-up instruction                                               remove worktree
```

Only one live agent session per PR, keyed by branch name.

## Components

- **`infra/`** — Terraform for the SQS queue + DLQ, the webhook Lambda, API Gateway, IAM
  (a role for the Lambda, a scoped-down IAM user for the consumer), and the GitHub repo
  webhooks themselves (`github.tf`, one per repo in `github_repositories`).
- **`webhook/handler.py`** — Lambda handler. Verifies `X-Hub-Signature-256`, filters for
  the event/action combinations we care about, normalizes them into a small JSON schema,
  and forwards to SQS. Stdlib + boto3 only, so Terraform can zip it with no build step.
- **`consumer/`** — the long-running Python service. Long-polls SQS and, per PR branch:
  - `workspace.py` maintains a local clone + one git worktree per branch, checked out on
    the PR branch. `sbx run claude` runs in direct mode on that worktree, so the agent's
    commits land on the host as they're made. (`sbx` refuses `--clone` inside a worktree.)
  - `tmux_manager.py` owns the one tmux session per branch. `sbx run claude` is the
    pane's own process (no shell underneath), kept as a long-lived interactive REPL, and
    follow-up comments are delivered via `tmux load-buffer`/`paste-buffer`. If the sandbox
    exits, the dead pane is kept for inspection, nothing is pasted into it, and the next
    event logs its last output and starts a fresh session.
  - `state_store.py` is a local sqlite db (`~/.pr-agent-flow/state.db` by default) tracking
    branch -> session/workspace/sandbox state, and a dedup table keyed on GitHub's
    `X-GitHub-Delivery` id (protects against SQS/GitHub redelivery).
  - `dispatcher.py` ties it together: dedup, provision-or-reuse a session, send the
    instruction, or tear down on PR close. Comments and reviews are only acted on when
    their author is in `ALLOWED_COMMENT_AUTHORS` (required, case-insensitive). This keeps
    strangers on public repos from directing the agent, and keeps the agent's own machine
    user from looping its comments back in — so never add that user to the list. PR-close
    events are exempt, so teardown happens whoever closes the PR.
  - `github_client.py` is read-only (resolving branch names, PR metadata) via a PAT —
    pushing commits happens from inside the sandbox using its own injected git
    credentials (see the sandbox's "Git Authentication" behavior), never this client.

## Prompt vs. code split

Code's job stops at "get new comment context in front of the already-running orchestrator
session." Everything else is instructed via prompt (`consumer/consumer/prompts.py`):
- Use the Task tool to spawn a subagent per incoming comment.
- Commit and `git push origin HEAD:<branch>` once currently outstanding comments are
  addressed (explicit refspec, so the push target never depends on upstream config).
- Never merge or close the PR itself.

v1 has no closed-loop confirmation that a push actually happened — accepted tradeoff,
revisit later with e.g. `git ls-remote` polling if needed.

## Known risks / open items

- `sbx stop`/teardown subcommand used in `consumer/consumer/sandbox.py` is unverified
  against the real `sbx` CLI — implemented defensively (log and continue).
- Session readiness is detected by polling `tmux capture-pane` output until it stabilizes
  (`tmux_manager.wait_until_ready`) — there's no structured "ready" signal from `sbx run`/
  `claude` today, so this is a heuristic, not a guarantee.
- Consumer AWS auth is a static IAM user access key in `.env` — fine for a single-operator
  setup; rotate periodically and consider short-lived credentials if this grows beyond
  single-operator use.

## Runbook

1. `openssl rand -hex 32` for a webhook secret; copy `infra/terraform.tfvars.example` to
   `infra/terraform.tfvars` and fill it in (gitignored), including `github_owner` and
   `github_repositories`.
2. `export GITHUB_TOKEN=...` — a PAT with admin rights on those repos (fine-grained:
   "Webhooks: read and write"). Terraform's GitHub provider reads it from the env.
3. `cd infra && terraform init && terraform apply` — this creates the AWS resources *and*
   installs the webhook (`infra/github.tf`) on each listed repo, pointed at the API Gateway
   endpoint with the shared secret. Note the `sqs_queue_url` and
   `consumer_access_key_id`/`consumer_secret_access_key` outputs (`terraform output -json`
   to see sensitive ones).
4. Copy `.env.example` to `consumer/.env` and fill in `GITHUB_TOKEN` (a PAT), the AWS
   creds + `SQS_QUEUE_URL` from step 2, `WORKSPACE_ROOT`, and `ALLOWED_COMMENT_AUTHORS`
   (comma-separated logins allowed to direct the agent).
5. `pip install -e consumer/` then `pr-agent-consumer` (or `python -m consumer.main`) on
   the host that has `sbx`/docker sandboxes and `tmux` available.
6. Comment on an open PR. Watch it land: `aws sqs receive-message --queue-url <url>` (it
   should already be gone once the consumer picks it up), then `tmux attach -t
   <branch-name>` to watch the orchestrator work.
