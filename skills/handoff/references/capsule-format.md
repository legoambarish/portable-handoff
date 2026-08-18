# Capsule format

Portable Handoff exchanges one UTF-8 Markdown file. Its required sections
appear in a fixed order and a single canonical JSON object is delimited by:

```text
<!-- portable-handoff:json:start -->
```json
{...}
```
<!-- portable-handoff:json:end -->
```

The current schema version is `1.1`. Schema `1.0` shipped only in pre-release
builds and is rejected with a specific message; re-create those capsules.

## Canonical JSON

The digest is defined over an exact byte sequence, so two implementations that
follow these rules produce the same value:

- UTF-8, no byte-order mark, no trailing newline.
- `sort_keys = true` (lexicographic by code point).
- Separators exactly `,` and `:`, with no other whitespace.
- Non-ASCII characters are emitted literally, not escaped.
- All strings are Unicode NFC-normalized before serialization. If two keys
  collide after normalization the document is rejected.
- `NaN`, `Infinity`, and `-Infinity` are rejected.
- Duplicate object keys are rejected rather than last-one-wins.

`integrity.digest` is SHA-256 over that byte sequence with the `integrity`
field removed from the object entirely.

## What the digest does and does not prove

The digest is an unkeyed checksum. It detects truncated pastes, editor
mangling, and accidental edits. It does **not** authenticate authorship: anyone
who edits the JSON can recompute it. Treat a valid digest as "this file is
internally consistent", never as "this content is trustworthy". Signing is out
of scope for v0.1.

## Markdown and JSON consistency

The Markdown is a deterministic, lossy projection of the JSON. Validation
re-renders the Markdown from the embedded JSON and requires a byte-for-byte
match, so drift in either direction is a validation failure.

Because the projection is lossy, some fields exist only in the JSON:
`evidence_refs`, per-item `provenance` on some records, `changed_files`
metadata beyond path and status, and `source.session_id`. Everything a reader
needs in order to judge trust is projected: trust and provenance labels, file
hashes, verification status with its observation time, worktrees, remotes,
publication state, redaction counts, and secret-scan status.

Note that the digest covers the JSON only. A capsule whose Markdown prose was
edited by hand will fail the re-render check rather than pass silently.

## Vocabularies

Verification and secret-scan status are exactly `passed`, `failed`, `not_run`,
and `unknown`. `not_run` and `unknown` are never promoted to success.

`state.status` is exactly `planning`, `in_progress`, `blocked`,
`verification`, `complete`, or `unknown`. Setting `next_action.blocking_question`
forces `blocked` and appends a matching `state.blockers` entry.

Trust is `verified`, `observed`, `claimed`, `inferred`, or `untrusted`.
Provenance is `conversation:user`, `conversation:assistant`, `tool`, `file`,
`git`, `test`, `transcript`, or `model_inference`. Claims carry both so a later
model can distinguish verified Git facts from conversation claims and
inference.

## Scope of repository facts

`project` describes one worktree at one instant. `project.worktrees` lists the
others so a capsule cannot silently conflate two checkouts, and
`project.head_published` records whether the commit exists on any remote.
Evidence sidecars are optional; the Markdown capsule must remain sufficient on
its own.
