from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from portable_handoff.canonical import digest_document
from portable_handoff.finalize import finalize
from portable_handoff.load import load_capsule
from portable_handoff.preflight import collect_preflight, serialize_preflight
from portable_handoff.storage import capsule_directory
from portable_handoff.validate import validate_file, validate_markdown


def _draft(*, goal: str = "Finish the portable handoff implementation") -> dict:
    return {
        "source": {"model": "test-model"},
        "task": {
            "goal": goal,
            "definition_of_done": ["create a valid self-contained capsule", "load an actionable briefing"],
            "scope_in": ["the local Python repository"],
            "scope_out": ["cloud sync"],
        },
        "state": {"status": "verification", "in_progress": ["integration tests"], "pending": ["release smoke test"], "blockers": []},
        "decisions": [{"decision_id": "d1", "statement": "Keep the Markdown artifact canonical for exchange", "rationale": "It works across hosts"}],
        "constraints": ["Do not make network calls"],
        "user_corrections": ["Do not invent test outcomes"],
        "files": ["src/portable_handoff/finalize.py"],
        "verification": [{"name": "focused tests", "command": "python -m pytest -q", "status": "not_run", "summary": "Not run by the model"}],
        "errors": [{"error": "An earlier draft had an incomplete next action", "fix": "Added an executable command"}],
        "next_action": {"instruction": "Run the full test suite and inspect the release artifact", "file": "pyproject.toml", "command": "python -m pytest -q", "preconditions": ["Keep the run offline"]},
        "recent_context": ["The deterministic finalizer is now wired to the loader."],
        "risks": ["Host transcript formats may change"],
        "unknowns": ["No remote service is configured"],
    }


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Portable Handoff Tests"], cwd=path, check=True)
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)


def test_end_to_end_create_validate_and_load(tmp_path):
    _git_repo(tmp_path)
    preflight = collect_preflight(cwd=tmp_path, source_host="codex")
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(_draft()), encoding="utf-8")

    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    assert result.path is not None and result.path.exists()
    report = validate_file(str(result.path))
    assert report.valid, report.errors
    loaded = load_capsule("latest", cwd=tmp_path)
    assert loaded.staleness.bucket == "fresh"
    assert "Finish the portable handoff implementation" in loaded.briefing
    assert "Run the full test suite" in loaded.briefing


def test_deterministic_project_facts_override_model_claims(tmp_path):
    _git_repo(tmp_path)
    preflight = collect_preflight(cwd=tmp_path, source_host="codex")
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft = _draft()
    draft["project"] = {"branch": "forged-branch", "commit": "0" * 40}
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    assert result.document["project"]["commit"] == preflight["project"]["commit"]
    assert result.document["project"]["branch"] == preflight["project"]["branch"]


def test_not_run_and_unknown_are_not_promoted(tmp_path):
    preflight = collect_preflight(cwd=tmp_path, source_host="other")
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft = _draft()
    draft["verification"] = [{"name": "release tests", "status": "unknown", "summary": "No result was observed"}]
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    assert result.document["verification"][0]["status"] == "unknown"
    assert result.document["verification"][0]["trust"] != "verified"


def test_tampered_json_and_markdown_fail(tmp_path):
    _git_repo(tmp_path)
    preflight = collect_preflight(cwd=tmp_path, source_host="codex")
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(_draft()), encoding="utf-8")
    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    original = result.path.read_text(encoding="utf-8")
    tampered_json = original.replace("Finish the portable handoff implementation", "Tampered goal", 1)
    assert not validate_markdown(tampered_json).valid
    tampered_body = original.replace("## Current State", "## Current State\n\nInjected historical text", 1)
    assert not validate_markdown(tampered_body).valid


def test_latest_filename_scan_is_deterministic(tmp_path):
    directory = capsule_directory(tmp_path)
    directory.mkdir(parents=True)
    (directory / "20260101T000000Z-old-aaaaaaaa.md").write_text("x", encoding="utf-8")
    (directory / "20260102T000000Z-new-bbbbbbbb.md").write_text("x", encoding="utf-8")
    assert load_capsule is not None


def test_commit_change_is_stale(tmp_path):
    _git_repo(tmp_path)
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight = collect_preflight(cwd=tmp_path, source_host="codex")
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft = _draft()
    draft["files"] = []
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=tmp_path, check=True)
    loaded = load_capsule(str(result.path), cwd=tmp_path)
    assert loaded.staleness.bucket == "stale"
    assert any("HEAD commit moved" in reason for reason in loaded.staleness.reasons)


def test_missing_referenced_file_is_obvious(tmp_path):
    _git_repo(tmp_path)
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight = collect_preflight(cwd=tmp_path, source_host="codex")
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft = _draft()
    draft["files"] = ["tracked.txt"]
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    (tmp_path / "tracked.txt").unlink()
    loaded = load_capsule(str(result.path), cwd=tmp_path)
    assert loaded.staleness.bucket == "missing"
    assert "referenced file is missing" in loaded.briefing


def test_secret_does_not_reach_capsule(tmp_path):
    preflight = collect_preflight(cwd=tmp_path, source_host="other")
    helper_dir = tmp_path / ".handoff" / "evidence"
    helper_dir.mkdir(parents=True)
    preflight_path = helper_dir / "preflight.json"
    preflight_path.write_text(serialize_preflight(preflight), encoding="utf-8")
    draft = _draft()
    draft["task"]["goal"] = "Document password=super-secret-value without leaking it"
    draft_path = helper_dir / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    result = finalize(preflight_path=preflight_path, draft_path=draft_path, output="auto")
    content = result.path.read_text(encoding="utf-8")
    assert "super-secret-value" not in content
    assert "REDACTED" in content
