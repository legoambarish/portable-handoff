"""Strict JSON parsing and canonical JSON serialization."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from .bounds import DEFAULT_BOUNDS, Bounds, require_bytes, walk_bounds
from .errors import SchemaError


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise SchemaError("non-finite JSON number is not allowed")


def loads_strict(data: str | bytes, *, bounds: Bounds = DEFAULT_BOUNDS, label: str = "JSON") -> Any:
    if isinstance(data, bytes):
        raw = require_bytes(data, maximum=bounds.max_json_bytes, label=label)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError(f"{label} is not valid UTF-8") from exc
    elif isinstance(data, str):
        raw = data.encode("utf-8")
        require_bytes(raw, maximum=bounds.max_json_bytes, label=label)
        text = data
    else:
        raise SchemaError(f"{label} must be UTF-8 JSON text")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SchemaError(f"invalid {label}") from exc
    walk_bounds(value, bounds=bounds, label=label)
    return value


def _normalize_unicode(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_unicode(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_unicode(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = unicodedata.normalize("NFC", str(key))
            if normalized_key in result:
                raise SchemaError("Unicode normalization creates duplicate JSON keys")
            result[normalized_key] = _normalize_unicode(item)
        return result
    return value


def dumps_canonical(value: Any) -> str:
    normalized = _normalize_unicode(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise SchemaError("value cannot be represented as canonical JSON") from exc


def canonical_bytes(value: Any) -> bytes:
    return dumps_canonical(value).encode("utf-8")


def omit_empty(value: Any) -> Any:
    """Drop keys whose value is null or an empty list.

    Every reader re-expands these from the schema defaults, so carrying them in
    the file costs tokens and says nothing. Only the serialized text changes:
    the integrity digest is always computed over the fully expanded document,
    so this is not a change to the digest definition.
    """
    if isinstance(value, dict):
        return {key: omit_empty(item) for key, item in value.items() if item is not None and item != []}
    if isinstance(value, list):
        return [omit_empty(item) for item in value]
    return value
