"""Read-only Claude Code JSONL adapter with explicit version detection."""

from __future__ import annotations

from pathlib import Path

from .host_common import LocalJsonlHostAdapter


class ClaudeAdapter(LocalJsonlHostAdapter):
    host = "claude"
    default_roots = (
        Path.home() / ".claude" / "projects",
        Path.home() / ".config" / "claude" / "projects",
        Path.home() / "AppData" / "Roaming" / "Claude" / "projects",
    )
