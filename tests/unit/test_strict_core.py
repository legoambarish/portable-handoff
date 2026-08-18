from __future__ import annotations

import json
import uuid

import pytest

from portable_handoff.canonical import verify_integrity, with_integrity
from portable_handoff.errors import IntegrityError, LimitError, SchemaError
from portable_handoff.models import empty_document, normalize_draft, validate_document
from portable_handoff.strict_json import canonical_bytes, loads_strict


def complete_document():
    value = empty_document(handoff_id=str(uuid.uuid4()), created_at="2026-08-17T00:00:00Z")
    value["task"] = {
        "goal": "Implement the portable handoff core",
        "definition_of_done": ["strict parsing works"],
        "scope_in": ["the local repository"],
        "scope_out": ["remote services"],
    }
    value["state"] = {"status": "verification", "completed": [], "in_progress": ["core"], "pending": ["tests"], "blockers": []}
    value["next_action"] = {"instruction": "run the focused tests", "file": None, "command": "python -m pytest -q", "preconditions": []}
    return value


def test_duplicate_keys_are_rejected():
    with pytest.raises(SchemaError):
        loads_strict('{"a":1,"a":2}')


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected(literal):
    with pytest.raises(SchemaError):
        loads_strict(literal)


def test_canonical_json_is_sorted_and_unicode_stable():
    assert canonical_bytes({"b": 1, "a": "e\u0301"}) == '{"a":"é","b":1}'.encode()


def test_nested_and_byte_bounds_are_enforced():
    with pytest.raises(LimitError):
        loads_strict(json.dumps([[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]))
    with pytest.raises(LimitError):
        loads_strict("x" * (512 * 1024 + 1))


def test_model_normalization_and_exact_top_level_fields():
    normalized = validate_document(with_integrity(complete_document()))
    assert set(normalized) == {
        "schema_version", "handoff_id", "created_at", "source", "project", "task", "state", "decisions",
        "constraints", "user_corrections", "files", "verification", "errors", "next_action", "recent_context",
        "evidence", "risks", "unknowns", "security", "integrity",
    }
    with pytest.raises(SchemaError):
        validate_document({**normalized, "unexpected": True})


def test_draft_is_not_allowed_to_supply_integrity():
    draft = normalize_draft({"task": {"goal": "draft"}, "next_action": {"instruction": "continue"}, "integrity": {"digest": "f" * 64}})
    assert draft["integrity"]["digest"] == ""


def test_digest_detects_tampering():
    capsule = with_integrity(complete_document())
    verify_integrity(capsule)
    capsule["task"]["goal"] = "tampered"
    with pytest.raises(IntegrityError):
        verify_integrity(capsule)
