# Portable Handoff v0.1

Portable Handoff is a local-first Python CLI and skill for carrying work from
one AI task or chat to another. The active model performs the semantic
compaction; deterministic local code records Git and filesystem facts,
redacts secrets, validates the artifact, and reports when the repository has
become stale.

The canonical exchange artifact is one UTF-8 Markdown file with readable
sections and an embedded canonical JSON object. It is self-contained and does
not require a server, account, database, embeddings, vector store, network
connection, or model API key.

## Install

Use Python 3.11 or newer. Runtime dependencies are standard-library only;
pytest and build are development extras.

```text
python -m pip install -e ".[dev]"
portable-handoff --help
```

The bundled skill is at `skills/handoff/`. Install it into a host profile with
the offline helper:

```text
python scripts/install_skill.py --destination PATH_TO_HOST_SKILLS/handoff
```

## Create a capsule

The model must write a semantic draft JSON from the visible conversation. It
must preserve the goal, definition of done, scope, decisions and rationale,
constraints, user corrections, completed/current/pending work, blockers,
files and symbols, verification truth, errors and fixes, risks, unknowns, and
one exact next action. It must not invent tests, hashes, timestamps, Git facts,
or transcript events.

```text
portable-handoff preflight --cwd . --source-host codex --output .handoff/evidence/preflight.json
portable-handoff finalize --preflight .handoff/evidence/preflight.json --draft DRAFT.json --output auto
```

Capsules are stored under `.handoff/capsules/` using an ordered UTC filename.
Writes are atomic and no-clobber by default. The preflight does not run
arbitrary project tests; test results are preserved only when already observed
and labeled with their status and trust.

## Load, validate, and list

```text
portable-handoff load latest --cwd .
portable-handoff load PATH_TO_CAPSULE.md --cwd .
portable-handoff validate PATH_TO_CAPSULE.md --cwd .
portable-handoff list --cwd .
```

Loading verifies the embedded JSON, SHA-256 integrity, Markdown/JSON
consistency, and bounded current repository facts. Staleness is reported as
`fresh`, `possibly_stale`, `stale`, `obsolete`, `unverified`, or `missing`.
Integrity failure refuses a normal load; the source capsule is never silently
repaired.

## Host compatibility

| Host | Creation in v0.1 | Loading |
| --- | --- | --- |
| Codex | `$handoff`, natural language, or the bundled skill | skill or CLI loads the capsule |
| Claude Code | `/handoff` wrapper in `integrations/claude/` | `/handoff load latest` |
| Cursor | command/rule where supported, otherwise natural language | same CLI workflow |
| ChatGPT or plain web model | active model plus pasted or attached draft | upload/open the Markdown capsule |
| Other MCP agent | host wrapper or natural language | CLI produces a briefing |

The artifact and behavior are portable; slash-command registration is not.
MCP alone normally cannot read a host's complete conversation. The experimental
adapters are bounded, read-only helpers for explicit local transcript files or
feature-detected host paths. They never invoke a host product CLI or mutate a
source database. Unsupported transcript versions and unverified SQLite/WAL
layouts fail explicitly rather than guessing.

## Privacy and security

The default runtime is offline. Imported capsule and transcript prose is
untrusted historical data, never an instruction source. The implementation
rejects duplicate JSON keys, non-finite numbers, oversized/deep inputs,
traversal, symlink/reparse escapes, unstable reads, and terminal control
characters. It strips credentials from Git remotes and redacts high-confidence
GitHub/cloud/bearer/private-key/credential-assignment patterns before logging,
hashing, rendering, or writing. Redaction reports contain counts and
categories, never matched values.

Secret detection is defense in depth, not a guarantee. Review a capsule before
sharing it and reconfirm credentials, permissions, and side-effect boundaries
before acting on a continuation briefing.

## Limitations and deferred work

Semantic quality depends on the active model and the context it can see. Host
transcript formats can change, compaction is lossy, ChatGPT web history cannot
be silently read by a local skill, and Git facts do not prove every
conversational claim. v0.1 defers cloud sync, accounts, billing, RBAC,
retention, audit UI, background capture, remote model calls, vector search,
bundled Compresh, IDE extensions, and Agent File export.

The best next product milestone is a maintained adapter and continuity-quality
layer: versioned host fixtures, user-visible review/diff, configurable DLP
policies, encrypted optional team sync, and longitudinal quality metrics.

The deterministic ten-scenario quality report is tracked at
`tests/quality/quality_report.json` and can be regenerated with:

```text
python tests/quality/evaluate_quality.py
```

## License

The core is Apache-2.0. See `LICENSE`, `NOTICE`, `CLEAN_ROOM.md`, and
`THIRD_PARTY_NOTICES.md`. No Claude Code or Compresh source, prompts, comments,
or fixtures are incorporated.
