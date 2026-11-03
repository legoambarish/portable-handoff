"""Bounded, read-only Git fact collection."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .bounds import DEFAULT_BOUNDS
from .models import Provenance, Trust, now_utc
from .sanitize import normalize_relative_path


def strip_credentials(remote: str | None) -> str | None:
    if not remote:
        return None
    value = remote.strip()
    if "@" in value and "://" not in value:
        # SCP-style Git remote. Keep the host/path but drop the transport user.
        value = value.split("@", 1)[1]
    if "://" in value:
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname or ""
            if not hostname:
                return value[:2048]
            netloc = hostname
            if parsed.port:
                netloc = f"{hostname}:{parsed.port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))[:2048]
        except ValueError:
            return re.sub(r"//[^/@:]+(?::[^/@]*)?@", "//", value)[:2048]
    return value[:2048]


def _run_git(args: list[str], cwd: Path, *, timeout: float = 5.0) -> tuple[int, bytes, bytes]:
    git = shutil.which("git") or "git"
    try:
        completed = subprocess.run(
            [git, *args],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, b"", b"git unavailable or timed out"
    return completed.returncode, completed.stdout[: DEFAULT_BOUNDS.max_command_output_bytes], completed.stderr[: DEFAULT_BOUNDS.max_command_output_bytes]


def find_repo_root(cwd: str | Path) -> Path | None:
    candidate = Path(cwd).resolve()
    if not candidate.exists():
        return None
    if candidate.is_file():
        candidate = candidate.parent
    code, out, _ = _run_git(["-C", str(candidate), "rev-parse", "--show-toplevel"], candidate)
    if code != 0:
        return None
    try:
        return Path(out.decode("utf-8", "replace").strip()).resolve()
    except (OSError, ValueError):
        return None


def _sha256_file(path: Path) -> str | None:
    try:
        before = path.stat()
        if not path.is_file() or path.is_symlink() or before.st_size > 32 * 1024 * 1024:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            return None
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip()


def _parse_status(root: Path, raw: bytes, captured_at: str) -> tuple[list[dict[str, Any]], int]:
    parts = raw.split(b"\0")
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if not record:
            continue
        text = record.decode("utf-8", "replace")
        code = text[:2] if len(text) >= 2 else "??"
        path_text = text[3:] if len(text) >= 4 and text[2] == " " else text[2:].lstrip()
        orig_text: str | None = None
        if code[0] in "RC" and index < len(parts) and parts[index]:
            # porcelain -z emits "XY <path>" NUL "<origPath>" NUL. The first field is
            # the path the file has now; the second is where it came from.
            # Recording the second as the path would point at a file that no
            # longer exists, so keep the current path and carry the origin.
            orig_text = parts[index].decode("utf-8", "replace")
            index += 1
        try:
            rel = normalize_relative_path(path_text, root=root)
        except Exception:
            continue
        rel_orig: str | None = None
        if orig_text is not None:
            try:
                rel_orig = normalize_relative_path(orig_text, root=root)
            except Exception:
                rel_orig = None
        # Capsules and sidecars are Portable Handoff's own local metadata;
        # creating one must not make an otherwise unchanged worktree stale.
        if rel == ".handoff" or rel.startswith(".handoff/"):
            continue
        absolute = root / Path(*rel.split("/"))
        exists = absolute.exists() and not absolute.is_symlink()
        status = "untracked" if code == "??" else ("deleted" if "D" in code else ("renamed" if "R" in code else ("copied" if "C" in code else "modified")))
        result.append({
            "path": rel,
            "orig_path": rel_orig,
            "status": status,
            "staged": code[0] not in " ?!",
            "hash": _sha256_file(absolute) if exists else None,
            "exists": exists,
            "provenance": Provenance.GIT.value,
            "trust": Trust.VERIFIED.value,
            "captured_at": captured_at,
        })
    # The total is reported even when the sample is capped, so a capsule never
    # claims a clean tree just because the list was too long to record.
    return result[: DEFAULT_BOUNDS.max_recorded_changed_files], len(result)


def _collect_remotes(root: Path) -> list[dict[str, Any]]:
    """All configured remotes, not just origin, with credentials stripped.

    An empty list is a meaningful verified fact: the checkout has nowhere to
    push, so every commit in it exists only on this machine.
    """
    code, out, _ = _run_git(["-C", str(root), "remote"], root)
    if code != 0:
        return []
    result: list[dict[str, Any]] = []
    for name in _decode(out).splitlines()[:64]:
        name = name.strip()
        if not name:
            continue
        url_code, url_out, _ = _run_git(["-C", str(root), "config", "--get", f"remote.{name}.url"], root)
        result.append({"name": name[:256], "url": strip_credentials(_decode(url_out)) if url_code == 0 else None})
    return result


def _collect_worktrees(root: Path) -> list[dict[str, Any]]:
    """Linked worktrees, so a capsule cannot silently conflate two checkouts."""
    code, out, _ = _run_git(["-C", str(root), "worktree", "list", "--porcelain"], root)
    if code != 0:
        return []
    result: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in _decode(out).splitlines():
        if line.startswith("worktree "):
            if current.get("path"):
                result.append(current)
            current = {"path": line[len("worktree ") :][: DEFAULT_BOUNDS.max_path_chars], "branch": None, "commit": None, "is_current": False}
        elif line.startswith("HEAD ") and current:
            candidate = line[len("HEAD ") :].strip()
            current["commit"] = candidate if re.fullmatch(r"[0-9a-f]{40,64}", candidate) else None
        elif line.startswith("branch ") and current:
            reference = line[len("branch ") :].strip()
            current["branch"] = reference[len("refs/heads/") :] if reference.startswith("refs/heads/") else reference
    if current.get("path"):
        result.append(current)
    for item in result:
        item["is_current"] = _same_directory(item["path"], root)
    if result and not any(item["is_current"] for item in result):
        # Git can omit the current worktree when its administrative entry is
        # stale, typically after the directory was moved. Listing the others
        # without the reader's own location is worse than listing nothing, so
        # the real root is added explicitly.
        result.insert(0, {"path": str(root).replace("\\", "/"), "branch": None, "commit": None, "is_current": True})
    return result[:64]


def _same_directory(left: str, right: Path) -> bool:
    try:
        return Path(left).resolve() == right.resolve()
    except (OSError, ValueError):
        return False


def _head_is_published(root: Path, commit: str | None, has_remotes: bool) -> bool | None:
    """Whether HEAD is reachable from any remote-tracking branch.

    ``False`` means the commit exists only locally, which matters when a
    capsule describes a deployed or otherwise important release.
    """
    if not commit:
        return None
    if not has_remotes:
        return False
    code, out, _ = _run_git(["-C", str(root), "branch", "--remotes", "--contains", commit], root)
    if code != 0:
        return None
    return bool(_decode(out).strip())


def collect_git_facts(cwd: str | Path) -> dict[str, Any]:
    captured_at = now_utc()
    resolved_cwd = Path(cwd).resolve()
    facts: dict[str, Any] = {
        "captured_at": captured_at,
        "cwd": str(resolved_cwd),
        "repo_root": None,
        "branch": None,
        "detached": None,
        "commit": None,
        "remote": None,
        "dirty": None,
        "changed_files": [],
        "changed_files_total": 0,
        "remotes": [],
        "worktrees": [],
        "head_published": None,
        "diff_stat": None,
        "git_available": shutil.which("git") is not None,
        "error": None,
    }
    root = find_repo_root(resolved_cwd)
    if root is None:
        facts["error"] = "not a Git repository or Git is unavailable"
        return facts
    facts["repo_root"] = str(root)
    code, out, _ = _run_git(["-C", str(root), "rev-parse", "HEAD"], root)
    if code == 0 and re.fullmatch(rb"[0-9a-f]{40,64}\s*", out):
        facts["commit"] = _decode(out)
    code, out, _ = _run_git(["-C", str(root), "symbolic-ref", "--short", "-q", "HEAD"], root)
    if code == 0 and _decode(out):
        facts["branch"] = _decode(out)
        facts["detached"] = False
    else:
        facts["detached"] = True
    code, out, _ = _run_git(["-C", str(root), "config", "--get", "remote.origin.url"], root)
    if code == 0:
        facts["remote"] = strip_credentials(_decode(out))
    facts["remotes"] = _collect_remotes(root)
    facts["worktrees"] = _collect_worktrees(root)
    facts["head_published"] = _head_is_published(root, facts["commit"], bool(facts["remotes"]))
    code, out, _ = _run_git(["-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"], root)
    if code == 0:
        facts["changed_files"], facts["changed_files_total"] = _parse_status(root, out, captured_at)
        facts["dirty"] = bool(facts["changed_files_total"])
    else:
        facts["error"] = "Git status could not be collected"
    code, out, _ = _run_git(["-C", str(root), "diff", "--stat", "HEAD", "--no-ext-diff"], root)
    if code == 0:
        facts["diff_stat"] = _decode(out)[: DEFAULT_BOUNDS.max_diff_bytes]
    return facts


def project_from_facts(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo_root_hint": facts.get("repo_root"),
        "remote": strip_credentials(facts.get("remote")),
        "remotes": list(facts.get("remotes") or []),
        "branch": facts.get("branch"),
        "commit": facts.get("commit"),
        "dirty": facts.get("dirty"),
        "changed_files": list(facts.get("changed_files") or []),
        "changed_files_total": int(facts.get("changed_files_total") or 0),
        "worktrees": list(facts.get("worktrees") or []),
        "head_published": facts.get("head_published"),
    }
