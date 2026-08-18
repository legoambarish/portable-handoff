# Contributing

Thanks for helping improve Portable Handoff. This project has a narrow scope
and a few hard rules that shape every change.

## Project invariants

These are not style preferences. A change that breaks one of them will not be
merged, however useful it is otherwise.

1. **No runtime dependencies.** The package imports only the Python standard
   library. `pytest`, `build`, `ruff`, and `mypy` are development extras.
2. **Offline by default.** No network calls, no model API calls, no telemetry.
   The active model does the semantic work; this code does the deterministic
   work.
3. **Never promote a status.** `not_run` and `unknown` never become `passed`.
   A model claim never becomes a `verified` fact.
4. **Imported prose is data.** Capsule, transcript, and tool text is never an
   instruction source, and a capsule-supplied command is never executed.
5. **Fail explicitly.** An unsupported transcript version, an unverifiable
   layout, or an unsafe path is an error, not a guess.

## Sign your commits

This project uses the Developer Certificate of Origin ([DCO.txt](DCO.txt)).
Every commit must carry a `Signed-off-by` line, which `git commit -s` adds for
you:

```bash
git commit -s -m "fix: keep the current path for renamed files"
```

Signing certifies you wrote the patch or otherwise have the right to submit it
under Apache-2.0. There is no separate CLA to sign.

## Getting set up

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/verify_release.py
```

All three must pass before you open a pull request. `verify_release.py` checks
packaging invariants that the unit tests do not, including the no-dependency
rule and the ten-scenario quality report.

## Changing the capsule format

The format is a compatibility surface. If you add, remove, or rename a field:

1. Update `src/portable_handoff/models.py`, which is the authoritative
   contract.
2. Update `schemas/handoff-v1.schema.json`. The copy under
   `src/portable_handoff/resources/` must stay byte-identical; a test enforces
   this.
3. Update `src/portable_handoff/render.py` if the field should be visible to a
   human reader. Validation re-renders Markdown from JSON and requires an exact
   match, so a rendering change is a format change.
4. Bump `SCHEMA_VERSION` and add the previous value to
   `SUPERSEDED_SCHEMA_VERSIONS` so old capsules fail with a clear message
   instead of a confusing structural error.
5. Update `skills/handoff/references/capsule-format.md`.

## Changing the secret patterns

Patterns live in `src/portable_handoff/sanitize.py`. Bump
`SECRET_PATTERNS_VERSION` whenever you change them, so capsules record which
rules were actually applied. Add a test that asserts the pattern redacts, and
never add a test fixture containing a real credential.

## Style

Match the surrounding code. Comments explain why a constraint exists, not what
a line does. Keep public errors free of secrets, paths outside the repository,
and raw subprocess output.
