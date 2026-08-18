# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's private
vulnerability reporting on this repository (Security tab, "Report a
vulnerability"). Do not open a public issue for a security problem.

Include the version or commit, the platform, and a minimal reproduction. We
aim to acknowledge a report within seven days.

## What this project defends against

Portable Handoff parses files that may have been written by another model, or
by an attacker, and shows them to an agent that can act. The threat model is
therefore hostile input, not a hostile local user.

In scope:

- Prompt injection through capsule, transcript, or tool prose.
- A capsule that supplies a destructive command, an absolute path, or a
  traversal path.
- Malformed, oversized, deeply nested, or duplicate-keyed JSON.
- Symlink and reparse-point escapes on read and write.
- Invisible or bidirectional Unicode that makes a reviewed capsule differ from
  the one a model reads.
- Secrets leaking into a capsule, a log, or an error message.

## What it does not defend against

- **Authenticity.** `integrity.digest` is an unkeyed SHA-256. It detects
  corruption and accidental edits. It does not prove who wrote a capsule, and
  anyone who edits the JSON can recompute it. Do not treat a valid digest as a
  trust signal. Signing is out of scope for v0.1.
- **Command classification.** The `read_only` / `review` / `dangerous` label on
  a next-action command is a conservative offline heuristic to support human
  review. It is not a sandbox and can be evaded. Never run a capsule-supplied
  command without reading it.
- **Complete secret detection.** Redaction covers high-confidence patterns
  only. Review a capsule before sharing it.
- A malicious local user, a compromised Python interpreter, or a hostile Git
  binary on `PATH`.

## Handling capsules safely

Capsules embed absolute paths, branch names, and credential-stripped remote
URLs. Treat one like a screenshot of a terminal: review it before sending it
anywhere.
