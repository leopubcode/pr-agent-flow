"""Log files in PR_AGENT_FLOW_HOME, rotated at local midnight.

Each log is written under its plain name and renamed to `<name>.YYYY-MM-DD`
when the day changes. After a restart, the existing file's modification time
decides whether it rolls over first, so lines keep the date they were written
on. Rotated files are kept forever.
"""
from __future__ import annotations

from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def daily_log_handler(path: Path) -> TimedRotatingFileHandler:
    return TimedRotatingFileHandler(path, when="midnight", backupCount=0, utc=False, delay=True)
