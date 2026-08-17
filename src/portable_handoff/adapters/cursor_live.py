"""No live Cursor process access is performed by Portable Handoff v0.1."""

from __future__ import annotations

from ..errors import SourceError


def probe(*args, **kwargs):
    raise SourceError("live Cursor process access is unsupported; provide a bounded transcript file")
