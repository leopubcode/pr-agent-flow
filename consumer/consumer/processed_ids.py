"""Plain-text record of GitHub delivery IDs the consumer has already handled.

One entry per line: ``<delivery-id> <ISO-8601 UTC timestamp>``. The Operator
can read or edit the file by hand; deleting a line lets that delivery be
handled again on redelivery. Entries older than the retention period are
ignored and dropped the next time the file is rewritten.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .atomic_write import atomic_write_text


class ProcessedIds:
    def __init__(self, path: Path, retention_days: int):
        self._path = path
        self._retention = timedelta(days=retention_days)

    def contains(self, delivery_id: str) -> bool:
        return delivery_id in self._read()

    def record(self, delivery_id: str) -> None:
        entries = self._read()
        entries[delivery_id] = datetime.now(UTC)
        self._write(entries)

    def _read(self) -> dict[str, datetime]:
        if not self._path.exists():
            return {}
        cutoff = datetime.now(UTC) - self._retention
        entries: dict[str, datetime] = {}
        for line in self._path.read_text().splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            delivery_id, stamp = parts
            processed_at = datetime.fromisoformat(stamp)
            if processed_at >= cutoff:
                entries[delivery_id] = processed_at
        return entries

    def _write(self, entries: dict[str, datetime]) -> None:
        atomic_write_text(self._path, "".join(f"{i} {ts.isoformat()}\n" for i, ts in entries.items()))
