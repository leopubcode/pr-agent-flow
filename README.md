# PR Agent Flow

Listens for review activity on GitHub pull requests and hands it to a long-lived coding agent
working on that pull request's branch.

A GitHub webhook sends PR Comments, Reviews, Review Comments and PR-close events through a Lambda
to an SQS queue. The consumer, running on the Operator's machine, reads the queue one message at
a time. For Feedback from an allowlisted Reviewer on a same-repo pull request (pull requests from
forks are ignored), it prompts that pull request's Coordinator through herdr, first starting one
with `sbx-start` from the Operator's local clone if none is running; the Coordinator checks out
the pull request's branch itself. Each sandbox gets only its own repository's token. The Coordinator hands each piece of Feedback to one Implementer
at a time and pushes after each. When the pull request closes, the consumer stops the sandbox,
closes the herdr tab and forgets the Coordinator.

See [`docs/architecture.md`](docs/architecture.md) for the design and runbook,
[`GLOSSARY.md`](GLOSSARY.md) for the vocabulary, and [`docs/adr/`](docs/adr/) for the decisions.
