"""The agent file: one tab-separated line per Coordinator.

Fields: PR Key, pane ID, tab label, sandbox name. Plain text so the Operator
can inspect and edit it by hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentRecord:
    pr_key: str
    pane_id: str
    tab_label: str
    sandbox_name: str


class AgentFile:
    def __init__(self, path: Path):
        self._path = Path(path)

    def get(self, pr_key: str) -> AgentRecord | None:
        for record in self._read():
            if record.pr_key == pr_key:
                return record
        return None

    def put(self, record: AgentRecord) -> None:
        """Add the record, replacing any existing line for its PR Key in place."""
        records = self._read()
        for i, existing in enumerate(records):
            if existing.pr_key == record.pr_key:
                records[i] = record
                break
        else:
            records.append(record)
        self._write(records)

    def remove(self, pr_key: str) -> None:
        self._write([r for r in self._read() if r.pr_key != pr_key])

    def _read(self) -> list[AgentRecord]:
        if not self._path.exists():
            return []
        records = []
        for line in self._path.read_text().splitlines():
            fields = line.split("\t")
            if len(fields) == 4:
                records.append(AgentRecord(*fields))
        return records

    def _write(self, records: list[AgentRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(
            "".join(f"{r.pr_key}\t{r.pane_id}\t{r.tab_label}\t{r.sandbox_name}\n" for r in records)
        )
        tmp.replace(self._path)
