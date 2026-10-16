from __future__ import annotations

import json
import logging

import boto3

from .agent_file import AgentFile
from .config import Config
from .debug_log import DebugLog
from .dispatcher import Dispatcher
from .github_client import GithubClient
from .herdr_runtime import HerdrSbxRuntime
from .log_files import daily_log_handler
from .processed_ids import ProcessedIds
from .repo_config import RepoConfig

logger = logging.getLogger(__name__)


def run(config: Config) -> None:
    sqs = boto3.client("sqs", region_name=config.aws_region)
    dispatcher = Dispatcher(
        runtime=HerdrSbxRuntime(
            sbx_start_command=config.sbx_start_command,
            prompt_timeout_seconds=config.prompt_timeout_seconds,
        ),
        github_with_token=GithubClient,
        repo_config=RepoConfig(config.repo_config_path),
        agent_file=AgentFile(config.agent_file_path),
        debug_log=DebugLog(config.debug_log_path),
        processed_ids=ProcessedIds(config.processed_ids_path, config.delivery_retention_days),
        ready_timeout_seconds=config.coordinator_ready_timeout_seconds,
        allowed_comment_authors=config.allowed_comment_authors,
    )
    logger.info("Accepting Feedback from: %s", ", ".join(sorted(config.allowed_comment_authors)))
    logger.info("Using PR_AGENT_FLOW_HOME %s", config.home)

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


def main() -> None:
    config = Config.from_env()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), daily_log_handler(config.consumer_log_path)],
    )
    run(config)


if __name__ == "__main__":
    main()
