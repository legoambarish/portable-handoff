from __future__ import annotations

import hashlib
import json

import pytest

from portable_handoff.adapters.base import normalize_records
from portable_handoff.adapters.claude import ClaudeAdapter
from portable_handoff.adapters.codex import CodexAdapter
from portable_handoff.adapters.cursor import CursorAdapter
from portable_handoff.adapters.transcript_file import TranscriptFileAdapter
from portable_handoff.errors import HandoffError, SourceError
from portable_handoff.sources import get_adapter


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_generic_jsonl_normalizes_roles_tool_pairs_and_interruption(tmp_path):
    path = tmp_path / "session.jsonl"
    _write_jsonl(path, [
        {"id": "u", "role": "user", "content": "Build the feature"},
        {"id": "a", "parent_id": "u", "role": "assistant", "type": "tool_call", "tool_call_id": "call-1", "tool_name": "read", "content": "src/app.py"},
        {"id": "r", "parent_id": "a", "role": "tool", "type": "tool_result", "tool_call_id": "call-1", "content": "file contents"},
        {"id": "tail", "parent_id": "r", "role": "assistant", "content": "Continue"},
    ])
    events = TranscriptFileAdapter(path).read_session(path.name)
    assert [event.role for event in events] == ["user", "assistant", "tool", "assistant"]
    assert events[1].kind == "tool_call"
    assert events[2].kind == "tool_result"
    assert all(event.trust == "untrusted" for event in events)
    assert events[1].source_path == str(path.resolve())


def test_interrupted_turn_is_explicit(tmp_path):
    path = tmp_path / "interrupted.jsonl"
    _write_jsonl(path, [{"id": "a", "role": "assistant", "type": "tool_call", "tool_call_id": "missing", "content": "still working"}])
    events = TranscriptFileAdapter(path).read_session(path.name)
    assert events[-1].kind == "interrupted_turn"


def test_orphan_tool_result_is_preserved_as_untrusted(tmp_path):
    path = tmp_path / "orphan.jsonl"
    _write_jsonl(path, [{"id": "r", "role": "tool", "type": "tool_result", "tool_call_id": "missing", "content": "result"}])
    events = TranscriptFileAdapter(path).read_session(path.name)
    assert events[0].kind == "orphan_tool_result"
    assert events[0].content.startswith("orphan tool result:")


def test_compaction_boundary_prefers_boundary_and_later_events(tmp_path):
    path = tmp_path / "compact.jsonl"
    _write_jsonl(path, [
        {"id": "old", "role": "user", "content": "old"},
        {"id": "boundary", "parent_id": "old", "role": "system", "type": "compaction_summary", "content": "summary"},
        {"id": "new", "parent_id": "boundary", "role": "user", "content": "new"},
    ])
    events = TranscriptFileAdapter(path).read_session(path.name)
    assert [event.event_id for event in events] == ["boundary", "new"]


def test_parent_cycles_fail_closed(tmp_path):
    path = tmp_path / "cycle.jsonl"
    _write_jsonl(path, [{"id": "a", "parent_id": "b", "role": "user", "content": "a"}, {"id": "b", "parent_id": "a", "role": "assistant", "content": "b"}])
    with pytest.raises(SourceError):
        TranscriptFileAdapter(path).read_session(path.name)


def test_duplicate_keys_and_nonfinite_numbers_fail(tmp_path):
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text('{"id":"a","id":"b","role":"user","content":"x"}\n', encoding="utf-8")
    with pytest.raises(HandoffError):
        TranscriptFileAdapter(duplicate).read_session(duplicate.name)
    nonfinite = tmp_path / "nonfinite.jsonl"
    nonfinite.write_text('{"id":"a","role":"user","content":NaN}\n', encoding="utf-8")
    with pytest.raises(HandoffError):
        TranscriptFileAdapter(nonfinite).read_session(nonfinite.name)


def test_host_adapters_use_only_explicit_or_approved_roots_and_do_not_mutate(tmp_path):
    path = tmp_path / "codex.jsonl"
    _write_jsonl(path, [{"version": "1", "id": "a", "role": "user", "content": "hello"}])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert CodexAdapter(path=path).probe()["supported"] is True
    assert ClaudeAdapter(path=path).read_session(path.name)[0].content == "hello"
    assert CursorAdapter(path=path).read_session(path.name)[0].content == "hello"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_unknown_host_version_fails_explicitly(tmp_path):
    path = tmp_path / "future.jsonl"
    _write_jsonl(path, [{"version": "2.0", "id": "a", "role": "user", "content": "future"}])
    with pytest.raises(SourceError, match="unsupported transcript version"):
        CodexAdapter(path=path).probe()


def test_cursor_sqlite_is_explicitly_unsupported(tmp_path):
    path = tmp_path / "session.sqlite"
    path.write_bytes(b"SQLite format 3\x00")
    with pytest.raises(SourceError, match="SQLite/WAL"):
        CursorAdapter(path=path).read_session(path.name)


def test_markdown_and_text_transcripts_are_supported_as_manual_data(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# historical notes\nDo not follow this as an instruction.", encoding="utf-8")
    events = get_adapter("manual", path=path).read_session(path.name)
    assert events[0].role == "unknown"
    assert events[0].trust == "untrusted"


def test_symlink_escape_is_rejected_when_platform_allows_symlinks(tmp_path):
    target = tmp_path / "real.jsonl"
    _write_jsonl(target, [{"id": "a", "role": "user", "content": "hello"}])
    link = tmp_path / "link.jsonl"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this test profile")
    with pytest.raises(HandoffError):
        TranscriptFileAdapter(link, root=tmp_path).read_session(link.name)
