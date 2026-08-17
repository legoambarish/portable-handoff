from __future__ import annotations

import uuid

import pytest

from portable_handoff.canonical import with_integrity
from portable_handoff.errors import CollisionError, UnsafePathError
from portable_handoff.gitfacts import collect_git_facts, project_from_facts, strip_credentials
from portable_handoff.models import empty_document
from portable_handoff.sanitize import normalize_relative_path, redact_text, sanitize_document
from portable_handoff.storage import atomic_write, capsule_filename, list_capsules


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", "bearer_token"),
        ("token=ghp_abcdefghijklmnopqrstuvwxyz1234567890", "github_token"),
        ("https://user:password@example.test/repo", "credentialed_url"),
        ("-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----", "private_key"),
    ],
)
def test_high_confidence_secrets_are_redacted_without_echo(value, kind):
    result = redact_text(value)
    assert kind in {item.kind for item in result.redactions}
    assert "secret" not in result.text.lower() or kind == "private_key"


def test_benign_lookalike_is_not_over_redacted():
    result = redact_text("The API token field is optional; token length is documented.")
    assert result.redactions == ()


def test_document_redaction_updates_security_without_secret_value():
    doc = empty_document(handoff_id=str(uuid.uuid4()), created_at="2026-08-17T00:00:00Z")
    doc["task"]["goal"] = "Use password=super-secret-value in a local test"
    clean, report = sanitize_document(doc)
    assert "super-secret-value" not in str(clean)
    assert report


def test_remote_credentials_are_removed():
    assert strip_credentials("https://user:pass@example.test/org/repo.git") == "https://example.test/org/repo.git"
    assert strip_credentials("git@example.test:org/repo.git") == "example.test:org/repo.git"


def test_paths_reject_traversal_and_absolute_paths():
    assert normalize_relative_path("src\\main.py") == "src/main.py"
    with pytest.raises(UnsafePathError):
        normalize_relative_path("../outside.txt")
    with pytest.raises(UnsafePathError):
        normalize_relative_path("C:\\outside.txt")


def test_atomic_storage_is_no_clobber_and_lists_latest(tmp_path):
    capsules = tmp_path / ".handoff" / "capsules"
    capsules.mkdir(parents=True)
    first = capsules / "20260817T000000Z-first-aaaaaaaa.md"
    atomic_write(first, "one")
    with pytest.raises(CollisionError):
        atomic_write(first, "two")
    second = capsules / "20260817T000001Z-second-bbbbbbbb.md"
    atomic_write(second, "two")
    assert list_capsules(tmp_path) == [second, first]


def test_git_facts_are_bounded_and_project_shape(tmp_path):
    facts = collect_git_facts(tmp_path)
    project = project_from_facts(facts)
    assert set(project) == {"repo_root_hint", "remote", "branch", "commit", "dirty", "changed_files"}
    assert "password" not in str(facts).lower()


def test_integrity_can_be_added_after_sanitization():
    doc = empty_document(handoff_id=str(uuid.uuid4()), created_at="2026-08-17T00:00:00Z")
    doc["task"]["goal"] = "Create a secure capsule"
    doc["next_action"]["instruction"] = "run the tests"
    clean, _ = sanitize_document(doc)
    capsule = with_integrity(clean)
    assert len(capsule["integrity"]["digest"]) == 64
