"""Bounded, read-only Git fact collection."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .bounds import DEFAULT_BOUNDS
from .errors import BusySourceError
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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


def _parse_status(root: Path, raw: bytes, captured_at: str) -> list[dict[str, Any]]:
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
        if code[0] in "RC" and index < len(parts) and parts[index]:
            path_text = parts[index].decode("utf-8", "replace")
            index += 1
        try:
            rel = normalize_relative_path(path_text, root=root)
        except Exception:
            continue
        # Capsules and sidecars are Portable Handoff's own local metadata;
        # creating one must not make an otherwise unchanged worktree stale.
        if rel == ".handoff" or rel.startswith(".handoff/"):
            continue
        absolute = root / Path(*rel.split("/"))
        exists = absolute.exists() and not absolute.is_symlink()
        status = "untracked" if code == "??" else ("deleted" if "D" in code else ("renamed" if "R" in code else ("copied" if "C" in code else "modified")))
        result.append({
            "path": rel,
            "status": status,
            "staged": code[0] not in " ?!",
            "hash": _sha256_file(absolute) if exists else None,
            "exists": exists,
            "provenance": Provenance.GIT.value,
            "trust": Trust.VERIFIED.value,
            "captured_at": captured_at,
        })
    return result[: DEFAULT_BOUNDS.max_changed_files]


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
        "diff_stat": None,
        "git_available": shutil.which("git") is not None,
        "error": None,
    }
    root = find_repo_root(resolved_cwd)
    if root is None:
        facts["error"] = "not a Git repository or Git is unavailable"
        return facts
    facts["repo_root"] = str(root)
    code, out, err = _run_git(["-C", str(root), "rev-parse", "HEAD"], root)
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
    code, out, _ = _run_git(["-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"], root)
    if code == 0:
        facts["changed_files"] = _parse_status(root, out, captured_at)
        facts["dirty"] = bool(facts["changed_files"])
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
        "branch": facts.get("branch"),
        "commit": facts.get("commit"),
        "dirty": facts.get("dirty"),
        "changed_files": list(facts.get("changed_files") or []),
    }
