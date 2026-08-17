"""Shared transcript event types for bounded read-only adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptEvent:
    event_id: str
    parent_id: str | None
    timestamp: str | None
    role: str
    kind: str
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    source_path: str | None = None
    trust: str = "untrusted"


class SourceAdapter:
    host = "unknown"

    def probe(self) -> dict[str, object]:
        return {"host": self.host, "supported": False, "reason": "unsupported"}
