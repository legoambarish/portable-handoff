# Portable Handoff

Use the installed CLI to create the canonical artifact. If `portable-handoff`
is not on `PATH`, substitute `python -m portable_handoff` in each line.

```text
portable-handoff preflight --cwd . --source-host codex --output .handoff/evidence/preflight.json
portable-handoff finalize --preflight .handoff/evidence/preflight.json --draft DRAFT.json --output auto
portable-handoff load latest --cwd .
```

The active model must supply `DRAFT.json` from its live context. Do not invent
tests, Git facts, hashes, transcript events, or an exact next action.

Keep the draft terse. Claim lists accept bare strings, which default to
`provenance: model_inference` and `trust: inferred`; use the object form only
where the source is genuinely stronger. Minimal draft shape:

```json
{
  "task": {"goal": "one sentence", "definition_of_done": ["..."]},
  "state": {"status": "in_progress", "completed": ["..."], "pending": ["..."]},
  "files": [{"path": "relative/path.py", "symbols": ["name"], "role": "why it matters"}],
  "next_action": {
    "instruction": "one immediate step",
    "cwd": "relative/dir",
    "file": "relative/path.py",
    "command": "git status --short",
    "blocking_question": null,
    "preconditions": ["..."]
  }
}
```

Set `blocking_question` when the step cannot start until the user decides
something. Leave `command` empty rather than guessing one.
