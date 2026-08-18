"""Conservative local JSONL discovery shared by host adapters."""

from __future__ import annotations

from pathlib import Path

from ..bounds import DEFAULT_BOUNDS, Bounds
from ..errors import SourceError
from ..sanitize import safe_read_bytes
from ..strict_json import loads_strict
from .base import SourceAdapter, TranscriptEvent
from .transcript_file import SUPPORTED_SUFFIXES, _iter_files, read_transcript_records


class LocalJsonlHostAdapter(SourceAdapter):
    host = "unknown"
    default_roots: tuple[Path, ...] = ()

    def __init__(self, path: str | Path | None = None, *, root: str | Path | None = None):
        self.path = Path(path).resolve() if path else None
        self.explicit_root = Path(root).resolve() if root else (self.path.parent if self.path else None)

    def _roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        if self.explicit_root is not None:
            roots.append(self.explicit_root)
        roots.extend(self.default_roots)
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root).lower()
            if key not in seen:
                seen.add(key)
                unique.append(root)
        return tuple(unique)

    def approved_roots(self) -> tuple[str, ...]:
        return tuple(str(root) for root in self._roots() if root.exists() and root.is_dir() and not root.is_symlink())

    def _paths(self, limit: int) -> list[Path]:
        if self.path is not None:
            return [self.path]
        result: list[Path] = []
        for root in self._roots():
            remaining = max(0, limit - len(result))
            if remaining == 0:
                break
            result.extend(_iter_files(root, limit=remaining))
        return result[:limit]

    def _resolve(self, reference: str) -> Path:
        if self.path is not None and reference in {self.path.name, self.path.stem, str(self.path)}:
            return self.path
        candidate = Path(reference)
        if candidate.is_absolute():
            candidate = candidate.resolve(strict=False)
            roots = self._roots()
            if not any(_contained(candidate, root) for root in roots):
                raise SourceError("transcript path is outside approved roots")
        else:
            matches = [path for path in self._paths(DEFAULT_BOUNDS.max_filenames) if path.name == reference or path.stem == reference]
            if len(matches) != 1:
                raise SourceError("transcript session was not found")
            candidate = matches[0]
        if not candidate.is_file() or candidate.is_symlink() or candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise SourceError("transcript file is unsupported")
        return candidate

    def _feature_version(self, path: Path) -> str | None:
        try:
            raw = safe_read_bytes(path, maximum=DEFAULT_BOUNDS.max_transcript_bytes, root=path.parent)
            if path.suffix.lower() == ".jsonl":
                first = next((line for line in raw.splitlines() if line.strip()), b"")
                value = loads_strict(first, bounds=DEFAULT_BOUNDS, label="transcript version record") if first else {}
            else:
                value = loads_strict(raw, bounds=DEFAULT_BOUNDS, label="transcript version document")
        except Exception as exc:
            raise SourceError("transcript version could not be verified") from exc
        if isinstance(value, dict):
            if not any(key in value for key in ("id", "uuid", "event_id", "message_id", "role", "message", "content", "text", "type", "events", "messages", "records")):
                raise SourceError("transcript format could not be verified")
            version = value.get("version") or value.get("schema_version") or value.get("format_version")
            if version is None:
                return None
            text = str(version)
            if text.split(".", 1)[0] not in {"0", "1"}:
                raise SourceError("unsupported transcript version")
            return text
        return None

    def probe(self) -> dict[str, object]:
        paths = self._paths(1)
        if self.path is not None and not self.path.exists():
            return {"host": self.host, "supported": False, "available": False, "reason": "session file not found"}
        if not paths:
            return {"host": self.host, "supported": True, "available": False, "reason": "no approved local session root found"}
        path = paths[0]
        if path.suffix.lower() not in {".json", ".jsonl"}:
            return {"host": self.host, "supported": False, "available": True, "reason": "only JSON/JSONL transcript files are verified in v0.1"}
        version = self._feature_version(path)
        return {"host": self.host, "supported": True, "available": True, "format": path.suffix.lower(), "version": version}

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        if limit < 1 or limit > DEFAULT_BOUNDS.max_filenames:
            raise SourceError("session list limit is outside the safety bound")
        result: list[dict[str, object]] = []
        for path in self._paths(limit):
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix.lower() not in {".json", ".jsonl"}:
                continue
            result.append({"session_id": path.stem, "path": str(path), "format": path.suffix.lower(), "bytes": path.stat().st_size, "updated_at_ns": path.stat().st_mtime_ns, "trust": "untrusted"})
        return result[:limit]

    def read_session(self, reference: str, bounds: Bounds = DEFAULT_BOUNDS) -> list[TranscriptEvent]:
        path = self._resolve(reference)
        self._feature_version(path)
        records = read_transcript_records(path, root=path.parent, bounds=bounds)
        return self.normalize(records, source_path=str(path), bounds=bounds)


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
