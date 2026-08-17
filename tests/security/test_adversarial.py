from __future__ import annotations

import json

import pytest

from portable_handoff.errors import HandoffError, SchemaError
from portable_handoff.finalize import finalize
from portable_handoff.preflight import collect_preflight, serialize_preflight
from portable_handoff.strict_json import loads_strict


def _minimal_draft():
    return {"task": {"goal": "secure goal"}, "next_action": {"instruction": "continue safely"}}


def _paths(tmp_path):
    evidence = tmp_path / ".handoff" / "evidence"
    evidence.mkdir(parents=True)
    preflight = evidence / "preflight.json"
    preflight.write_text(serialize_preflight(collect_preflight(cwd=tmp_path)), encoding="utf-8")
    draft = evidence / "draft.json"
    draft.write_text(json.dumps(_minimal_draft()), encoding="utf-8")
    return preflight, draft


def test_forged_timestamp_integrity_and_evidence_hash_are_rejected(tmp_path):
    preflight, draft = _paths(tmp_path)
    for mutation in (
        {"created_at": "2000-01-01T00:00:00Z"},
        {"integrity": {"algorithm": "sha256", "digest": "0" * 64}},
        {"evidence": [{"evidence_id": "x", "kind": "x", "source": "x", "digest": "0" * 64}]},
    ):
        value = _minimal_draft()
        value.update(mutation)
        draft.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(HandoffError):
            finalize(preflight_path=preflight, draft_path=draft, output="auto")


def test_malformed_json_never_echoes_content():
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    with pytest.raises(SchemaError) as exc:
        loads_strict('{"x":1,"x":"' + secret + '"}')
    assert secret not in str(exc.value)


def test_large_nested_input_is_bounded():
    value = "1"
    for _ in range(30):
        value = "[" + value + "]"
    with pytest.raises(HandoffError):
        loads_strict(value)
