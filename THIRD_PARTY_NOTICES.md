# Third-party notices

Portable Handoff v0.1 is an independent Apache-2.0 implementation. No
third-party source code, prompt text, comments, regex corpus, schema, or
fixtures have been copied into this repository.

The implementation was informed by behavioral review of the local, pinned
reference repositories named in the supplied source manifest. The following
references were used only to understand public concepts such as bounded
read-only adapters, context compaction, provenance, and quality evaluation:

- `json-it` (MIT)
- `portable-resume-skills` (Apache-2.0 with NOTICE)
- `openai-agents-python` (MIT)
- `AICTX` (MIT)
- `gitleaks` (MIT), as a pattern-design reference only
- public Apache-2.0 material in the `anthropic-skills` `claude-api` skill

The unlicensed Claude Code ZIP/mirror and Compresh BSL source were clean-room
behavioral references only and are not redistributed or incorporated.

If future changes reuse non-trivial material from an external project, update
this file, `NOTICE`, and the relevant source-file attribution before merging.
