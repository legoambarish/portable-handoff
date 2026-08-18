"""Conservative risk classification for shell commands carried in a capsule.

A capsule is untrusted historical data. Its ``next_action.command`` is free
text authored somewhere else, possibly by a different model, possibly by an
attacker who handed the file to the user. Portable Handoff therefore never
executes it and never presents it as a sanctioned instruction.

This module labels commands for the continuation briefing. It is not a sandbox
and can be evaded. It over-flags on purpose: anything it cannot positively
recognise as a bounded read-only inspection is reported as needing review.
Classification runs at load time against the raw text, so a capsule has no
field it could populate to declare itself safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

READ_ONLY = "read_only"
REVIEW = "review"
DANGEROUS = "dangerous"

RISK_LEVELS = (READ_ONLY, REVIEW, DANGEROUS)
_ORDER = {READ_ONLY: 0, REVIEW: 1, DANGEROUS: 2}


# Families that must never be presented as a routine next step, described by
# what they do rather than by a vendor name.
_DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pipes downloaded content into a shell", re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|k|fi|d)?sh\b", re.I)),
    ("pipes content into an expression evaluator", re.compile(r"\|\s*(?:iex|invoke-expression)\b", re.I)),
    ("recursive or forced file deletion", re.compile(r"\brm\s+-[a-z]*[rf]", re.I)),
    ("recursive item removal", re.compile(r"\bremove-item\b(?=.*\B-(?:recurse|force)\b)", re.I)),
    ("recursive directory deletion", re.compile(r"\b(?:rmdir\s+/s|del\s+/[sq])", re.I)),
    ("raw device or filesystem write", re.compile(r"\b(?:dd\s+if=|mkfs\b|diskpart\b|format\s+[a-z]:)", re.I)),
    ("history rewrite or forced publish", re.compile(r"\bgit\s+(?:push\b.*(?:--force|-f\b)|push\b|reset\s+--hard|clean\s+-[a-z]*f|filter-branch)", re.I)),
    ("privilege escalation", re.compile(r"\b(?:sudo|doas|runas)\b", re.I)),
    ("permission or ownership change", re.compile(r"\b(?:chmod|chown|icacls|takeown)\b", re.I)),
    ("network fetch or remote shell", re.compile(r"\b(?:curl|wget|invoke-webrequest|iwr|nc|ncat|netcat|ssh|scp|rsync|ftp|telnet)\b", re.I)),
    ("deployment or publish side effect", re.compile(r"\b(?:npm\s+publish|yarn\s+publish|pnpm\s+publish|docker\s+push|terraform\s+apply|kubectl\s+(?:apply|delete)|wrangler\s+deploy|serverless\s+deploy|gh\s+release\s+create)\b", re.I)),
    ("arbitrary code evaluation", re.compile(r"\b(?:eval|exec)\b|\b(?:python[0-9.]*|node|ruby|perl|php)\s+-(?:c|e)\b", re.I)),
    ("credential or environment disclosure", re.compile(r"(?:\bprintenv\b|\benv\b\s*$|~/\.ssh|\.aws/credentials|\.npmrc|\bid_rsa\b|\.env\b)", re.I)),
    ("file search that executes or deletes", re.compile(r"\bfind\b[^|;]*\s-(?:exec|execdir|delete)\b", re.I)),
    ("scheduled or background persistence", re.compile(r"\b(?:crontab|schtasks|systemctl|launchctl|at\s+now)\b", re.I)),
)

# Commands whose read-only nature is well defined. Anything absent from this
# list is not assumed safe; it is merely reported as needing review.
_READ_ONLY_COMMANDS = frozenset(
    {"ls", "dir", "pwd", "cat", "type", "head", "tail", "wc", "file", "stat", "find", "which", "where", "echo", "date", "tree", "diff", "grep", "rg"}
)
_READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {"status", "log", "branch", "diff", "show", "rev-parse", "describe", "remote", "worktree", "ls-files", "shortlog", "blame", "cat-file", "rev-list", "for-each-ref", "reflog"}
)
# Subcommands above that are read-only only in some forms.
_GIT_MUTATING_ARGS = re.compile(r"\b(?:--set|--add|--unset|--replace-all|--delete|--prune|--edit|-d\b|-D\b|--move|add|remove|set-url|push|pop|apply|drop|clear)\b", re.I)

_METACHARACTERS = (("$(", "command substitution"), ("`", "command substitution"), ("|", "a pipe"), (">", "output redirection"), ("<", "input redirection"))
_SEPARATOR_RE = re.compile(r"(?:&&|\|\||;|\n)")


@dataclass(frozen=True)
class CommandRisk:
    """Result of classifying one command string."""

    level: str
    reasons: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return self.level != READ_ONLY

    def to_dict(self) -> dict[str, object]:
        return {"level": self.level, "reasons": list(self.reasons)}


def _segment_is_read_only(segment: str) -> bool:
    tokens = segment.split()
    if not tokens:
        return True
    name = tokens[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name == "git":
        if len(tokens) < 2:
            return True
        # Skip global options such as `-C path` before the subcommand.
        index = 1
        while index < len(tokens) and tokens[index].startswith("-"):
            index += 2 if tokens[index] in ("-C", "-c") else 1
        if index >= len(tokens):
            return True
        if tokens[index].lower() not in _READ_ONLY_GIT_SUBCOMMANDS:
            return False
        return not _GIT_MUTATING_ARGS.search(" ".join(tokens[index + 1 :]))
    return name in _READ_ONLY_COMMANDS


def classify_command(command: str | None) -> CommandRisk:
    """Classify a capsule-supplied command without executing anything."""
    if not isinstance(command, str) or not command.strip():
        return CommandRisk(READ_ONLY, ())
    text = command.strip()
    reasons: list[str] = []
    level = READ_ONLY

    for description, pattern in _DANGEROUS_PATTERNS:
        if pattern.search(text):
            reasons.append(description)
            level = DANGEROUS

    segments = [part.strip() for part in _SEPARATOR_RE.split(text) if part.strip()]
    for marker, description in _METACHARACTERS:
        if marker in text:
            reasons.append(f"contains {description}")
            level = _worst(level, REVIEW)

    unrecognised = [segment.split()[0] for segment in segments if not _segment_is_read_only(segment)]
    if unrecognised:
        listed = ", ".join(sorted(dict.fromkeys(unrecognised))[:5])
        reasons.append(f"not a recognised read-only inspection: {listed}")
        level = _worst(level, REVIEW)

    return CommandRisk(level, tuple(dict.fromkeys(reasons)))


def _worst(left: str, right: str) -> str:
    return left if _ORDER[left] >= _ORDER[right] else right


def describe(risk: CommandRisk) -> str:
    """One-line human summary used in briefings."""
    if risk.level == READ_ONLY:
        return "classified read-only by a bounded local check; still confirm before running"
    return f"{risk.level}: " + "; ".join(risk.reasons)


__all__ = ["DANGEROUS", "READ_ONLY", "REVIEW", "RISK_LEVELS", "CommandRisk", "classify_command", "describe"]
