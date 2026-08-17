"""Deterministic capsule budgeting with preservation priorities."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .bounds import DEFAULT_BOUNDS, estimate_tokens
from .strict_json import canonical_bytes


@dataclass
class BudgetReport:
    estimated_tokens: int = 0
    dropped: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"estimated_tokens": self.estimated_tokens, "dropped": list(self.dropped), "truncated": list(self.truncated)}


def _size(document: dict[str, Any]) -> int:
    return estimate_tokens(canonical_bytes(document))


def _drop_oldest(document: dict[str, Any], path: tuple[str, ...], report: BudgetReport) -> bool:
    current: Any = document
    for part in path[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    key = path[-1]
    values = current.get(key) if isinstance(current, dict) else None
    if not isinstance(values, list) or not values:
        return False
    values.pop(0)
    report.dropped.append(".".join(path))
    return True


def _truncate_at(document: dict[str, Any], path: tuple[str, ...], maximum: int, report: BudgetReport) -> bool:
    current: Any = document
    for part in path[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    key = path[-1]
    value = current.get(key) if isinstance(current, dict) else None
    if not isinstance(value, str) or len(value) <= maximum:
        return False
    current[key] = value[:maximum].rstrip() + " …[budgeted]"
    report.truncated.append(".".join(path))
    return True


def budget_document(document: dict[str, Any], *, target_tokens: int = DEFAULT_BOUNDS.target_estimated_tokens, maximum_tokens: int = DEFAULT_BOUNDS.max_estimated_tokens) -> tuple[dict[str, Any], BudgetReport]:
    result = copy.deepcopy(document)
    result["integrity"] = {"algorithm": "sha256", "digest": ""}
    report = BudgetReport(estimated_tokens=_size(result))

    # Preserve exact next action, user corrections, hard constraints, blockers,
    # active decisions, and verified facts while trimming narrative first.
    drop_paths = (
        ("recent_context",),
        ("evidence",),
        ("state", "completed"),
        ("risks",),
        ("errors",),
        ("files",),
        ("task", "scope_out"),
    )
    index = 0
    while report.estimated_tokens > target_tokens and index < 100_000:
        path = drop_paths[index % len(drop_paths)]
        if _drop_oldest(result, path, report):
            report.estimated_tokens = _size(result)
        else:
            index += 1
            if index >= len(drop_paths) and all(not _drop_oldest(result, p, report) for p in drop_paths):
                break

    # If a few long fields still exceed the hard cap, shorten low-priority
    # narratives; never silently replace the goal or immediate next action.
    truncate_paths = (
        ("recent_context",),
        ("errors",),
        ("evidence",),
        ("files",),
        ("task", "scope_out"),
        ("task", "scope_in"),
    )
    if report.estimated_tokens > maximum_tokens:
        # The collection trimmer above is usually sufficient. This compact
        # fallback strips text from the first remaining narrative item.
        for path in truncate_paths:
            if report.estimated_tokens <= maximum_tokens:
                break
            current: Any = result
            for part in path[:-1]:
                current = current.get(part) if isinstance(current, dict) else None
            values = current.get(path[-1]) if isinstance(current, dict) else None
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        for key in ("text", "summary", "error", "fix", "statement"):
                            if isinstance(item.get(key), str) and len(item[key]) > 256:
                                item[key] = item[key][:256].rstrip() + " …[budgeted]"
                                report.truncated.append(".".join(path) + "." + key)
                                report.estimated_tokens = _size(result)
                                if report.estimated_tokens <= maximum_tokens:
                                    break
                        if report.estimated_tokens <= maximum_tokens:
                            break
    report.estimated_tokens = _size(result)
    return result, report
