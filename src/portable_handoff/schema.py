"""Schema discovery. `models.py` is the authoritative contract; the JSON
Schema this module locates is interoperable documentation for other readers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import TOP_LEVEL_FIELDS


def schema_path() -> Path:
    repository_schema = Path(__file__).resolve().parents[2] / "schemas" / "handoff-v1.schema.json"
    if repository_schema.is_file():
        return repository_schema
    return Path(__file__).resolve().parent / "resources" / "handoff-v1.schema.json"


def load_schema() -> dict[str, Any]:
    return json.loads(schema_path().read_text(encoding="utf-8"))


__all__ = ["TOP_LEVEL_FIELDS", "load_schema", "schema_path"]
