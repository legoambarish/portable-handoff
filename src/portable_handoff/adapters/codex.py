"""Read-only Codex JSONL adapter; SQLite is intentionally not guessed."""

from __future__ import annotations

from pathlib import Path

from .host_common import LocalJsonlHostAdapter


class CodexAdapter(LocalJsonlHostAdapter):
    host = "codex"
    default_roots = (
        Path.home() / ".codex" / "sessions",
        Path.home() / ".codex" / "transcripts",
    )
