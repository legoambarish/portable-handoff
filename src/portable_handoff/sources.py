"""Source command dispatcher; bounded adapters are implemented in M6."""

from __future__ import annotations

from typing import Any

from .errors import SourceError


def source_command(args: Any) -> dict[str, Any]:
    raise SourceError("requested transcript adapter is not available in this build")
