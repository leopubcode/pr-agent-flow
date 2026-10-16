from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# The project checkout; the agent file, repo config file and debug log live here by default.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    aws_region: str
    sqs_queue_url: str
    processed_ids_path: Path
    repo_config_path: Path
    agent_file_path: Path
    debug_log_path: Path
    sbx_start_command: list[str] | None
    poll_wait_seconds: int
    max_messages_per_poll: int
    session_ready_timeout_seconds: int
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

        def _path(name: str, default: Path) -> Path:
            return Path(os.environ.get(name) or default).expanduser()

        sbx_start = os.environ.get("SBX_START_COMMAND")
        return cls(
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            sqs_queue_url=_required("SQS_QUEUE_URL"),
            processed_ids_path=_path("PROCESSED_IDS_PATH", Path("~/.pr-agent-flow/processed-ids")),
            repo_config_path=_path("REPO_CONFIG_PATH", PROJECT_ROOT / "repos.txt"),
            agent_file_path=_path("AGENT_FILE_PATH", PROJECT_ROOT / "agents.tsv"),
            debug_log_path=_path("DEBUG_LOG_PATH", PROJECT_ROOT / "debug.log"),
            sbx_start_command=shlex.split(sbx_start) if sbx_start else None,
            poll_wait_seconds=int(os.environ.get("POLL_WAIT_SECONDS", "20")),
            max_messages_per_poll=int(os.environ.get("MAX_MESSAGES_PER_POLL", "10")),
            session_ready_timeout_seconds=int(os.environ.get("SESSION_READY_TIMEOUT_SECONDS", "120")),
            prompt_timeout_seconds=int(os.environ.get("PROMPT_TIMEOUT_SECONDS", "30")),
            delivery_retention_days=int(os.environ.get("DELIVERY_RETENTION_DAYS", "7")),
            allowed_comment_authors=parse_logins(_required("ALLOWED_COMMENT_AUTHORS")),
        )


def parse_logins(value: str) -> frozenset[str]:
    """Comma-separated GitHub logins, lowercased (GitHub logins are case-insensitive)."""
    return frozenset(login.strip().lower() for login in value.split(",") if login.strip())
