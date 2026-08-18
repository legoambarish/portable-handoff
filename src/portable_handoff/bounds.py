"""Central conservative limits used by parsers, renderers, and adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from typing import Any

from .errors import LimitError


@dataclass(frozen=True)
class Bounds:
    max_json_bytes: int = 512 * 1024
    max_capsule_bytes: int = 768 * 1024
    max_string_chars: int = 16_384
    max_goal_chars: int = 12_000
    max_event_chars: int = 16_384
    max_key_chars: int = 128
    max_path_chars: int = 1_024
    max_nesting: int = 14
    max_list_items: int = 256
    max_changed_files: int = 2_000
    # Kept small deliberately. This list orients a reader and flags drift; it
    # is not a diff, and the files that matter to the task are in `files`.
    # Staying well under max_list_items also keeps a very dirty worktree
    # parseable by finalize.
    max_recorded_changed_files: int = 25
    max_file_symbols: int = 128
    max_recent_context: int = 64
    max_evidence: int = 512
    max_transcript_records: int = 10_000
    max_transcript_bytes: int = 8 * 1024 * 1024
    max_diff_bytes: int = 64 * 1024
    max_command_output_bytes: int = 64 * 1024
    max_total_items: int = 8_000
    max_estimated_tokens: int = 12_000
    target_estimated_tokens: int = 7_000
    max_filenames: int = 512


DEFAULT_BOUNDS = Bounds()


def require_bytes(value: bytes | bytearray | memoryview, *, maximum: int, label: str) -> bytes:
    result = bytes(value)
    if len(result) > maximum:
        raise LimitError(f"{label} exceeds {maximum} bytes")
    return result


def require_text(value: object, *, maximum: int = DEFAULT_BOUNDS.max_string_chars, label: str = "text") -> str:
    if not isinstance(value, str):
        raise LimitError(f"{label} must be text")
    if len(value) > maximum:
        raise LimitError(f"{label} exceeds {maximum} characters")
    return value


def require_count(value: object, *, maximum: int, label: str) -> None:
    if not isinstance(value, (list, tuple, dict)):
        raise LimitError(f"{label} must be a bounded collection")
    if len(value) > maximum:
        raise LimitError(f"{label} exceeds {maximum} items")


def walk_bounds(value: Any, *, bounds: Bounds = DEFAULT_BOUNDS, depth: int = 0, label: str = "JSON") -> int:
    """Validate generic JSON shape and return the number of visited values."""
    if depth > bounds.max_nesting:
        raise LimitError(f"{label} exceeds nesting depth {bounds.max_nesting}")
    if isinstance(value, str):
        require_text(value, maximum=bounds.max_string_chars, label=label)
        return 1
    if value is None or isinstance(value, (bool, int, float)):
        return 1
    if isinstance(value, list):
        require_count(value, maximum=bounds.max_list_items, label=label)
        total = 1
        for item in value:
            total += walk_bounds(item, bounds=bounds, depth=depth + 1, label=label)
        if total > bounds.max_total_items:
            raise LimitError(f"{label} contains too many values")
        return total
    if isinstance(value, dict):
        require_count(value, maximum=128, label=label)
        total = 1
        for key, item in value.items():
            require_text(key, maximum=bounds.max_key_chars, label=f"{label} key")
            total += walk_bounds(item, bounds=bounds, depth=depth + 1, label=label)
        if total > bounds.max_total_items:
            raise LimitError(f"{label} contains too many values")
        return total
    raise LimitError(f"{label} contains an unsupported value")


def estimate_tokens(value: str | bytes | object) -> int:
    """Use a conservative, deterministic character estimate for model tokens."""
    if isinstance(value, bytes):
        size = len(value)
    elif isinstance(value, str):
        size = len(value.encode("utf-8"))
    else:
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    return max(1, ceil(size / 4))
