from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Holds every file the consumer reads or writes: the Operator's repos.json and
# everything generated at runtime. Never created by the consumer.
DEFAULT_HOME = Path("~/.pr-agent-flow")


@dataclass(frozen=True)
class Config:
    aws_region: str
    sqs_queue_url: str
    home: Path
    sbx_start_command: list[str] | None
    poll_wait_seconds: int
    max_messages_per_poll: int
    coordinator_ready_timeout_seconds: int
    prompt_timeout_seconds: int
    delivery_retention_days: int
    allowed_comment_authors: frozenset[str]

    @classmethod
    def from_env(cls) -> Config:
        def _required(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        home = Path(os.environ.get("PR_AGENT_FLOW_HOME") or DEFAULT_HOME).expanduser()
        if not home.is_dir():
            raise RuntimeError(
                f"PR_AGENT_FLOW_HOME directory {home} does not exist. Create it from the template: "
                f"cp -r examples/pr-agent-flow-home {home} (see docs/architecture.md)"
            )
        sbx_start = os.environ.get("SBX_START_COMMAND")
        return cls(
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            sqs_queue_url=_required("SQS_QUEUE_URL"),
            home=home,
            sbx_start_command=shlex.split(sbx_start) if sbx_start else None,
            poll_wait_seconds=int(os.environ.get("POLL_WAIT_SECONDS", "20")),
            max_messages_per_poll=int(os.environ.get("MAX_MESSAGES_PER_POLL", "10")),
            coordinator_ready_timeout_seconds=int(os.environ.get("COORDINATOR_READY_TIMEOUT_SECONDS", "120")),
            prompt_timeout_seconds=int(os.environ.get("PROMPT_TIMEOUT_SECONDS", "30")),
            delivery_retention_days=int(os.environ.get("DELIVERY_RETENTION_DAYS", "7")),
            allowed_comment_authors=parse_logins(_required("ALLOWED_COMMENT_AUTHORS")),
        )

    @property
    def repo_config_path(self) -> Path:
        return self.home / "repos.json"

    @property
    def agent_file_path(self) -> Path:
        return self.home / "agents.tsv"

    @property
    def processed_ids_path(self) -> Path:
        return self.home / "processed-ids"

    @property
    def debug_log_path(self) -> Path:
        return self.home / "debug.log"

    @property
    def consumer_log_path(self) -> Path:
        return self.home / "consumer.log"


def parse_logins(value: str) -> frozenset[str]:
    """Comma-separated GitHub logins, lowercased (GitHub logins are case-insensitive)."""
    return frozenset(login.strip().lower() for login in value.split(",") if login.strip())
