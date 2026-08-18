"""Fail if the runtime package imports anything outside the standard library.

The no-dependency rule is a promise the project makes to hosts that run it in
locked-down environments, so it is checked mechanically rather than by review.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "portable_handoff"


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        # level > 0 is a relative import inside this package, so it is skipped.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def main() -> int:
    allowed = set(sys.stdlib_module_names) | {"portable_handoff"}
    offenders: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        external = _top_level_imports(path) - allowed
        if external:
            offenders[str(path.relative_to(ROOT))] = external
    if offenders:
        for name, modules in offenders.items():
            print(f"{name}: imports non-stdlib module(s): {', '.join(sorted(modules))}", file=sys.stderr)
        return 1
    print(f"ok: {len(list(PACKAGE.rglob('*.py')))} runtime modules import only the standard library")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
