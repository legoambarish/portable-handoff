# Host compatibility

Command registration is host-specific; the artifact and CLI behavior are the
portable part.

| Host | Creation | Load |
| --- | --- | --- |
| Codex | `$handoff` or natural language in the current task | skill runs `load latest` |
| Claude Code | `/handoff` wrapper shipped in `integrations/claude/` | `/handoff load latest` |
| Cursor | `integrations/cursor/` where commands are supported, otherwise natural language | same CLI workflow |
| ChatGPT or plain web model | active model writes the semantic draft | upload or paste the Markdown capsule |
| Other MCP agent | host wrapper or natural language, see `integrations/generic/` | CLI produces the briefing |

MCP alone cannot normally read a host's complete conversation. Creation must
use the active model's visible context or an explicitly supplied transcript.
The local adapters are experimental, bounded, read-only, and fail explicitly
when a transcript version cannot be verified.

If the `portable-handoff` console script is not on `PATH` in a given host,
`python -m portable_handoff` and `python scripts/handoff.py` accept the same
arguments.
