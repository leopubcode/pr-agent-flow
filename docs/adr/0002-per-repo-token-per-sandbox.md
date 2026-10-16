# Each sandbox gets its own repository's token

When the consumer starts a Coordinator, it runs `sbx secret set github --sandbox <name>` with a fine-grained personal access token scoped to that pull request's repository only, looked up in an Operator-maintained file that lists each `owner/repo` with its local clone path (where `sbx-start` runs) and its token. We chose this over a single global `sbx secret set github` so that a Coordinator can only read and push to its own repository, even though the system watches several. A repository with no token or no clone path gets no Coordinator, and that is written to the debug log.

That file lives outside the project checkout (`repos.json` in `PR_AGENT_FLOW_HOME`, default `~/.pr-agent-flow`), not in it. This repository can itself be a watched repository, and a Coordinator's sandbox is started from that repository's clone, so a token file inside the checkout would let that one Coordinator read every other repository's token.
