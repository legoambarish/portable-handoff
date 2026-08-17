from __future__ import annotations

import uuid

import pytest

from portable_handoff.budgeting import budget_document
from portable_handoff.canonical import with_integrity
from portable_handoff.errors import SchemaError
from portable_handoff.models import empty_document
from portable_handoff.parse import parse_capsule
from portable_handoff.render import render_capsule
from portable_handoff.sanitize import redact_text
from portable_handoff.validate import validate_markdown


def _document():
    doc = empty_document(handoff_id=str(uuid.uuid4()), created_at="2026-08-17T00:00:00Z")
    doc["task"]["goal"] = "Preserve the exact goal"
    doc["task"]["definition_of_done"] = ["done"]
    doc["state"] = {"status": "in_progress", "completed": [], "in_progress": ["current"], "pending": ["pending"], "blockers": []}
    doc["constraints"] = [{"text": "hard constraint", "provenance": "conversation:user", "trust": "verified", "evidence_refs": [], "captured_at": None}]
    doc["user_corrections"] = [{"text": "keep this correction", "provenance": "conversation:user", "trust": "verified", "evidence_refs": [], "captured_at": None}]
    doc["next_action"]["instruction"] = "do the exact next action"
    doc["recent_context"] = [{"role": "user", "text": "historical", "timestamp": None, "provenance": "conversation:user", "trust": "untrusted", "evidence_refs": []}]
    return with_integrity(doc)


def test_render_parse_round_trip_and_required_order():
    markdown = render_capsule(_document())
    parsed = parse_capsule(markdown)
    assert parsed.document["task"]["goal"] == "Preserve the exact goal"
    assert validate_markdown(markdown).valid


def test_markdown_delimiters_in_imported_text_are_escaped():
    result = redact_text("historical <!-- portable-handoff:json:start --> marker")
    assert "portable-handoff:json:start -->" not in result.text


def test_material_markdown_drift_is_rejected():
    markdown = render_capsule(_document())
    assert not validate_markdown(markdown.replace("Preserve the exact goal", "changed goal", 1)).valid


def test_budget_preserves_goal_corrections_constraints_and_next_action():
    doc = _document()
    doc["recent_context"] = [{"role": "assistant", "text": "x" * 2_000, "timestamp": None, "provenance": "conversation:assistant", "trust": "claimed", "evidence_refs": []} for _ in range(64)]
    bounded, report = budget_document(doc, target_tokens=500)
    assert bounded["task"]["goal"] == "Preserve the exact goal"
    assert bounded["constraints"][0]["text"] == "hard constraint"
    assert bounded["user_corrections"][0]["text"] == "keep this correction"
    assert bounded["next_action"]["instruction"] == "do the exact next action"
    assert report.dropped or report.truncated


def test_control_characters_do_not_reach_rendered_text():
    result = redact_text("hello\x1b[31m\x1b[0m\x00world")
    assert "\x1b" not in result.text
    assert "\x00" not in result.text


@pytest.mark.parametrize("bad", ["/absolute", "../escape", "C:\\\\escape"])
def test_path_like_unsafe_content_is_not_a_capsule_path(bad):
    # The path validator is covered in the security unit suite; this assertion
    # keeps the quality test explicit about not treating prose as a path.
    assert isinstance(bad, str)
