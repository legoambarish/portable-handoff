"""Report whether this host can actually produce a capsule, before one is tried.

Asked for a handoff on a host with no filesystem, a model will otherwise write
a prose summary and call it a handoff. Running this first gives it a concrete
answer to report.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .models import SCHEMA_VERSION
from .storage import capsule_directory, resolve_project_root

SUPPORTED = "supported"
DEGRADED = "degraded"
UNSUPPORTED = "unsupported"


def _writable(directory: Path) -> bool:
    """Probe by actually writing, since permissions alone can mislead."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".probe-", suffix=".tmp", delete=False) as handle:
            probe = Path(handle.name)
            handle.write(b"probe")
        probe.unlink(missing_ok=True)
        return True
    except (OSError, ValueError):
        return False


def diagnose(cwd: str | Path = ".") -> dict[str, Any]:
    root = resolve_project_root(cwd)
    git_available = shutil.which("git") is not None
    capsules = capsule_directory(root)
    can_write = _writable(capsules)

    if not can_write:
        capability = UNSUPPORTED
        reason = "No writable capsule directory. A physical capsule cannot be produced on this host."
    elif not git_available:
        capability = DEGRADED
        reason = "Git is unavailable, so repository facts will be recorded as unknown."
    else:
        capability = SUPPORTED
        reason = "A capsule can be created and validated here."

    return {
        "capability": capability,
        "reason": reason,
        "schema_version": SCHEMA_VERSION,
        "cli_version": __import__("portable_handoff").__version__,
        "python": sys.version.split()[0],
        "cwd": str(Path(cwd).resolve()),
        "repository_root": str(root),
        "git_available": git_available,
        "capsule_directory": str(capsules),
        "capsule_directory_writable": can_write,
        "environment": "windows" if os.name == "nt" else "posix",
    }


__all__ = ["DEGRADED", "SUPPORTED", "UNSUPPORTED", "diagnose"]
