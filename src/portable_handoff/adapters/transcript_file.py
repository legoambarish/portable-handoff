"""Generic bounded JSON, JSONL, Markdown, and text transcript adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..bounds import DEFAULT_BOUNDS, Bounds
from ..errors import SourceError
from ..sanitize import ensure_no_symlink, safe_read_bytes
from ..strict_json import loads_strict
from .base import SourceAdapter, TranscriptEvent

SUPPORTED_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".markdown", ".txt"})


def _supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def read_transcript_records(path: str | Path, *, root: str | Path | None = None, bounds: Bounds = DEFAULT_BOUNDS) -> list[Any]:
    candidate = Path(path)
    if not _supported(candidate):
        raise SourceError("transcript file extension is unsupported")
    raw = safe_read_bytes(candidate, maximum=bounds.max_transcript_bytes, root=root)
    suffix = candidate.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return [{"id": "text-1", "role": "unknown", "type": "text", "content": raw.decode("utf-8", "replace")}]
    if suffix == ".jsonl":
        records: list[Any] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            if len(records) >= bounds.max_transcript_records:
                raise SourceError("transcript record limit exceeded")
            try:
                value = loads_strict(line, bounds=bounds, label=f"transcript JSONL record {line_number}")
            except Exception as exc:
                if isinstance(exc, SourceError):
                    raise
                raise SourceError("malformed transcript JSONL") from exc
            records.append(value)
        return records
    value = loads_strict(raw, bounds=bounds, label="transcript JSON")
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("events", "messages", "records", "entries"):
            if isinstance(value.get(key), list):
                return value[key]
        if any(key in value for key in ("role", "content", "message", "text", "type")):
            return [value]
    raise SourceError("JSON transcript shape is unsupported")


def _iter_files(root: Path, *, limit: int) -> list[Path]:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        return []
    result: list[Path] = []
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
        for name in sorted(filenames):
            path = Path(current) / name
            if path.is_symlink() or not _supported(path):
                continue
            result.append(path)
            if len(result) >= limit:
                return result
    return result


class TranscriptFileAdapter(SourceAdapter):
    host = "manual"

    def __init__(self, path: str | Path | None = None, *, root: str | Path | None = None):
        self.path = Path(path).resolve() if path is not None else None
        self.root = Path(root).resolve() if root is not None else (self.path.parent if self.path else None)

    def approved_roots(self) -> tuple[str, ...]:
        return (str(self.root),) if self.root else ()

    def probe(self) -> dict[str, object]:
        if self.path is None:
            return {"host": self.host, "supported": True, "available": bool(self.root), "formats": sorted(SUPPORTED_SUFFIXES)}
        return {"host": self.host, "supported": _supported(self.path), "path": str(self.path), "format": self.path.suffix.lower()}

    def _resolve(self, reference: str) -> Path:
        if self.path is not None and (reference == self.path.name or reference == str(self.path) or reference == self.path.stem):
            return self.path
        if self.root is None:
            raise SourceError("no approved transcript root was supplied")
        candidate = Path(reference)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        # Checked on the path as given, before resolving. Resolving first, as
        # this used to do, follows a symlink to its target and inspects that
        # instead of the link itself, which is exactly the indirection a
        # symlink placed inside the approved root depends on.
        ensure_no_symlink(candidate, root=self.root)
        candidate = candidate.resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise SourceError("transcript path is outside the approved root") from exc
        if not candidate.is_file():
            matches = [item for item in _iter_files(self.root, limit=DEFAULT_BOUNDS.max_filenames) if item.stem == reference or item.name == reference]
            if len(matches) == 1:
                candidate = matches[0]
            else:
                raise SourceError("transcript session was not found")
        return candidate

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        if limit < 1 or limit > DEFAULT_BOUNDS.max_filenames:
            raise SourceError("session list limit is outside the safety bound")
        paths = [self.path] if self.path is not None else _iter_files(self.root, limit=limit) if self.root else []
        result: list[dict[str, object]] = []
        for path in paths:
            if path is not None and path.is_file() and not path.is_symlink() and _supported(path):
                stat = path.stat()
                result.append({"session_id": path.stem, "path": str(path), "format": path.suffix.lower(), "bytes": stat.st_size, "updated_at_ns": stat.st_mtime_ns, "trust": "untrusted"})
        return result[:limit]

    def read_session(self, reference: str, bounds: Bounds = DEFAULT_BOUNDS) -> list[TranscriptEvent]:
        path = self._resolve(reference)
        records = read_transcript_records(path, root=self.root, bounds=bounds)
        return self.normalize(records, source_path=str(path), bounds=bounds)
