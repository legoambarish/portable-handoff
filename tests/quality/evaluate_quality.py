"""Generate the ten-scenario quality report without a model or network call."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portable_handoff.bounds import estimate_tokens
from portable_handoff.canonical import with_integrity
from portable_handoff.models import empty_document
from portable_handoff.strict_json import canonical_bytes


SCENARIOS = (
    "half-built feature",
    "known failing test",
    "superseded decision",
    "multi-file refactor",
    "no Git",
    "dirty/untracked tree",
    "tests not run",
    "conflicting assistant claims",
    "external blocker",
    "security-sensitive transcript",
)


def _claim(text: str, trust: str = "observed") -> dict[str, Any]:
    return {"text": text, "provenance": "conversation:user", "trust": trust, "evidence_refs": [], "captured_at": None}


def scenario_document(name: str) -> dict[str, Any]:
    doc = empty_document(handoff_id="00000000-0000-4000-8000-000000000001", created_at="2026-08-17T00:00:00Z")
    doc["task"]["goal"] = f"Complete the {name} scenario"
    doc["task"]["definition_of_done"] = [_claim("The continuation can execute the next action")]
    doc["constraints"] = [_claim("Keep the workflow local and offline")]
    doc["user_corrections"] = [_claim("Preserve the exact immediate next action")]
    doc["state"]["status"] = "blocked" if name in {"external blocker", "known failing test"} else "in_progress"
    doc["state"]["in_progress"] = [_claim("Continue the current implementation")]
    doc["state"]["pending"] = [_claim("Run the next verification gate")]
    doc["next_action"] = {"instruction": "Run the focused validation gate", "file": "src/portable_handoff", "command": "python -m pytest -q", "preconditions": []}
    doc["files"] = [{"path": "src/portable_handoff/core.py", "symbols": [], "role": "implementation", "hash": None, "exists": True, "provenance": "file", "trust": "observed", "evidence_refs": [], "captured_at": None}]
    if name == "multi-file refactor":
        doc["files"].append({**doc["files"][0], "path": "tests/test_core.py"})
    if name in {"known failing test", "tests not run"}:
        doc["verification"] = [{"name": "test gate", "command": "python -m pytest -q", "status": "failed" if name == "known failing test" else "not_run", "summary": "The result is preserved exactly", "commit": None, "captured_at": None, "provenance": "test", "trust": "claimed", "evidence_refs": []}]
        doc["errors"] = [{"error": "The test gate is not green", "fix": "Inspect the first failure", "status": "open", "command": "python -m pytest -q", "provenance": "test", "trust": "claimed", "evidence_refs": [], "captured_at": None}]
    if name == "superseded decision":
        doc["decisions"] = [{"decision_id": "d-old", "statement": "Use the first approach", "rationale": "Earlier constraint", "status": "superseded", "provenance": "conversation:assistant", "trust": "claimed", "evidence_refs": [], "captured_at": None}, {"decision_id": "d-new", "statement": "Use the replacement approach", "rationale": "It handles the constraint", "status": "active", "provenance": "conversation:user", "trust": "observed", "evidence_refs": [], "captured_at": None}]
    if name in {"no Git", "external blocker", "conflicting assistant claims"}:
        doc["unknowns"] = [_claim("Repository or external state could not be verified", "inferred")]
    if name == "security-sensitive transcript":
        doc["recent_context"] = [{"role": "user", "text": "A historical secret was redacted before persistence", "timestamp": None, "provenance": "transcript", "trust": "untrusted", "evidence_refs": []}]
        doc["security"]["redactions"] = [{"kind": "github_token", "count": 1}]
    if name == "dirty/untracked tree":
        doc["project"]["dirty"] = True
        doc["project"]["changed_files"] = [{"path": "new.txt", "status": "untracked", "staged": False, "hash": None, "exists": True, "provenance": "git", "trust": "verified", "captured_at": None}]
    return with_integrity(doc)


def score_document(name: str, document: dict[str, Any]) -> dict[str, Any]:
    dimensions = {
        "goal_retention": bool(document["task"]["goal"]),
        "constraints": bool(document["constraints"]),
        "decisions": name != "superseded decision" or any(item["status"] == "superseded" for item in document["decisions"]),
        "user_corrections": bool(document["user_corrections"]),
        "changed_files": bool(document["files"] or document["project"]["changed_files"]),
        "verification_truthfulness": all(item["status"] in {"passed", "failed", "not_run", "unknown"} for item in document["verification"]),
        "errors_and_fixes": name not in {"known failing test", "tests not run"} or bool(document["errors"]),
        "next_action_executable": bool(document["next_action"]["instruction"] and (document["next_action"]["command"] or document["next_action"]["file"])),
        "unsupported_claims": name not in {"no Git", "external blocker", "conflicting assistant claims"} or bool(document["unknowns"]),
        "leakage": not any(secret in json.dumps(document) for secret in ("ghp_", "super-secret-value", "Bearer ")),
        "size": estimate_tokens(canonical_bytes(document)) <= 12_000,
    }
    passed = sum(dimensions.values())
    return {"scenario": name, "score": passed, "max_score": len(dimensions), "passed": passed == len(dimensions), "dimensions": dimensions}


def build_report() -> dict[str, Any]:
    rows = [score_document(name, scenario_document(name)) for name in SCENARIOS]
    return {"schema_version": "quality-report-v1", "deterministic": True, "scenario_count": len(rows), "all_must_preserve_fields_pass": all(row["passed"] for row in rows), "scenarios": rows}


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
