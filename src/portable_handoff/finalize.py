"""Safe deterministic finalization of a semantic draft into a capsule."""

from __future__ import annotations

import copy
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .budgeting import BudgetReport, budget_document
from .canonical import digest_bytes, with_integrity
from .errors import SchemaError, UnsafePathError
from .models import Provenance, Trust, empty_document, normalize_draft, now_utc
from .preflight import read_preflight
from .render import render_capsule
from .sanitize import (
    SECRET_PATTERNS_VERSION,
    count_text_fields,
    ensure_no_symlink,
    normalize_relative_path,
    safe_read_bytes,
    sanitize_document,
)
from .storage import atomic_write, capsule_directory, capsule_filename
from .strict_json import canonical_bytes, loads_strict
from .validate import validate_markdown


@dataclass(frozen=True)
class FinalizeResult:
    path: Path | None
    markdown: str
    document: dict[str, Any]
    budget: BudgetReport
    redactions: list[dict[str, Any]]


def _reject_forged_draft_fields(raw: object) -> None:
    if not isinstance(raw, dict):
        raise SchemaError("draft must be a JSON object")
    if "created_at" in raw:
        raise SchemaError("draft cannot set deterministic created_at")
    if "handoff_id" in raw:
        raise SchemaError("draft cannot set deterministic handoff_id")
    integrity = raw.get("integrity")
    if integrity not in (None, {}):
        raise SchemaError("draft cannot set integrity")
    # A model may mention repository facts in a draft, but those structured
    # claims are deliberately ignored. Only the deterministic preflight supplies
    # the final project object, so a conflict cannot forge evidence.
    evidence = raw.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("digest") not in (None, ""):
                raise SchemaError("draft cannot set evidence hashes")


def _safe_root(preflight: dict[str, Any]) -> Path:
    git = preflight.get("git") or {}
    raw = git.get("repo_root") or preflight.get("cwd") or "."
    return Path(str(raw)).resolve()


def _hash_file(path: Path) -> str | None:
    try:
        before = path.stat()
        if not path.is_file() or path.is_symlink() or before.st_size > 32 * 1024 * 1024:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            return None
        return digest.hexdigest()
    except OSError:
        return None


def _normalize_file_path(raw_path: str, root: Path) -> str:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise UnsafePathError("file reference escapes repository root") from exc
        raw_path = relative.as_posix()
    return normalize_relative_path(raw_path, root=root)


