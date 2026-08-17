# Portable Handoff v0.1

Use the installed CLI to create the canonical artifact:

```text
portable-handoff preflight --cwd . --output .handoff/evidence/preflight.json
portable-handoff finalize --preflight .handoff/evidence/preflight.json --draft DRAFT.json --output auto
portable-handoff load latest --cwd .
```

The active model must supply `DRAFT.json` from its live context. Do not invent
tests, Git facts, hashes, transcript events, or an exact next action.
