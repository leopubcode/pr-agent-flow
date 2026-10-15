from __future__ import annotations

import json
import logging

import boto3

from .config import Config
from .dispatcher import Dispatcher
from .github_client import GithubClient
from .state_store import LOST, StateStore
from .tmux_manager import TmuxManager
from .workspace import Workspace

logger = logging.getLogger(__name__)


def _reconcile_on_startup(state: StateStore, tmux: TmuxManager) -> None:
    """Mark any tracked session whose tmux session no longer exists as lost.

    It will be re-provisioned the next time an event arrives for that branch.
    """
    live = tmux.live_session_names()
    for row in state.all_active():
        if row.session_name not in live:
            logger.warning("Session '%s' not found in tmux on startup, marking lost", row.session_name)
            state.set_status(row.branch, LOST)


def run(config: Config) -> None:
    sqs = boto3.client("sqs", region_name=config.aws_region)
    state = StateStore(config.state_db_path)
    tmux = TmuxManager()
    github = GithubClient(config.github_token)
    workspace = Workspace(config.workspace_root)
    dispatcher = Dispatcher(
        state=state,
        tmux=tmux,
        github=github,
        workspace=workspace,
        session_ready_timeout_seconds=config.session_ready_timeout_seconds,
    )

    _reconcile_on_startup(state, tmux)

    logger.info("Polling %s", config.sqs_queue_url)
    while True:
        response = sqs.receive_message(
            QueueUrl=config.sqs_queue_url,
            MaxNumberOfMessages=config.max_messages_per_poll,
            WaitTimeSeconds=config.poll_wait_seconds,
        )
        messages = response.get("Messages", [])
        for raw in messages:
            try:
                msg = json.loads(raw["Body"])
                dispatcher.handle_message(msg)
            except Exception:
                logger.exception("Failed to process message %s; leaving it for redelivery", raw.get("MessageId"))
                continue
            sqs.delete_message(QueueUrl=config.sqs_queue_url, ReceiptHandle=raw["ReceiptHandle"])

        state.prune(config.delivery_retention_days)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(Config.from_env())


if __name__ == "__main__":
    main()
