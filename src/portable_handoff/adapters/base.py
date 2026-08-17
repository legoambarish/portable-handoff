"""Shared transcript event types and clean-room normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..bounds import DEFAULT_BOUNDS, Bounds
from ..errors import SourceError
from ..sanitize import redact_text


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

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "role": self.role,
            "kind": self.kind,
            "content": self.content,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "source_path": self.source_path,
            "trust": self.trust,
        }


class SourceAdapter:
    host = "unknown"

    def probe(self) -> dict[str, object]:
        return {"host": self.host, "supported": False, "reason": "unsupported"}

    def approved_roots(self) -> tuple[str, ...]:
        return ()

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        raise SourceError("adapter does not support session listing")

    def read_session(self, reference: str, bounds: Bounds = DEFAULT_BOUNDS) -> list[TranscriptEvent]:
        raise SourceError("adapter does not support session reading")

    def normalize(self, records: Iterable[Any], *, source_path: str | None = None, bounds: Bounds = DEFAULT_BOUNDS) -> list[TranscriptEvent]:
        return normalize_records(records, source_path=source_path, bounds=bounds)


def _nested(raw: dict[str, Any], *keys: str) -> Any:
    current: Any = raw
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces: list[str] = []
        for item in value:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, dict):
                kind = str(item.get("type", ""))
                if isinstance(item.get("text"), str):
                    pieces.append(item["text"])
                elif kind in {"tool_use", "tool_call"}:
                    pieces.append(f"tool call {item.get('name', 'unknown')}: {item.get('input', item.get('arguments', ''))}")
                elif kind in {"tool_result", "tool_response"}:
                    pieces.append(f"tool result: {item.get('content', item.get('output', ''))}")
                else:
                    pieces.append(str(item))
        return "\n".join(pieces)
    if value is None:
        return ""
    return str(value)


def _role(raw: dict[str, Any]) -> str:
    value = raw.get("role") or _nested(raw, "message", "role") or _nested(raw, "author", "role") or raw.get("type") or "unknown"
    value = str(value).lower()
    if value in {"human", "user", "prompt"}:
        return "user"
    if value in {"assistant", "agent", "model"}:
        return "assistant"
    if value in {"tool", "function"}:
        return "tool"
    if value in {"system", "developer"}:
        return "system"
    return value[:64] or "unknown"


def _kind(raw: dict[str, Any], role: str) -> str:
    kind = str(raw.get("kind") or raw.get("type") or raw.get("event_type") or "").lower()
    if any(token in kind for token in ("compact", "summary", "context_edit", "context_boundary")):
        return "compaction_boundary"
    if any(token in kind for token in ("tool_result", "tool_response", "function_result")) or role == "tool":
        return "tool_result"
    if any(token in kind for token in ("tool_call", "tool_use", "function_call")):
        return "tool_call"
    if isinstance(raw.get("tool_calls"), list) or isinstance(raw.get("tool_use"), dict):
        return "tool_call"
    return "message"


def _event_from_record(raw: Any, index: int, *, source_path: str | None) -> TranscriptEvent:
    if not isinstance(raw, dict):
        raise SourceError("transcript record must be an object")
    event_id = raw.get("event_id") or raw.get("id") or raw.get("uuid") or raw.get("message_id") or f"event-{index + 1}"
    parent = raw.get("parent_id") or raw.get("parentId") or raw.get("parent_uuid") or raw.get("parentUuid") or raw.get("parent")
    timestamp = raw.get("timestamp") or raw.get("created_at") or raw.get("createdAt") or _nested(raw, "message", "timestamp")
    role = _role(raw)
    kind = _kind(raw, role)
    content = raw.get("content")
    if content is None:
        content = _nested(raw, "message", "content")
    if content is None:
        content = raw.get("text") or raw.get("output") or raw.get("summary") or raw.get("result") or ""
    tool_name = raw.get("tool_name") or raw.get("toolName") or raw.get("name") or _nested(raw, "tool", "name")
    tool_call_id = raw.get("tool_call_id") or raw.get("toolCallId") or raw.get("tool_use_id") or raw.get("toolUseId")
    clean = redact_text(_content(content), maximum=DEFAULT_BOUNDS.max_event_chars).text
    if kind == "compaction_boundary" and not clean:
        clean = "compaction boundary"
    return TranscriptEvent(str(event_id)[:128], str(parent)[:128] if parent is not None else None, str(timestamp)[:128] if timestamp is not None else None, role, kind, clean, str(tool_name)[:128] if tool_name is not None else None, str(tool_call_id)[:128] if tool_call_id is not None else None, source_path, "untrusted")


def _parent_order(events: list[TranscriptEvent]) -> list[TranscriptEvent]:
    by_id: dict[str, TranscriptEvent] = {}
    for event in events:
        if event.event_id in by_id:
            raise SourceError("duplicate transcript event id")
        by_id[event.event_id] = event
    state: dict[str, int] = {}
    ordered: list[TranscriptEvent] = []

    def visit(event: TranscriptEvent) -> None:
        marker = state.get(event.event_id, 0)
        if marker == 1:
            raise SourceError("transcript parent cycle detected")
        if marker == 2:
            return
        state[event.event_id] = 1
        if event.parent_id and event.parent_id in by_id:
            visit(by_id[event.parent_id])
        state[event.event_id] = 2
        ordered.append(event)

    for event in events:
        visit(event)
    return ordered


def _pair_tools(events: list[TranscriptEvent]) -> list[TranscriptEvent]:
    by_call: dict[str, list[TranscriptEvent]] = {}
    call_ids = {event.tool_call_id for event in events if event.kind == "tool_call" and event.tool_call_id}
    for event in events:
        if event.kind == "tool_result" and event.tool_call_id:
            by_call.setdefault(event.tool_call_id, []).append(event)
    output: list[TranscriptEvent] = []
    consumed: set[str] = set()
    for event in events:
        if event.event_id in consumed:
            continue
        if event.kind == "tool_result":
            if event.tool_call_id in call_ids:
                continue
            output.append(TranscriptEvent(event.event_id, event.parent_id, event.timestamp, event.role, "orphan_tool_result", f"orphan tool result: {event.content}", event.tool_name, event.tool_call_id, event.source_path, "untrusted"))
            continue
        output.append(event)
        if event.kind == "tool_call" and event.tool_call_id:
            for result in by_call.get(event.tool_call_id, []):
                if result.event_id not in consumed:
                    output.append(result)
                    consumed.add(result.event_id)
    return output


def normalize_records(records: Iterable[Any], *, source_path: str | None = None, bounds: Bounds = DEFAULT_BOUNDS) -> list[TranscriptEvent]:
    raw_records = list(records)
    if len(raw_records) > bounds.max_transcript_records:
        raise SourceError("transcript record limit exceeded")
    events = [_event_from_record(item, index, source_path=source_path) for index, item in enumerate(raw_records)]
    ordered = _parent_order(events)
    boundary_positions = [index for index, event in enumerate(ordered) if event.kind == "compaction_boundary"]
    if boundary_positions:
        ordered = ordered[boundary_positions[-1] :]
    paired = _pair_tools(ordered)
    if paired and paired[-1].role == "assistant" and paired[-1].kind == "tool_call":
        paired.append(TranscriptEvent(f"{paired[-1].event_id}:interrupted", paired[-1].event_id, paired[-1].timestamp, "system", "interrupted_turn", "assistant turn appears interrupted before a final tool result", trust="untrusted"))
    return paired[: bounds.max_transcript_records]
