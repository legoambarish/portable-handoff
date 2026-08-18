"""Offline release verifier for the Portable Handoff source tree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _check(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise RuntimeError(message)
    checks.append(message)


def _run_python(args: list[str]) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    source_path = str(ROOT / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source_path if not existing else source_path + os.pathsep + existing
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=environment, capture_output=True, text=True, check=False, shell=False)


def verify() -> dict[str, object]:
    checks: list[str] = []
    required = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "CLEAN_ROOM.md", "README.md", "pyproject.toml", "schemas/handoff-v1.schema.json", "skills/handoff/SKILL.md", "skills/handoff/agents/openai.yaml")
    for relative in required:
        _check((ROOT / relative).is_file(), f"present:{relative}", checks)
    skill = (ROOT / "skills/handoff/SKILL.md").read_text(encoding="utf-8")
    _check(len(skill.splitlines()) < 500, "skill-under-500-lines", checks)
    _check("TODO" not in skill, "skill-has-no-todo-placeholders", checks)
    _check(skill.startswith("---\nname: handoff\ndescription:"), "skill-frontmatter", checks)
    metadata = (ROOT / "skills/handoff/agents/openai.yaml").read_text(encoding="utf-8")
    for key in ("display_name", "short_description", "default_prompt"):
        _check(f"{key}:" in metadata, f"skill-metadata:{key}", checks)
    result = _run_python(["-m", "portable_handoff", "--help"])
    _check(result.returncode == 0 and "portable-handoff" in result.stdout, "cli-help", checks)
    compile_result = _run_python(["-m", "compileall", "-q", "src"])
    _check(compile_result.returncode == 0, "compileall", checks)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.quality.evaluate_quality import build_report

    report = build_report()
    _check(report["scenario_count"] >= 12, "quality-scenario-coverage", checks)
    _check(report["runs_real_pipeline"] is True, "quality-exercises-real-pipeline", checks)
    _check(report["all_must_preserve_fields_pass"] is True, "quality-must-preserve-fields", checks)
    _check("dependencies = []" in (ROOT / "pyproject.toml").read_text(encoding="utf-8"), "runtime-has-no-dependencies", checks)

    published = (ROOT / "schemas/handoff-v1.schema.json").read_bytes()
    packaged = (ROOT / "src/portable_handoff/resources/handoff-v1.schema.json").read_bytes()
    _check(published == packaged, "schema-copies-identical", checks)

    from portable_handoff.models import SCHEMA_VERSION

    _check(json.loads(published)["properties"]["schema_version"]["const"] == SCHEMA_VERSION, "schema-version-matches-contract", checks)

    stdlib_result = _run_python(["scripts/check_stdlib_only.py"])
    _check(stdlib_result.returncode == 0, "runtime-imports-stdlib-only", checks)

    _check("Signed-off-by" in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"), "contributing-documents-dco", checks)
    _check("verbatim" in skill, "skill-requires-verbatim-reporting", checks)
    _check("doctor" in skill, "skill-checks-host-capability", checks)
    for relative in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md", "DCO.txt"):
        _check((ROOT / relative).is_file(), f"present:{relative}", checks)
    return {"ok": True, "checks": checks}


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:500]}, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
