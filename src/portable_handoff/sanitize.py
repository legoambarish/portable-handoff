"""Defensive text sanitation, secret redaction, and safe relative paths."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .bounds import DEFAULT_BOUNDS, Bounds, require_text
from .errors import BusySourceError, LimitError, UnsafePathError


@dataclass(frozen=True)
class Redaction:
    kind: str
    count: int


@dataclass(frozen=True)
class SanitizedText:
    text: str
    redactions: tuple[Redaction, ...] = ()
    truncated: bool = False


# These are intentionally high-confidence families, not a copied vendor rule
# corpus. Values are replaced without ever returning or logging the match.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE | re.DOTALL), "[REDACTED:private_key]"),
    ("credentialed_url", re.compile(r"\bhttps?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE), "[REDACTED:url]@"),
    ("bearer_token", re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{20,}"), r"\1[REDACTED:bearer]"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[REDACTED:github]"),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "[REDACTED:gitlab]"),
    ("cloud_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED:cloud_key]"),
    ("secret_assignment", re.compile(r"(?i)(\b(?:password|passwd|api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]\s*[\"']?)[^\s,;\"']{8,}"), r"\1[REDACTED:assignment]"),
    ("opaque_api_key", re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"), "[REDACTED:api_key]"),
)
_ANSI_RE = re.compile(r"(?:\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\))")
_DELIMITER_TEXT = (
    "<!-- portable-handoff:json:start -->",
    "<!-- portable-handoff:json:end -->",
)


def _safe_controls(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    output: list[str] = []
    for char in text:
        code = ord(char)
        if char in "\n\t" or code >= 0x20:
            if code != 0x7F:
                output.append(char)
        else:
            output.append(" ")
    return "".join(output)


def redact_text(value: str, *, maximum: int = DEFAULT_BOUNDS.max_string_chars) -> SanitizedText:
    text = unicodedata.normalize("NFC", _safe_controls(value))
    redactions: list[Redaction] = []
    for kind, pattern, replacement in _SECRET_PATTERNS:
        text, count = pattern.subn(replacement, text)
        if count:
            redactions.append(Redaction(kind, count))
    for marker in _DELIMITER_TEXT:
        count = text.count(marker)
        if count:
            text = text.replace(marker, "[delimiter text removed]")
            redactions.append(Redaction("markdown_delimiter", count))
    truncated = len(text) > maximum
    if truncated:
        text = text[:maximum]
    return SanitizedText(text, tuple(redactions), truncated)


def escape_delimiters(value: str) -> str:
    result = value
    for marker in _DELIMITER_TEXT:
        result = result.replace(marker, "[delimiter text removed]")
    return result


def redaction_counts(items: list[Redaction] | tuple[Redaction, ...]) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}
    for item in items:
        totals[item.kind] = totals.get(item.kind, 0) + item.count
    return [{"kind": kind, "count": totals[kind]} for kind in sorted(totals)]


_STRUCTURAL_KEYS = frozenset({"handoff_id", "created_at", "integrity", "digest", "hash", "commit", "exists", "dirty", "staged", "count", "evidence_refs"})


def sanitize_value(value: Any, *, key: str | None = None, maximum: int = DEFAULT_BOUNDS.max_string_chars) -> tuple[Any, list[Redaction]]:
    if isinstance(value, str):
        if key in _STRUCTURAL_KEYS:
            return value, []
        sanitized = redact_text(value, maximum=maximum)
        return sanitized.text, list(sanitized.redactions)
    if isinstance(value, list):
        output: list[Any] = []
        all_redactions: list[Redaction] = []
        for item in value:
            clean, found = sanitize_value(item, key=key, maximum=maximum)
            output.append(clean)
            all_redactions.extend(found)
        return output, all_redactions
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        all_redactions = []
        for item_key, item in value.items():
            clean, found = sanitize_value(item, key=item_key, maximum=maximum)
            output[item_key] = clean
            all_redactions.extend(found)
        return output, all_redactions
    return value, []


def sanitize_document(document: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    clean, redactions = sanitize_value(document)
    security = clean.setdefault("security", {})
    existing = security.get("redactions", [])
    if not isinstance(existing, list):
        existing = []
    merged: dict[str, int] = {}
    for raw in existing:
        if isinstance(raw, dict) and isinstance(raw.get("kind"), str) and isinstance(raw.get("count"), int):
            merged[raw["kind"]] = merged.get(raw["kind"], 0) + raw["count"]
    for raw in redaction_counts(redactions):
        merged[raw["kind"]] = merged.get(raw["kind"], 0) + raw["count"]
    security["redactions"] = [{"kind": kind, "count": merged[kind]} for kind in sorted(merged)]
    return clean, security["redactions"]


def normalize_relative_path(value: str, *, root: str | Path | None = None, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise UnsafePathError("path must be text")
    if "\x00" in value:
        raise UnsafePathError("NUL in path rejected")
    value = value.replace("\\", "/")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if windows.is_absolute() or posix.is_absolute() or windows.drive:
        raise UnsafePathError("absolute path rejected")
    parts = [part for part in posix.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise UnsafePathError("path traversal rejected")
    normalized = "/".join(parts)
    if not normalized and not allow_empty:
        raise UnsafePathError("empty path rejected")
    if len(normalized) > DEFAULT_BOUNDS.max_path_chars:
        raise LimitError("path exceeds its safety bound")
    if root is not None and normalized:
        root_path = Path(root).resolve()
        candidate = (root_path / Path(*parts)).resolve(strict=False)
        try:
            if os.path.commonpath((str(root_path), str(candidate))) != str(root_path):
                raise UnsafePathError("path escapes repository root")
        except ValueError as exc:
            raise UnsafePathError("path root mismatch") from exc
    return normalized


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt":
        try:
            import ctypes

            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            return attrs != 0xFFFFFFFF and bool(attrs & 0x400)
        except Exception:
            return False
    return False


def ensure_no_symlink(path: Path, *, root: Path | None = None) -> None:
    path = path.absolute()
    if root is None:
        root = path.anchor and Path(path.anchor) or Path.cwd().anchor and Path(Path.cwd().anchor) or Path.cwd()
    root = root.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError("path escapes allowed root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if _is_reparse_or_symlink(current):
            raise UnsafePathError("symlink or reparse point rejected")


def safe_read_bytes(path: str | Path, *, maximum: int = DEFAULT_BOUNDS.max_capsule_bytes, root: str | Path | None = None) -> bytes:
    candidate = Path(path)
    if root is not None:
        root_path = Path(root).resolve()
        resolved = candidate.resolve(strict=False) if not candidate.is_absolute() else candidate.resolve(strict=False)
        try:
            if os.path.commonpath((str(root_path), str(resolved))) != str(root_path):
                raise UnsafePathError("read path escapes allowed root")
        except ValueError as exc:
            raise UnsafePathError("read path root mismatch") from exc
        ensure_no_symlink(resolved, root=root_path)
        candidate = resolved
    else:
        candidate = candidate.absolute()
        ensure_no_symlink(candidate, root=Path(candidate.anchor or Path.cwd().anchor or Path.cwd()))
    try:
        before = candidate.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(candidate)) from exc
    if not stat.S_ISREG(before.st_mode):
        raise UnsafePathError("only regular files may be read")
    if before.st_size > maximum:
        raise LimitError("file exceeds its safety bound")
    try:
        with candidate.open("rb") as handle:
            data = handle.read(maximum + 1)
    except OSError as exc:
        raise UnsafePathError("file could not be read safely") from exc
    if len(data) > maximum:
        raise LimitError("file exceeds its safety bound")
    after = candidate.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise BusySourceError()
    return data
