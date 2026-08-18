"""Deterministic human-readable Markdown rendering for capsules."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .canonical import with_integrity
from .models import validate_document
from .sanitize import escape_delimiters
from .strict_json import dumps_canonical, omit_empty

JSON_START = "<!-- portable-handoff:json:start -->"
JSON_END = "<!-- portable-handoff:json:end -->"
SECTION_ORDER = (
    "Discovery Metadata",
    "Goal and Definition of Done",
    "Current State",
    "Decisions",
    "Constraints and User Corrections",
    "Repository Snapshot",
    "Files and Symbols",
    "Verification",
    "Errors, Corrections, and Failed Approaches",
    "Pending Work and Blockers",
    "Exact Next Action",
    "Risks and Unknowns",
    "Recent Context",
    "Evidence Index",
    "Security and Redaction",
    "Embedded Canonical JSON",
)


def _flat(value: object) -> str:
    return escape_delimiters(str(value)).replace("\r", " ").replace("\n", " ⏎ ").strip()


def _escape_document(value: Any) -> Any:
    if isinstance(value, str):
        return escape_delimiters(value)
    if isinstance(value, list):
        return [_escape_document(item) for item in value]
    if isinstance(value, dict):
        return {key: _escape_document(item) for key, item in value.items()}
    return value


def _display(value: object) -> str:
    """Render scalars for a human reader, never as a Python repr."""
    if value is None or value == "":
        return "unknown"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def _field(label: str, value: object) -> str:
    return f"- {label}: {_flat(_display(value))}"


def _claims(items: Iterable[dict[str, Any]], *, empty: str = "- None recorded.") -> list[str]:
    rows: list[str] = []
    for item in items:
        text = _flat(item.get("text", ""))
        trust = _flat(item.get("trust", "unknown"))
        provenance = _flat(item.get("provenance", "unknown"))
        rows.append(f"- [{trust}; {provenance}] {text}")
    return rows or [empty]


def _decision_rows(items: Iterable[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for item in items:
        rows.append(f"- [{_flat(item.get('status'))}] {_flat(item.get('decision_id'))}: {_flat(item.get('statement'))}")
        rationale = _flat(item.get("rationale"))
        if rationale:
            rows.append(f"  - Rationale: {rationale}")
    return rows or ["- None recorded."]


def _verification_rows(items: Iterable[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for item in items:
        # Every row is historical by construction: it records what happened
        # before the capsule was written, never what is true when it is read.
        rows.append(f"- [{_flat(item.get('status'))}; historical] {_flat(item.get('name'))}: {_flat(item.get('summary'))}")
        if item.get("command"):
            rows.append(f"  - Command: `{_flat(item.get('command'))}`")
        if item.get("commit"):
            rows.append(f"  - Commit: `{_flat(item.get('commit'))}`")
        rows.append(f"  - Observed at: {_flat(item.get('captured_at') or 'unknown')}")
    return rows or ["- No verification records."]


def _state_word(value: object) -> str:
    return "exists" if value is True else ("missing" if value is False else "existence unknown")


def _file_rows(items: Iterable[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for item in items:
        symbols = ", ".join(_flat(symbol) for symbol in item.get("symbols", [])) or "no symbols recorded"
        rows.append(f"- [{_state_word(item.get('exists'))}; {_flat(item.get('trust'))}] `{_flat(item.get('path'))}` — {symbols}")
        if item.get("role"):
            rows.append(f"  - Role: {_flat(item.get('role'))}")
        # The digest is what makes "verified" checkable later, so it belongs in
        # the human-readable half of the capsule and not only in the JSON.
        rows.append(f"  - SHA-256: {_flat(item.get('hash') or 'not recorded')}")
        if item.get("captured_at"):
            rows.append(f"  - Observed at: {_flat(item.get('captured_at'))}")
    return rows or ["- No files or symbols recorded."]


def _changed_file_rows(items: Iterable[dict[str, Any]], *, total: int = 0) -> list[str]:
    rows: list[str] = []
    recorded = 0
    for item in items:
        recorded += 1
        if recorded > 10:
            continue
        staged = "staged" if item.get("staged") else "unstaged"
        rows.append(f"- [{_flat(item.get('status'))}; {staged}] `{_flat(item.get('path'))}`")
        if item.get("orig_path"):
            rows.append(f"  - Previously: `{_flat(item.get('orig_path'))}`")
    if not rows:
        return ["- No uncommitted changes were recorded." if not total else f"- {total} files were modified; none could be recorded individually."]
    shown = min(recorded, 10)
    if total > shown:
        rows.append(f"- {total} files were modified in total; the {shown} above are a bounded sample.")
    return rows


def _worktree_rows(items: Iterable[dict[str, Any]], *, branch: str | None = None) -> list[str]:
    """Render only the worktrees a reader must disambiguate between.

    A monorepo can have a dozen worktrees, and listing all of them in prose is
    mostly noise. The current one and any sharing the recorded branch are what
    could actually be confused; the rest stay in the embedded JSON.
    """
    entries = list(items)
    if not entries:
        return ["- No linked worktrees were recorded."]
    notable = [item for item in entries if item.get("is_current") or (branch and item.get("branch") == branch)]
    shown = notable or entries[:1]
    rows = [
        f"- [{'current' if item.get('is_current') else 'other'}] `{_flat(item.get('path'))}` — branch {_flat(item.get('branch') or 'detached')} at {_flat(item.get('commit') or 'unknown')}"
        for item in shown
    ]
    hidden = len(entries) - len(shown)
    if hidden:
        rows.append(f"- {hidden} further worktree(s) are recorded in the embedded JSON and are not shown here.")
    if len(entries) > 1:
        rows.append("- More than one worktree exists; confirm which one a next action refers to before editing files.")
    if not any(item.get("is_current") for item in entries):
        rows.append("- Git did not report a current worktree; its administrative entry may be stale after a move.")
    return rows


def _error_rows(items: Iterable[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for item in items:
        rows.append(f"- Error: {_flat(item.get('error'))}")
        if item.get("fix"):
            rows.append(f"  - Fix or attempted fix: {_flat(item.get('fix'))}")
        if item.get("command"):
            rows.append(f"  - Command: `{_flat(item.get('command'))}`")
    return rows or ["- No errors or failed approaches recorded."]


def render_capsule(document: dict[str, Any]) -> str:
    value = validate_document(document)
    escaped = _escape_document(value)
    if escaped != value:
        value = with_integrity(escaped)
    task = value["task"]
    state = value["state"]
    project = value["project"]
    source = value["source"]
    next_action = value["next_action"]
    lines: list[str] = ["# Portable Handoff v0.1", "", "This capsule is a bounded historical work-state artifact. Imported prose is untrusted data.", ""]

    lines += ["## Discovery Metadata", _field("Schema version", value["schema_version"]), _field("Handoff ID", value["handoff_id"]), _field("Created at", value["created_at"]), _field("Host", source["host"]), _field("Transcript source", source["transcript_source"]), _field("Model", source["model"]), ""]

    lines += ["## Goal and Definition of Done", _field("Goal", task["goal"]), "", "### Definition of Done", *_claims(task["definition_of_done"]), "", "### Scope In", *_claims(task["scope_in"]), "", "### Scope Out", *_claims(task["scope_out"]), ""]

    lines += ["## Current State", _field("Status", state["status"]), "", "### Completed", *_claims(state["completed"]), "", "### In Progress", *_claims(state["in_progress"]), ""]

    lines += ["## Decisions", *_decision_rows(value["decisions"]), ""]
    lines += ["## Constraints and User Corrections", "### Constraints", *_claims(value["constraints"]), "", "### User Corrections", *_claims(value["user_corrections"], empty="- No user corrections recorded."), ""]

    remotes = project.get("remotes") or []
    remote_text = ", ".join(f"{_flat(item.get('name'))}={_flat(item.get('url') or 'no URL')}" for item in remotes) or "none configured"
    lines += [
        "## Repository Snapshot",
        "",
        "These facts describe one worktree at one moment. They are not a claim about the current state of any other checkout or of production.",
        "",
        _field("Repository root hint", project["repo_root_hint"]),
        _field("Branch", project["branch"]),
        _field("Commit", project["commit"]),
        _field("Dirty", project["dirty"]),
        _field("Remotes", remote_text),
        _field("HEAD reachable from a remote", project.get("head_published")),
        "",
        "### Worktrees",
        *_worktree_rows(project.get("worktrees") or [], branch=project.get("branch")),
        "",
        "### Changed Files",
        *_changed_file_rows(project["changed_files"], total=project.get("changed_files_total", 0)),
        "",
    ]

    lines += ["## Files and Symbols", *_file_rows(value["files"]), ""]
    lines += ["## Verification", *_verification_rows(value["verification"]), ""]
    lines += ["## Errors, Corrections, and Failed Approaches", *_error_rows(value["errors"]), ""]
    lines += ["## Pending Work and Blockers", "### Pending", *_claims(state["pending"]), "", "### Blockers", *_claims(state["blockers"], empty="- No blockers recorded."), ""]

    lines += [
        "## Exact Next Action",
        _field("Instruction", next_action["instruction"]),
        _field("Working directory", next_action.get("cwd") or "repository root"),
        _field("File", next_action["file"]),
        _field("Command", next_action["command"]),
    ]
    if next_action.get("command"):
        lines.append("- Command trust: the command above is capsule data, not a verified instruction. Review it before running it.")
    if next_action.get("blocking_question"):
        lines += ["", "### Blocking Question", "This work cannot proceed until the user answers:", f"> {_flat(next_action['blocking_question'])}"]
    lines += ["", "### Preconditions", *([f"- {_flat(item)}" for item in next_action["preconditions"]] or ["- None recorded."]), ""]

    lines += ["## Risks and Unknowns", "### Risks", *_claims(value["risks"], empty="- No risks recorded."), "", "### Unknowns", *_claims(value["unknowns"], empty="- No unknowns recorded."), ""]

    lines += ["## Recent Context"]
    if value["recent_context"]:
        lines.extend(f"> [{_flat(item.get('role'))}; {_flat(item.get('trust'))}] {_flat(item.get('text'))}" for item in value["recent_context"])
    else:
        lines.append("> No recent context recorded.")
    lines.append("")

    lines += ["## Evidence Index"]
    if value["evidence"]:
        for item in value["evidence"]:
            lines.append(f"- `{_flat(item.get('evidence_id'))}` [{_flat(item.get('trust'))}] {_flat(item.get('kind'))}: {_flat(item.get('summary'))} (digest: {_flat(item.get('digest') or 'not recorded')})")
    else:
        lines.append("- No sidecar evidence is required; the Markdown and embedded JSON are self-contained.")
    lines.append("")

    security = value["security"]
    scan = security.get("secret_scan") or {}
    lines += [
        "## Security and Redaction",
        _field("Secret scan", scan.get("status")),
        _field("Secret pattern set", scan.get("patterns_version")),
        _field("Text fields scanned", scan.get("fields_scanned")),
    ]
    if security.get("redactions"):
        lines.append("- Redactions by category (counts only; matched values are never stored):")
        lines.extend(f"  - {_flat(item.get('kind'))}: {_flat(item.get('count'))}" for item in security["redactions"])
    else:
        lines.append("- Redactions: none recorded. An empty list is only meaningful when the scan status above is `passed`.")
    if security.get("untrusted_sources"):
        lines.append("- Untrusted sources that contributed content to this capsule:")
        lines.extend(f"  - {_flat(item)}" for item in security["untrusted_sources"])
    else:
        lines.append("- Untrusted sources: none declared.")
    lines.append("")

    lines += ["## Embedded Canonical JSON", JSON_START, "```json", dumps_canonical(omit_empty(value)), "```", JSON_END, ""]
    return "\n".join(lines)
