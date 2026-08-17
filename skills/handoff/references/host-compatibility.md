# Host compatibility

Command registration is host-specific; the artifact and CLI behavior are the
portable part.

| Host | Creation | Load |
| --- | --- | --- |
| Codex | `$handoff` or natural language in the current task | skill runs `load latest` |
| Claude Code | `/handoff` command wrapper | `/handoff load latest` |
| Cursor | command/rule where supported, otherwise natural language | same CLI workflow |
| ChatGPT or plain web model | active model writes the semantic draft | upload or paste the Markdown capsule |
| Other MCP agent | host wrapper or natural language | CLI produces the briefing |

MCP alone cannot normally read a host's complete conversation. Creation must
use the active model's visible context or an explicitly supplied transcript.
The local adapters are experimental, bounded, read-only, and fail explicitly
when a transcript version cannot be verified.
