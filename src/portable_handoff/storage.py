"""Safe local capsule storage with atomic no-clobber writes."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .bounds import DEFAULT_BOUNDS
from .errors import CollisionError, LimitError, UnsafePathError
from .sanitize import ensure_no_symlink, safe_read_bytes

_FILENAME_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9][a-z0-9-]{0,63}-[A-Za-z0-9_-]{4,128}\.md$")


def capsule_directory(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    return root / ".handoff" / "capsules"


def evidence_directory(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    return root / ".handoff" / "evidence"


def slugify_goal(goal: str) -> str:
    import re as _re
    import unicodedata

    text = unicodedata.normalize("NFKD", goal).encode("ascii", "ignore").decode("ascii").lower()
    slug = _re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (slug or "handoff")[:64]


def capsule_filename(created_at: str, goal: str, handoff_id: str) -> str:
    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    short_id = re.sub(r"[^A-Za-z0-9]", "", handoff_id)[:8].lower() or "unknown1"
    return f"{timestamp}-{slugify_goal(goal)}-{short_id}.md"


def _assert_filename(name: str) -> None:
    if not _FILENAME_RE.fullmatch(name):
        raise UnsafePathError("capsule filename is not in the approved format")


def atomic_write(path: str | Path, data: bytes | str, *, force: bool = False, maximum: int = DEFAULT_BOUNDS.max_capsule_bytes) -> Path:
    target = Path(path)
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if len(raw) > maximum:
        raise LimitError("output exceeds its safety bound")
    raw_parent = target.parent.absolute()
    anchor = Path(target.anchor or Path.cwd().anchor or Path.cwd())
    ensure_no_symlink(raw_parent, root=anchor)
    parent = raw_parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / target.name
    ensure_no_symlink(parent, root=anchor)
    if target.exists() and not force:
        raise CollisionError()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(temp_path, 0o600)
        if target.exists() and not force:
            raise CollisionError()
        os.replace(temp_path, target)
        temp_path = None
        try:
            directory_fd = os.open(str(parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        return target
    finally:
        if temp_path is not None:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)


def read_capsule(path: str | Path) -> bytes:
    return safe_read_bytes(path, maximum=DEFAULT_BOUNDS.max_capsule_bytes)


def list_capsules(project_root: str | Path) -> list[Path]:
    directory = capsule_directory(project_root)
    if not directory.exists():
        return []
    ensure_no_symlink(directory, root=Path(project_root).resolve())
    result: list[Path] = []
    for item in directory.iterdir():
        if item.is_file() and not item.is_symlink() and _FILENAME_RE.fullmatch(item.name):
            result.append(item)
    # Two capsules can share a created_at when one preflight is finalized more
    # than once, so modification time breaks the tie and "latest" stays honest.
    def _order(path: Path) -> tuple[str, float]:
        try:
            return (path.name, path.stat().st_mtime)
        except OSError:
            return (path.name, 0.0)

    return sorted(result, key=_order, reverse=True)[: DEFAULT_BOUNDS.max_filenames]


def latest_capsule(project_root: str | Path) -> Path:
    capsules = list_capsules(project_root)
    if not capsules:
        raise FileNotFoundError("no Portable Handoff capsules found")
    return capsules[0]


def resolve_project_root(cwd: str | Path) -> Path:
    """Resolve a Git worktree root, falling back to the supplied directory."""
    from .gitfacts import find_repo_root

    return find_repo_root(cwd) or Path(cwd).resolve()


def resolve_capsule(reference: str, *, cwd: str | Path) -> Path:
    if reference == "latest":
        return latest_capsule(resolve_project_root(cwd))
    candidate = Path(reference)
    if not candidate.is_absolute():
        root = Path(cwd).resolve()
        candidate = (root / candidate).resolve(strict=False)
        try:
            if os.path.commonpath((str(root), str(candidate))) != str(root):
                raise UnsafePathError("relative capsule path escapes the working root")
        except ValueError as exc:
            raise UnsafePathError("relative capsule path root mismatch") from exc
    if candidate.suffix.lower() != ".md":
        raise UnsafePathError("capsule path must end in .md")
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    if candidate.is_symlink() or not candidate.is_file():
        raise UnsafePathError("capsule path must be a regular non-symlink file")
    return candidate
