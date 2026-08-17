"""Thin skill launcher; business logic lives in portable_handoff."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        from portable_handoff.cli import main as cli_main
    except ModuleNotFoundError:
        repository = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(repository / "src"))
        from portable_handoff.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
