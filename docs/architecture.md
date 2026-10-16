# Architecture

Terms in **bold** are defined in [`GLOSSARY.md`](../GLOSSARY.md). Design decisions are in
[ADR 0001](adr/0001-herdr-and-sbx-start-manage-agents.md) (herdr and `sbx-start` manage
Coordinators) and [ADR 0002](adr/0002-per-repo-token-per-sandbox.md) (each sandbox gets its own
repository's token).

## Flow

```
GitHub PR Comment / Review / Review Comment / PR closed
        |
        v
  GitHub webhook  --(HMAC-signed POST)-->  API Gateway --> Lambda (webhook/handler.py)
                                                               |
                                                               v
                                                         SQS (main queue + DLQ)
                                                               |
                                                               v
                                  consumer (long-polls SQS on the Operator's host, one message at a time)
                                                               |
                     +-----------------------------------------+------------------------------+
                     v                                                                        v
        Feedback from a Reviewer on a same-repo PR                                   PR closed (by anyone)
                     |                                                                        |
                     v                                                                        v
  look up PR Key in the agent file                                             sbx stop <sandbox>,
  pane alive?  yes -> herdr agent prompt <pane> <Feedback>                     herdr tab close <tab_id>,
               no  -> sbx-start <branch> from the repo's clone,                remove agent file line
                      sbx secret set github --sandbox <name>,
                      wait for `idle`, record in agent file,
                      startup prompt, then the Feedback
```

There is one **Coordinator** per pull request, identified by its **PR Key** `owner/repo:branch`,
so two repositories with the same branch name never share one.

## Components

- **`infra/`**: Terraform for the SQS queue and DLQ, the webhook Lambda, API Gateway, IAM (a
  role for the Lambda and a scoped-down IAM user for the consumer), and the GitHub repo webhooks
  themselves (`github.tf`, one per repo in `github_repositories`).
- **`webhook/handler.py`**: the Lambda handler. It verifies `X-Hub-Signature-256`, keeps only
  **Feedback** (PR Comments, Reviews with a written body, Review Comments) and PR-close events,
  normalizes them into a small JSON schema, and forwards them to SQS. An empty approval or empty
  Review wrapper is dropped; each Review Comment arrives as its own message. It uses only the
  stdlib and boto3, so Terraform can zip it with no build step.
- **`consumer/`**: the long-running Python service. It long-polls SQS and handles each message
  through `Dispatcher.handle_message`:
  - `agent_runtime.py` is the port wrapping every herdr and sbx interaction; `herdr_runtime.py`
    is the real adapter that shells out to `sbx-start`, `sbx` and `herdr`.
  - `agent_file.py` is the **agent file**: one tab-separated line per Coordinator (PR Key, pane
    ID, tab label, sandbox name). The Operator can read and edit it by hand.
  - `repo_config.py` reads the Operator's **repo config file** (see below).
  - `processed_ids.py` is the **processed-IDs file**: `X-GitHub-Delivery` IDs with timestamps,
    used to skip duplicate deliveries from GitHub or SQS and pruned by age
    (`DELIVERY_RETENTION_DAYS`). An ID is recorded only after its message was handled.
  - `debug_log.py` is the **debug log** (see below).
  - `github_client.py` makes read-only lookups (a PR Comment's branch and fork status) with the
    repository's own token. Pushing happens from inside the sandbox with its injected
    credentials, never through this client.
  - `dispatcher.py` ties it together, in this order:
    1. Skip duplicate delivery IDs.
    2. PR closed: tear down (below), whoever closed the pull request.
    3. Ignore Feedback whose author is not a **Reviewer** (`ALLOWED_COMMENT_AUTHORS`,
       case-insensitive). This keeps strangers on public repos from directing the agent, and
       keeps the **Agent Account** from looping its own comments back in, so never add that
       account to the list.
    4. Resolve the branch and fork status (through the GitHub client for PR Comments).
    5. **Ignore pull requests from forks** (head repository differs from the base repository,
       or the fork was deleted) and write a `fork PR ignored` line to the debug log:
       `sbx-start <branch>` and `git push origin` can't reach a fork's branch.
    6. If the agent file has a line for the PR Key and herdr still has its pane, prompt that
       Coordinator with the Feedback, whatever its `agent_status`.
    7. Otherwise start a new Coordinator: if there was a line, log `pane missing` and
       `sandbox orphaned` (the old sandbox is left running). Look up the repo config, run
       `sbx-start <branch>` from the repository's clone, set the sandbox's GitHub secret, poll
       `herdr agent get` until the agent is `idle` (`SESSION_READY_TIMEOUT_SECONDS`), write the
       agent-file line, then send the startup prompt followed by the Feedback.

### Failure handling

- **Prompt timeout** (`PROMPT_TIMEOUT_SECONDS`): logged as `prompt timed out` and raised, so the
  message stays in SQS for redelivery and eventually lands in the DLQ. No replacement
  Coordinator is started.
- **Never became idle**: a new Coordinator that isn't `idle` in time is logged and raised; the
  message is redelivered.
- **Missing repo config**: a repository with no clone path or token gets no Coordinator and a
  `missing repo config` line. The consumer never falls back to broader credentials.

### PR-close teardown

When a pull request closes (merged or not, by anyone), the dispatcher looks up its agent-file
line and runs three steps, each logging and continuing on failure:

1. `sbx stop <sandbox name>`.
2. `herdr agent get <pane>` for the current `tab_id`, then `herdr tab close <tab_id>`. If the
   pane is already gone, this step is skipped and logged.
3. Remove the agent-file line, so a reopened pull request gets a fresh Coordinator.

A closed pull request with no agent-file line (including every fork PR) is a no-op.

## Prompt vs. code split

Code's job stops at "get the Feedback in front of the pull request's running Coordinator."
Everything else is instructed by prompt (`consumer/consumer/prompts.py`). The startup prompt
names the pull request, repository and branch, and tells the Coordinator to:

- hand each piece of Feedback to exactly one **Implementer**, one at a time;
- commit and `git push origin HEAD:<branch>` after each Implementer (an explicit refspec, so the
  push target never depends on upstream config);
- rely on the sandbox's injected credentials;
- never merge or close the pull request;
- expect more Feedback over time.

There is no closed-loop confirmation that a push actually happened. That's an accepted tradeoff
for now.

## Local files

All are plain text and gitignored. Paths default to the project checkout and can be overridden
in `consumer/.env` (see `.env.example`).

| File | Default | Setting | Owner |
| --- | --- | --- | --- |
| Repo config file | `./repos.txt` | `REPO_CONFIG_PATH` | Operator |
| Agent file | `./agents.tsv` | `AGENT_FILE_PATH` | consumer (Operator may edit) |
| Debug log | `./debug.log` | `DEBUG_LOG_PATH` | consumer |
| Processed-IDs file | `~/.pr-agent-flow/processed-ids` | `PROCESSED_IDS_PATH` | consumer |

### Repo config file

The Operator lists each watched repository once, whitespace-separated:

```
# owner/repo          local clone path              fine-grained token
leopubcode/my-repo    ~/dev/my-repo                 github_pat_...
```

The clone path is where `sbx-start` runs. The token is a fine-grained personal access token
scoped to that repository only (contents read/write and pull requests read is enough for the
Agent Account to read the PR and push). It's given to the repository's sandboxes with
`sbx secret set github --sandbox <name>` and used for the consumer's own GitHub lookups, so there
is no global token. The file is re-read on every lookup, so it can be edited while the consumer
runs. Because it holds tokens, keep it out of git (it is gitignored) and readable only by you.

### Debug log

One tab-separated line per unusual event: UTC timestamp, PR Key, pane ID (`-` if none), event
kind, detail. Event kinds: `missing repo config`, `fork PR ignored`, `pane missing`,
`sandbox orphaned`, `prompt timed out`, `never became idle`, and the teardown steps
(`teardown sandbox stopped`, `teardown tab closed`, `teardown tab skipped`,
`teardown agent file line removed`, `teardown step failed`). Grep it by PR Key or kind. The
consumer's ordinary progress goes to stdout.

## Known risks / open items

- `herdr_runtime.py` isn't unit-tested, and the JSON it reads (`sbx-start` output,
  `sbx list --json`, `herdr agent get`) is unverified until run by hand against the real tools.
- Assumptions to check by hand: `herdr agent prompt` delivers to a busy agent; `sbx secret set
  github --sandbox` takes effect for a running sandbox; `sbx-start <branch>` run from a clone
  checks out that branch; herdr never reuses pane IDs.
- Orphaned sandboxes (pane gone, sandbox still running) are only logged; stop them by hand.
- A stuck Coordinator after a prompt timeout is not replaced or stopped.
- Consumer AWS auth is a static IAM user access key in `.env`. Fine for a single Operator;
  rotate it periodically.

## Runbook

### Host requirements

The consumer runs on the Operator's machine, which needs:

- Docker sandboxes (`sbx`) and herdr, with herdr running and its `sbx` plugin installed.
- The `sbx-start` shell alias, which starts a sandbox in branch mode in a new herdr pane and
  prints herdr's JSON result (`.result.context.focused_pane_id` and `.tab_label`). Because it's
  an alias, the consumer runs it through an interactive shell: by default
  `$SHELL -ic 'sbx-start "$1"' sbx-start <branch>`. Set `SBX_START_COMMAND` if your alias lives
  in a different shell's rc file (e.g. `zsh -ic 'sbx-start "$1"' sbx-start`).
- A local clone of each watched repository.

### Setup

1. `openssl rand -hex 32` for a webhook secret; copy `infra/terraform.tfvars.example` to
   `infra/terraform.tfvars` (gitignored) and fill it in, including `github_owner` and
   `github_repositories`.
2. `export GITHUB_TOKEN=...`: a token with admin rights on those repos (fine-grained:
   "Webhooks: read and write"), used only by Terraform's GitHub provider. The consumer never
   reads it.
3. `cd infra && terraform init && terraform apply`. This creates the AWS resources and installs
   the webhook on each listed repo. Note the `sqs_queue_url` and
   `consumer_access_key_id`/`consumer_secret_access_key` outputs (`terraform output -json` shows
   the sensitive ones).
4. Copy `.env.example` to `consumer/.env` and fill in the AWS credentials, `SQS_QUEUE_URL` and
   `ALLOWED_COMMENT_AUTHORS` (the Reviewers).
5. Create the repo config file (`repos.txt` in the project checkout) with one line per repo in
   `github_repositories`: `owner/repo`, its local clone path, and its fine-grained token.
6. `pip install -e consumer/` then `pr-agent-consumer` (or `python -m consumer.main`).

### Operating

- Leave a PR Comment on an open, same-repo pull request. A new herdr tab appears for its
  Coordinator; watch it work there. `agents.tsv` gains a line for the PR Key.
- `tail -f debug.log` to see unusual events: missing panes, orphaned sandboxes, timeouts, fork
  PRs, missing repo config, and teardown.
- Messages that keep failing end up in the DLQ; inspect them with
  `aws sqs receive-message --queue-url <dlq-url>`.
- Close the pull request: its sandbox stops, its herdr tab closes and its `agents.tsv` line is
  removed.
- If a Coordinator misbehaves, close its herdr tab and `sbx stop` its sandbox by hand; the next
  Feedback starts a fresh one. Deleting its `agents.tsv` line has the same effect but leaves the
  old pane and sandbox running.
