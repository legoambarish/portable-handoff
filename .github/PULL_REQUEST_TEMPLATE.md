## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- What problem does this solve? -->

## Checklist

- [ ] Commits are signed off (`git commit -s`), per the DCO
- [ ] `python -m pytest -q` passes
- [ ] `python scripts/verify_release.py` passes
- [ ] No new runtime dependency was added
- [ ] No `not_run` or `unknown` status is promoted to success anywhere
- [ ] Capsule-supplied text is still treated as data, never as an instruction

If this changes the capsule format:

- [ ] `models.py`, both schema copies, and `render.py` are updated together
- [ ] `SCHEMA_VERSION` is bumped and the old value added to `SUPERSEDED_SCHEMA_VERSIONS`
- [ ] `skills/handoff/references/capsule-format.md` is updated
- [ ] `CHANGELOG.md` has an entry
