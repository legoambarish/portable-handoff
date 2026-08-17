"""Deterministic local preflight collection and bounded serialization."""

from __future__ import annotations

import platform
import sys
import uuid
from pathlib import Path
from typing import Any

from .bounds import DEFAULT_BOUNDS
from .gitfacts import collect_git_facts, project_from_facts
from .models import Host, now_utc
from .sanitize import safe_read_bytes, sanitize_value
from .storage import atomic_write, capsule_directory, evidence_directory
from .strict_json import canonical_bytes, loads_strict


PREFLIGHT_FIELDS = frozenset({"preflight_version", "preflight_id", "captured_at", "cwd", "source", "git", "project", "runtime", "output_locations", "warnings"})


def _host(value: str | None) -> str:
    value = (value or "unknown").lower()
    return value if value in {item.value for item in Host} else Host.UNKNOWN.value


def collect_preflight(*, cwd: str | Path = ".", source_host: str | None = None, session: str | None = None) -> dict[str, Any]:
    facts = collect_git_facts(cwd)
    captured_at = facts["captured_at"]
    root = facts.get("repo_root") or facts["cwd"]
    preflight: dict[str, Any] = {
        "preflight_version": "0.1",
        "preflight_id": str(uuid.uuid4()),
        "captured_at": captured_at,
        "cwd": facts["cwd"],
        "source": {"host": _host(source_host), "session_ref": session, "transcript_source": "live_context" if session is None else "local_adapter"},
        "git": facts,
        "project": project_from_facts(facts),
        "runtime": {"python": sys.version.split()[0], "implementation": platform.python_implementation(), "platform": platform.system()},
        "output_locations": {"capsules": str(capsule_directory(root)), "evidence": str(evidence_directory(root))},
        "warnings": [],
    }
    if not facts.get("git_available"):
        preflight["warnings"].append("Git was unavailable; repository facts are unknown.")
    elif not facts.get("repo_root"):
        preflight["warnings"].append("The working directory is not a Git repository; repository facts are unknown.")
    if facts.get("error"):
        preflight["warnings"].append(str(facts["error"]))
    clean, _ = sanitize_value(preflight)
    return clean


def serialize_preflight(preflight: dict[str, Any]) -> str:
    return canonical_bytes(preflight).decode("utf-8") + "\n"


def write_preflight(preflight: dict[str, Any], output: str | None) -> str | Path:
    rendered = serialize_preflight(preflight)
    if output in (None, "-"):
        return rendered
    return atomic_write(output, rendered, maximum=DEFAULT_BOUNDS.max_json_bytes)


def read_preflight(path: str | Path) -> dict[str, Any]:
    raw = safe_read_bytes(path, maximum=DEFAULT_BOUNDS.max_json_bytes)
    value = loads_strict(raw, bounds=DEFAULT_BOUNDS, label="preflight JSON")
    if not isinstance(value, dict) or set(value) != PREFLIGHT_FIELDS:
        raise ValueError("preflight JSON has an unsupported shape")
    return value
