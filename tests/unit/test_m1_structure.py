from pathlib import Path


def test_skill_and_package_layout():
    root = Path(__file__).resolve().parents[2]
    assert (root / "skills/handoff/SKILL.md").exists()
    assert (root / "skills/handoff/agents/openai.yaml").exists()
    assert (root / "src/portable_handoff/__main__.py").exists()
