"""Explicit unsupported boundary for unverified Codex SQLite layouts."""

from __future__ import annotations

from ..errors import SourceError


def read_session(*args, **kwargs):
    raise SourceError("Codex SQLite transcripts are unsupported until a local schema is verified; export JSONL instead")
