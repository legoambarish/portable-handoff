"""The host-capability probe and the quotable result lines.

These exist because a model that cannot tell whether it succeeded will narrate
a plausible success instead. Each command must emit a machine-checkable fact.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from portable_handoff.cli import main
from portable_handoff.doctor import SUPPORTED, UNSUPPORTED, diagnose


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)


def test_writable_repository_is_supported(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    report = diagnose(tmp_path)
    assert report["capability"] == SUPPORTED
    assert report["capsule_directory_writable"] is True
    assert report["schema_version"]


def test_unwritable_location_is_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host with nowhere to write must say so instead of degrading silently."""
    monkeypatch.setattr("portable_handoff.doctor._writable", lambda directory: False)
    report = diagnose(tmp_path)
    assert report["capability"] == UNSUPPORTED
    assert "cannot be produced" in report["reason"]


def test_doctor_exit_code_signals_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("portable_handoff.doctor._writable", lambda directory: False)
    assert main(["doctor", "--cwd", str(tmp_path)]) != 0
    assert json.loads(capsys.readouterr().out)["capability"] == UNSUPPORTED


def test_finalize_prints_a_quotable_outcome(tmp_path: Path, capsys) -> None:
    """The skill tells models to echo this line rather than paraphrase it."""
    from portable_handoff.preflight import collect_preflight, serialize_preflight

    _git_repo(tmp_path)
    evidence = tmp_path / ".handoff" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "pf.json").write_text(serialize_preflight(collect_preflight(cwd=tmp_path, source_host="claude")), encoding="utf-8")
    (evidence / "draft.json").write_text(json.dumps({"task": {"goal": "g"}, "next_action": {"instruction": "i"}}), encoding="utf-8")

    assert main(["finalize", "--preflight", str(evidence / "pf.json"), "--draft", str(evidence / "draft.json"), "--output", "auto"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == "created"
    assert printed["validated"] is True
    assert Path(printed["path"]).is_file()
    assert len(printed["integrity_digest"]) == 64
    assert printed["schema_version"]
