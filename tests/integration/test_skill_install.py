from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_installer(root: Path):
    spec = importlib.util.spec_from_file_location("portable_handoff_installer", root / "scripts" / "install_skill.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_installs_into_a_temporary_profile(tmp_path):
    root = Path(__file__).resolve().parents[2]
    installer = _load_installer(root)
    destination = tmp_path / "profile" / "handoff"
    installed = installer.install(source=root / "skills" / "handoff", destination=destination)
    assert (installed / "SKILL.md").is_file()
    assert (installed / "agents" / "openai.yaml").is_file()


def test_thin_skill_launcher_reaches_cli_help():
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run([sys.executable, str(root / "skills" / "handoff" / "scripts" / "handoff.py"), "--help"], cwd=root, capture_output=True, text=True)
    assert completed.returncode == 0
    assert "portable-handoff" in completed.stdout
