"""Read-only Cursor file adapter; SQLite/WAL is an explicit unsupported state."""

from __future__ import annotations

from pathlib import Path

from ..errors import SourceError
from .host_common import LocalJsonlHostAdapter


class CursorAdapter(LocalJsonlHostAdapter):
    host = "cursor"
    default_roots = (
        Path.home() / ".cursor",
        Path.home() / "AppData" / "Local" / "Cursor" / "User" / "History",
    )

    def _resolve(self, reference: str) -> Path:
        path = super()._resolve(reference)
        if path.suffix.lower() in {".sqlite", ".db", ".wal", ".shm"}:
            raise SourceError("Cursor SQLite/WAL transcripts are unsupported until a local schema is verified")
        return path
