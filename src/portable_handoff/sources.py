"""Read-only transcript adapter registry and source CLI operations."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .adapters.base import TranscriptEvent
from .adapters.claude import ClaudeAdapter
from .adapters.codex import CodexAdapter
from .adapters.cursor import CursorAdapter
from .adapters.transcript_file import TranscriptFileAdapter
from .bounds import DEFAULT_BOUNDS
from .errors import SourceError
from .storage import atomic_write
from .strict_json import dumps_canonical


def get_adapter(host: str, *, path: str | Path | None = None, root: str | Path | None = None):
    normalized = (host or "unknown").lower()
    if normalized == "claude":
        return ClaudeAdapter(path, root=root)
    if normalized == "codex":
        return CodexAdapter(path, root=root)
    if normalized == "cursor":
        return CursorAdapter(path, root=root)
    if normalized in {"manual", "other", "unknown", "chatgpt"}:
        return TranscriptFileAdapter(path, root=root)
    raise SourceError("unsupported transcript host")


def source_command(args: argparse.Namespace) -> str | dict[str, Any]:
    command = args.source_command
    host = args.host
    if command == "probe":
        return get_adapter(host).probe()
    if command == "list":
        adapter = get_adapter(host)
        return {"host": host, "sessions": adapter.list_sessions(args.limit), "approved_roots": list(adapter.approved_roots())}
    if command == "show":
        reference = args.session
        path = reference if host in {"manual", "other", "unknown", "chatgpt"} and Path(reference).suffix else None
        adapter = get_adapter(host, path=path)
        events = adapter.read_session(reference)
        value = {"host": host, "session": reference, "events": [event.to_dict() for event in events], "untrusted_content": True}
        rendered = dumps_canonical(value) + "\n"
        if args.output in (None, "-"):
            return rendered
        atomic_write(args.output, rendered, maximum=DEFAULT_BOUNDS.max_transcript_bytes)
        return {"output": str(Path(args.output).resolve()), "events": len(events), "untrusted_content": True}
    raise SourceError("unsupported source operation")
