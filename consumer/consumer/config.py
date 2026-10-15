from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    aws_region: str
    sqs_queue_url: str
    github_token: str
    workspace_root: Path
    state_db_path: Path
    poll_wait_seconds: int
    max_messages_per_poll: int
    session_ready_timeout_seconds: int
    delivery_retention_days: int

    @classmethod
    def from_env(cls) -> "Config":
        def _required(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        return cls(
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            sqs_queue_url=_required("SQS_QUEUE_URL"),
            github_token=_required("GITHUB_TOKEN"),
            workspace_root=Path(os.environ.get("WORKSPACE_ROOT", "~/pr-agent-flow-workspace")).expanduser(),
            state_db_path=Path(os.environ.get("STATE_DB_PATH", "~/.pr-agent-flow/state.db")).expanduser(),
            poll_wait_seconds=int(os.environ.get("POLL_WAIT_SECONDS", "20")),
            max_messages_per_poll=int(os.environ.get("MAX_MESSAGES_PER_POLL", "10")),
            session_ready_timeout_seconds=int(os.environ.get("SESSION_READY_TIMEOUT_SECONDS", "60")),
            delivery_retention_days=int(os.environ.get("DELIVERY_RETENTION_DAYS", "7")),
        )