def _verified_files(draft_files: list[dict[str, Any]], *, root: Path, captured_at: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in draft_files:
        path = _normalize_file_path(item["path"], root)
        if path in seen:
            continue
        seen.add(path)
        candidate = root / Path(*path.split("/"))
        exists = False
        digest = None
        if candidate.exists():
            ensure_no_symlink(candidate, root=root)
            exists = candidate.is_file()
            if exists:
                digest = _hash_file(candidate)
        result.append({
            "path": path,
            "symbols": item.get("symbols", []),
            "role": item.get("role"),
            "hash": digest,
            "exists": exists,
            "provenance": Provenance.GIT.value if (root / ".git").exists() else Provenance.FILE.value,
            "trust": Trust.VERIFIED.value,
            "evidence_refs": item.get("evidence_refs", []),
            "captured_at": captured_at,
        })
    return result


def _downgrade_model_verification(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = copy.deepcopy(records)
    for item in result:
        if item.get("trust") == Trust.VERIFIED.value:
            item["trust"] = Trust.CLAIMED.value
        if item.get("provenance") == Provenance.GIT.value:
            item["provenance"] = Provenance.TEST.value
    return result


def _final_document(preflight: dict[str, Any], draft_raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], BudgetReport]:
    _reject_forged_draft_fields(draft_raw)
    task_raw = draft_raw.get("task")
    if not isinstance(task_raw, dict) or not isinstance(task_raw.get("goal"), str) or not task_raw.get("goal", "").strip():
        raise SchemaError("draft must include a non-empty task.goal")
    next_raw = draft_raw.get("next_action")
    if not isinstance(next_raw, dict) or not isinstance(next_raw.get("instruction"), str) or not next_raw.get("instruction", "").strip():
        raise SchemaError("draft must include a non-empty next_action.instruction")
    semantic = normalize_draft(draft_raw)
    captured_at = str(preflight.get("captured_at") or now_utc())
    root = _safe_root(preflight)
    git = preflight.get("git") or {}
    project = copy.deepcopy(preflight.get("project") or {})
    if not project:
        project = {"repo_root_hint": None, "remote": None, "branch": None, "commit": None, "dirty": None, "changed_files": []}

    source_claim = semantic["source"]
    pf_source = preflight.get("source") or {}
    source = {
        "host": pf_source.get("host", "unknown"),
        "model": source_claim.get("model"),
        "session_id": pf_source.get("session_ref") or source_claim.get("session_id"),
        "transcript_source": pf_source.get("transcript_source", "none"),
        "cwd": preflight.get("cwd"),
    }
    base = empty_document(handoff_id=str(uuid.uuid4()), created_at=captured_at)
    base.update({
        "source": source,
        "project": project,
        "task": semantic["task"],
        "state": semantic["state"],
        "decisions": semantic["decisions"],
        "constraints": semantic["constraints"],
        "user_corrections": semantic["user_corrections"],
        "verification": _downgrade_model_verification(semantic["verification"]),
        "errors": semantic["errors"],
        "next_action": semantic["next_action"],
        "recent_context": semantic["recent_context"],
        "risks": semantic["risks"],
        "unknowns": semantic["unknowns"],
        "security": semantic["security"],
    })
    base["files"] = _verified_files(semantic["files"], root=root, captured_at=captured_at)

    unknowns = base["unknowns"]
    if not git.get("git_available") or not git.get("repo_root"):
        unknowns.append({"text": "Git repository facts were unavailable; repository identity, branch, commit, and changed-file facts are unknown.", "provenance": Provenance.TOOL.value, "trust": Trust.OBSERVED.value, "evidence_refs": [], "captured_at": captured_at})
    if not git.get("commit"):
        unknowns.append({"text": "No committed HEAD was observed during preflight.", "provenance": Provenance.GIT.value, "trust": Trust.OBSERVED.value, "evidence_refs": [], "captured_at": captured_at})

    evidence = copy.deepcopy(semantic["evidence"])
    evidence.append({
        "evidence_id": "preflight-git",
        "kind": "deterministic_preflight",
        "source": "portable-handoff preflight",
        "digest": digest_bytes(canonical_bytes(git)),
        "summary": "Bounded local Git and working-directory facts captured before semantic finalization.",
        "captured_at": captured_at,
        "provenance": Provenance.TOOL.value,
        "trust": Trust.VERIFIED.value,
    })
    base["evidence"] = evidence
    if pf_source.get("transcript_source") not in (None, "none", "live_context"):
        base["security"]["untrusted_sources"] = sorted(set(base["security"].get("untrusted_sources", [])) | {f"local_adapter:{pf_source.get('host', 'unknown')}"})
    scanned = count_text_fields(base)
    clean, redactions = sanitize_document(base)
    # An empty redaction list is not evidence that anything was checked, so the
    # capsule records that a scan ran, which rules it used, and how much it saw.
    clean["security"]["secret_scan"] = {"status": "passed", "patterns_version": SECRET_PATTERNS_VERSION, "fields_scanned": scanned}
    clean = _derive_blockers(clean, captured_at=captured_at)
    clean, budget = budget_document(clean)
    capsule = with_integrity(clean)
    return capsule, redactions, budget


def _derive_blockers(document: dict[str, Any], *, captured_at: str) -> dict[str, Any]:
    """A capsule that is waiting on a person must say so where blockers are read.

    A future model scans `state.blockers`. Recording the dependency only in
    `unknowns` or `preconditions` lets that model read "no blockers" and start
    editing files while a decision is still outstanding.
    """
    question = document["next_action"].get("blocking_question")
    if not question:
        return document
    existing = {item["text"] for item in document["state"]["blockers"]}
    text = "Awaiting a user decision before the next action can proceed; see the blocking question in the next action."
    if text not in existing:
        document["state"]["blockers"].append({
            "text": text,
            "provenance": Provenance.ASSISTANT.value,
            "trust": Trust.CLAIMED.value,
            "evidence_refs": [],
            "captured_at": captured_at,
        })
    if document["state"]["status"] not in ("blocked", "complete"):
        document["state"]["status"] = "blocked"
    return document


def _output_path(output: str | None, *, preflight: dict[str, Any], document: dict[str, Any]) -> Path | None:
    if output in (None, "-"):
        return None
    root = _safe_root(preflight)
    if output == "auto":
        directory = capsule_directory(root)
        return directory / capsule_filename(document["created_at"], document["task"]["goal"], document["handoff_id"])
    path = Path(output)
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    try:
        if os.path.commonpath((str(root), str(path))) != str(root):
            raise UnsafePathError("output path escapes repository root")
    except ValueError as exc:
        raise UnsafePathError("output path root mismatch") from exc
    if path.suffix.lower() != ".md":
        raise UnsafePathError("output path must end in .md")
    return path


def finalize(*, preflight_path: str | Path, draft_path: str | Path, output: str | None = "auto", force: bool = False) -> FinalizeResult:
    preflight = read_preflight(preflight_path)
    draft_raw = loads_strict(safe_read_bytes(draft_path, maximum=512 * 1024), label="draft JSON")
    if not isinstance(draft_raw, dict):
        raise SchemaError("draft must be a JSON object")
    document, redactions, budget = _final_document(preflight, draft_raw)
    markdown = render_capsule(document)
    validation = validate_markdown(markdown)
    if not validation.valid:
        raise SchemaError("finalized capsule did not pass its own validation")
    path = _output_path(output, preflight=preflight, document=document)
    if path is not None:
        atomic_write(path, markdown, force=force)
    return FinalizeResult(path, markdown, document, budget, redactions)
