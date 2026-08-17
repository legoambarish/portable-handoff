# Capsule format

Portable Handoff v0.1 exchanges one UTF-8 Markdown file. Its required sections
appear in a fixed order and a single canonical JSON object is delimited by:

```text
<!-- portable-handoff:json:start -->
```json
{...}
```
<!-- portable-handoff:json:end -->
```

The JSON is schema version `1.0`, uses strict duplicate-key-free parsing, and
contains a SHA-256 digest over canonical UTF-8 JSON with `integrity` omitted.
Markdown/JSON drift is a validation failure. Evidence sidecars are optional;
the Markdown capsule must remain sufficient on its own.

Verification statuses are exactly `passed`, `failed`, `not_run`, and `unknown`.
`not_run` and `unknown` are never promoted to success. Claims carry provenance
and trust so a later model can distinguish verified Git facts from conversation
claims and inference.
