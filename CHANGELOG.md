# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
aims to follow semantic versioning once it reaches 1.0.

## [Unreleased]

Capsule schema `1.2`. Capsules on `1.0` or `1.1` are rejected with an explicit
message; re-create them. Neither shipped outside pre-release builds.

### Added

- `project.changed_files_total`, so a bounded sample of changed files can no
  longer read as a clean tree.
- Trust is capped at the source: `verified` now requires a deterministic
  provenance (`git`, `tool`, `test`, `file`, `transcript`) and is downgraded to
  `claimed` otherwise, everywhere a draft supplies it rather than only inside
  `verification`.

### Changed

- The embedded JSON omits keys whose value is null or an empty list, which a
  reader re-expands from schema defaults. Roughly 9% off the JSON half. The
  integrity digest is unchanged: it is still computed over the fully expanded
  document, so this is not a change to the digest definition.
- `changed_files` records a 25-entry sample rather than up to 2,000, with at
  most 10 rendered in prose. It orients a reader and flags drift; it is not a
  diff, and the files that matter to a task belong in `files`.
- Worktree prose lists only the current worktree and any sharing the recorded
  branch, with a count of the rest. The full list stays in the JSON.
- A derived blocker points at the blocking question instead of restating it.
- `preflight --output` defaults to a file instead of stdout. On a repository
  with 304 modified files the previous default printed roughly 48,000 tokens of
  JSON into the calling model's context; it now prints a ~105 token summary
  naming the branch, dirty state, changed-file count, and warnings.

### Added

- `next_action.cwd` so a step states which directory it runs in, and
  `next_action.blocking_question` for a user decision that gates the step.
  Setting the question forces `state.status` to `blocked` and appends a
  matching `state.blockers` entry, so a later model cannot read "no blockers"
  while a decision is outstanding.
- `project.worktrees`, `project.remotes`, and `project.head_published`.
  Preflight now records every configured remote, every linked worktree, and
  whether the recorded commit is reachable from any remote-tracking branch,
  so "this release exists only on one machine" is a verified fact rather than
  an inference.
- `security.secret_scan` recording scan status, the secret-pattern set version,
  and the number of text fields inspected. An empty redaction list no longer
  looks the same as a scan that never ran.
- A `Security and Redaction` section in the rendered Markdown, plus file
  hashes, file roles, worktrees, remotes, and per-verification observation
  times. These were previously present only in the embedded JSON.
- Command risk classification (`read_only`, `review`, `dangerous`) computed at
  load time in `command_safety.py`. The briefing prints a next-action command
  as inert, fenced, review-required text instead of an authoritative step.
- Capsule age in the briefing, and an explicit warning past seven days.
- `portable-handoff doctor --cwd .` reports whether a host can produce a capsule
  at all (`supported` / `degraded` / `unsupported`) before one is attempted, and
  exits non-zero when it cannot. An accuracy audit found models emitting prose
  summaries and calling them handoffs on hosts with no filesystem.
- `finalize` and `load --format json` print an explicit `outcome` line carrying
  the path, schema version, integrity digest, and validation result. The skill
  now requires models to quote it verbatim rather than describe what they
  believe happened; the same audit caught a model reporting a schema version, a
  validator error, and a migration that had not occurred.
- Developer Certificate of Origin (`DCO.txt`), documented in `CONTRIBUTING.md`
  and the pull-request template.
- `portable-handoff export PATH --format prose|briefing|json` emits one half of
  a validated capsule, for when a capsule has to be pasted into a chat rather
  than loaded through the CLI.

### Fixed

- Renamed and copied files were recorded under their pre-rename path, so a
  path that no longer existed was reported as missing with no hash. `git
  status --porcelain -z` emits the current path first; the previous path is
  now kept separately in `changed_files[].orig_path`.
- Invisible and bidirectional Unicode (zero-width characters, bidi embeddings,
  overrides, isolates) is stripped and counted as an `invisible_character`
  redaction. Previously only ANSI and C0 controls were removed, so a capsule
  could show a reviewer something other than what a model read.
- `next_action.file` and `next_action.cwd` are validated as repository-relative
  at the schema boundary; absolute paths and traversal are rejected.
- The Markdown renderer leaked Python reprs (`True`, `False`, `None`) into
  human-facing prose. Booleans render as `yes`/`no` and absent digests as
  `not recorded`.
- `schemas/handoff-v1.schema.json` and the packaged copy under
  `src/portable_handoff/resources/` had drifted apart. They are now identical
  and a test enforces it.
- `list`/`load latest` fell back to alphabetical order when two capsules shared
  a `created_at`, which happens when one preflight is finalized twice.
  Modification time now breaks the tie.
- The skill launcher assumed a fixed directory depth to find a source
  checkout. It now walks upward for the package and prints an actionable error
  when it finds nothing.
- Removed an unreachable exception clause in the strict JSON parser and a
  fragile `locals()` lookup in the CLI error handler.
