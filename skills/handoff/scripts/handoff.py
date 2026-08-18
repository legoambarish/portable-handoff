"""Thin skill launcher; business logic lives in portable_handoff."""

from __future__ import annotations

import sys
from pathlib import Path


def _add_source_tree_to_path() -> bool:
    """Find a checkout of this project without assuming an install depth.

    The skill directory can be copied anywhere a host keeps skills, so walk up
    looking for the package rather than counting parent directories.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src"
        if (candidate / "portable_handoff" / "cli.py").is_file():
            sys.path.insert(0, str(candidate))
            return True
    return False


def main() -> int:
    try:
        from portable_handoff.cli import main as cli_main
    except ModuleNotFoundError:
        if not _add_source_tree_to_path():
            sys.stderr.write(
                "portable_handoff is not importable and no source checkout was found.\n"
                "Install it with: python -m pip install portable-handoff\n"
            )
            return 3
        from portable_handoff.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
