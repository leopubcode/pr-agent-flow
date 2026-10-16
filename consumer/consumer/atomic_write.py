from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Replace `path` with `text` via a sibling temp file, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)
