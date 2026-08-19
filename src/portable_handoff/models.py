"""Versioned Portable Handoff contract and strict model normalization."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .bounds import DEFAULT_BOUNDS, require_text, walk_bounds
from .errors import SchemaError
from .sanitize import normalize_relative_path

SCHEMA_VERSION = "1.2"

# Provenances a deterministic check can stand behind. A claim sourced from
# conversation or from the model's own reasoning is never `verified`, whatever
# the draft asserts, since that would let a model promote its own recollection
# into a fact.
DETERMINISTIC_PROVENANCES = frozenset({"git", "tool", "test", "file", "transcript"})
# Schema 1.0 shipped only in pre-release builds. It is rejected with a specific
# message rather than silently accepted, because 1.1 adds fields a 1.0 reader
# would not know to distrust (worktrees, blocking questions, secret-scan state).
SUPERSEDED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})


class _TextEnum(StrEnum):
    """Base for the closed vocabularies the capsule format depends on."""


class Host(_TextEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR = "cursor"
    CHATGPT = "chatgpt"
    OTHER = "other"
    UNKNOWN = "unknown"


class TranscriptSource(_TextEnum):
    LIVE_CONTEXT = "live_context"
    FILE = "file"
    LOCAL_ADAPTER = "local_adapter"
    NONE = "none"


class TaskStatus(_TextEnum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    VERIFICATION = "verification"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


class VerificationStatus(_TextEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    UNKNOWN = "unknown"


class ScanStatus(_TextEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    UNKNOWN = "unknown"


class DecisionStatus(_TextEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class Trust(_TextEnum):
    VERIFIED = "verified"
    OBSERVED = "observed"
    CLAIMED = "claimed"
    INFERRED = "inferred"
    UNTRUSTED = "untrusted"


class Provenance(_TextEnum):
    USER = "conversation:user"
    ASSISTANT = "conversation:assistant"
    TOOL = "tool"
    FILE = "file"
    GIT = "git"
    TEST = "test"
    TRANSCRIPT = "transcript"
    MODEL_INFERENCE = "model_inference"


TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "handoff_id",
        "created_at",
        "source",
        "project",
        "task",
        "state",
        "decisions",
        "constraints",
        "user_corrections",
        "files",
        "verification",
        "errors",
        "next_action",
        "recent_context",
        "evidence",
        "risks",
        "unknowns",
        "security",
        "integrity",
    }
)
PROVENANCE_VALUES = frozenset(item.value for item in Provenance)
TRUST_VALUES = frozenset(item.value for item in Trust)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_rfc3339_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _closed(mapping: Mapping[str, Any], expected: set[str] | frozenset[str], label: str) -> None:
    unknown = set(mapping) - set(expected)
    if unknown:
        raise SchemaError(f"{label} contains unknown field")


def _text(value: object, *, label: str, maximum: int = DEFAULT_BOUNDS.max_string_chars, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise SchemaError(f"{label} must not be empty")
    try:
        return require_text(value, maximum=maximum, label=label)
    except Exception as exc:
        if isinstance(exc, SchemaError):
            raise
        raise SchemaError(str(exc)) from exc


def _nullable_text(value: object, *, label: str, maximum: int = DEFAULT_BOUNDS.max_string_chars) -> str | None:
    if value is None:
        return None
    return _text(value, label=label, maximum=maximum)


def cap_trust(provenance: str, trust: str) -> str:
    """Downgrade `verified` to `claimed` when the source cannot support it."""
    if trust == Trust.VERIFIED.value and provenance not in DETERMINISTIC_PROVENANCES:
        return Trust.CLAIMED.value
    return trust


def _enum(value: object, allowed: frozenset[str], *, label: str) -> str:
    result = _text(value, label=label, maximum=64, allow_empty=False)
    if result not in allowed:
        raise SchemaError(f"{label} has an unsupported value")
    return result


def _string_list(value: object, *, label: str, maximum_items: int = DEFAULT_BOUNDS.max_list_items, item_chars: int = DEFAULT_BOUNDS.max_string_chars) -> list[str]:
    if not isinstance(value, list):
        raise SchemaError(f"{label} must be a list")
    if len(value) > maximum_items:
        raise SchemaError(f"{label} exceeds its item bound")
    return [_text(item, label=f"{label} item", maximum=item_chars) for item in value]


def _provenanced_fields(item: Mapping[str, Any], *, label: str, expected: set[str] | frozenset[str]) -> None:
    _closed(item, expected, label)
    _enum(item.get("provenance"), PROVENANCE_VALUES, label=f"{label}.provenance")
    _enum(item.get("trust"), TRUST_VALUES, label=f"{label}.trust")
    refs = _string_list(item.get("evidence_refs", []), label=f"{label}.evidence_refs", maximum_items=64, item_chars=128)
    if len(refs) > 64:
        raise SchemaError(f"{label}.evidence_refs exceeds its item bound")
    captured = item.get("captured_at")
    if captured is not None and not is_rfc3339_utc(captured):
        raise SchemaError(f"{label}.captured_at must be RFC3339 UTC")


CLAIM_FIELDS = {"text", "provenance", "trust", "evidence_refs", "captured_at"}


def _claim(value: object, *, label: str, default_provenance: str = Provenance.MODEL_INFERENCE.value, default_trust: str = Trust.INFERRED.value) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"text": value}
    if not isinstance(value, dict):
        raise SchemaError(f"{label} must be a string or object")
    _closed(value, CLAIM_FIELDS, label)
    text = _text(value.get("text", ""), label=f"{label}.text", allow_empty=False)
    provenance = _enum(value.get("provenance", default_provenance), PROVENANCE_VALUES, label=f"{label}.provenance")
    trust = _enum(value.get("trust", default_trust), TRUST_VALUES, label=f"{label}.trust")
    refs = _string_list(value.get("evidence_refs", []), label=f"{label}.evidence_refs", maximum_items=64, item_chars=128)
    captured = value.get("captured_at")
    if captured is not None and not is_rfc3339_utc(captured):
        raise SchemaError(f"{label}.captured_at must be RFC3339 UTC")
    return {"text": text, "provenance": provenance, "trust": cap_trust(provenance, trust), "evidence_refs": refs, "captured_at": captured}


def _claims(value: object, *, label: str, maximum_items: int = DEFAULT_BOUNDS.max_list_items) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SchemaError(f"{label} must be a list")
    if len(value) > maximum_items:
        raise SchemaError(f"{label} exceeds its item bound")
    return [_claim(item, label=f"{label}[{index}]") for index, item in enumerate(value)]


DECISION_FIELDS = {"decision_id", "statement", "rationale", "status", "provenance", "trust", "evidence_refs", "captured_at"}


def _decisions(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_list_items:
        raise SchemaError("decisions must be a bounded list")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if isinstance(raw, str):
            raw = {"statement": raw, "decision_id": f"decision-{index + 1}"}
        if not isinstance(raw, dict):
            raise SchemaError("decision must be an object")
        _closed(raw, DECISION_FIELDS, "decision")
        decision_id = _text(raw.get("decision_id", f"decision-{index + 1}"), label="decision_id", maximum=128, allow_empty=False)
        statement = _text(raw.get("statement", ""), label="decision.statement", allow_empty=False)
        rationale = _text(raw.get("rationale", ""), label="decision.rationale")
        status = _enum(raw.get("status", DecisionStatus.ACTIVE.value), frozenset(item.value for item in DecisionStatus), label="decision.status")
        provenance = _enum(raw.get("provenance", Provenance.MODEL_INFERENCE.value), PROVENANCE_VALUES, label="decision.provenance")
        trust = _enum(raw.get("trust", Trust.INFERRED.value), TRUST_VALUES, label="decision.trust")
        refs = _string_list(raw.get("evidence_refs", []), label="decision.evidence_refs", maximum_items=64, item_chars=128)
        captured = raw.get("captured_at")
        if captured is not None and not is_rfc3339_utc(captured):
            raise SchemaError("decision.captured_at must be RFC3339 UTC")
        result.append({"decision_id": decision_id, "statement": statement, "rationale": rationale, "status": status, "provenance": provenance, "trust": cap_trust(provenance, trust), "evidence_refs": refs, "captured_at": captured})
    return result


FILE_FIELDS = {"path", "symbols", "role", "hash", "exists", "provenance", "trust", "evidence_refs", "captured_at"}


def _files(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_changed_files:
        raise SchemaError("files must be a bounded list")
    result: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            raise SchemaError("file reference must be an object")
        _closed(raw, FILE_FIELDS, "file")
        path = _text(raw.get("path", ""), label="file.path", maximum=DEFAULT_BOUNDS.max_path_chars, allow_empty=False)
        symbols = _string_list(raw.get("symbols", []), label="file.symbols", maximum_items=DEFAULT_BOUNDS.max_file_symbols, item_chars=256)
        role = _nullable_text(raw.get("role"), label="file.role", maximum=512)
        digest = _nullable_text(raw.get("hash"), label="file.hash", maximum=64)
        if digest is not None and not _SHA256_RE.fullmatch(digest):
            raise SchemaError("file.hash must be a SHA-256 digest")
        exists = raw.get("exists")
        if exists is not None and not isinstance(exists, bool):
            raise SchemaError("file.exists must be boolean or null")
        provenance = _enum(raw.get("provenance", Provenance.MODEL_INFERENCE.value), PROVENANCE_VALUES, label="file.provenance")
        trust = _enum(raw.get("trust", Trust.INFERRED.value), TRUST_VALUES, label="file.trust")
        refs = _string_list(raw.get("evidence_refs", []), label="file.evidence_refs", maximum_items=64, item_chars=128)
        captured = raw.get("captured_at")
        if captured is not None and not is_rfc3339_utc(captured):
            raise SchemaError("file.captured_at must be RFC3339 UTC")
        result.append({"path": path, "symbols": symbols, "role": role, "hash": digest, "exists": exists, "provenance": provenance, "trust": trust, "evidence_refs": refs, "captured_at": captured})
    return result


VERIFICATION_FIELDS = {"name", "command", "status", "summary", "commit", "captured_at", "provenance", "trust", "evidence_refs"}


def _verification(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_list_items:
        raise SchemaError("verification must be a bounded list")
    result: list[dict[str, Any]] = []
    allowed = frozenset(item.value for item in VerificationStatus)
    for raw in value:
        if isinstance(raw, str):
            raw = {"name": raw}
        if not isinstance(raw, dict):
            raise SchemaError("verification record must be an object")
        _closed(raw, VERIFICATION_FIELDS, "verification")
        name = _text(raw.get("name", ""), label="verification.name", maximum=512, allow_empty=False)
        command = _nullable_text(raw.get("command"), label="verification.command", maximum=2_048)
        status = _enum(raw.get("status", VerificationStatus.UNKNOWN.value), allowed, label="verification.status")
        summary = _text(raw.get("summary", ""), label="verification.summary", maximum=DEFAULT_BOUNDS.max_event_chars)
        commit = _nullable_text(raw.get("commit"), label="verification.commit", maximum=64)
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise SchemaError("verification.commit must be a Git SHA")
        captured = raw.get("captured_at")
        if captured is not None and not is_rfc3339_utc(captured):
            raise SchemaError("verification.captured_at must be RFC3339 UTC")
        provenance = _enum(raw.get("provenance", Provenance.MODEL_INFERENCE.value), PROVENANCE_VALUES, label="verification.provenance")
        trust = _enum(raw.get("trust", Trust.CLAIMED.value), TRUST_VALUES, label="verification.trust")
        refs = _string_list(raw.get("evidence_refs", []), label="verification.evidence_refs", maximum_items=64, item_chars=128)
        result.append({"name": name, "command": command, "status": status, "summary": summary, "commit": commit, "captured_at": captured, "provenance": provenance, "trust": cap_trust(provenance, trust), "evidence_refs": refs})
    return result


ERROR_FIELDS = {"error", "fix", "status", "command", "provenance", "trust", "evidence_refs", "captured_at"}


def _errors(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_list_items:
        raise SchemaError("errors must be a bounded list")
    result: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            raw = {"error": raw}
        if not isinstance(raw, dict):
            raise SchemaError("error record must be an object")
        _closed(raw, ERROR_FIELDS, "error")
        error = _text(raw.get("error", ""), label="error.error", maximum=DEFAULT_BOUNDS.max_event_chars, allow_empty=False)
        fix = _nullable_text(raw.get("fix"), label="error.fix", maximum=DEFAULT_BOUNDS.max_event_chars)
        status = _nullable_text(raw.get("status"), label="error.status", maximum=64)
        command = _nullable_text(raw.get("command"), label="error.command", maximum=2_048)
        provenance = _enum(raw.get("provenance", Provenance.MODEL_INFERENCE.value), PROVENANCE_VALUES, label="error.provenance")
        trust = _enum(raw.get("trust", Trust.CLAIMED.value), TRUST_VALUES, label="error.trust")
        refs = _string_list(raw.get("evidence_refs", []), label="error.evidence_refs", maximum_items=64, item_chars=128)
        captured = raw.get("captured_at")
        if captured is not None and not is_rfc3339_utc(captured):
            raise SchemaError("error.captured_at must be RFC3339 UTC")
        result.append({"error": error, "fix": fix, "status": status, "command": command, "provenance": provenance, "trust": cap_trust(provenance, trust), "evidence_refs": refs, "captured_at": captured})
    return result


CONTEXT_FIELDS = {"role", "text", "timestamp", "provenance", "trust", "evidence_refs"}


def _recent_context(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_recent_context:
        raise SchemaError("recent_context must be a bounded list")
    result: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            raw = {"role": "context", "text": raw}
        if not isinstance(raw, dict):
            raise SchemaError("recent context item must be an object")
        _closed(raw, CONTEXT_FIELDS, "recent_context")
        role = _text(raw.get("role", "context"), label="recent_context.role", maximum=64, allow_empty=False)
        text = _text(raw.get("text", ""), label="recent_context.text", maximum=DEFAULT_BOUNDS.max_event_chars)
        timestamp = raw.get("timestamp")
        if timestamp is not None and not is_rfc3339_utc(timestamp):
            raise SchemaError("recent_context.timestamp must be RFC3339 UTC")
        provenance = _enum(raw.get("provenance", Provenance.MODEL_INFERENCE.value), PROVENANCE_VALUES, label="recent_context.provenance")
        trust = _enum(raw.get("trust", Trust.CLAIMED.value), TRUST_VALUES, label="recent_context.trust")
        refs = _string_list(raw.get("evidence_refs", []), label="recent_context.evidence_refs", maximum_items=64, item_chars=128)
        result.append({"role": role, "text": text, "timestamp": timestamp, "provenance": provenance, "trust": cap_trust(provenance, trust), "evidence_refs": refs})
    return result


EVIDENCE_FIELDS = {"evidence_id", "kind", "source", "digest", "summary", "captured_at", "provenance", "trust"}


def _evidence(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_evidence:
        raise SchemaError("evidence must be a bounded list")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if isinstance(raw, str):
            raw = {"evidence_id": f"evidence-{index + 1}", "kind": "note", "source": "model", "summary": raw}
        if not isinstance(raw, dict):
            raise SchemaError("evidence record must be an object")
        _closed(raw, EVIDENCE_FIELDS, "evidence")
        evidence_id = _text(raw.get("evidence_id", f"evidence-{index + 1}"), label="evidence.evidence_id", maximum=128, allow_empty=False)
        kind = _text(raw.get("kind", "note"), label="evidence.kind", maximum=128, allow_empty=False)
        source = _text(raw.get("source", "unknown"), label="evidence.source", maximum=DEFAULT_BOUNDS.max_path_chars, allow_empty=False)
        digest = _nullable_text(raw.get("digest"), label="evidence.digest", maximum=64)
        if digest is not None and not _SHA256_RE.fullmatch(digest):
            raise SchemaError("evidence.digest must be a SHA-256 digest")
        summary = _text(raw.get("summary", ""), label="evidence.summary", maximum=DEFAULT_BOUNDS.max_event_chars)
        captured = raw.get("captured_at")
        if captured is not None and not is_rfc3339_utc(captured):
            raise SchemaError("evidence.captured_at must be RFC3339 UTC")
        provenance = _enum(raw.get("provenance", Provenance.TOOL.value), PROVENANCE_VALUES, label="evidence.provenance")
        trust = _enum(raw.get("trust", Trust.OBSERVED.value), TRUST_VALUES, label="evidence.trust")
        result.append({"evidence_id": evidence_id, "kind": kind, "source": source, "digest": digest, "summary": summary, "captured_at": captured, "provenance": provenance, "trust": trust})
    return result


def _source(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("source must be an object")
    fields = {"host", "model", "session_id", "transcript_source", "cwd"}
    _closed(value, fields, "source")
    host = _enum(value.get("host", Host.UNKNOWN.value), frozenset(item.value for item in Host), label="source.host")
    model = _nullable_text(value.get("model"), label="source.model", maximum=256)
    session_id = _nullable_text(value.get("session_id"), label="source.session_id", maximum=256)
    transcript_source = _enum(value.get("transcript_source", TranscriptSource.NONE.value), frozenset(item.value for item in TranscriptSource), label="source.transcript_source")
    cwd = _nullable_text(value.get("cwd"), label="source.cwd", maximum=DEFAULT_BOUNDS.max_path_chars)
    return {"host": host, "model": model, "session_id": session_id, "transcript_source": transcript_source, "cwd": cwd}


PROJECT_FIELDS = {"repo_root_hint", "remote", "remotes", "branch", "commit", "dirty", "changed_files", "changed_files_total", "worktrees", "head_published"}
CHANGED_FILE_FIELDS = {"path", "orig_path", "status", "staged", "hash", "exists", "provenance", "trust", "captured_at"}
REMOTE_FIELDS = {"name", "url"}
WORKTREE_FIELDS = {"path", "branch", "commit", "is_current"}


def _remotes(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 64:
        raise SchemaError("project.remotes must be a bounded list")
    result: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise SchemaError("project.remotes item must be an object")
        _closed(raw, REMOTE_FIELDS, "project.remotes item")
        result.append({
            "name": _text(raw.get("name", ""), label="remote.name", maximum=256, allow_empty=False),
            "url": _nullable_text(raw.get("url"), label="remote.url", maximum=2_048),
        })
    return result


def _worktrees(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 64:
        raise SchemaError("project.worktrees must be a bounded list")
    result: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise SchemaError("project.worktrees item must be an object")
        _closed(raw, WORKTREE_FIELDS, "project.worktrees item")
        commit = _nullable_text(raw.get("commit"), label="worktree.commit", maximum=64)
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise SchemaError("worktree.commit must be a Git SHA")
        is_current = raw.get("is_current", False)
        if not isinstance(is_current, bool):
            raise SchemaError("worktree.is_current must be boolean")
        result.append({
            "path": _text(raw.get("path", ""), label="worktree.path", maximum=DEFAULT_BOUNDS.max_path_chars, allow_empty=False),
            "branch": _nullable_text(raw.get("branch"), label="worktree.branch", maximum=512),
            "commit": commit,
            "is_current": is_current,
        })
    return result


def _changed_files(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > DEFAULT_BOUNDS.max_changed_files:
        raise SchemaError("project.changed_files must be a bounded list")
    result: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            raise SchemaError("changed file must be an object")
        _closed(raw, CHANGED_FILE_FIELDS, "project.changed_files item")
        path = _text(raw.get("path", ""), label="changed_file.path", maximum=DEFAULT_BOUNDS.max_path_chars, allow_empty=False)
        orig_path = _nullable_text(raw.get("orig_path"), label="changed_file.orig_path", maximum=DEFAULT_BOUNDS.max_path_chars)
        status = _text(raw.get("status", "unknown"), label="changed_file.status", maximum=16, allow_empty=False)
        staged = raw.get("staged", False)
        if not isinstance(staged, bool):
            raise SchemaError("changed_file.staged must be boolean")
        digest = _nullable_text(raw.get("hash"), label="changed_file.hash", maximum=64)
        if digest is not None and not _SHA256_RE.fullmatch(digest):
            raise SchemaError("changed_file.hash must be a SHA-256 digest")
        exists = raw.get("exists")
        if exists is not None and not isinstance(exists, bool):
            raise SchemaError("changed_file.exists must be boolean or null")
        provenance = _enum(raw.get("provenance", Provenance.GIT.value), PROVENANCE_VALUES, label="changed_file.provenance")
        trust = _enum(raw.get("trust", Trust.VERIFIED.value), TRUST_VALUES, label="changed_file.trust")
        captured = raw.get("captured_at")
        if captured is not None and not is_rfc3339_utc(captured):
            raise SchemaError("changed_file.captured_at must be RFC3339 UTC")
        result.append({"path": path, "orig_path": orig_path, "status": status, "staged": staged, "hash": digest, "exists": exists, "provenance": provenance, "trust": trust, "captured_at": captured})
    return result


def _project(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("project must be an object")
    _closed(value, PROJECT_FIELDS, "project")
    root = _nullable_text(value.get("repo_root_hint"), label="project.repo_root_hint", maximum=DEFAULT_BOUNDS.max_path_chars)
    remote = _nullable_text(value.get("remote"), label="project.remote", maximum=2_048)
    branch = _nullable_text(value.get("branch"), label="project.branch", maximum=512)
    commit = _nullable_text(value.get("commit"), label="project.commit", maximum=64)
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise SchemaError("project.commit must be a Git SHA")
    dirty = value.get("dirty")
    if dirty is not None and not isinstance(dirty, bool):
        raise SchemaError("project.dirty must be boolean or null")
    published = value.get("head_published")
    if published is not None and not isinstance(published, bool):
        raise SchemaError("project.head_published must be boolean or null")
    recorded = _changed_files(value.get("changed_files", []))
    total = value.get("changed_files_total", len(recorded))
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise SchemaError("project.changed_files_total must be a non-negative integer")
    return {
        "repo_root_hint": root,
        "remote": remote,
        "remotes": _remotes(value.get("remotes", [])),
        "branch": branch,
        "commit": commit,
        "dirty": dirty,
        "changed_files": recorded,
        "changed_files_total": max(total, len(recorded)),
        "worktrees": _worktrees(value.get("worktrees", [])),
        "head_published": published,
    }


def _task(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("task must be an object")
    _closed(value, {"goal", "definition_of_done", "scope_in", "scope_out"}, "task")
    goal = _text(value.get("goal", ""), label="task.goal", maximum=DEFAULT_BOUNDS.max_goal_chars, allow_empty=False)
    return {"goal": goal, "definition_of_done": _claims(value.get("definition_of_done", []), label="task.definition_of_done"), "scope_in": _claims(value.get("scope_in", []), label="task.scope_in"), "scope_out": _claims(value.get("scope_out", []), label="task.scope_out")}


def _state(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("state must be an object")
    _closed(value, {"status", "completed", "in_progress", "pending", "blockers"}, "state")
    status = _enum(value.get("status", TaskStatus.UNKNOWN.value), frozenset(item.value for item in TaskStatus), label="state.status")
    return {"status": status, "completed": _claims(value.get("completed", []), label="state.completed"), "in_progress": _claims(value.get("in_progress", []), label="state.in_progress"), "pending": _claims(value.get("pending", []), label="state.pending"), "blockers": _claims(value.get("blockers", []), label="state.blockers")}


def _next_action(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"instruction": value}
    if not isinstance(value, dict):
        raise SchemaError("next_action must be an object")
    _closed(value, {"instruction", "file", "cwd", "command", "blocking_question", "preconditions"}, "next_action")
    instruction = _text(value.get("instruction", ""), label="next_action.instruction", maximum=DEFAULT_BOUNDS.max_event_chars, allow_empty=False)
    file = _nullable_text(value.get("file"), label="next_action.file", maximum=DEFAULT_BOUNDS.max_path_chars)
    if file:
        # A capsule may be loaded into any checkout, so a next-action path must
        # stay inside the target repository. Absolute paths and traversal are
        # rejected here rather than at the point of use.
        file = normalize_relative_path(file)
    cwd = _nullable_text(value.get("cwd"), label="next_action.cwd", maximum=DEFAULT_BOUNDS.max_path_chars)
    if cwd:
        cwd = normalize_relative_path(cwd)
    command = _nullable_text(value.get("command"), label="next_action.command", maximum=2_048)
    blocking_question = _nullable_text(value.get("blocking_question"), label="next_action.blocking_question", maximum=DEFAULT_BOUNDS.max_event_chars)
    preconditions = _string_list(value.get("preconditions", []), label="next_action.preconditions", maximum_items=64, item_chars=DEFAULT_BOUNDS.max_event_chars)
    return {"instruction": instruction, "file": file, "cwd": cwd, "command": command, "blocking_question": blocking_question, "preconditions": preconditions}


def _security(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("security must be an object")
    _closed(value, {"redactions", "untrusted_sources", "secret_scan"}, "security")
    redactions_raw = value.get("redactions", [])
    if not isinstance(redactions_raw, list) or len(redactions_raw) > DEFAULT_BOUNDS.max_list_items:
        raise SchemaError("security.redactions must be a bounded list")
    redactions: list[dict[str, Any]] = []
    for raw in redactions_raw:
        if isinstance(raw, str):
            raw = {"kind": raw, "count": 1}
        if not isinstance(raw, dict):
            raise SchemaError("security.redaction must be an object")
        _closed(raw, {"kind", "count"}, "security.redaction")
        kind = _text(raw.get("kind", "unknown"), label="security.redaction.kind", maximum=128, allow_empty=False)
        count = raw.get("count", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > 1_000_000:
            raise SchemaError("security.redaction.count must be a bounded integer")
        redactions.append({"kind": kind, "count": count})
    return {
        "redactions": redactions,
        "untrusted_sources": _string_list(value.get("untrusted_sources", []), label="security.untrusted_sources", maximum_items=DEFAULT_BOUNDS.max_list_items, item_chars=DEFAULT_BOUNDS.max_path_chars),
        "secret_scan": _secret_scan(value.get("secret_scan")),
    }


def _secret_scan(value: object) -> dict[str, Any]:
    """An empty redaction list means nothing unless a scan is known to have run."""
    if value is None:
        return {"status": ScanStatus.NOT_RUN.value, "patterns_version": None, "fields_scanned": 0}
    if not isinstance(value, dict):
        raise SchemaError("security.secret_scan must be an object")
    _closed(value, {"status", "patterns_version", "fields_scanned"}, "security.secret_scan")
    scanned = value.get("fields_scanned", 0)
    if not isinstance(scanned, int) or isinstance(scanned, bool) or scanned < 0 or scanned > 10_000_000:
        raise SchemaError("security.secret_scan.fields_scanned must be a bounded integer")
    return {
        "status": _enum(value.get("status", ScanStatus.NOT_RUN.value), frozenset(item.value for item in ScanStatus), label="security.secret_scan.status"),
        "patterns_version": _nullable_text(value.get("patterns_version"), label="security.secret_scan.patterns_version", maximum=64),
        "fields_scanned": scanned,
    }


def _integrity(value: object, *, allow_missing: bool) -> dict[str, Any]:
    if value is None and allow_missing:
        return {"algorithm": "sha256", "digest": ""}
    if not isinstance(value, dict):
        raise SchemaError("integrity must be an object")
    _closed(value, {"algorithm", "digest"}, "integrity")
    algorithm = _text(value.get("algorithm", "sha256"), label="integrity.algorithm", maximum=16, allow_empty=False)
    if algorithm != "sha256":
        raise SchemaError("integrity.algorithm must be sha256")
    digest = _text(value.get("digest", ""), label="integrity.digest", maximum=64, allow_empty=allow_missing)
    if digest and not _SHA256_RE.fullmatch(digest):
        raise SchemaError("integrity.digest must be a SHA-256 digest")
    if not allow_missing and not digest:
        raise SchemaError("integrity.digest is required")
    return {"algorithm": algorithm, "digest": digest}


def empty_document(*, handoff_id: str | None = None, created_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": handoff_id or str(uuid.uuid4()),
        "created_at": created_at or now_utc(),
        "source": {"host": Host.UNKNOWN.value, "model": None, "session_id": None, "transcript_source": TranscriptSource.NONE.value, "cwd": None},
        "project": {"repo_root_hint": None, "remote": None, "remotes": [], "branch": None, "commit": None, "dirty": None, "changed_files": [], "changed_files_total": 0, "worktrees": [], "head_published": None},
        "task": {"goal": "", "definition_of_done": [], "scope_in": [], "scope_out": []},
        "state": {"status": TaskStatus.UNKNOWN.value, "completed": [], "in_progress": [], "pending": [], "blockers": []},
        "decisions": [],
        "constraints": [],
        "user_corrections": [],
        "files": [],
        "verification": [],
        "errors": [],
        "next_action": {"instruction": "", "file": None, "cwd": None, "command": None, "blocking_question": None, "preconditions": []},
        "recent_context": [],
        "evidence": [],
        "risks": [],
        "unknowns": [],
        "security": {"redactions": [], "untrusted_sources": [], "secret_scan": {"status": ScanStatus.NOT_RUN.value, "patterns_version": None, "fields_scanned": 0}},
        "integrity": {"algorithm": "sha256", "digest": ""},
    }


def normalize_draft(value: object) -> dict[str, Any]:
    """Normalize a model-authored draft without granting it trusted facts."""
    if not isinstance(value, dict):
        raise SchemaError("draft must be a JSON object")
    unknown = set(value) - TOP_LEVEL_FIELDS
    if unknown:
        raise SchemaError("draft contains an unknown top-level field")
    base = empty_document()
    merged = dict(base)
    for key, item in value.items():
        if key == "integrity":
            continue
        if key in base and isinstance(base[key], dict) and isinstance(item, dict):
            merged[key] = {**base[key], **item}
        else:
            merged[key] = item
    # A draft may omit its goal and next action while it is being assembled;
    # finalization will reject an empty goal or action.
    if not merged.get("task", {}).get("goal"):
        merged["task"]["goal"] = "draft goal unavailable"
    if not merged.get("next_action", {}).get("instruction"):
        merged["next_action"]["instruction"] = "determine the next action from the current work"
    normalized = _normalize_document(merged, allow_missing_integrity=True)
    normalized["integrity"] = {"algorithm": "sha256", "digest": ""}
    return normalized


def _normalize_document(value: object, *, allow_missing_integrity: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("handoff must be a JSON object")
    _closed(value, TOP_LEVEL_FIELDS, "handoff")
    declared = value.get("schema_version")
    if declared in SUPERSEDED_SCHEMA_VERSIONS:
        raise SchemaError(f"capsule uses superseded schema {declared}; re-create it with schema {SCHEMA_VERSION}")
    if declared != SCHEMA_VERSION:
        raise SchemaError("unsupported schema_version")
    handoff_id = _text(value.get("handoff_id", ""), label="handoff_id", maximum=128, allow_empty=False)
    try:
        uuid.UUID(handoff_id)
    except (ValueError, AttributeError) as exc:
        raise SchemaError("handoff_id must be a UUID") from exc
    created_at = value.get("created_at")
    if not is_rfc3339_utc(created_at):
        raise SchemaError("created_at must be RFC3339 UTC")
    result = {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": handoff_id,
        "created_at": created_at,
        "source": _source(value.get("source", {})),
        "project": _project(value.get("project", {})),
        "task": _task(value.get("task", {})),
        "state": _state(value.get("state", {})),
        "decisions": _decisions(value.get("decisions", [])),
        "constraints": _claims(value.get("constraints", []), label="constraints"),
        "user_corrections": _claims(value.get("user_corrections", []), label="user_corrections"),
        "files": _files(value.get("files", [])),
        "verification": _verification(value.get("verification", [])),
        "errors": _errors(value.get("errors", [])),
        "next_action": _next_action(value.get("next_action", {})),
        "recent_context": _recent_context(value.get("recent_context", [])),
        "evidence": _evidence(value.get("evidence", [])),
        "risks": _claims(value.get("risks", []), label="risks"),
        "unknowns": _claims(value.get("unknowns", []), label="unknowns"),
        "security": _security(value.get("security", {})),
        "integrity": _integrity(value.get("integrity"), allow_missing=allow_missing_integrity),
    }
    walk_bounds(result, bounds=DEFAULT_BOUNDS, label="handoff")
    return result


def validate_document(value: object) -> dict[str, Any]:
    """Normalize and validate a complete, integrity-bearing document."""
    result = _normalize_document(value, allow_missing_integrity=False)
    return result
