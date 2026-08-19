# Portable Handoff

[![CI](https://github.com/legoambarish/portable-handoff/actions/workflows/ci.yml/badge.svg)](https://github.com/legoambarish/portable-handoff/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

Move work between AI sessions without losing what mattered.

You spend an hour with a coding agent. It learns your constraints, makes three
decisions you corrected twice, and gets halfway through a refactor. Then the
context window fills up, or you switch tools, and the next session starts from
nothing. Asking the model to "summarise what we did" gets you a summary that
reads well and quietly invents the parts it doesn't remember.

Portable Handoff writes a capsule instead: one Markdown file where the model
supplies the meaning and local code supplies the facts. Git state, file hashes
and timestamps come from your machine, not from the model's recollection. Every
claim is labelled with where it came from and how much to trust it.

## What a capsule gets you

Loading one produces a briefing sized for a fresh session:

```
Written: 2026-08-18T05:52:51Z (less than a day old)
Staleness: **fresh**

## Current State
- Status: `blocked`
- Blockers: Awaiting a user decision before the next action can proceed

## Repository facts recorded in the capsule
- Branch: `master`
- Commit: `6e963af6a921724a647ffe09426ba12d17cd2d17`
- HEAD reachable from a remote: no
- Warning: the recorded commit was not present on any remote, so it may exist
  only on the machine that wrote this capsule.

## Blocking question - answer before editing files
> Should phase 1 land on main or on the release branch?
```

Three things there are worth noticing. The status is `blocked`, not
`in_progress`, because the draft carried an unanswered question and the tool
promoted it. The publication warning was not written by a model; it came from
`git branch --remotes --contains`. And the capsule refuses to let a later
session read "no blockers" while a decision is still open, which is how these
things quietly go wrong.

## Install

Clone the repository. `pip install` alone gets you the CLI, but the skill
files an agent actually reads live next to it in the same clone, and pip does
not package them.

```bash
git clone https://github.com/legoambarish/portable-handoff
cd portable-handoff
pip install -e .
portable-handoff doctor --cwd .
```

Python 3.11 or newer. No runtime dependencies at all, no network access, no
account, no API key, no database, no vector store. `doctor` prints
`supported`, `degraded`, or `unsupported` for wherever you just ran it, which
is worth checking before anything else.

The commands below assume you're inside that clone.

### Claude Code

Skills live in `~/.claude/skills/` for every project on the machine, or in
`.claude/skills/` for one project only.

```bash
python scripts/install_skill.py --destination ~/.claude/skills/handoff
```

Start a new session and `handoff` shows up in the skill list. There's also a
`/handoff` slash command at `integrations/claude/commands/handoff.md`; copy it
to `.claude/commands/handoff.md` in a project if you'd rather type the command
than wait for the skill to trigger on its own.

### OpenAI Codex CLI

Same idea, Codex's own directory: `~/.codex/skills/` machine-wide, or
`.codex/skills/` for one project.

```bash
python scripts/install_skill.py --destination ~/.codex/skills/handoff
```

Codex picks up a new skill on its own, or you can call it directly with
`$handoff`.

### Cursor

Cursor's agent already has a shell, so it can run the CLI commands above with
nothing extra installed. If you want it to reach for the skill without being
told, turn the existing instructions into a project rule:

```bash
mkdir -p .cursor/rules
cp integrations/cursor/commands/handoff.md .cursor/rules/handoff.mdc
```

That file has no frontmatter yet, so add the `alwaysApply` or `globs` block
Cursor's [rules docs](https://cursor.com/docs/rules) describe if you want it
to load without being asked.

### ChatGPT, or anything with no shell

There's nowhere here to write a file and no CLI to run `doctor` with, so
there's nothing to install. Paste the shape from
`skills/handoff/assets/handoff-template.md` into the chat, have the model fill
it in, and save what comes back. That's a draft, not a capsule. It has no
digest and no verified repository facts. Run `finalize` on it later, from a
machine that has the CLI, to get an actual one.

### Anything else with a shell

```bash
python scripts/install_skill.py --destination PATH_TO_HOST_SKILLS/handoff
```

`integrations/generic/HANDOFF_INSTRUCTIONS.md` has the same instructions
written for a host that doesn't read `SKILL.md` on its own.

## Have your agent install this for you

Paste into Claude Code, Codex, Cursor, or anything else with a shell:

> Clone `https://github.com/legoambarish/portable-handoff`, run `pip install -e .`
> inside the clone, then run `python scripts/install_skill.py --destination`
> pointed at your own skills directory: `~/.claude/skills/handoff` if you're
> Claude Code, `~/.codex/skills/handoff` if you're Codex, or wherever else is
> right for you. Run `portable-handoff doctor --cwd .` afterward and paste its
> output back to me exactly as printed, with nothing added.

That last instruction is not incidental. The skill's own rule is to quote a
command's result, not describe it, because a paraphrased success and an
invented one read the same on the page. Asking for it during install is what
catches the run that silently failed instead of the one that says it did.

## Creating one

The model writes a draft JSON from what it can see. Local code collects the
facts and merges them, overriding the model wherever the two disagree.

```bash
portable-handoff preflight --cwd . --source-host codex
portable-handoff finalize --preflight .handoff/evidence/preflight-xxxx.json --draft DRAFT.json --output auto
```

`finalize` prints one line you can quote:

```json
{"outcome":"created","path":"...","schema_version":"1.2","validated":true,"redactions":[]}
```

Drafts are meant to be cheap to write. Any list of claims takes a bare string,
which defaults to `model_inference` / `inferred`, so a model only spends tokens
on the few items that deserve a stronger label:

```json
"constraints": [
  "Never deploy the full dirty worktree",
  {"text": "Page speed is a hard requirement", "provenance": "conversation:user", "trust": "claimed"}
]
```

`trust: verified` needs a deterministic source (`git`, `tool`, `test`, `file`,
`transcript`). Anything else gets downgraded to `claimed` on the way in, so a
model cannot launder its own recollection into a fact.

## Reading one

```bash
portable-handoff load latest --cwd .          # briefing, ~15% the size of the file
portable-handoff validate CAPSULE.md --cwd .
portable-handoff list --cwd .
portable-handoff export CAPSULE.md --format prose   # for pasting into a chat
```

A capsule holds its content twice, as prose and as canonical JSON, because
humans and parsers want different things. Nobody needs both at once, so `load`
and `export` each hand you one half.

Loading checks the embedded JSON, the SHA-256 digest, agreement between the two
halves, and the current repository against what was recorded. Staleness comes
back as `fresh`, `possibly_stale`, `stale`, `obsolete`, `unverified`, or
`missing`. A capsule that fails its integrity check is refused, never repaired.

## Where it runs

Portable Handoff needs a filesystem and a shell. It works in Claude Code,
Codex, Cursor, or any terminal. It does not work inside a plain ChatGPT or
Claude web conversation, where there is nowhere to write a capsule and nothing
to validate it with. `doctor` answers this per host:

| `capability` | Meaning |
| --- | --- |
| `supported` | Capsules can be created and validated here |
| `degraded` | No Git, so repository facts are recorded as unknown |
| `unsupported` | No writable capsule directory; the skill will say so instead of improvising a prose summary |

Slash-command registration differs per host; the artifact and the CLI behave
the same everywhere. Wrappers for Claude Code and Cursor live in
`integrations/`.

## Security

The threat model assumes a capsule may have been written by someone hostile,
because the whole point is that capsules travel. Imported prose is data, never
instructions. Paths coming from a capsule are validated as repository-relative
before use. A `next_action.command` is printed as inert fenced text with a
`read_only` / `review` / `dangerous` label and is never executed.

Text is stripped of terminal control sequences and of invisible or
bidirectional Unicode, so a reviewer sees what the model reads. High-confidence
secrets are redacted before anything is hashed or written, and the report keeps
counts and categories without the matched values.

One thing the digest does not do: prove authorship. It is an unkeyed SHA-256,
so it catches truncation and accidental edits, and anyone who edits the JSON
can recompute it. `SECURITY.md` has the full model and the reporting process.

## Limits

Semantic quality tracks the model doing the compaction. In practice most
entries in a real capsule end up labelled `inferred`, which is honest but thin,
and a capsule is only as good as what the model bothered to notice. Compaction
loses things. Git facts prove the repository state and nothing about what
anyone said.

v0.1 has no sync, no accounts, no team features, and no second model checking
the first one's work. The quality harness at `tests/quality/evaluate_quality.py`
runs twelve scenarios through the real pipeline and is itself mutation-tested,
which tells you the plumbing preserves what it is given. It cannot tell you the
model gave it much.

## Contributing

`CONTRIBUTING.md` covers the invariants that shape every change, the
development loop, and what to update when the capsule format moves. Commits
need a `Signed-off-by` line (`git commit -s`) under the DCO.

## License

Apache-2.0. See `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md`.
`CLEAN_ROOM.md` records the provenance of the implementation.
