"""Install the handoff skill into a host profile without network access."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def install(*, source: str | Path, destination: str | Path, force: bool = False) -> Path:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_dir() or not (source_path / "SKILL.md").is_file():
        raise ValueError("source is not a valid handoff skill")
    if destination_path.exists() and not force:
        raise FileExistsError(str(destination_path))
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_path, destination_path, dirs_exist_ok=force)
    return destination_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the local handoff skill into a host profile.")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1] / "skills" / "handoff"))
    parser.add_argument("--destination", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    path = install(source=args.source, destination=args.destination, force=args.force)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
